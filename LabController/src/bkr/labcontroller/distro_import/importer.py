# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import os
import copy
import logging
import json
import pprint
import time
import socket

from bkr.common.bexceptions import BX

from six.moves import configparser
from six.moves import xmlrpc_client

from bkr.labcontroller.distro_import.utils import (
    url_exists,
    is_rhel8_alpha,
    IncompleteTree,
)
from bkr.labcontroller.distro_import.proxy import SchedulerProxy
from bkr.labcontroller.distro_import.parser import Cparser, Tparser, TparserRhel5


class Importer(object):
    def __init__(self, parser):
        self.parser = parser

    def check_input(self, opts):
        pass

    def check_arches(self, arches, multiple=True, single=True):
        if not arches:
            return
        if len(arches) > 1 and not multiple:
            raise BX(
                "Multiple values for arch are incompatible with %s "
                "importer" % self.__class__.__name__
            )
        if not single:
            raise BX(
                "Specific value for arch is incompatible with %s "
                "importer" % self.__class__.__name__
            )

    def check_variants(self, variants, multiple=True, single=True):
        if not variants:
            return
        if len(variants) > 1 and not multiple:
            raise BX(
                "Multiple values for variant are incompatible with %s "
                "importer" % self.__class__.__name__
            )
        if not single:
            raise BX(
                "Specific value for variant is incompatible with %s "
                "importer" % self.__class__.__name__
            )


class ComposeInfoMixin(object):
    @classmethod
    def is_importer_for(cls, url, options=None):
        parser = Cparser()
        if not parser.parse(url):
            return False
        for r in cls.required:
            if parser.get(r["section"], r["key"], "") == "":
                return False
        for e in cls.excluded:
            if parser.get(e["section"], e["key"], "") != "":
                return False
        return parser

    def run_jobs(self):
        """
        Run a job with the newly imported distro_trees
        """
        arches = []
        variants = []
        for distro_tree in self.distro_trees:
            arches.append(distro_tree["arch"])
            variants.append(distro_tree["variant"])
            name = distro_tree["name"]
            tags = distro_tree.get("tags", [])
            osversion = "%s.%s" % (distro_tree["osmajor"], distro_tree["osminor"])
        self.scheduler.run_distro_test_job(
            name=name,
            tags=tags,
            osversion=osversion,
            arches=list(set(arches)),
            variants=list(set(variants)),
        )


class ComposeInfoLegacy(ComposeInfoMixin, Importer):
    """
    [tree]
    arches = i386,x86_64,ia64,ppc64,s390,s390x
    name = RHEL4-U8
    """

    required = [
        dict(section="tree", key="name"),
    ]
    excluded = [
        dict(section="product", key="variants"),
    ]
    arches = ["i386", "x86_64", "ia64", "ppc", "ppc64", "s390", "s390x"]
    os_dirs = ["os", "tree"]

    def get_arches(self):
        """Return a list of arches"""
        specific_arches = self.options.arch
        if specific_arches:
            return filter(
                lambda x: url_exists(os.path.join(self.parser.url, x)) and x,
                [arch for arch in specific_arches],
            )
        else:
            return filter(
                lambda x: url_exists(os.path.join(self.parser.url, x)) and x,
                [arch for arch in self.arches],
            )

    def get_os_dir(self, arch):
        """Return path to os directory"""
        base_path = os.path.join(self.parser.url, arch)
        try:
            os_dir = list(
                filter(
                    lambda x: url_exists(os.path.join(base_path, x)) and x, self.os_dirs
                )
            )[0]
        except IndexError as e:
            raise BX("%s no os_dir found: %s" % (base_path, e))
        return os.path.join(arch, os_dir)

    def check_input(self, options):
        self.check_variants(options.variant, single=False)

    def process(self, urls, options):
        exit_status = 0

        self.options = options
        self.scheduler = SchedulerProxy(self.options)
        self.distro_trees = []
        for arch in self.get_arches():
            try:
                os_dir = self.get_os_dir(arch)
                full_os_dir = os.path.join(self.parser.url, os_dir)
                options = copy.deepcopy(self.options)
                if not options.name:
                    options.name = self.parser.get("tree", "name")
                urls_arch = [os.path.join(url, os_dir) for url in urls]
                # find our repos, but relative from os_dir
                # repos = self.find_repos(full_os_dir, arch)
                build = Build(full_os_dir)
                build.process(urls_arch, options)
                self.distro_trees.append(build.tree)
            except BX as err:
                if not options.ignore_missing:
                    exit_status = 1
                    logging.warn(err)

        return exit_status


class ComposeInfo(ComposeInfoMixin, Importer):
    """
    [product]
    family = RHEL
    name = Red Hat Enterprise Linux
    variants = Client,ComputeNode,Server,Workstation
    version = 7.0

    [variant-Client]
    arches = x86_64
    id = Client
    name = Client
    type = variant
    uid = Client
    variants = Client-optional

    [variant-Client-optional]
    arches = x86_64
    id = optional
    name = optional
    parent = Client
    type = optional
    uid = Client-optional
    variants =

    [variant-Client-optional.x86_64]
    arch = x86_64
    debuginfo = Client-optional/x86_64/debuginfo
    os_dir = Client-optional/x86_64/os
    packages = Client-optional/x86_64/os/Packages
    parent = Client.x86_64
    repository = Client-optional/x86_64/os
    sources = Client-optional/source/SRPMS

    [variant-Client.x86_64]
    arch = x86_64
    debuginfo = Client/x86_64/debuginfo
    isos = Client/x86_64/iso
    os_dir = Client/x86_64/os
    packages = Client/x86_64/os/Packages
    repository = Client/x86_64/os
    source_isos = Client/source/iso
    sources = Client/source/SRPMS

    [variant-ComputeNode]
    arches = x86_64
    id = ComputeNode
    name = Compute Node
    type = variant
    uid = ComputeNode
    variants = ComputeNode-optional

    [variant-ComputeNode-optional]
    arches = x86_64
    id = optional
    name = optional
    parent = ComputeNode
    type = optional
    uid = ComputeNode-optional
    variants =

    [variant-ComputeNode-optional.x86_64]
    arch = x86_64
    debuginfo = ComputeNode-optional/x86_64/debuginfo
    os_dir = ComputeNode-optional/x86_64/os
    packages = ComputeNode-optional/x86_64/os/Packages
    parent = ComputeNode.x86_64
    repository = ComputeNode-optional/x86_64/os
    sources = ComputeNode-optional/source/SRPMS

    [variant-ComputeNode.x86_64]
    arch = x86_64
    debuginfo = ComputeNode/x86_64/debuginfo
    isos = ComputeNode/x86_64/iso
    os_dir = ComputeNode/x86_64/os
    packages = ComputeNode/x86_64/os/Packages
    repository = ComputeNode/x86_64/os
    source_isos = ComputeNode/source/iso
    sources = ComputeNode/source/SRPMS

    [variant-Server]
    arches = ppc64,s390x,x86_64
    id = Server
    name = Server
    type = variant
    uid = Server
    variants = Server-HighAvailability,Server-LoadBalancer,Server-ResilientStorage,Server-ScalableFileSystem,Server-optional

    [variant-Server-HighAvailability]
    arches = x86_64
    id = HighAvailability
    name = High Availability
    parent = Server
    type = addon
    uid = Server-HighAvailability
    variants =

    [variant-Server-HighAvailability.x86_64]
    arch = x86_64
    debuginfo = Server/x86_64/debuginfo
    os_dir = Server/x86_64/os
    packages = Server/x86_64/os/addons/HighAvailability
    parent = Server.x86_64
    repository = Server/x86_64/os/addons/HighAvailability
    sources = Server/source/SRPMS

    [variant-Server-LoadBalancer]
    arches = x86_64
    id = LoadBalancer
    name = Load Balancer
    parent = Server
    type = addon
    uid = Server-LoadBalancer
    variants =

    [variant-Server-LoadBalancer.x86_64]
    arch = x86_64
    debuginfo = Server/x86_64/debuginfo
    os_dir = Server/x86_64/os
    packages = Server/x86_64/os/addons/LoadBalancer
    parent = Server.x86_64
    repository = Server/x86_64/os/addons/LoadBalancer
    sources = Server/source/SRPMS

    [variant-Server-ResilientStorage]
    arches = x86_64
    id = ResilientStorage
    name = Resilient Storage
    parent = Server
    type = addon
    uid = Server-ResilientStorage
    variants =

    [variant-Server-ResilientStorage.x86_64]
    arch = x86_64
    debuginfo = Server/x86_64/debuginfo
    os_dir = Server/x86_64/os
    packages = Server/x86_64/os/addons/ResilientStorage
    parent = Server.x86_64
    repository = Server/x86_64/os/addons/ResilientStorage
    sources = Server/source/SRPMS

    [variant-Server-ScalableFileSystem]
    arches = x86_64
    id = ScalableFileSystem
    name = Scalable Filesystem Support
    parent = Server
    type = addon
    uid = Server-ScalableFileSystem
    variants =

    [variant-Server-ScalableFileSystem.x86_64]
    arch = x86_64
    debuginfo = Server/x86_64/debuginfo
    os_dir = Server/x86_64/os
    packages = Server/x86_64/os/addons/ScalableFileSystem
    parent = Server.x86_64
    repository = Server/x86_64/os/addons/ScalableFileSystem
    sources = Server/source/SRPMS

    [variant-Server-optional]
    arches = ppc64,s390x,x86_64
    id = optional
    name = optional
    parent = Server
    type = optional
    uid = Server-optional
    variants =

    [variant-Server-optional.ppc64]
    arch = ppc64
    debuginfo = Server-optional/ppc64/debuginfo
    os_dir = Server-optional/ppc64/os
    packages = Server-optional/ppc64/os/Packages
    parent = Server.ppc64
    repository = Server-optional/ppc64/os
    sources = Server-optional/source/SRPMS

    [variant-Server-optional.s390x]
    arch = s390x
    debuginfo = Server-optional/s390x/debuginfo
    os_dir = Server-optional/s390x/os
    packages = Server-optional/s390x/os/Packages
    parent = Server.s390x
    repository = Server-optional/s390x/os
    sources = Server-optional/source/SRPMS

    [variant-Server-optional.x86_64]
    arch = x86_64
    debuginfo = Server-optional/x86_64/debuginfo
    os_dir = Server-optional/x86_64/os
    packages = Server-optional/x86_64/os/Packages
    parent = Server.x86_64
    repository = Server-optional/x86_64/os
    sources = Server-optional/source/SRPMS

    [variant-Server.ppc64]
    arch = ppc64
    debuginfo = Server/ppc64/debuginfo
    isos = Server/ppc64/iso
    os_dir = Server/ppc64/os
    packages = Server/ppc64/os/Packages
    repository = Server/ppc64/os
    source_isos = Server/source/iso
    sources = Server/source/SRPMS

    [variant-Server.s390x]
    arch = s390x
    debuginfo = Server/s390x/debuginfo
    isos = Server/s390x/iso
    os_dir = Server/s390x/os
    packages = Server/s390x/os/Packages
    repository = Server/s390x/os
    source_isos = Server/source/iso
    sources = Server/source/SRPMS

    [variant-Server.x86_64]
    arch = x86_64
    debuginfo = Server/x86_64/debuginfo
    isos = Server/x86_64/iso
    os_dir = Server/x86_64/os
    packages = Server/x86_64/os/Packages
    repository = Server/x86_64/os
    source_isos = Server/source/iso
    sources = Server/source/SRPMS

    [variant-Workstation]
    arches = x86_64
    id = Workstation
    name = Workstation
    type = variant
    uid = Workstation
    variants = Workstation-ScalableFileSystem,Workstation-optional

    [variant-Workstation-ScalableFileSystem]
    arches = x86_64
    id = ScalableFileSystem
    name = Scalable Filesystem Support
    parent = Workstation
    type = addon
    uid = Workstation-ScalableFileSystem
    variants =

    [variant-Workstation-ScalableFileSystem.x86_64]
    arch = x86_64
    debuginfo = Workstation/x86_64/debuginfo
    os_dir = Workstation/x86_64/os
    packages = Workstation/x86_64/os/addons/ScalableFileSystem
    parent = Workstation.x86_64
    repository = Workstation/x86_64/os/addons/ScalableFileSystem
    sources = Workstation/source/SRPMS

    [variant-Workstation-optional]
    arches = x86_64
    id = optional
    name = optional
    parent = Workstation
    type = optional
    uid = Workstation-optional
    variants =

    [variant-Workstation-optional.x86_64]
    arch = x86_64
    debuginfo = Workstation-optional/x86_64/debuginfo
    os_dir = Workstation-optional/x86_64/os
    packages = Workstation-optional/x86_64/os/Packages
    parent = Workstation.x86_64
    repository = Workstation-optional/x86_64/os
    sources = Workstation-optional/source/SRPMS

    [variant-Workstation.x86_64]
    arch = x86_64
    debuginfo = Workstation/x86_64/debuginfo
    isos = Workstation/x86_64/iso
    os_dir = Workstation/x86_64/os
    packages = Workstation/x86_64/os/Packages
    repository = Workstation/x86_64/os
    source_isos = Workstation/source/iso
    sources = Workstation/source/SRPMS

    """

    required = [
        dict(section="product", key="variants"),
    ]
    excluded = []

    def get_arches(self, variant):
        """Return a list of arches for variant"""

        all_arches = self.parser.get("variant-%s" % variant, "arches").split(",")
        # Fedora 25+ .composeinfo includes src but it's not a real arch that can be installed
        if "src" in all_arches:
            all_arches.remove("src")
        specific_arches = set(self.options.arch)
        if specific_arches:
            applicable_arches = specific_arches.intersection(set(all_arches))
            return list(applicable_arches)
        else:
            return all_arches

    def get_variants(self):
        """Return a list of variants"""
        specific_variants = self.options.variant
        if specific_variants:
            return specific_variants
        return self.parser.get("product", "variants").split(",")

    def find_repos(self, repo_base, rpath, variant, arch):
        """Find all variant repos"""
        repos = []
        variants = self.parser.get("variant-%s" % variant, "variants", "")
        if variants:
            for sub_variant in variants.split(","):
                repos.extend(self.find_repos(repo_base, rpath, sub_variant, arch))

        # Skip addon variants from .composeinfo, we pick these up from
        # .treeinfo
        repotype = self.parser.get("variant-%s" % variant, "type", "")
        if repotype == "addon":
            return repos

        repopath = self.parser.get("variant-%s.%s" % (variant, arch), "repository", "")
        if repopath:
            if url_exists(os.path.join(repo_base, rpath, repopath, "repodata")):
                repos.append(
                    dict(
                        repoid=variant,
                        type=repotype,
                        path=os.path.join(rpath, repopath),
                    )
                )
            else:
                logging.warn(
                    "%s repo found in .composeinfo but does not exist", variant
                )

        debugrepopath = self.parser.get(
            "variant-%s.%s" % (variant, arch), "debuginfo", ""
        )
        if debugrepopath:
            if url_exists(os.path.join(repo_base, rpath, debugrepopath, "repodata")):
                repos.append(
                    dict(
                        repoid="%s-debuginfo" % variant,
                        type="debug",
                        path=os.path.join(rpath, debugrepopath),
                    )
                )
            else:
                logging.warn(
                    "%s-debuginfo repo found in .composeinfo but does not exist",
                    variant,
                )
        if is_rhel8_alpha(self.parser):
            appstream_repos = self._guess_appstream_repos(rpath, arch, repo_base)
            if not debugrepopath:
                appstream_repos.pop()

            for repo in appstream_repos:
                url = os.path.join(repo_base, repo[2], "repodata")
                if url_exists(url):
                    repos.append(dict(repoid=repo[0], type=repo[1], path=repo[2]))
                else:
                    raise ValueError(
                        "Expected {0} compose at {1} but it doesn't exist".format(
                            repo[0], url
                        )
                    )

        return repos

    def _guess_appstream_repos(self, rpath, arch, repo_base):
        """Iterate over possible layouts to guess which one fits and return a list of repositories."""
        repo_layout = {
            "8.0-AppStream-Alpha": [
                (
                    "AppStream",
                    "variant",
                    os.path.join(
                        rpath, "..", "8.0-AppStream-Alpha", "AppStream", arch, "os"
                    ),
                ),
                (
                    "AppStream-debuginfo",
                    "debug",
                    os.path.join(
                        rpath,
                        "..",
                        "8.0-AppStream-Alpha",
                        "AppStream",
                        arch,
                        "debug",
                        "tree",
                    ),
                ),
            ],
            "AppStream-8.0-20180531.0": [
                (
                    "AppStream",
                    "variant",
                    os.path.join(
                        rpath,
                        "..",
                        "..",
                        "AppStream-8.0-20180531.0",
                        "compose",
                        "AppStream",
                        arch,
                        "os",
                    ),
                ),
                (
                    "AppStream-debuginfo",
                    "debug",
                    os.path.join(
                        rpath,
                        "..",
                        "..",
                        "AppStream-8.0-20180531.0",
                        "compose",
                        "AppStream",
                        arch,
                        "debug",
                        "tree",
                    ),
                ),
            ],
        }

        appstream_repos = []
        for dirname, repos in repo_layout.items():
            url = os.path.join(repo_base, repos[0][2], "repodata")
            logging.debug("Trying to import %s", repos[0][2])
            if not url_exists(url):
                continue
            else:
                appstream_repos = repos

        if not appstream_repos:
            raise ValueError(
                "Could not determine repository layout to import AppStream repo"
            )
        return appstream_repos

    def process(self, urls, options):
        exit_status = 0

        self.options = options
        self.scheduler = SchedulerProxy(self.options)
        self.distro_trees = []
        for variant in self.get_variants():
            for arch in self.get_arches(variant):
                os_dir = self.parser.get("variant-%s.%s" % (variant, arch), "os_dir")
                options = copy.deepcopy(self.options)
                if not options.name:
                    options.name = self.parser.get("product", "name")

                # our current path relative to the os_dir "../.."
                rpath = os.path.join(*[".." for i in range(0, len(os_dir.split("/")))])

                # find our repos, but relative from os_dir
                repos = self.find_repos(
                    os.path.join(self.parser.url, os_dir), rpath, variant, arch
                )

                urls_variant_arch = [os.path.join(url, os_dir) for url in urls]
                try:
                    options.variant = [variant]
                    options.arch = [arch]
                    build = Build(os.path.join(self.parser.url, os_dir))
                    labels = self.parser.get("compose", "label", "")
                    tags = [
                        label.strip() for label in (labels and labels.split() or [])
                    ]
                    try:
                        isos_path = self.parser.get(
                            "variant-%s.%s" % (variant, arch), "isos"
                        )
                        isos_path = os.path.join(rpath, isos_path)
                    except configparser.NoOptionError:
                        isos_path = None
                    build.process(
                        urls_variant_arch,
                        options,
                        repos=repos,
                        tags=tags,
                        isos_path=isos_path,
                    )
                    self.distro_trees.append(build.tree)
                except BX as err:
                    if not options.ignore_missing:
                        exit_status = 1
                        logging.warn(err)
        return exit_status


class NakedTree(Importer):
    @classmethod
    def is_importer_for(cls, url, options=None):
        if not options:
            return False
        if not options.kernel:
            return False
        if not options.initrd:
            return False
        if not options.name:
            return False
        if not options.family:
            return False
        if not options.version:
            return False
        if not options.arch:
            return False
        return True

    def check_input(self, options):
        self.check_variants(options.variant, multiple=False)
        self.check_arches(options.arch, multiple=False)

    def process(self, urls, options, repos=[]):
        self.scheduler = SchedulerProxy(options)
        self.tree = dict()

        urls = [os.path.join(url, "") for url in urls]
        self.tree["urls"] = urls
        if not options.preserve_install_options:
            self.tree["kernel_options"] = options.kopts
            self.tree["kernel_options_post"] = options.kopts_post
            self.tree["ks_meta"] = options.ks_meta
        family = options.family
        version = options.version
        self.tree["name"] = options.name
        try:
            self.tree["variant"] = options.variant[0]
        except IndexError:
            self.tree["variant"] = ""
        try:
            self.tree["arch"] = options.arch[0]
        except IndexError:
            self.tree["arch"] = ""
        self.tree["tree_build_time"] = options.buildtime or time.time()
        self.tree["tags"] = options.tags
        self.tree["osmajor"] = "%s%s" % (family, version.split(".")[0])
        if version.find(".") != -1:
            self.tree["osminor"] = version.split(".")[1]
        else:
            self.tree["osminor"] = "0"

        self.tree["arches"] = options.arch
        self.tree["repos"] = repos

        # Add install images
        self.tree["images"] = []
        self.tree["images"].append(dict(type="kernel", path=options.kernel))
        self.tree["images"].append(dict(type="initrd", path=options.initrd))

        if options.json:
            print(json.dumps(self.tree))
        logging.debug("\n%s" % pprint.pformat(self.tree))
        try:
            self.add_to_beaker()
            logging.info("%s added to beaker." % self.tree["name"])
        except (xmlrpc_client.Fault, socket.error) as e:
            raise BX("failed to add %s to beaker: %s" % (self.tree["name"], e))

    def add_to_beaker(self):
        self.scheduler.add_distro(self.tree)


def Build(url, options=None):
    # Try all other importers before trying NakedTree
    for cls in Importer.__subclasses__() + [NakedTree]:
        parser = cls.is_importer_for(url, options)
        if parser != False:
            logging.debug("\tImporter %s Matches", cls.__name__)
            logging.info("Attempting to import: %s", url)
            return cls(parser)
        else:
            logging.debug("\tImporter %s does not match", cls.__name__)
    raise BX("No valid importer found for %s" % url)
