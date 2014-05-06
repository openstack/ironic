# coding=utf-8

# Copyright 2014 International Business Machines Corporation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Test class for console_utils driver module."""

import mock
import os
import random
import string
import subprocess
import tempfile

from oslo.config import cfg

from ironic.common import exception
from ironic.common import utils
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import ipmitool as ipmi
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils


CONF = cfg.CONF

INFO_DICT = db_utils.get_test_ipmi_info()


class ConsoleUtilsTestCase(base.TestCase):

    def setUp(self):
        super(ConsoleUtilsTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.node = obj_utils.get_test_node(
                self.context,
                driver='fake_ipmitool',
                driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    def test__get_console_pid_file(self):
        tempdir = tempfile.gettempdir()
        self.config(terminal_pid_dir=tempdir, group='console')
        path = console_utils._get_console_pid_file(self.info['uuid'])
        self.assertEqual(path,
                         '%(tempdir)s/%(uuid)s.pid'
                                 % {'tempdir': tempdir,
                                    'uuid': self.info.get('uuid')})

    @mock.patch.object(console_utils, '_get_console_pid_file', autospec=True)
    def test__get_console_pid(self, mock_exec):
        tmp_file_handle = tempfile.NamedTemporaryFile()
        tmp_file = tmp_file_handle.name
        self.addCleanup(utils.unlink_without_raise, tmp_file)
        with open(tmp_file, "w") as f:
            f.write("12345\n")

        mock_exec.return_value = tmp_file

        pid = console_utils._get_console_pid(self.info['uuid'])

        mock_exec.assert_called_once_with(self.info['uuid'])
        self.assertEqual(pid, 12345)

    @mock.patch.object(console_utils, '_get_console_pid_file', autospec=True)
    def test__get_console_pid_not_a_num(self, mock_exec):
        tmp_file_handle = tempfile.NamedTemporaryFile()
        tmp_file = tmp_file_handle.name
        self.addCleanup(utils.unlink_without_raise, tmp_file)
        with open(tmp_file, "w") as f:
            f.write("Hello World\n")

        mock_exec.return_value = tmp_file

        self.assertRaises(exception.NoConsolePid,
                          console_utils._get_console_pid,
                          self.info['uuid'])
        mock_exec.assert_called_once_with(self.info['uuid'])

    def test__get_console_pid_file_not_found(self):
        self.assertRaises(exception.NoConsolePid,
                          console_utils._get_console_pid,
                          self.info['uuid'])

    def test_get_shellinabox_console_url(self):
        generated_url = console_utils.get_shellinabox_console_url(
                self.info['port'])
        console_host = CONF.my_ip
        if utils.is_valid_ipv6(console_host):
            console_host = '[%s]' % console_host
        http_url = "http://%s:%s" % (console_host, self.info['port'])
        self.assertEqual(generated_url, http_url)

    def test_make_persistent_password_file(self):
        filepath = '%(tempdir)s/%(node_uuid)s' % {
                'tempdir': tempfile.gettempdir(),
                'node_uuid': self.info['uuid']}
        password = ''.join([random.choice(string.ascii_letters)
                            for n in xrange(16)])
        console_utils.make_persistent_password_file(filepath, password)
        # make sure file exists
        self.assertTrue(os.path.exists(filepath))
        # make sure the content is correct
        with open(filepath) as file:
            content = file.read()
        self.assertEqual(password, content)
        # delete the file
        os.unlink(filepath)

    @mock.patch.object(os, 'mknod', autospec=True)
    def test_make_persistent_password_file_fail(self, mock_mknod):
        mock_mknod.side_effect = IOError()
        filepath = '%(tempdir)s/%(node_uuid)s' % {
                'tempdir': tempfile.gettempdir(),
                'node_uuid': self.info['uuid']}
        self.assertRaises(exception.PasswordFileFailedToCreate,
                          console_utils.make_persistent_password_file,
                          filepath,
                          'password')

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    def test_start_shellinabox_console(self, mock_popen):
        mock_popen.return_value.poll.return_value = 0

        # touch the pid file
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        open(pid_file, 'a').close()
        self.assertTrue(os.path.exists(pid_file))

        console_utils.start_shellinabox_console(self.info['uuid'],
                                                 self.info['port'],
                                                 'ls&')

        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_once_with()

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    def test_start_shellinabox_console_fail(self, mock_popen):
        mock_popen.return_value.poll.return_value = 1
        mock_popen.return_value.communicate.return_value = ('output', 'error')

        self.assertRaises(exception.ConsoleSubprocessFailed,
                          console_utils.start_shellinabox_console,
                          self.info['uuid'],
                          self.info['port'],
                          'ls&')

        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_once_with()
        mock_popen.return_value.communicate.assert_called_once_with()

    def test_stop_shellinabox_console(self):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        open(pid_file, 'a').close()
        self.assertTrue(os.path.exists(pid_file))

        console_utils.stop_shellinabox_console(self.info['uuid'])

        self.assertFalse(os.path.exists(pid_file))
