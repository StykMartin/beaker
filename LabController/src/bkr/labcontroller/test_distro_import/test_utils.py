# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import io
import unittest

try:
    from unittest import mock
except ImportError:
    import mock

import six

from six.moves import configparser
from six.moves import urllib

from bkr.labcontroller.distro_import import (
    _get_primary_url,
    _get_url_by_scheme,
    is_rhel8_alpha,
    url_exists,
)


class TestUrlExists(unittest.TestCase):
    @mock.patch("bkr.labcontroller.distro_import.utils.urllib.request.urlopen")
    def test_returns_true_when_urlopen_succeeds(self, mock_urlopen):
        mock_urlopen.return_value = io.BytesIO(b"data")
        self.assertTrue(url_exists("http://example.com/path"))

    @mock.patch("bkr.labcontroller.distro_import.utils.urllib.request.urlopen")
    def test_returns_false_on_urlerror(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("not found")
        self.assertFalse(url_exists("http://example.com/missing"))

    @mock.patch("bkr.labcontroller.distro_import.utils.urllib.request.urlopen")
    def test_returns_true_on_ioerror_errno_21(self, mock_urlopen):
        err = IOError()
        err.errno = 21
        mock_urlopen.side_effect = err
        self.assertTrue(url_exists("http://example.com/dir"))

    @mock.patch("bkr.labcontroller.distro_import.utils.urllib.request.urlopen")
    def test_reraises_ioerror_with_other_errno(self, mock_urlopen):
        err = IOError()
        err.errno = 13
        mock_urlopen.side_effect = err
        with self.assertRaises(IOError):
            url_exists("http://example.com/noperm")


class TestIsRhel8Alpha(unittest.TestCase):
    def _make_parser(self, data):
        cp = configparser.ConfigParser()
        if six.PY2:
            cp.readfp(io.BytesIO(data.encode("utf-8")))
        else:
            cp.read_string(data)
        return cp

    def test_returns_true_for_correct_rhel8_alpha(self):
        p = self._make_parser(
            "[compose]\nlabel = Alpha-1.2\n"
            "[product]\nshort = RHEL\nversion = 8.0\n"
            "[variant-BaseOS]\nuid = BaseOS\n"
        )
        self.assertTrue(is_rhel8_alpha(p))

    def test_returns_false_when_label_doesnt_match(self):
        p = self._make_parser(
            "[compose]\nlabel = Beta-1.0\n[product]\nshort = RHEL\nversion = 8.0\n"
        )
        self.assertFalse(is_rhel8_alpha(p))

    def test_returns_false_when_product_short_doesnt_match(self):
        p = self._make_parser(
            "[compose]\nlabel = Alpha-1.2\n[product]\nshort = Fedora\nversion = 8.0\n"
        )
        self.assertFalse(is_rhel8_alpha(p))

    def test_returns_false_when_variant_baseos_has_variants(self):
        p = self._make_parser(
            "[compose]\nlabel = Alpha-1.2\n"
            "[product]\nshort = RHEL\nversion = 8.0\n"
            "[variant-BaseOS]\nvariants = AppStream\n"
        )
        self.assertFalse(is_rhel8_alpha(p))

    def test_returns_false_when_configparser_raises_error(self):
        p = self._make_parser("[general]\nfoo = bar\n")
        self.assertFalse(is_rhel8_alpha(p))


class TestGetPrimaryUrl(unittest.TestCase):
    def test_returns_http_url(self):
        urls = ["nfs://server/path", "http://server/path", "ftp://server/path"]
        self.assertEqual(_get_primary_url(urls), "http://server/path")

    def test_returns_https_url(self):
        self.assertEqual(_get_primary_url(["nfs://s/p", "https://s/p"]), "https://s/p")

    def test_returns_ftp_url(self):
        self.assertEqual(_get_primary_url(["nfs://s/p", "ftp://s/p"]), "ftp://s/p")

    def test_returns_none_for_nfs_only(self):
        self.assertIsNone(_get_primary_url(["nfs://server/path"]))

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(_get_primary_url([]))


class TestGetUrlByScheme(unittest.TestCase):
    def test_returns_matching_url(self):
        urls = ["http://server/path", "nfs://server/path", "ftp://server/path"]
        self.assertEqual(_get_url_by_scheme(urls, "nfs"), "nfs://server/path")

    def test_returns_none_when_no_match(self):
        self.assertIsNone(_get_url_by_scheme(["http://s/p", "ftp://s/p"], "nfs"))

    def test_returns_first_match(self):
        self.assertEqual(
            _get_url_by_scheme(["nfs://s1/p", "nfs://s2/p"], "nfs"), "nfs://s1/p"
        )

    def test_returns_none_for_empty_list(self):
        self.assertIsNone(_get_url_by_scheme([], "http"))
