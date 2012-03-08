import unittest, datetime, os, threading
from time import sleep
from bkr.server.model import TaskStatus, Job, System, User, \
        Group, SystemStatus, SystemActivity, Recipe, LabController
import sqlalchemy.orm
from turbogears.database import session
from bkr.inttest import data_setup, stub_cobbler
from bkr.inttest.assertions import assert_datetime_within, \
        assert_durations_not_overlapping
from bkr.server.tools import beakerd

class TestBeakerd(unittest.TestCase):

    def setUp(self):
        self.stub_cobbler_thread = stub_cobbler.StubCobblerThread()
        self.stub_cobbler_thread.start()
        self.lab_controller = data_setup.create_labcontroller(
                fqdn=u'localhost:%d' % self.stub_cobbler_thread.port)
        data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)

    def tearDown(self):
        self.stub_cobbler_thread.stop()

    def test_loaned_machine_can_be_scheduled(self):
        user = data_setup.create_user()
        distro = data_setup.create_distro()
        system = data_setup.create_system(status=u'Automated', shared=True,
                lab_controller=self.lab_controller)
        # System has groups, which the user is not a member of, but is loaned to the user
        system.loaned = user
        data_setup.add_group_to_system(system, data_setup.create_group())
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (
                '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                % system.fqdn)
        session.flush()
        session.expunge_all()
        beakerd.new_recipes()
        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.processed)

    def test_reservations_are_created(self):
        data_setup.create_task(name=u'/distribution/install')
        user = data_setup.create_user()
        distro = data_setup.create_distro()
        system = data_setup.create_system(owner=user, status=u'Automated',
                shared=True, lab_controller=self.lab_controller)
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (
                '<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                % system.fqdn)
        session.flush()
        session.expunge_all()

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()

        job = Job.query.get(job.id)
        system = System.query.get(system.id)
        user = User.query.get(user.user_id)
        self.assertEqual(job.status, TaskStatus.scheduled)
        self.assertEqual(system.reservations[0].type, u'recipe')
        self.assertEqual(system.reservations[0].user, user)
        assert_datetime_within(system.reservations[0].start_time,
                tolerance=datetime.timedelta(seconds=60),
                reference=datetime.datetime.utcnow())
        self.assert_(system.reservations[0].finish_time is None)
        assert_durations_not_overlapping(system.reservations)

    def test_empty_and_element(self):
        data_setup.create_task(name=u'/distribution/install')
        user = data_setup.create_user()
        distro = data_setup.create_distro()
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (
                u'<hostRequires><and></and></hostRequires>')
        session.flush()
        session.expunge_all()

        beakerd.new_recipes()

        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.processed)

    def test_or_lab_controller(self):
        data_setup.create_task(name=u'/distribution/install')
        user = data_setup.create_user()
        lc1 = data_setup.create_labcontroller(u'lab1')
        lc2 = data_setup.create_labcontroller(u'lab2')
        lc3 = data_setup.create_labcontroller(u'lab3')
        distro = data_setup.create_distro()
        system1 = data_setup.create_system(arch=u'i386', shared=True)
        system1.lab_controller = lc1
        system2 = data_setup.create_system(arch=u'i386', shared=True)
        system2.lab_controller = lc2
        system3 = data_setup.create_system(arch=u'i386', shared=True)
        system3.lab_controller = lc3
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (u"""
               <hostRequires>
                <or>
                 <hostlabcontroller op="=" value="lab1"/>
                 <hostlabcontroller op="=" value="lab2"/>
                </or>
               </hostRequires>
               """)
        session.flush()
        session.expunge_all()

        beakerd.new_recipes()

        job = Job.query.get(job.id)
        system1 = System.query.get(system1.id)
        system2 = System.query.get(system2.id)
        system3 = System.query.get(system3.id)
        self.assertEqual(job.status, TaskStatus.processed)
        candidate_systems = job.recipesets[0].recipes[0].systems
        self.assertEqual(len(candidate_systems), 2)
        self.assert_(system1 in candidate_systems)
        self.assert_(system2 in candidate_systems)
        self.assert_(system3 not in candidate_systems)

    def check_user_cannot_run_job_on_system(self, user, system):
        """
        Asserts that the given user is not allowed to run a job against the 
        given system, i.e. that it aborts due to no matching systems.
        """
        distro = data_setup.create_distro()
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (
                '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                % system.fqdn)
        session.flush()
        session.expunge_all()
        beakerd.new_recipes()
        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.aborted)
        return job.id

    def check_user_can_run_job_on_system(self, user, system):
        """
        Asserts that the given user *is* allowed to run a job against the given 
        system, i.e. that it does not abort due to no matching systems. Inverse 
        of the method above.
        """
        distro = data_setup.create_distro()
        job = data_setup.create_job(owner=user, distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (
                '<hostRequires><hostname op="=" value="%s"/></hostRequires>'
                % system.fqdn)
        session.flush()
        session.expunge_all()
        beakerd.new_recipes()
        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.processed)
        return job.id

    def test_nonshared_system_not_owner(self):
        user = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=False, owner=data_setup.create_user())
        self.check_user_cannot_run_job_on_system(user, system)

    def test_nonshared_system_owner(self):
        user = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=False, owner=user)
        self.check_user_can_run_job_on_system(user, system)

    def test_nonshared_system_admin(self):
        admin = data_setup.create_admin()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=False)
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_shared_system_not_owner(self):
        user = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        self.check_user_can_run_job_on_system(user, system)

    def test_shared_system_admin(self):
        admin = data_setup.create_admin()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        self.check_user_can_run_job_on_system(admin, system)

    def test_shared_group_system_with_user_not_in_group(self):
        user = data_setup.create_user()
        group = data_setup.create_group()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        system.groups.append(group)
        self.check_user_cannot_run_job_on_system(user, system)

    def test_shared_group_system_with_user_in_group(self):
        group = data_setup.create_group()
        user = data_setup.create_user()
        user.groups.append(group)
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        system.groups.append(group)
        self.check_user_can_run_job_on_system(user, system)

    def test_shared_group_system_with_admin_not_in_group(self):
        admin = data_setup.create_admin()
        group = data_setup.create_group()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        system.groups.append(group)
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_shared_group_system_with_admin_in_group(self):
        group = data_setup.create_group()
        admin = data_setup.create_admin()
        admin.groups.append(group)
        system = data_setup.create_system(lab_controller=self.lab_controller,
                shared=True)
        system.groups.append(group)
        self.check_user_can_run_job_on_system(admin, system)

    def test_loaned_system_with_admin(self):
        loanee = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                loaned=loanee)
        admin = data_setup.create_admin()
        self.check_user_cannot_run_job_on_system(admin, system)

    def test_loaned_system_with_loanee(self):
        loanee = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                loaned=loanee)
        job_id = self.check_user_can_run_job_on_system(loanee, system)
        beakerd.processed_recipesets()
        job = Job.query.get(job_id)
        self.assertEqual(job.status, TaskStatus.queued)
        beakerd.queued_recipes()
        job = Job.query.get(job_id)
        self.assertEqual(job.status, TaskStatus.scheduled)
        system = System.query.get(system.id)
        self.assertEqual(system.user.user_id, loanee.user_id)

    def test_loaned_system_with_not_loanee(self):
        loanee = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                loaned=loanee)
        user = data_setup.create_user()
        self.check_user_cannot_run_job_on_system(user, system)

    def test_loaned_system_with_owner(self):
        loanee = data_setup.create_user()
        owner = data_setup.create_user()
        system = data_setup.create_system(lab_controller=self.lab_controller,
                owner=owner, loaned=loanee)
        # owner of the system has access, when the
        # loan is returned their job will be able to run.
        job_id = self.check_user_can_run_job_on_system(owner, system)
        beakerd.processed_recipesets()
        job = Job.query.get(job_id)
        self.assertEqual(job.status, TaskStatus.queued)
        # Even though the system is free the job should stay queued while
        # the loan is in place.
        beakerd.queued_recipes()
        job = Job.query.get(job_id)
        self.assertEqual(job.status, TaskStatus.queued)
        system = System.query.get(system.id)
        self.assertEqual(system.user, None)
    
    def test_fail_harness_repo(self):
        data_setup.create_task(name=u'/distribution/install')
        user = data_setup.create_user()
        distro = data_setup.create_distro()
        system = data_setup.create_system(owner=user, status=u'Automated', shared=True,
                lab_controller=self.lab_controller)
        job = data_setup.create_job(owner=user, distro=distro)
        recipe = job.recipesets[0].recipes[0]
        recipe._host_requires = (
                u'<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                % system.fqdn)

        harness_dir = '%s/%s' % (recipe.harnesspath, \
            recipe.distro.osversion.osmajor)
        try:
            if os.path.exists(harness_dir):
                os.rmdir(harness_dir)
            session.flush()
            beakerd.new_recipes()
            beakerd.processed_recipesets()
            beakerd.queued_recipes()

            for r in Recipe.query:
                if r.system:
                    r.system.lab_controller = self.lab_controller
            beakerd.scheduled_recipes()
            job = Job.by_id(job.id)
            self.assertEqual(job.status, TaskStatus.aborted)
        finally:
            if not os.path.exists(harness_dir):
                os.mkdir(harness_dir)
    
    def test_success_harness_repo(self):
        data_setup.create_task(name=u'/distribution/install')
        user = data_setup.create_user()
        distro = data_setup.create_distro()
        system = data_setup.create_system(owner=user, status=u'Automated',
                shared=True, lab_controller=self.lab_controller)
        job = data_setup.create_job(owner=user, distro=distro)
        recipe = job.recipesets[0].recipes[0]
        recipe._host_requires = (
                '<hostRequires><and><hostname op="=" value="%s"/></and></hostRequires>'
                % system.fqdn)

        harness_dir = '%s/%s' % (recipe.harnesspath, \
            recipe.distro.osversion.osmajor)

        if not os.path.exists(harness_dir):
            os.mkdir(harness_dir)
        session.flush()
        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        for r in Recipe.query:
            if r.system:
                r.system.lab_controller = self.lab_controller
        beakerd.scheduled_recipes()
        job = Job.by_id(job.id)
        self.assertEqual(job.status, TaskStatus.running)

    def test_successful_recipe_start(self):
        distro = data_setup.create_distro()
        system = data_setup.create_system(shared=True,
                lab_controller=self.lab_controller)
        job = data_setup.create_job(distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (u"""
            <hostRequires>
                <hostname op="=" value="%s" />
            </hostRequires>
            """ % system.fqdn)
        session.flush()

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        beakerd.scheduled_recipes()
        beakerd.queued_commands()

        session.expunge_all()
        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.running)
        self.assertEqual(self.stub_cobbler_thread.cobbler\
                .system_actions[system.fqdn], 'reboot')

class TestPowerFailures(unittest.TestCase):

    def setUp(self):
        self.stub_cobbler_thread = stub_cobbler.StubCobblerThread()
        self.stub_cobbler_thread.start()
        self.lab_controller = data_setup.create_labcontroller(
                fqdn=u'localhost:%d' % self.stub_cobbler_thread.port)
        session.flush()

    def tearDown(self):
        self.stub_cobbler_thread.stop()

    # https://bugzilla.redhat.com/show_bug.cgi?id=738423
    def test_unreserve(self):
        user = data_setup.create_user()
        automated_system = data_setup.create_system(fqdn=u'raise1.example.org',
                                                    lab_controller=self.lab_controller,owner = user,
                                                    status = SystemStatus.by_name(u'Automated'))
        automated_system.reserve(u'Scheduler', user)
        session.flush()
        automated_system.unreserve(u'Scheduler', user)
        session.flush()
        session.expunge_all()
        beakerd.queued_commands()
        beakerd.running_commands()
        automated_system = System.query.get(automated_system.id)
        system_activity = automated_system.dyn_activity\
                .filter(SystemActivity.field_name == u'Power').first()
        self.assertEqual(system_activity.action, 'off')
        self.assertTrue(system_activity.new_value.startswith('Failed'))

    def test_automated_system_marked_broken(self):
        automated_system = data_setup.create_system(fqdn=u'broken1.example.org',
                                                    lab_controller=self.lab_controller,
                                                    status = SystemStatus.by_name(u'Automated'))
        automated_system.action_power(u'on')
        session.flush()
        session.expunge_all()
        beakerd.queued_commands()
        beakerd.running_commands()
        automated_system = System.query.get(automated_system.id)
        self.assertEqual(automated_system.status, SystemStatus.by_name(u'Broken'))
        system_activity = automated_system.activity[0]
        self.assertEqual(system_activity.action, 'on')
        self.assertTrue(system_activity.new_value.startswith('Failed'))

    # https://bugzilla.redhat.com/show_bug.cgi?id=720672
    def test_manual_system_status_not_changed(self):
        manual_system = data_setup.create_system(fqdn = u'broken2.example.org',
                                                 lab_controller = self.lab_controller,
                                                 status = SystemStatus.by_name(u'Manual'))
        manual_system.action_power(u'on')
        session.flush()
        session.expunge_all()
        beakerd.queued_commands()
        beakerd.running_commands()
        manual_system = System.query.get(manual_system.id)
        self.assertEqual(manual_system.status, SystemStatus.by_name(u'Manual'))
        system_activity = manual_system.activity[0]
        self.assertEqual(system_activity.action, 'on')
        self.assertTrue(system_activity.new_value.startswith('Failed'))

    def test_mark_broken_updates_history(self):
        system = data_setup.create_system(status = SystemStatus.by_name(u'Automated'))
        system.mark_broken(reason = "Attacked by cyborgs")
        session.flush()
        session.expunge_all()
        system = System.query.get(system.id)
        system_activity = system.dyn_activity.filter(SystemActivity.field_name == u'Status').first()
        self.assertEqual(system_activity.old_value, u'Automated')
        self.assertEqual(system_activity.new_value, u'Broken')

    def test_broken_power_aborts_recipe(self):
        system = data_setup.create_system(fqdn = u'broken.dreams.example.org',
                                          lab_controller = self.lab_controller,
                                          status = SystemStatus.by_name(u'Automated'),
                                          shared = True)
        distro = data_setup.create_distro()
        job = data_setup.create_job(distro=distro)
        job.recipesets[0].recipes[0]._host_requires = (u"""
            <hostRequires>
                <hostname op="=" value="%s" />
            </hostRequires>
            """ % system.fqdn)
        session.flush()

        beakerd.new_recipes()
        beakerd.processed_recipesets()
        beakerd.queued_recipes()
        beakerd.scheduled_recipes()
        beakerd.queued_commands()

        session.expunge_all()
        job = Job.query.get(job.id)
        self.assertEqual(job.status, TaskStatus.running)

        beakerd.running_commands()
        job = Job.query.get(job.id)
        self.assertEqual(job.recipesets[0].recipes[0].status,
                         TaskStatus.aborted)
