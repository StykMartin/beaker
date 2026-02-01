# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from six.moves import configparser
from six.moves import urllib

from bkr.common.bexceptions import BX
from bkr.labcontroller.distro_import import (
    Tparser,
    TparserRhel5,
)

from bkr.labcontroller.test_distro_import import (
    _mock_urlopen,
    _mock_urlopen_discinfo,
)


class TestParser(unittest.TestCase):
    TREEINFO = (
        "[general]\nfamily = Red Hat Enterprise Linux\nversion = 7.0\narch = x86_64\n"
    )

    def _parse_tparser(self, mock_urlopen, content=None):
        content = content or self.TREEINFO
        mock_urlopen.side_effect = [
            _mock_urlopen(content),
            _mock_urlopen_discinfo(),
        ]
        p = Tparser()
        p.parse("http://example.com/tree")
        return p

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_parse_reads_config_from_url(self, mock_urlopen):
        p = self._parse_tparser(mock_urlopen)
        self.assertEqual(p.get("general", "family"), "Red Hat Enterprise Linux")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_parse_returns_false_on_urlerror(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("not found")
        p = Tparser()
        self.assertFalse(p.parse("http://example.com/missing"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_parse_raises_bx_on_missing_section_header(self, mock_urlopen):
        mock_urlopen.return_value = _mock_urlopen("this is not ini format\n")
        p = Tparser()
        with self.assertRaises(BX):
            p.parse("http://example.com/bad")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_get_returns_value(self, mock_urlopen):
        p = self._parse_tparser(mock_urlopen)
        self.assertEqual(p.get("general", "arch"), "x86_64")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_get_returns_default_when_missing(self, mock_urlopen):
        p = self._parse_tparser(mock_urlopen)
        self.assertEqual(p.get("general", "nonexistent", "fallback"), "fallback")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_get_raises_when_missing_and_no_default(self, mock_urlopen):
        p = self._parse_tparser(mock_urlopen)
        with self.assertRaises(
            (configparser.NoSectionError, configparser.NoOptionError)
        ):
            p.get("general", "nonexistent")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_has_option_delegates(self, mock_urlopen):
        p = self._parse_tparser(mock_urlopen)
        self.assertTrue(p.has_option("general", "family"))
        self.assertFalse(p.has_option("general", "nonexistent"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_has_section_startswith(self, mock_urlopen):
        content = (
            "[general]\nfamily = RHEL\n"
            "[images-x86_64]\nkernel = images/pxeboot/vmlinuz\n"
        )
        p = self._parse_tparser(mock_urlopen, content)
        self.assertTrue(p.has_section_startswith("images-"))
        self.assertFalse(p.has_section_startswith("variant-"))

    def test_repr(self):
        p = Tparser()
        p.url = "http://example.com/tree"
        self.assertEqual(repr(p), "http://example.com/tree/.treeinfo")


class TestTparserRhel5(unittest.TestCase):
    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_get_remaps_ppc_to_ppc64(self, mock_urlopen):
        content = (
            "[general]\n"
            "family = Red Hat Enterprise Linux Server\n"
            "version = 5.2\n"
            "arch = ppc\n"
        )
        mock_urlopen.side_effect = [
            _mock_urlopen(content),
            _mock_urlopen_discinfo(),
        ]
        p = TparserRhel5()
        p.parse("http://example.com/tree")
        self.assertEqual(p.get("general", "arch"), "ppc64")

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_get_passes_through_other_values(self, mock_urlopen):
        content = (
            "[general]\n"
            "family = Red Hat Enterprise Linux Server\n"
            "version = 5.2\n"
            "arch = x86_64\n"
        )
        mock_urlopen.side_effect = [
            _mock_urlopen(content),
            _mock_urlopen_discinfo(),
        ]
        p = TparserRhel5()
        p.parse("http://example.com/tree")
        self.assertEqual(p.get("general", "arch"), "x86_64")
        self.assertEqual(p.get("general", "version"), "5.2")
