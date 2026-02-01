# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from six.moves import urllib

from bkr.common.bexceptions import BX
from bkr.labcontroller.distro_import import (
    Build,
    NakedTree,
    TreeInfoRhel5,
)

from bkr.labcontroller.test_distro_import import (
    _mock_urlopen,
    _mock_urlopen_discinfo,
)


class TestNakedTreeIsImporterFor(unittest.TestCase):
    def _make_options(self, **overrides):
        defaults = dict(
            kernel="images/pxeboot/vmlinuz",
            initrd="images/pxeboot/initrd.img",
            name="TestDistro",
            family="TestFamily",
            version="1.0",
            arch=["x86_64"],
        )
        defaults.update(overrides)
        opts = mock.Mock()
        for k, v in defaults.items():
            setattr(opts, k, v)
        return opts

    def test_returns_true_when_all_options_present(self):
        self.assertTrue(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options()
            )
        )

    def test_returns_false_when_no_options(self):
        self.assertFalse(NakedTree.is_importer_for("http://example.com/tree"))

    def test_returns_false_when_kernel_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(kernel=None)
            )
        )

    def test_returns_false_when_initrd_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(initrd=None)
            )
        )

    def test_returns_false_when_name_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(name=None)
            )
        )

    def test_returns_false_when_family_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(family=None)
            )
        )

    def test_returns_false_when_version_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(version=None)
            )
        )

    def test_returns_false_when_arch_missing(self):
        self.assertFalse(
            NakedTree.is_importer_for(
                "http://example.com/tree", options=self._make_options(arch=[])
            )
        )


class TestBuildFactory(unittest.TestCase):
    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_raises_bx_when_no_importer_matches(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("not found")
        with self.assertRaises(BX):
            Build("http://example.com/nonexistent")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_returns_correct_importer_for_rhel5(self, mock_urlopen):
        content = (
            "[general]\n"
            "family = Red Hat Enterprise Linux Server\n"
            "version = 5.2\n"
            "arch = x86_64\n"
            "[images-x86_64]\n"
            "kernel = images/pxeboot/vmlinuz\n"
            "initrd = images/pxeboot/initrd.img\n"
        )
        mock_urlopen.side_effect = [
            urllib.error.URLError("no composeinfo"),
            urllib.error.URLError("no composeinfo"),
            _mock_urlopen(content),
            _mock_urlopen_discinfo(),
            _mock_urlopen(content),
            _mock_urlopen_discinfo(),
        ]
        self.assertIsInstance(Build("http://example.com/RHEL5"), TreeInfoRhel5)
