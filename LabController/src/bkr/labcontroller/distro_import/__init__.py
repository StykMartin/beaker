# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import sys
import logging
from optparse import OptionParser, OptionGroup

from bkr.log import log_to_stream

from six.moves import configparser
from six.moves import xmlrpc_client

from bkr.labcontroller.distro_import.utils import (
    url_exists,
    is_rhel8_alpha,
    IncompleteTree,
    _primary_methods,
    _get_primary_url,
    _get_url_by_scheme,
)
from bkr.labcontroller.distro_import.proxy import (
    _DummyProxy,
    SchedulerProxy,
)
from bkr.labcontroller.distro_import.parser import (
    Parser,
    Cparser,
    Tparser,
    TparserRhel5,
)
from bkr.labcontroller.distro_import.importer import (
    Importer,
    ComposeInfoMixin,
    ComposeInfoLegacy,
    ComposeInfo,
    NakedTree,
    Build,
)
from bkr.labcontroller.distro_import.treeinfo import (
    TreeInfoMixin,
    TreeInfoLegacy,
    TreeInfoRhel5,
    TreeInfoFedora,
    TreeInfoFedoraArm,
    TreeInfoRhel6,
    TreeInfoRHVH4,
    TreeInfoRhel7,
    TreeInfoRhel,
    TreeInfoRhelArm,
)


def main():
    usage = "usage: %prog [options] distro_url [distro_url] [distro_url]"
    description = """Imports distro(s) from the given distro_url.  Valid distro_urls are nfs://, http:// and ftp://.  A primary distro_url of either http:// or ftp:// must be specified. In order for an import to succeed a .treeinfo or a .composeinfo must be present at the distro_url or you can do what is called a "naked" import if you specify the following arguments: --family, --version, --name, --arch, --kernel, --initrd. Only one tree can be imported at a time when doing a naked import."""

    parser = OptionParser(usage=usage, description=description)
    parser.add_option(
        "-j",
        "--json",
        default=False,
        action="store_true",
        help="Prints the tree to be imported, in JSON format",
    )
    parser.add_option(
        "-c",
        "--add-distro-cmd",
        default="/var/lib/beaker/addDistro.sh",
        help="Command to run to add a new distro",
    )
    parser.add_option(
        "-n",
        "--name",
        default=None,
        help="Alternate name to use, otherwise we read it from .treeinfo",
    )
    parser.add_option(
        "-t",
        "--tag",
        default=[],
        action="append",
        dest="tags",
        help="Additional tags to add",
    )
    parser.add_option(
        "-r",
        "--run-jobs",
        action="store_true",
        default=False,
        help="Run automated Jobs",
    )
    parser.add_option(
        "-v", "--debug", action="store_true", default=False, help="show debug messages"
    )
    parser.add_option(
        "--dry-run",
        action="store_true",
        help="Do not actually add any distros to beaker",
    )
    parser.add_option(
        "-q", "--quiet", action="store_true", default=False, help="less messages"
    )
    parser.add_option("--family", default=None, help="Specify family")
    parser.add_option(
        "--variant",
        action="append",
        default=[],
        help="Specify variant. Multiple values are valid when importing a compose >=RHEL7",
    )
    parser.add_option("--version", default=None, help="Specify version")
    parser.add_option(
        "--kopts", default=None, help="add kernel options to use for install"
    )
    parser.add_option(
        "--kopts-post", default=None, help="add kernel options to use for after install"
    )
    parser.add_option(
        "--ks-meta", default=None, help="add variables to use in kickstart templates"
    )
    parser.add_option(
        "--preserve-install-options",
        action="store_true",
        default=False,
        help=(
            "Do not overwrite the 'Install Options' (Kickstart "
            "Metadata, Kernel Options, & Kernel Options Post) already "
            "stored for the distro. This option can not be used with "
            "any of --kopts, --kopts-post, or --ks-meta"
        ),
    )
    parser.add_option(
        "--buildtime", default=None, type=float, help="Specify build time"
    )
    parser.add_option(
        "--arch",
        action="append",
        default=[],
        help="Specify arch. Multiple values are valid when importing a compose",
    )
    parser.add_option(
        "--ignore-missing-tree-compose",
        dest="ignore_missing",
        action="store_true",
        default=False,
        help="If a specific tree within a compose is missing, do not print any errors",
    )
    group = OptionGroup(
        parser,
        "Naked Tree Options",
        "These options only apply when importing without a .treeinfo or .composeinfo",
    )
    group.add_option(
        "--kernel", default=None, help="Specify path to kernel (relative to distro_url)"
    )
    group.add_option(
        "--initrd", default=None, help="Specify path to initrd (relative to distro_url)"
    )
    group.add_option(
        "--lab-controller",
        default="http://localhost:8000",
        help="Specify which lab controller to import to. Defaults to http://localhost:8000",
    )
    parser.add_option_group(group)

    (opts, urls) = parser.parse_args()

    logging.getLogger().setLevel(logging.DEBUG)
    if opts.debug:
        log_level = logging.DEBUG
    elif opts.quiet:
        log_level = logging.CRITICAL
    else:
        log_level = logging.INFO
    log_to_stream(sys.stderr, level=log_level)

    if opts.preserve_install_options:
        if any([opts.kopts, opts.kopts_post, opts.ks_meta]):
            logging.critical(
                "--preserve-install-options can not be used with any of: "
                "--kopt, --kopts-post, or --ks-meta"
            )
            sys.exit(4)

    if not urls:
        logging.critical("No location(s) specified!")
        sys.exit(1)

    primary_url = _get_primary_url(urls)
    if primary_url == None:
        logging.critical(
            "missing a valid primary installer! %s, are valid install methods"
            % " and ".join(_primary_methods)
        )
        sys.exit(2)
    if opts.dry_run:
        logging.info("Dry Run only, no data will be sent to beaker")
    exit_status = []
    try:
        build = Build(primary_url, options=opts)
        try:
            build.check_input(opts)
            exit_status.append(build.process(urls, opts))
        except (configparser.NoSectionError, configparser.NoOptionError) as e:
            logging.critical(str(e))
            sys.exit(3)
    except (xmlrpc_client.Fault, BX) as err:
        logging.critical(err)
        sys.exit(127)
    if opts.run_jobs:
        logging.info("running jobs.")
        build.run_jobs()

    # if the list of exit_status-es contain any non-zero
    # value it means that at least one tree failed to import
    # correctly, and hence set the exit status of the script
    # accordingly
    return bool(any(exit_status))
