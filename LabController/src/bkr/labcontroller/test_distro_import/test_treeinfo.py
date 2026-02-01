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
    IncompleteTree,
    TreeInfoFedora,
    TreeInfoFedoraArm,
    TreeInfoLegacy,
    TreeInfoRHVH4,
    TreeInfoRhel,
    TreeInfoRhel5,
    TreeInfoRhel6,
    TreeInfoRhel7,
    TreeInfoRhelArm,
)

from bkr.labcontroller.test_distro_import import (
    _fake_parser_get_tuples,
    _mock_urlopen,
    _mock_urlopen_discinfo,
)


class TestTreeInfoMixinInstallableIsosUrl(unittest.TestCase):
    def _make_tree(self, parser_url="http://example.com/RHEL7/Server/x86_64/os"):
        mock_parser = mock.Mock()
        mock_parser.url = parser_url
        tree = TreeInfoLegacy(mock_parser)
        tree.tree = {}
        return tree

    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=True
    )
    def test_returns_nfs_iso_url_when_http_exists(self, mock_url_exists):
        result = self._make_tree()._installable_isos_url(
            "nfs://server.example.com:/export/RHEL7/Server/x86_64/os"
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("nfs+iso://"))

    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=False
    )
    def test_returns_none_when_guessed_path_missing(self, mock_url_exists):
        result = self._make_tree()._installable_isos_url(
            "nfs://server.example.com:/export/RHEL7/Server/x86_64/os"
        )
        self.assertIsNone(result)

    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=False
    )
    def test_raises_incomplete_tree_when_compose_isos_missing(self, mock_url_exists):
        with self.assertRaises(IncompleteTree):
            self._make_tree()._installable_isos_url(
                "nfs://server.example.com:/export/RHEL7/Server/x86_64/os",
                isos_path_from_compose="../iso",
            )


class TestTreeInfoLegacyIsImporterFor(unittest.TestCase):
    def _treeinfo(self, family, version, extra_sections=""):
        return "[general]\nfamily = %s\nversion = %s\narch = x86_64\n%s" % (
            family,
            version,
            extra_sections,
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhel4(self, mock_urlopen):
        content = self._treeinfo("Red Hat Enterprise Linux Server", "4.8")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoLegacy.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_rhel7(self, mock_urlopen):
        content = self._treeinfo("Red Hat Enterprise Linux Server", "7.0")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoLegacy.is_importer_for("http://example.com/tree"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_centos4(self, mock_urlopen):
        content = self._treeinfo("CentOS", "4.8")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoLegacy.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_fedora(self, mock_urlopen):
        content = self._treeinfo("Fedora", "30")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoLegacy.is_importer_for("http://example.com/tree"))


class TestTreeInfoRhel5IsImporterFor(unittest.TestCase):
    def _treeinfo(
        self,
        family="Red Hat Enterprise Linux Server",
        version="5.2",
        arch="x86_64",
        extra="",
    ):
        return (
            "[general]\n"
            "family = %s\n"
            "version = %s\n"
            "arch = %s\n"
            "%s"
            "[images-%s]\n"
            "kernel = images/pxeboot/vmlinuz\n"
            "initrd = images/pxeboot/initrd.img\n"
        ) % (family, version, arch, extra, arch)

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhel5(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self._treeinfo()),
            _mock_urlopen_discinfo(),
        ]
        self.assertNotEqual(
            TreeInfoRhel5.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_fedora(self, mock_urlopen):
        content = self._treeinfo(family="Fedora", version="30")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoRhel5.is_importer_for("http://example.com/tree"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_when_has_repository(self, mock_urlopen):
        content = self._treeinfo(extra="repository = .\n")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoRhel5.is_importer_for("http://example.com/tree"))


class TestTreeInfoFedoraIsImporterFor(unittest.TestCase):
    def _treeinfo(self, family="Fedora", arch="x86_64"):
        return (
            "[general]\n"
            "family = %s\n"
            "version = 30\n"
            "arch = %s\n"
            "[images-%s]\n"
            "kernel = images/pxeboot/vmlinuz\n"
            "initrd = images/pxeboot/initrd.img\n"
        ) % (family, arch, arch)

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_fedora(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self._treeinfo()),
            _mock_urlopen_discinfo(),
        ]
        self.assertNotEqual(
            TreeInfoFedora.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_rhel(self, mock_urlopen):
        content = self._treeinfo(family="Red Hat Enterprise Linux")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoFedora.is_importer_for("http://example.com/tree"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_arm(self, mock_urlopen):
        content = self._treeinfo(arch="armhfp")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoFedora.is_importer_for("http://example.com/tree"))


class TestTreeInfoFedoraArmIsImporterFor(unittest.TestCase):
    FEDORA_ARM = (
        "[general]\n"
        "family = Fedora\n"
        "version = 30\n"
        "arch = armhfp\n"
        "[images-armhfp]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
    )

    FEDORA_X86 = (
        "[general]\n"
        "family = Fedora\n"
        "version = 30\n"
        "arch = x86_64\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_fedora_arm(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.FEDORA_ARM),
            _mock_urlopen_discinfo(),
        ]
        self.assertNotEqual(
            TreeInfoFedoraArm.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_fedora_x86_64(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.FEDORA_X86),
            _mock_urlopen_discinfo(),
        ]
        self.assertFalse(TreeInfoFedoraArm.is_importer_for("http://example.com/tree"))


class TestTreeInfoRhel6IsImporterFor(unittest.TestCase):
    RHEL6 = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 6.3\n"
        "arch = x86_64\n"
        "variant = Server\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[variant-Server]\n"
        "addons = HighAvailability\n"
        "repository = Server/repodata\n"
    )

    NO_ADDONS = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = x86_64\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[variant-Server]\n"
        "variants = Server-optional\n"
        "repository = Server/repodata\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhel6(self, mock_urlopen):
        mock_urlopen.side_effect = [_mock_urlopen(self.RHEL6), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoRhel6.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_when_no_addons_in_variant(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.NO_ADDONS),
            _mock_urlopen_discinfo(),
        ]
        self.assertFalse(TreeInfoRhel6.is_importer_for("http://example.com/tree"))


class TestTreeInfoRhel7IsImporterFor(unittest.TestCase):
    RHEL7 = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = x86_64\n"
        "variant = Server\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[variant-Server]\n"
        "variants = Server-HighAvailability\n"
        "repository = Server\n"
    )

    HAS_GENERAL_ADDONS = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = x86_64\n"
        "addons = HighAvailability\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[variant-Server]\n"
        "variants = Server-HighAvailability\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhel7(self, mock_urlopen):
        mock_urlopen.side_effect = [_mock_urlopen(self.RHEL7), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoRhel7.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_when_has_general_addons(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.HAS_GENERAL_ADDONS),
            _mock_urlopen_discinfo(),
        ]
        self.assertFalse(TreeInfoRhel7.is_importer_for("http://example.com/tree"))


class TestTreeInfoRhelIsImporterFor(unittest.TestCase):
    def _treeinfo(self, arch="x86_64"):
        return (
            "[general]\n"
            "family = Red Hat Enterprise Linux\n"
            "version = 7.0\n"
            "arch = %s\n"
            "repository = .\n"
            "addons = HighAvailability\n"
            "[images-%s]\n"
            "kernel = images/pxeboot/vmlinuz\n"
            "initrd = images/pxeboot/initrd.img\n"
            "[addon-HighAvailability]\n"
            "id = HighAvailability\n"
            "repository = addons/HighAvailability\n"
        ) % (arch, arch)

    HAS_VARIANT_SECTION = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = x86_64\n"
        "repository = .\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[variant-Server]\n"
        "variants = foo\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhel_pre_ga(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self._treeinfo()),
            _mock_urlopen_discinfo(),
        ]
        self.assertNotEqual(
            TreeInfoRhel.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_arm(self, mock_urlopen):
        content = self._treeinfo(arch="armhfp")
        mock_urlopen.side_effect = [_mock_urlopen(content), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoRhel.is_importer_for("http://example.com/tree"))

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_when_has_variant_section(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.HAS_VARIANT_SECTION),
            _mock_urlopen_discinfo(),
        ]
        self.assertFalse(TreeInfoRhel.is_importer_for("http://example.com/tree"))


class TestTreeInfoRhelArmIsImporterFor(unittest.TestCase):
    ARM = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = armhfp\n"
        "repository = .\n"
        "addons = HighAvailability\n"
        "[images-armhfp]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
        "[addon-HighAvailability]\n"
        "id = HighAvailability\n"
        "repository = addons/HighAvailability\n"
    )

    X86 = (
        "[general]\n"
        "family = Red Hat Enterprise Linux\n"
        "version = 7.0\n"
        "arch = x86_64\n"
        "repository = .\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_arm(self, mock_urlopen):
        mock_urlopen.side_effect = [_mock_urlopen(self.ARM), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoRhelArm.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_x86_64(self, mock_urlopen):
        mock_urlopen.side_effect = [_mock_urlopen(self.X86), _mock_urlopen_discinfo()]
        self.assertFalse(TreeInfoRhelArm.is_importer_for("http://example.com/tree"))


class TestTreeInfoRHVH4IsImporterFor(unittest.TestCase):
    RHVH = (
        "[general]\n"
        "family = RHVH\n"
        "version = 4.0\n"
        "arch = x86_64\n"
        "[images-x86_64]\n"
        "kernel = images/pxeboot/vmlinuz\n"
        "initrd = images/pxeboot/initrd.img\n"
    )

    NOT_RHVH = (
        "[general]\nfamily = Red Hat Enterprise Linux\nversion = 7.0\narch = x86_64\n"
    )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_matches_rhvh(self, mock_urlopen):
        mock_urlopen.side_effect = [_mock_urlopen(self.RHVH), _mock_urlopen_discinfo()]
        self.assertNotEqual(
            TreeInfoRHVH4.is_importer_for("http://example.com/tree"), False
        )

    @mock.patch("bkr.labcontroller.distro_import.parser.urllib.request.urlopen")
    def test_rejects_non_rhvh(self, mock_urlopen):
        mock_urlopen.side_effect = [
            _mock_urlopen(self.NOT_RHVH),
            _mock_urlopen_discinfo(),
        ]
        self.assertFalse(TreeInfoRHVH4.is_importer_for("http://example.com/tree"))


class TestTreeInfoRepoFinding(unittest.TestCase):
    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=True
    )
    def test_legacy_find_repos(self, mock_url_exists):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/RHEL4/AS/x86_64/tree"
        imp = TreeInfoLegacy(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "AS"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("AS", repoids)
        self.assertIn("AS-debuginfo", repoids)

    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=True
    )
    def test_rhel5_find_repos(self, mock_url_exists):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/RHEL5/Server/x86_64/os"
        imp = TreeInfoRhel5(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "Server"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("Server", repoids)
        self.assertIn("distro", repoids)

    @mock.patch(
        "bkr.labcontroller.distro_import.treeinfo.url_exists", return_value=True
    )
    def test_fedora_find_repos(self, mock_url_exists):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/Fedora/x86_64/os"
        imp = TreeInfoFedora(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "Fedora"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("Fedora", repoids)
        self.assertIn("Fedora-Everything", repoids)

    def test_rhel6_find_repos(self):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/RHEL6/Server/x86_64/os"
        mock_parser.get.side_effect = _fake_parser_get_tuples(
            {
                ("variant-Server", "repository"): "Server/repodata",
                ("variant-Server", "addons"): "HighAvailability,LoadBalancer",
                ("addon-HighAvailability", "repository"): "HighAvailability",
                ("addon-LoadBalancer", "repository"): "LoadBalancer",
            }
        )
        imp = TreeInfoRhel6(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "Server"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("Server", repoids)
        self.assertIn("HighAvailability", repoids)
        self.assertIn("LoadBalancer", repoids)

    def test_rhel7_find_repos(self):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/RHEL7/Server/x86_64/os"
        mock_parser.get.side_effect = _fake_parser_get_tuples(
            {
                ("variant-Server", "variants"): "Server-HighAvailability",
                ("variant-Server-HighAvailability", "type"): "addon",
                ("variant-Server-HighAvailability", "id"): "HighAvailability",
                (
                    "variant-Server-HighAvailability",
                    "repository",
                ): "addons/HighAvailability",
            }
        )
        imp = TreeInfoRhel7(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "Server"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("HighAvailability", repoids)

    def test_rhel_find_repos(self):
        mock_parser = mock.Mock()
        mock_parser.url = "http://example.com/RHEL7/Server/x86_64/os"
        mock_parser.get.side_effect = _fake_parser_get_tuples(
            {
                ("general", "repository"): ".",
                ("general", "addons"): "HighAvailability",
                ("addon-HighAvailability", "repository"): "addons/HighAvailability",
            }
        )
        imp = TreeInfoRhel(mock_parser)
        imp.tree = {"arch": "x86_64", "variant": "Server"}
        repoids = [r["repoid"] for r in imp.find_repos()]
        self.assertIn("distro", repoids)
        self.assertIn("HighAvailability", repoids)
