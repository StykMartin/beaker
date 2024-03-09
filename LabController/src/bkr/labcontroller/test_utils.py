# Copyright Contributors to the Beaker project.
# SPDX-License-Identifier: GPL-2.0-or-later

import unittest

from bkr.labcontroller.utils import get_console_files

try:
    from unittest.mock import patch
except ImportError:
    from mock import patch


class TestGetConsoleFiles(unittest.TestCase):
    @patch("os.path.isdir")
    def test_directory_not_exist(self, mock_isdir):
        mock_isdir.return_value = False
        actual = get_console_files("/non/existing/path", "test_system")
        self.assertEqual([], actual)

    @patch("os.path.isdir")
    def test_empty_system_name(self, mock_isdir):
        mock_isdir.return_value = True
        actual = get_console_files("/existing/path", "")
        self.assertEqual([], actual)

    @patch("os.listdir")
    @patch("os.path.isdir")
    def test_normal_operation(self, mock_isdir, mock_listdir):
        t_system = "system.example.com"
        t_path = "/existing/path"
        t_logs = ["{}-log{}".format(t_system, idx) for idx in range(2)]
        expected = [
            (
                "{}/{}-log{}".format(t_path, t_system, idx),
                "console-log{}.log".format(idx),
            )
            for idx in range(2)
        ]
        mock_isdir.return_value = True
        mock_listdir.return_value = t_logs

        actual = get_console_files(t_path, t_system)

        for e, a in zip(expected, actual):
            self.assertEqual(e, a)

    @patch("os.listdir")
    @patch("os.path.isdir")
    def test_no_match(self, mock_isdir, mock_listdir):
        t_system = "system2.example.com"
        t_path = "/existing/path"
        t_logs = ["{}-log{}".format(t_system, idx) for idx in range(2)]
        mock_isdir.return_value = True
        mock_listdir.return_value = t_logs

        actual = get_console_files(t_path, "system.example.com")
        self.assertEqual([], actual)
