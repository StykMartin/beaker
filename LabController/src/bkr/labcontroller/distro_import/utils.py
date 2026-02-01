# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from bkr.common.bexceptions import BX

from six.moves import configparser
from six.moves import urllib


def url_exists(url):
    try:
        urllib.request.urlopen(url)
    except urllib.error.URLError:
        return False
    except IOError as e:
        # errno 21 is you tried to retrieve a directory.  Thats ok. We just
        # want to ensure the path is valid so far.
        if e.errno == 21:
            pass
        else:
            raise
    return True


def is_rhel8_alpha(parser):
    result = False
    try:
        result = (
            parser.get("compose", "label") == "Alpha-1.2"
            and parser.get("product", "short") == "RHEL"
            and parser.get("product", "version") == "8.0"
            and
            # If the partner has made adjustments to the composeinfo
            # files so that the compose looks like a unified compose,
            # don't execute the extra code we would normally do for RHEL8
            # Alpha on partner servers. Instead assume that the code
            # which can import RHEL7 will do. This is the best guess at
            # the moment, since there is nothing really explicit which
            # distinguishes the ordinary partner sync from a non-adjusted
            # composeinfo.
            not parser.has_option("variant-BaseOS", "variants")
        )
    except configparser.Error:
        pass
    return result


class IncompleteTree(BX):
    """
    IncompleteTree is raised when there is a discrepancy between
    what is specified in a .composeinfo/.treeinfo, and what is actually
    found on disk.
    """

    pass


_primary_methods = [
    "http",
    "https",
    "ftp",
]


def _get_primary_url(urls):
    """Return primary method used to import distro

    Primary method is what we use to import the distro, we look for
            .composeinfo or .treeinfo at that location.  Because of this
             nfs can't be the primary install method.
    """
    for url in urls:
        method = url.split(":", 1)[0]
        if method in _primary_methods:
            primary = url
            return primary
    return None


def _get_url_by_scheme(urls, scheme):
    """Return the first url that matches the given scheme"""
    for url in urls:
        method = url.split(":", 1)[0]
        if method == scheme:
            return url
    return None
