# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import logging

from bkr.common.bexceptions import BX

from six.moves import xmlrpc_client


class _DummyProxy:
    """A class that enables RPCs to be accessed as attributes ala xmlrpc_client.ServerProxy
    Inspired/ripped from xmlrpc_client.ServerProxy
    """

    def __init__(self, name):
        self.__name = name

    def __getattr__(self, name):
        return _DummyProxy("%s.%s" % (self.__name, name))

    def __call__(self, *args):
        logging.debug("Dummy call to: %s, args: %s" % (self.__name, args))
        return True


class SchedulerProxy(object):
    """Scheduler Proxy"""

    def __init__(self, options):
        self.add_distro_cmd = options.add_distro_cmd
        # addDistroCmd = '/var/lib/beaker/addDistro.sh'
        if options.dry_run:

            class _Dummy(object):
                def __getattr__(self, name):
                    return _DummyProxy(name)

            self.proxy = _Dummy()
        else:
            self.proxy = xmlrpc_client.ServerProxy(
                options.lab_controller, allow_none=True
            )

    def add_distro(self, profile):
        return self.proxy.add_distro_tree(profile)

    def run_distro_test_job(
        self, name=None, tags=[], osversion=None, arches=[], variants=[]
    ):
        if self.is_add_distro_cmd:
            cmd = self._make_add_distro_cmd(
                name=name,
                tags=tags,
                osversion=osversion,
                arches=arches,
                variants=variants,
            )
            logging.debug(cmd)
            os.system(cmd)
        else:
            raise BX("%s is missing" % self.add_distro_cmd)

    def _make_add_distro_cmd(
        self, name=None, tags=[], osversion=None, arches=[], variants=[]
    ):
        # addDistro.sh "rel-eng" RHEL6.0-20090626.2 RedHatEnterpriseLinux6.0 x86_64,i386 "Server,Workstation,Client"
        cmd = '%s "%s" "%s" "%s" "%s" "%s"' % (
            self.add_distro_cmd,
            ",".join(tags),
            name,
            osversion,
            ",".join(arches),
            ",".join(variants),
        )
        return cmd

    @property
    def is_add_distro_cmd(self):
        # Kick off jobs automatically
        if os.path.exists(self.add_distro_cmd):
            return True
        return False
