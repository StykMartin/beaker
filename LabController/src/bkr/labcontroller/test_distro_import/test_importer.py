# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from bkr.common.bexceptions import BX
from bkr.labcontroller.distro_import import (
    ComposeInfo,
    ComposeInfoMixin,
    Cparser,
    Importer,
)

from bkr.labcontroller.test_distro_import import (
    _fake_parser_get,
)


class TestImporter(unittest.TestCase):
    def test_check_arches_no_arches_noop(self):
        Importer(mock.Mock()).check_arches([])

    def test_check_arches_raises_for_multiple_when_not_allowed(self):
        with self.assertRaises(BX):
            Importer(mock.Mock()).check_arches(["x86_64", "ppc64"], multiple=False)

    def test_check_arches_raises_when_single_not_allowed(self):
        with self.assertRaises(BX):
            Importer(mock.Mock()).check_arches(["x86_64"], single=False)

    def test_check_variants_no_variants_noop(self):
        Importer(mock.Mock()).check_variants([])

    def test_check_variants_raises_for_multiple_when_not_allowed(self):
        with self.assertRaises(BX):
            Importer(mock.Mock()).check_variants(["Server", "Client"], multiple=False)

    def test_check_variants_raises_when_single_not_allowed(self):
        with self.assertRaises(BX):
            Importer(mock.Mock()).check_variants(["Server"], single=False)


class TestComposeInfoMixinIsImporterFor(unittest.TestCase):
    def _make_test_importer(self, required, excluded):
        class _TestImporter(ComposeInfoMixin, Importer):
            pass

        _TestImporter.required = required
        _TestImporter.excluded = excluded
        return _TestImporter

    @mock.patch("bkr.labcontroller.distro_import.importer.Cparser")
    def test_returns_parser_when_all_required_and_no_excluded(self, MockCparser):
        mock_parser = mock.Mock()
        mock_parser.parse.return_value = True
        mock_parser.get.return_value = "some_value"
        MockCparser.return_value = mock_parser

        cls = self._make_test_importer(
            required=[dict(section="product", key="variants")],
            excluded=[],
        )
        self.assertIs(cls.is_importer_for("http://example.com/compose"), mock_parser)

    @mock.patch("bkr.labcontroller.distro_import.importer.Cparser")
    def test_returns_false_when_parse_fails(self, MockCparser):
        mock_parser = mock.Mock()
        mock_parser.parse.return_value = False
        MockCparser.return_value = mock_parser

        cls = self._make_test_importer(
            required=[dict(section="product", key="variants")],
            excluded=[],
        )
        self.assertFalse(cls.is_importer_for("http://example.com/compose"))

    @mock.patch("bkr.labcontroller.distro_import.importer.Cparser")
    def test_returns_false_when_required_key_missing(self, MockCparser):
        mock_parser = mock.Mock()
        mock_parser.parse.return_value = True
        mock_parser.get.return_value = ""
        MockCparser.return_value = mock_parser

        cls = self._make_test_importer(
            required=[dict(section="product", key="variants")],
            excluded=[],
        )
        self.assertFalse(cls.is_importer_for("http://example.com/compose"))

    @mock.patch("bkr.labcontroller.distro_import.importer.Cparser")
    def test_returns_false_when_excluded_key_present(self, MockCparser):
        mock_parser = mock.Mock()
        mock_parser.parse.return_value = True
        mock_parser.get.side_effect = lambda section, key, default="": {
            ("product", "variants"): "Server",
            ("tree", "name"): "RHEL4",
        }.get((section, key), default)
        MockCparser.return_value = mock_parser

        cls = self._make_test_importer(
            required=[dict(section="product", key="variants")],
            excluded=[dict(section="tree", key="name")],
        )
        self.assertFalse(cls.is_importer_for("http://example.com/compose"))


class TestComposeInfoGetArchesAndVariants(unittest.TestCase):
    def _make_compose_info(self, parser_data):
        mock_parser = mock.Mock()
        mock_parser.get.side_effect = _fake_parser_get(parser_data)
        ci = ComposeInfo(mock_parser)
        ci.options = mock.Mock()
        return ci

    def test_get_arches_returns_all_from_parser(self):
        ci = self._make_compose_info({"variant-Server": {"arches": "x86_64,ppc64"}})
        ci.options.arch = []
        self.assertEqual(sorted(ci.get_arches("Server")), ["ppc64", "x86_64"])

    def test_get_arches_filters_by_options(self):
        ci = self._make_compose_info(
            {"variant-Server": {"arches": "x86_64,ppc64,s390x"}}
        )
        ci.options.arch = ["x86_64", "ppc64"]
        self.assertEqual(sorted(ci.get_arches("Server")), ["ppc64", "x86_64"])

    def test_get_arches_strips_src(self):
        ci = self._make_compose_info({"variant-Everything": {"arches": "x86_64,src"}})
        ci.options.arch = []
        self.assertEqual(ci.get_arches("Everything"), ["x86_64"])

    def test_get_variants_returns_parser_variants(self):
        ci = self._make_compose_info({"product": {"variants": "Server,Client"}})
        ci.options.variant = []
        self.assertEqual(ci.get_variants(), ["Server", "Client"])

    def test_get_variants_returns_specific_from_options(self):
        ci = self._make_compose_info({"product": {"variants": "Server,Client"}})
        ci.options.variant = ["Server"]
        self.assertEqual(ci.get_variants(), ["Server"])


class TestComposeInfoFindRepos(unittest.TestCase):
    def _make_compose_info(self, parser_data):
        mock_parser = mock.Mock()
        mock_parser.get.side_effect = _fake_parser_get(parser_data)
        ci = ComposeInfo(mock_parser)
        ci.options = mock.Mock()
        return ci

    @mock.patch(
        "bkr.labcontroller.distro_import.importer.is_rhel8_alpha", return_value=False
    )
    @mock.patch(
        "bkr.labcontroller.distro_import.importer.url_exists", return_value=True
    )
    def test_find_repos_returns_repos_for_variant_arch(
        self, mock_url_exists, mock_alpha
    ):
        ci = self._make_compose_info(
            {
                "variant-Server": {"variants": "", "type": "variant"},
                "variant-Server.x86_64": {
                    "repository": "Server/x86_64/os",
                    "debuginfo": "Server/x86_64/debuginfo",
                },
            }
        )
        repos = ci.find_repos("http://base", "../..", "Server", "x86_64")
        repoids = [r["repoid"] for r in repos]
        self.assertIn("Server", repoids)
        self.assertIn("Server-debuginfo", repoids)

    @mock.patch(
        "bkr.labcontroller.distro_import.importer.is_rhel8_alpha", return_value=False
    )
    @mock.patch(
        "bkr.labcontroller.distro_import.importer.url_exists", return_value=True
    )
    def test_find_repos_follows_sub_variants(self, mock_url_exists, mock_alpha):
        ci = self._make_compose_info(
            {
                "variant-Server": {"variants": "Server-optional", "type": "variant"},
                "variant-Server.x86_64": {
                    "repository": "Server/x86_64/os",
                    "debuginfo": "",
                },
                "variant-Server-optional": {"variants": "", "type": "optional"},
                "variant-Server-optional.x86_64": {
                    "repository": "Server-optional/x86_64/os",
                    "debuginfo": "",
                },
            }
        )
        repos = ci.find_repos("http://base", "../..", "Server", "x86_64")
        repoids = [r["repoid"] for r in repos]
        self.assertIn("Server", repoids)
        self.assertIn("Server-optional", repoids)

    @mock.patch(
        "bkr.labcontroller.distro_import.importer.is_rhel8_alpha", return_value=False
    )
    @mock.patch(
        "bkr.labcontroller.distro_import.importer.url_exists", return_value=True
    )
    def test_find_repos_skips_addon_type(self, mock_url_exists, mock_alpha):
        ci = self._make_compose_info(
            {
                "variant-Server": {"variants": "Server-HA", "type": "variant"},
                "variant-Server.x86_64": {
                    "repository": "Server/x86_64/os",
                    "debuginfo": "",
                },
                "variant-Server-HA": {"variants": "", "type": "addon"},
                "variant-Server-HA.x86_64": {
                    "repository": "Server-HA/x86_64/os",
                    "debuginfo": "",
                },
            }
        )
        repos = ci.find_repos("http://base", "../..", "Server", "x86_64")
        repoids = [r["repoid"] for r in repos]
        self.assertIn("Server", repoids)
        self.assertNotIn("Server-HA", repoids)

    @mock.patch(
        "bkr.labcontroller.distro_import.importer.is_rhel8_alpha", return_value=False
    )
    @mock.patch(
        "bkr.labcontroller.distro_import.importer.url_exists", return_value=True
    )
    def test_find_repos_includes_debuginfo(self, mock_url_exists, mock_alpha):
        ci = self._make_compose_info(
            {
                "variant-Server": {"variants": "", "type": "variant"},
                "variant-Server.x86_64": {
                    "repository": "Server/x86_64/os",
                    "debuginfo": "Server/x86_64/debuginfo",
                },
            }
        )
        repos = ci.find_repos("http://base", "../..", "Server", "x86_64")
        debug_repos = [r for r in repos if r["type"] == "debug"]
        self.assertEqual(len(debug_repos), 1)
        self.assertEqual(debug_repos[0]["repoid"], "Server-debuginfo")

    @mock.patch(
        "bkr.labcontroller.distro_import.importer.is_rhel8_alpha", return_value=False
    )
    @mock.patch(
        "bkr.labcontroller.distro_import.importer.url_exists", return_value=False
    )
    def test_find_repos_warns_when_repo_missing(self, mock_url_exists, mock_alpha):
        ci = self._make_compose_info(
            {
                "variant-Server": {"variants": "", "type": "variant"},
                "variant-Server.x86_64": {
                    "repository": "Server/x86_64/os",
                    "debuginfo": "",
                },
            }
        )
        with mock.patch(
            "bkr.labcontroller.distro_import.importer.logging"
        ) as mock_logging:
            repos = ci.find_repos("http://base", "../..", "Server", "x86_64")
            mock_logging.warn.assert_called()
        self.assertEqual(repos, [])
