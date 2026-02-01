# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from bkr.common.bexceptions import BX

from six.moves import configparser
from six.moves import urllib


class Parser(object):
    """
    base class to use for processing .composeinfo and .treeinfo
    """

    url = None
    parser = None
    last_modified = 0.0
    infofile = None  # overriden in subclasses
    discinfo = None

    def parse(self, url):
        self.url = url
        try:
            f = urllib.request.urlopen("%s/%s" % (self.url, self.infofile))
            self.parser = configparser.ConfigParser()
            self.parser.readfp(f)
            f.close()
        except urllib.error.URLError:
            return False
        except configparser.MissingSectionHeaderError as e:
            raise BX("%s/%s is not parsable: %s" % (self.url, self.infofile, e))

        if self.discinfo:
            try:
                f = urllib.request.urlopen("%s/%s" % (self.url, self.discinfo))
                self.last_modified = f.read().split("\n")[0]
                f.close()
            except urllib.error.URLError:
                pass
        return True

    def get(self, section, key, default=None):
        if self.parser:
            try:
                default = self.parser.get(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError) as e:
                if default is None:
                    raise
        return default

    def sections(self):
        return self.parser.sections()

    def has_option(self, section, option):
        return self.parser.has_option(section, option)

    def has_section_startswith(self, s):
        for section in self.parser.sections():
            if section.startswith(s):
                return True
        return False

    def __repr__(self):
        return "%s/%s" % (self.url, self.infofile)


class Cparser(Parser):
    infofile = ".composeinfo"
    discinfo = None


class Tparser(Parser):
    infofile = ".treeinfo"
    discinfo = ".discinfo"


class TparserRhel5(Tparser):
    def get(self, section, key, default=None):
        value = super(TparserRhel5, self).get(section, key, default=default)
        # .treeinfo for RHEL5 incorrectly reports ppc when it should report ppc64
        if section == "general" and key == "arch" and value == "ppc":
            value = "ppc64"
        return value
