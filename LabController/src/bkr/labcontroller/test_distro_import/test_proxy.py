# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from bkr.labcontroller.distro_import import (
    SchedulerProxy,
    _DummyProxy,
)


class TestDummyProxy(unittest.TestCase):
    def test_getattr_chains_names(self):
        d = _DummyProxy("server")
        child = d.method
        self.assertIsInstance(child, _DummyProxy)
        grandchild = child.sub
        self.assertIsInstance(grandchild, _DummyProxy)

    def test_call_returns_true(self):
        d = _DummyProxy("server")
        self.assertTrue(d("arg1", "arg2"))


class TestSchedulerProxy(unittest.TestCase):
    def _make_options(
        self,
        dry_run=True,
        add_distro_cmd="/var/lib/beaker/addDistro.sh",
        lab_controller="http://localhost:8000",
    ):
        opts = mock.Mock()
        opts.dry_run = dry_run
        opts.add_distro_cmd = add_distro_cmd
        opts.lab_controller = lab_controller
        return opts

    def test_dry_run_uses_dummy_proxy(self):
        sp = SchedulerProxy(self._make_options(dry_run=True))
        self.assertTrue(sp.proxy.add_distro_tree({"name": "test"}))

    def test_make_add_distro_cmd_formats_correctly(self):
        sp = SchedulerProxy(self._make_options())
        cmd = sp._make_add_distro_cmd(
            name="RHEL-7.0",
            tags=["released"],
            osversion="RedHatEnterpriseLinux7.0",
            arches=["x86_64", "ppc64"],
            variants=["Server", "Client"],
        )
        self.assertIn("/var/lib/beaker/addDistro.sh", cmd)
        self.assertIn("RHEL-7.0", cmd)
        self.assertIn("RedHatEnterpriseLinux7.0", cmd)
        self.assertIn("x86_64,ppc64", cmd)
        self.assertIn("Server,Client", cmd)
        self.assertIn("released", cmd)

    @mock.patch("os.path.exists", return_value=True)
    def test_is_add_distro_cmd_true(self, mock_exists):
        sp = SchedulerProxy(self._make_options())
        self.assertTrue(sp.is_add_distro_cmd)

    @mock.patch("os.path.exists", return_value=False)
    def test_is_add_distro_cmd_false(self, mock_exists):
        sp = SchedulerProxy(self._make_options())
        self.assertFalse(sp.is_add_distro_cmd)
