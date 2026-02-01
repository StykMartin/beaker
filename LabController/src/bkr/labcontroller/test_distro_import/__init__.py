# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

import io
import sys

try:
    from unittest import mock
except ImportError:
    import mock

import six

if "dnf" not in sys.modules:
    sys.modules["dnf"] = mock.MagicMock()

from six.moves import configparser


def _mock_urlopen(content):
    if six.PY2:
        return io.BytesIO(content.encode("utf-8"))
    return io.StringIO(content)


def _mock_urlopen_discinfo(content="1234567890\n"):
    if six.PY2:
        return io.BytesIO(content.encode("utf-8"))
    return io.StringIO(content)


def _fake_parser_get(data):
    def fake_get(section, key, default=None):
        try:
            return data[section][key]
        except KeyError:
            if default is not None:
                return default
            raise configparser.NoOptionError(key, section)

    return fake_get


def _fake_parser_get_tuples(data):
    def fake_get(section, key, default=None):
        val = data.get((section, key))
        if val is not None:
            return val
        if default is not None:
            return default
        raise configparser.NoOptionError(key, section)

    return fake_get
