# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import logging
import json
import pprint
import socket
import dnf
import uuid

from bkr.common.bexceptions import BX

from six.moves import configparser
from six.moves import urllib
from six.moves import xmlrpc_client

from bkr.labcontroller.distro_import.utils import (
    url_exists,
    IncompleteTree,
    _get_url_by_scheme,
)
from bkr.labcontroller.distro_import.proxy import SchedulerProxy
from bkr.labcontroller.distro_import.parser import Tparser, TparserRhel5
from bkr.labcontroller.distro_import.importer import Importer


class TreeInfoMixin(object):
    """
    Base class for TreeInfo methods
    """

    required = [
        dict(section="general", key="family"),
        dict(section="general", key="version"),
        dict(section="general", key="arch"),
    ]
    excluded = []

    # This is a best guess for the relative iso path
    # for RHEL5/6/7 and Fedora trees
    isos_path = "../iso/"

    def check_input(self, options):
        self.check_variants(options.variant, single=False)
        self.check_arches(options.arch, single=False)

    def get_os_dir(self):
        """Return path to os directory
        This is just a sanity check, the parser's URL should be the os dir.
        """
        try:
            os_dir = filter(lambda x: url_exists(x) and x, [self.parser.url])[0]
        except IndexError as e:
            raise BX("%s no os_dir found: %s" % (self.parser.url, e))
        return os_dir

    def _installable_isos_url(self, nfs_url, isos_path_from_compose=None):
        """Returns the URL of an installable iso.

        The scheme of the returned URL is 'nfs+iso',
        which only has meaning to Beaker.
        """

        isos_path = isos_path_from_compose
        if not isos_path_from_compose:
            # Let's just guess! These are based on
            # well known locations for each family
            isos_path = self.isos_path
        http_url_components = list(urllib.parse.urlparse(self.parser.url))
        http_url_path = http_url_components[2]
        normalized_isos_path = os.path.normpath(os.path.join(http_url_path, isos_path))
        if not normalized_isos_path.endswith("/"):
            normalized_isos_path += "/"
        http_url_components[2] = normalized_isos_path
        http_isos_url = urllib.parse.urlunparse(http_url_components)
        reachable_iso_dir = url_exists(http_isos_url)
        if isos_path_from_compose and not reachable_iso_dir:
            # If .composeinfo says the isos path is there but it isn't, we
            # should let it be known.
            raise IncompleteTree(
                "Could not find iso url %s as specified in composeinfo" % http_isos_url
            )
        elif not isos_path_from_compose and not reachable_iso_dir:
            # We can't find the isos path, but we were only ever guessing.
            return None
        elif reachable_iso_dir:
            # We've found the isos path via http, convert it back to
            # nfs+iso URL.
            nfs_url_components = list(urllib.parse.urlparse(nfs_url))
            nfs_url_path = nfs_url_components[2]
            normalized_isos_path = os.path.normpath(
                os.path.join(nfs_url_path, isos_path)
            )
            if not normalized_isos_path.endswith("/"):
                normalized_isos_path += "/"
            nfs_isos_url_components = list(nfs_url_components)
            nfs_isos_url_components[2] = normalized_isos_path
            nfs_isos_url_components[0] = "nfs+iso"
            return urllib.parse.urlunparse(nfs_isos_url_components)

    def process(self, urls, options, repos=None, tags=None, isos_path=None):
        """
        distro_data = dict(
                name='RHEL-6-U1',
                arches=['i386', 'x86_64'], arch='x86_64',
                osmajor='RedHatEnterpriseLinux6', osminor='1',
                variant='Workstation', tree_build_time=1305067998.6483951,
                urls=['nfs://example.invalid:/RHEL-6-Workstation/U1/x86_64/os/',
                      'file:///net/example.invalid/RHEL-6-Workstation/U1/x86_64/os/',
                      'http://example.invalid/RHEL-6-Workstation/U1/x86_64/os/'],
                repos=[
                    dict(repoid='Workstation', type='os', path=''),
                    dict(repoid='ScalableFileSystem', type='addon', path='ScalableFileSystem/'),
                    dict(repoid='optional', type='addon', path='../../optional/x86_64/os/'),
                    dict(repoid='debuginfo', type='debug', path='../debug/'),
                ],
                images=[
                    dict(type='kernel', path='images/pxeboot/vmlinuz'),
                    dict(type='initrd', path='images/pxeboot/initrd.img'),
                ])

        """
        if not repos:
            repos = []
        self.options = options
        self.scheduler = SchedulerProxy(options)
        self.tree = dict()
        # Make sure all url's end with /
        urls = [os.path.join(url, "") for url in urls]
        self.tree["urls"] = urls
        family = self.options.family or self.parser.get("general", "family").replace(
            " ", ""
        )
        version = self.options.version or self.parser.get("general", "version").replace(
            "-", "."
        )
        self.tree["name"] = self.options.name or self.parser.get(
            "general", "name", "%s-%s" % (family, version)
        )

        try:
            self.tree["variant"] = self.options.variant[0]
        except IndexError:
            self.tree["variant"] = self.parser.get("general", "variant", "")
        self.tree["arch"] = self.parser.get("general", "arch")
        self.tree["tree_build_time"] = self.options.buildtime or self.parser.get(
            "general", "timestamp", self.parser.last_modified
        )
        common_tags = tags or []  # passed in from .composeinfo
        labels = self.parser.get("general", "label", "")
        self.tree["tags"] = list(
            set(self.options.tags)
            | set(common_tags)
            | set(map(lambda label: label.strip(), labels and labels.split(",") or []))
        )
        self.tree["osmajor"] = "%s%s" % (family, version.split(".")[0])
        if version.find(".") != -1:
            self.tree["osminor"] = version.split(".")[1]
        else:
            self.tree["osminor"] = "0"

        arches = self.parser.get("general", "arches", "")
        self.tree["arches"] = map(
            lambda arch: arch.strip(), arches and arches.split(",") or []
        )
        full_os_dir = self.get_os_dir()
        # These would have been passed from the Compose*.process()
        common_repos = repos
        if not common_repos:
            common_repos = self.find_common_repos(full_os_dir, self.tree["arch"])
        self.tree["repos"] = self.find_repos() + common_repos

        # Add install images
        self.tree["images"] = self.get_images()

        if not self.options.preserve_install_options:
            self.tree["kernel_options"] = self.options.kopts
            self.tree["kernel_options_post"] = self.options.kopts_post
            self.tree["ks_meta"] = self.options.ks_meta
        nfs_url = _get_url_by_scheme(urls, "nfs")
        if nfs_url:
            try:
                nfs_isos_url = self._installable_isos_url(nfs_url, isos_path)
            except IncompleteTree as e:
                logging.warn(str(e))
            else:
                if nfs_isos_url:
                    self.tree["urls"].append(nfs_isos_url)

        self.extend_tree()
        if options.json:
            print(json.dumps(self.tree))
        logging.debug("\n%s" % pprint.pformat(self.tree))
        try:
            self.add_to_beaker()
            logging.info(
                "%s %s %s added to beaker."
                % (self.tree["name"], self.tree["variant"], self.tree["arch"])
            )
        except (xmlrpc_client.Fault, socket.error) as e:
            raise BX(
                "failed to add %s %s %s to beaker: %s"
                % (self.tree["name"], self.tree["variant"], self.tree["arch"], e)
            )

    def extend_tree(self):
        pass

    def find_common_repos(self, repo_base, arch):
        """
        RHEL6 repos
        ../../optional/<ARCH>/os/repodata
        ../../optional/<ARCH>/debug/repodata
        ../debug/repodata
        """
        repo_paths = [
            ("debuginfo", "debug", "../debug"),
            ("optional-debuginfo", "debug", "../../optional/%s/debug" % arch),
            ("optional", "optional", "../../optional/%s/os" % arch),
        ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(repo_base, repo[2], "repodata")):
                repos.append(
                    dict(
                        repoid=repo[0],
                        type=repo[1],
                        path=repo[2],
                    )
                )
        return repos

    def get_images(self):
        images = []
        images.append(dict(type="kernel", path=self.get_kernel_path()))
        images.append(dict(type="initrd", path=self.get_initrd_path()))
        return images

    def add_to_beaker(self):
        self.scheduler.add_distro(self.tree)

    def run_jobs(self):
        arches = [self.tree["arch"]]
        variants = [self.tree["variant"]]
        name = self.tree["name"]
        tags = self.tree.get("tags", [])
        osversion = "%s.%s" % (self.tree["osmajor"], self.tree["osminor"])
        self.scheduler.run_distro_test_job(
            name=name, tags=tags, osversion=osversion, arches=arches, variants=variants
        )


class TreeInfoLegacy(TreeInfoMixin, Importer):
    """
    This version of .treeinfo importer has a workaround for missing
    images-$arch sections.
    """

    kernels = [
        "images/pxeboot/vmlinuz",
        "images/kernel.img",
        "ppc/ppc64/vmlinuz",
        "ppc/chrp/vmlinuz",
        # We don't support iSeries right now 'ppc/iSeries/vmlinux',
    ]
    initrds = [
        "images/pxeboot/initrd.img",
        "images/initrd.img",
        "ppc/ppc64/ramdisk.image.gz",
        "ppc/chrp/ramdisk.image.gz",
        # We don't support iSeries right now 'ppc/iSeries/ramdisk.image.gz',
    ]

    isos_path = "../ftp-isos/"

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if not (
            parser.get("general", "family").startswith("Red Hat Enterprise Linux")
            or parser.get("general", "family").startswith("CentOS")
        ):
            return False
        if int(parser.get("general", "version").split(".")[0]) > 4:
            return False
        return parser

    def get_kernel_path(self):
        try:
            return list(
                filter(
                    lambda x: url_exists(os.path.join(self.parser.url, x)) and x,
                    [kernel for kernel in self.kernels],
                )
            )[0]
        except IndexError as e:
            raise BX("%s no kernel found: %s" % (self.parser.url, e))

    def get_initrd_path(self):
        try:
            return list(
                filter(
                    lambda x: url_exists(os.path.join(self.parser.url, x)) and x,
                    [initrd for initrd in self.initrds],
                )
            )[0]
        except IndexError as e:
            raise BX("%s no kernel found: %s" % (self.parser.url, e))

    def find_repos(self, *args, **kw):
        """
        using info from .treeinfo and known locations

        RHEL4 repos
        ../repo-<VARIANT>-<ARCH>/repodata
        ../repo-debug-<VARIANT>-<ARCH>/repodata
        ../repo-srpm-<VARIANT>-<ARCH>/repodata
        arch = ppc64 = ppc

        RHEL3 repos
        ../repo-<VARIANT>-<ARCH>/repodata
        ../repo-debug-<VARIANT>-<ARCH>/repodata
        ../repo-srpm-<VARIANT>-<ARCH>/repodata
        arch = ppc64 = ppc
        """
        repos = []
        # ppc64 arch uses ppc for the repos
        arch = self.tree["arch"].replace("ppc64", "ppc")

        repo_paths = [
            ("%s-debuginfo" % self.tree["variant"], "debug", "../debug"),
            (
                "%s-debuginfo" % self.tree["variant"],
                "debug",
                "../repo-debug-%s-%s" % (self.tree["variant"], arch),
            ),
            (
                "%s-optional-debuginfo" % self.tree["variant"],
                "debug",
                "../optional/%s/debug" % arch,
            ),
            (
                "%s" % self.tree["variant"],
                "variant",
                "../repo-%s-%s" % (self.tree["variant"], arch),
            ),
            ("%s" % self.tree["variant"], "variant", "."),
            (
                "%s-optional" % self.tree["variant"],
                "optional",
                "../../optional/%s/os" % arch,
            ),
            ("VT", "addon", "VT"),
            ("Server", "addon", "Server"),
            ("Cluster", "addon", "Cluster"),
            ("ClusterStorage", "addon", "ClusterStorage"),
            ("Client", "addon", "Client"),
            ("Workstation", "addon", "Workstation"),
        ]
        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url, repo[2], "repodata")):
                repos.append(
                    dict(
                        repoid=repo[0],
                        type=repo[1],
                        path=repo[2],
                    )
                )
        return repos


class TreeInfoRhel5(TreeInfoMixin, Importer):
    # Used in RHEL5 and all CentOS releases from 5 onwards.
    # Has image locations but no repo info so we guess that.
    """
    [general]
    family = Red Hat Enterprise Linux Server
    timestamp = 1209596791.91
    totaldiscs = 1
    version = 5.2
    discnum = 1
    label = RELEASED
    packagedir = Server
    arch = ppc

    [images-ppc64]
    kernel = ppc/ppc64/vmlinuz
    initrd = ppc/ppc64/ramdisk.image.gz
    zimage = images/netboot/ppc64.img

    [stage2]
    instimage = images/minstg2.img
    mainimage = images/stage2.img

    """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = TparserRhel5()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if (
            not parser.has_section_startswith("images-")
            or parser.has_option("general", "repository")
            or parser.has_section_startswith("variant-")
            or parser.has_section_startswith("addon-")
        ):
            return False
        # Fedora has a special case below, see TreeInfoFedora
        if "Fedora" in parser.get("general", "family"):
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")

    def find_repos(self):
        """
        using info from known locations

        RHEL5 repos
        ../debug/repodata
        ./Server
        ./Cluster
        ./ClusterStorage
        ./VT
        ./Client
        ./Workstation

        CentOS repos
        .
        """
        # ppc64 arch uses ppc for the repos
        arch = self.tree["arch"].replace("ppc64", "ppc")

        repo_paths = [
            ("VT", "addon", "VT"),
            ("Server", "addon", "Server"),
            ("Cluster", "addon", "Cluster"),
            ("ClusterStorage", "addon", "ClusterStorage"),
            ("Client", "addon", "Client"),
            ("Workstation", "addon", "Workstation"),
            ("distro", "distro", "."),
        ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url, repo[2], "repodata")):
                repos.append(
                    dict(
                        repoid=repo[0],
                        type=repo[1],
                        path=repo[2],
                    )
                )
        return repos


class TreeInfoFedora(TreeInfoMixin, Importer):
    # This is basically the same as TreeInfoRHEL5 except that it hardcodes
    # 'Fedora' in the repoids.
    """ """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if not parser.get("general", "family").startswith("Fedora"):
            return False
        # Arm uses a different importer because of all the kernel types.
        if parser.get("general", "arch") in ["arm", "armhfp"]:
            return False
        return parser

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")

    def find_common_repos(self, repo_base, arch):
        """
        Fedora repos
        ../debug/repodata
        """
        repo_paths = [
            ("Fedora-debuginfo", "debug", "../debug"),
        ]
        repos = []
        for repo in repo_paths:
            if url_exists(os.path.join(repo_base, repo[2], "repodata")):
                repos.append(
                    dict(
                        repoid=repo[0],
                        type=repo[1],
                        path=repo[2],
                    )
                )
        return repos

    def find_repos(self):
        """
        using info from known locations

        """
        repos = []
        repo_paths = [
            ("Fedora", "variant", "."),
            (
                "Fedora-Everything",
                "fedora",
                "../../../Everything/%s/os" % self.tree["arch"],
            ),
        ]

        for repo in repo_paths:
            if url_exists(os.path.join(self.parser.url, repo[2], "repodata")):
                repos.append(
                    dict(
                        repoid=repo[0],
                        type=repo[1],
                        path=repo[2],
                    )
                )

        return repos


class TreeInfoFedoraArm(TreeInfoFedora, Importer):
    """ """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if not parser.get("general", "family").startswith("Fedora"):
            return False
        # Arm uses a different importer because of all the kernel types.
        if parser.get("general", "arch") not in ["arm", "armhfp"]:
            return False
        return parser

    def get_kernel_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "kernel"
        )

    def get_initrd_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "initrd"
        )

    def get_uimage_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "uimage", ""
        )

    def get_uinitrd_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "uinitrd", ""
        )

    def get_images(self):
        images = []
        images.append(dict(type="kernel", path=self.get_kernel_path()))
        images.append(dict(type="initrd", path=self.get_initrd_path()))
        uimage = self.get_uimage_path()
        if uimage:
            images.append(dict(type="uimage", path=uimage))
        uinitrd = self.get_uinitrd_path()
        if uinitrd:
            images.append(dict(type="uinitrd", path=uinitrd))
        kernel_type_string = self.parser.get(self.tree["arch"], "platforms", "")
        kernel_types = map(
            lambda item: item.strip(),
            kernel_type_string and kernel_type_string.split(",") or [],
        )
        for kernel_type in kernel_types:
            images.append(
                dict(
                    type="kernel",
                    kernel_type=kernel_type,
                    path=self.get_kernel_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="uimage",
                    kernel_type=kernel_type,
                    path=self.get_uimage_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="initrd",
                    kernel_type=kernel_type,
                    path=self.get_initrd_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="uinitrd",
                    kernel_type=kernel_type,
                    path=self.get_uinitrd_path(kernel_type=kernel_type),
                )
            )
        return images


class TreeInfoRhel6(TreeInfoMixin, Importer):
    # Used in RHS2 and RHEL6.
    # variant-* section has a repository key, and an addons key pointing at
    # addon-* sections.
    """
    [addon-ScalableFileSystem]
    identity = ScalableFileSystem/ScalableFileSystem.cert
    name = Scalable Filesystem Support
    repository = ScalableFileSystem

    [addon-ResilientStorage]
    identity = ResilientStorage/ResilientStorage.cert
    name = Resilient Storage
    repository = ResilientStorage

    [images-x86_64]
    kernel = images/pxeboot/vmlinuz
    initrd = images/pxeboot/initrd.img
    boot.iso = images/boot.iso

    [general]
    family = Red Hat Enterprise Linux
    timestamp = 1328166952.001091
    variant = Server
    totaldiscs = 1
    version = 6.3
    discnum = 1
    packagedir = Packages
    variants = Server
    arch = x86_64

    [images-xen]
    initrd = images/pxeboot/initrd.img
    kernel = images/pxeboot/vmlinuz

    [variant-Server]
    addons = ResilientStorage,HighAvailability,ScalableFileSystem,LoadBalancer
    identity = Server/Server.cert
    repository = Server/repodata

    [addon-HighAvailability]
    identity = HighAvailability/HighAvailability.cert
    name = High Availability
    repository = HighAvailability

    [checksums]
    images/pxeboot/initrd.img = sha256:4ffa63cd7780ec0715bd1c50b9eda177ecf28c58094ca519cfb6bb6aca5c225a
    images/efiboot.img = sha256:d9ba2cc6fd3286ed7081ce0846e9df7093f5d524461580854b7ac42259c574b1
    images/boot.iso = sha256:5e10d6d4e6e22a62cae1475da1599a8dac91ff7c3783fda7684cf780e067604b
    images/pxeboot/vmlinuz = sha256:7180f7f46682555cb1e86a9f1fbbfcc193ee0a52501de9a9002c34528c3ef9ab
    images/install.img = sha256:85aaf9f90efa4f43475e4828168a3f7755ecc62f6643d92d23361957160dbc69
    images/efidisk.img = sha256:e9bf66f54f85527e595c4f3b5afe03cdcd0bf279b861c7a20898ce980e2ce4ff

    [stage2]
    mainimage = images/install.img

    [addon-LoadBalancer]
    identity = LoadBalancer/LoadBalancer.cert
    name = Load Balancer
    repository = LoadBalancer
    """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if parser.get("images-%s" % parser.get("general", "arch"), "kernel", "") == "":
            return False
        if parser.get("images-%s" % parser.get("general", "arch"), "initrd", "") == "":
            return False
        if not (
            parser.has_section_startswith("images-")
            and parser.has_section_startswith("variant-")
        ):
            return False
        for section in parser.sections():
            if section.startswith("variant-") and not parser.has_option(
                section, "addons"
            ):
                return False
        return parser

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")

    def find_repos(self):
        """
        using info from .treeinfo
        """

        repos = []
        try:
            repopath = self.parser.get(
                "variant-%s" % self.tree["variant"], "repository"
            )
            # remove the /repodata from the entry, this should not be there
            repopath = repopath.replace("/repodata", "")
            repos.append(
                dict(
                    repoid=str(self.tree["variant"]),
                    type="variant",
                    path=repopath,
                )
            )
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logging.debug(
                ".treeinfo has no repository for variant %s, %s" % (self.parser.url, e)
            )
        try:
            addons = self.parser.get("variant-%s" % self.tree["variant"], "addons")
            addons = addons and addons.split(",") or []
            for addon in addons:
                repopath = self.parser.get("addon-%s" % addon, "repository", "")
                if repopath:
                    repos.append(
                        dict(
                            repoid=addon,
                            type="addon",
                            path=repopath,
                        )
                    )
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logging.debug(
                ".treeinfo has no addon repos for %s, %s" % (self.parser.url, e)
            )
        return repos


class TreeInfoRHVH4(TreeInfoMixin, Importer):
    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        if parser.get("general", "family") != "RHVH":
            return False
        return parser

    def extend_tree(self):
        kopts = self.tree.get("kernel_options") or ""
        self.tree["kernel_options"] = kopts + " inst.stage2=%s" % self.parser.url
        img_rpm = self._find_image_update_rpm()
        ks_meta = self.tree.get("ks_meta") or ""

        # RHVH assumes that installation is happening based on 'inst.ks' on kernel cmdline
        ks_keyword = "ks_keyword=inst.ks"
        autopart_type = "autopart_type=thinp liveimg={}".format(img_rpm)
        self.tree["ks_meta"] = "{} {} {}".format(ks_meta, autopart_type, ks_keyword)

    def _find_image_update_rpm(self):
        base = dnf.Base()
        base.repos.add_new_repo(uuid.uuid4().hex, base.conf, baseurl=[self.parser.url])
        base.fill_sack(load_system_repo=False)
        pkgs = (
            base.sack.query()
            .filter(name="redhat-virtualization-host-image-update")
            .run()
        )
        if not pkgs:
            raise IncompleteTree("Could not find a valid RHVH rpm")
        return pkgs[0].relativepath

    def find_repos(self):
        return []

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")


class TreeInfoRhel7(TreeInfoMixin, Importer):
    # Used in RHEL7 GA.
    # Main variant-* section has a repository and a variants key pointing at
    # addons (represented as additional variants).

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if parser.has_option("general", "addons") or not parser.has_section_startswith(
            "variant-"
        ):
            return False
        return parser

    def find_repos(self):
        repos = []
        try:
            addons = self.parser.get("variant-%s" % self.tree["variant"], "variants")
            addons = addons.split(",")
            for addon in addons:
                addon_section = "variant-%s" % addon
                addon_type = self.parser.get(addon_section, "type", "")
                # The type should be self-evident, but let's double check
                if addon_type == "addon":
                    repopath = self.parser.get(addon_section, "repository", "")
                    if repopath:
                        repos.append(
                            dict(
                                repoid=self.parser.get(addon_section, "id"),
                                type="addon",
                                path=repopath,
                            )
                        )
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logging.debug("no addon repos for %s, %s" % (self.parser.url, e))
        return repos

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")


class TreeInfoRhel(TreeInfoMixin, Importer):
    # Only used in RHEL7 prior to GA?!?
    # No variant-* sections, general has repository key, and addons key
    # pointing at addon-* sections.
    """
    [addon-HighAvailability]
    id = HighAvailability
    name = High Availability
    repository = addons/HighAvailability
    uid = Server-HighAvailability

    [addon-LoadBalancer]
    id = LoadBalancer
    name = Load Balancer
    repository = addons/LoadBalancer
    uid = Server-LoadBalancer

    [addon-ResilientStorage]
    id = ResilientStorage
    name = Resilient Storage
    repository = addons/ResilientStorage
    uid = Server-ResilientStorage

    [addon-ScalableFileSystem]
    id = ScalableFileSystem
    name = Scalable Filesystem Support
    repository = addons/ScalableFileSystem
    uid = Server-ScalableFileSystem

    [general]
    addons = HighAvailability,LoadBalancer,ResilientStorage,ScalableFileSystem
    arch = x86_64
    family = Red Hat Enterprise Linux
    version = 7.0
    variant = Server
    timestamp =
    name = RHEL-7.0-20120201.0
    repository =

    [images-x86_64]
    boot.iso = images/boot.iso
    initrd = images/pxeboot/initrd.img
    kernel = images/pxeboot/vmlinuz

    [images-xen]
    initrd = images/pxeboot/initrd.img
    kernel = images/pxeboot/vmlinuz

    """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if parser.get("images-%s" % parser.get("general", "arch"), "kernel", "") == "":
            return False
        if parser.get("images-%s" % parser.get("general", "arch"), "initrd", "") == "":
            return False
        if not parser.has_option(
            "general", "repository"
        ) or parser.has_section_startswith("variant-"):
            return False
        # Arm uses a different importer because of all the kernel types.
        if parser.get("general", "arch") in ["arm", "armhfp"]:
            return False
        return parser

    def find_repos(self):
        """
        using info from .treeinfo find addon repos
        """
        repos = []
        repos.append(
            dict(
                repoid="distro",
                type="distro",
                path=self.parser.get("general", "repository"),
            )
        )
        try:
            addons = self.parser.get("general", "addons")
            addons = addons and addons.split(",") or []
            for addon in addons:
                repopath = self.parser.get("addon-%s" % addon, "repository", "")
                if repopath:
                    repos.append(
                        dict(
                            repoid=addon,
                            type="addon",
                            path=repopath,
                        )
                    )
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logging.debug("no addon repos for %s, %s" % (self.parser.url, e))
        return repos

    def get_kernel_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "kernel")

    def get_initrd_path(self):
        return self.parser.get("images-%s" % self.tree["arch"], "initrd")


class TreeInfoRhelArm(TreeInfoRhel, Importer):
    """
    [addon-HighAvailability]
    id = HighAvailability
    name = High Availability
    repository = addons/HighAvailability
    uid = Server-HighAvailability

    [addon-LoadBalancer]
    id = LoadBalancer
    name = Load Balancer
    repository = addons/LoadBalancer
    uid = Server-LoadBalancer

    [addon-ResilientStorage]
    id = ResilientStorage
    name = Resilient Storage
    repository = addons/ResilientStorage
    uid = Server-ResilientStorage

    [addon-ScalableFileSystem]
    id = ScalableFileSystem
    name = Scalable Filesystem Support
    repository = addons/ScalableFileSystem
    uid = Server-ScalableFileSystem

    [general]
    addons = HighAvailability,LoadBalancer,ResilientStorage,ScalableFileSystem
    arch = x86_64
    family = Red Hat Enterprise Linux
    version = 7.0
    variant = Server
    timestamp =
    name = RHEL-7.0-20120201.0
    repository =

    [images-x86_64]
    boot.iso = images/boot.iso
    initrd = images/pxeboot/initrd.img
    kernel = images/pxeboot/vmlinuz

    [images-xen]
    initrd = images/pxeboot/initrd.img
    kernel = images/pxeboot/vmlinuz

    """

    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Tparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        if parser.get("images-%s" % parser.get("general", "arch"), "kernel", "") == "":
            return False
        if parser.get("images-%s" % parser.get("general", "arch"), "initrd", "") == "":
            return False
        if not parser.has_option(
            "general", "repository"
        ) or parser.has_section_startswith("variant-"):
            return False
        # Arm uses a different importer because of all the kernel types.
        if parser.get("general", "arch") not in ["arm", "armhfp"]:
            return False
        return parser

    def get_kernel_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "kernel"
        )

    def get_initrd_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "initrd"
        )

    def get_uimage_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "uimage", ""
        )

    def get_uinitrd_path(self, kernel_type=None):
        if kernel_type:
            kernel_type = "%s-" % kernel_type
        else:
            kernel_type = ""
        return self.parser.get(
            "images-%s%s" % (kernel_type, self.tree["arch"]), "uinitrd", ""
        )

    def get_images(self):
        images = []
        images.append(dict(type="kernel", path=self.get_kernel_path()))
        images.append(dict(type="initrd", path=self.get_initrd_path()))
        uimage = self.get_uimage_path()
        if uimage:
            images.append(dict(type="uimage", path=uimage))
        uinitrd = self.get_uinitrd_path()
        if uinitrd:
            images.append(dict(type="uinitrd", path=uinitrd))
        kernel_type_string = self.parser.get(self.tree["arch"], "platforms", "")
        kernel_types = map(
            lambda item: item.strip(),
            kernel_type_string and kernel_type_string.split(",") or [],
        )
        for kernel_type in kernel_types:
            images.append(
                dict(
                    type="kernel",
                    kernel_type=kernel_type,
                    path=self.get_kernel_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="uimage",
                    kernel_type=kernel_type,
                    path=self.get_uimage_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="initrd",
                    kernel_type=kernel_type,
                    path=self.get_initrd_path(kernel_type=kernel_type),
                )
            )
            images.append(
                dict(
                    type="uinitrd",
                    kernel_type=kernel_type,
                    path=self.get_uinitrd_path(kernel_type=kernel_type),
                )
            )
        return images
