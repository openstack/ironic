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

import errno
import fcntl
import os
import random
import signal
import string
import subprocess
import tempfile
import time

from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg
from oslo_service import loopingcall
from oslo_utils import netutils
import psutil

from ironic.common import exception
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import ipmitool as ipmi
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF

INFO_DICT = db_utils.get_test_ipmi_info()


class ConsoleUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ConsoleUtilsTestCase, self).setUp()
        self.node = obj_utils.get_test_node(
            self.context,
            driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    def test__get_console_pid_dir(self):
        pid_dir = '/tmp/pid_dir'
        self.config(terminal_pid_dir=pid_dir, group='console')
        dir = console_utils._get_console_pid_dir()
        self.assertEqual(pid_dir, dir)

    def test__get_console_pid_dir_tempdir(self):
        self.config(tempdir='/tmp/fake_dir')
        dir = console_utils._get_console_pid_dir()
        self.assertEqual(CONF.tempdir, dir)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__ensure_console_pid_dir_exists(self, mock_path_exists,
                                            mock_makedirs):
        mock_path_exists.return_value = True
        mock_makedirs.side_effect = OSError
        pid_dir = console_utils._get_console_pid_dir()

        console_utils._ensure_console_pid_dir_exists()

        mock_path_exists.assert_called_once_with(pid_dir)
        self.assertFalse(mock_makedirs.called)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(os.path, 'exists', autospec=True)
    def test__ensure_console_pid_dir_exists_fail(self, mock_path_exists,
                                                 mock_makedirs):
        mock_path_exists.return_value = False
        mock_makedirs.side_effect = OSError
        pid_dir = console_utils._get_console_pid_dir()

        self.assertRaises(exception.ConsoleError,
                          console_utils._ensure_console_pid_dir_exists)

        mock_path_exists.assert_called_once_with(pid_dir)
        mock_makedirs.assert_called_once_with(pid_dir)

    @mock.patch.object(console_utils, '_get_console_pid_dir', autospec=True)
    def test__get_console_pid_file(self, mock_dir):
        mock_dir.return_value = tempfile.gettempdir()
        expected_path = '%(tempdir)s/%(uuid)s.pid' % {
            'tempdir': mock_dir.return_value,
            'uuid': self.info['uuid']}
        path = console_utils._get_console_pid_file(self.info['uuid'])
        self.assertEqual(expected_path, path)
        mock_dir.assert_called_once_with()

    @mock.patch.object(console_utils, 'open',
                       mock.mock_open(read_data='12345\n'))
    @mock.patch.object(console_utils, '_get_console_pid_file', autospec=True)
    def test__get_console_pid(self, mock_pid_file):
        tmp_file_handle = tempfile.NamedTemporaryFile()
        tmp_file = tmp_file_handle.name

        mock_pid_file.return_value = tmp_file

        pid = console_utils._get_console_pid(self.info['uuid'])

        mock_pid_file.assert_called_once_with(self.info['uuid'])
        self.assertEqual(pid, 12345)

    @mock.patch.object(console_utils, 'open',
                       mock.mock_open(read_data='Hello World\n'))
    @mock.patch.object(console_utils, '_get_console_pid_file', autospec=True)
    def test__get_console_pid_not_a_num(self, mock_pid_file):
        tmp_file_handle = tempfile.NamedTemporaryFile()
        tmp_file = tmp_file_handle.name

        mock_pid_file.return_value = tmp_file

        self.assertRaises(exception.NoConsolePid,
                          console_utils._get_console_pid,
                          self.info['uuid'])
        mock_pid_file.assert_called_once_with(self.info['uuid'])

    def test__get_console_pid_file_not_found(self):
        self.assertRaises(exception.NoConsolePid,
                          console_utils._get_console_pid,
                          self.info['uuid'])

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(os, 'kill', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    def test__stop_console(self, mock_pid, mock_kill, mock_unlink):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        mock_pid.return_value = 12345

        console_utils._stop_console(self.info['uuid'])

        mock_pid.assert_called_once_with(self.info['uuid'])

        # a check if process still exist (signal 0) in a loop
        mock_kill.assert_any_call(mock_pid.return_value, signal.SIG_DFL)
        # and that it receives the SIGTERM
        mock_kill.assert_any_call(mock_pid.return_value, signal.SIGTERM)
        mock_unlink.assert_called_once_with(pid_file)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(os, 'kill', autospec=True)
    @mock.patch.object(psutil, 'pid_exists', autospec=True, return_value=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    def test__stop_console_forced_kill(self, mock_pid, mock_psutil, mock_kill,
                                       mock_unlink):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        mock_pid.return_value = 12345

        console_utils._stop_console(self.info['uuid'])

        mock_pid.assert_called_once_with(self.info['uuid'])

        # Make sure console process receives hard SIGKILL
        mock_kill.assert_any_call(mock_pid.return_value, signal.SIGKILL)
        mock_unlink.assert_called_once_with(pid_file)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(os, 'kill', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    def test__stop_console_nopid(self, mock_pid, mock_kill, mock_unlink):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        mock_pid.side_effect = exception.NoConsolePid(pid_path="/tmp/blah")

        self.assertRaises(exception.NoConsolePid,
                          console_utils._stop_console,
                          self.info['uuid'])

        mock_pid.assert_called_once_with(self.info['uuid'])
        self.assertFalse(mock_kill.called)
        mock_unlink.assert_called_once_with(pid_file)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(os, 'kill', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    def test__stop_console_shellinabox_not_running(self, mock_pid,
                                                   mock_kill, mock_unlink):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        mock_pid.return_value = 12345
        mock_kill.side_effect = OSError(errno.ESRCH, 'message')

        console_utils._stop_console(self.info['uuid'])

        mock_pid.assert_called_once_with(self.info['uuid'])
        mock_kill.assert_called_once_with(mock_pid.return_value,
                                          signal.SIGTERM)
        mock_unlink.assert_called_once_with(pid_file)

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(os, 'kill', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    def test__stop_console_exception(self, mock_pid, mock_kill, mock_unlink):
        pid_file = console_utils._get_console_pid_file(self.info['uuid'])
        mock_pid.return_value = 12345
        mock_kill.side_effect = OSError(2, 'message')

        self.assertRaises(exception.ConsoleError,
                          console_utils._stop_console,
                          self.info['uuid'])

        mock_pid.assert_called_once_with(self.info['uuid'])
        mock_kill.assert_called_once_with(mock_pid.return_value,
                                          signal.SIGTERM)
        mock_unlink.assert_called_once_with(pid_file)

    def _get_shellinabox_console(self, scheme):
        generated_url = (
            console_utils.get_shellinabox_console_url(self.info['port']))
        console_host = CONF.my_ip
        if netutils.is_valid_ipv6(console_host):
            console_host = '[%s]' % console_host
        http_url = "%s://%s:%s" % (scheme, console_host, self.info['port'])
        self.assertEqual(http_url, generated_url)

    def test_get_shellinabox_console_url(self):
        self._get_shellinabox_console('http')

    def test_get_shellinabox_console_https_url(self):
        # specify terminal_cert_dir in /etc/ironic/ironic.conf
        self.config(terminal_cert_dir='/tmp', group='console')
        # use https
        self._get_shellinabox_console('https')

    def test_make_persistent_password_file(self):
        filepath = '%(tempdir)s/%(node_uuid)s' % {
            'tempdir': tempfile.gettempdir(),
            'node_uuid': self.info['uuid']}
        password = ''.join([random.choice(string.ascii_letters)
                            for n in range(16)])
        console_utils.make_persistent_password_file(filepath, password)
        # make sure file exists
        self.assertTrue(os.path.exists(filepath))
        # make sure the content is correct
        with open(filepath) as file:
            content = file.read()
        self.assertEqual(password, content)
        # delete the file
        os.unlink(filepath)

    @mock.patch.object(os, 'chmod', autospec=True)
    def test_make_persistent_password_file_fail(self, mock_chmod):
        mock_chmod.side_effect = IOError()
        filepath = '%(tempdir)s/%(node_uuid)s' % {
            'tempdir': tempfile.gettempdir(),
            'node_uuid': self.info['uuid']}
        self.assertRaises(exception.PasswordFileFailedToCreate,
                          console_utils.make_persistent_password_file,
                          filepath,
                          'password')

    @mock.patch.object(fcntl, 'fcntl', autospec=True)
    @mock.patch.object(console_utils, 'open',
                       mock.mock_open(read_data='12345\n'))
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(subprocess, 'Popen')
    @mock.patch.object(psutil, 'pid_exists', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console(self, mock_stop,
                                       mock_dir_exists,
                                       mock_pid_exists,
                                       mock_popen,
                                       mock_path_exists, mock_fcntl):
        mock_popen.return_value.poll.return_value = 0
        mock_popen.return_value.stdout.return_value.fileno.return_value = 0
        mock_popen.return_value.stderr.return_value.fileno.return_value = 1
        mock_pid_exists.return_value = True
        mock_path_exists.return_value = True

        console_utils.start_shellinabox_console(self.info['uuid'],
                                                self.info['port'],
                                                'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_pid_exists.assert_called_once_with(12345)
        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_once_with()

    @mock.patch.object(fcntl, 'fcntl', autospec=True)
    @mock.patch.object(console_utils, 'open',
                       mock.mock_open(read_data='12345\n'))
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(subprocess, 'Popen')
    @mock.patch.object(psutil, 'pid_exists', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console_nopid(self, mock_stop,
                                             mock_dir_exists,
                                             mock_pid_exists,
                                             mock_popen,
                                             mock_path_exists, mock_fcntl):
        # no existing PID file before starting
        mock_stop.side_effect = exception.NoConsolePid('/tmp/blah')
        mock_popen.return_value.poll.return_value = 0
        mock_popen.return_value.stdout.return_value.fileno.return_value = 0
        mock_popen.return_value.stderr.return_value.fileno.return_value = 1
        mock_pid_exists.return_value = True
        mock_path_exists.return_value = True

        console_utils.start_shellinabox_console(self.info['uuid'],
                                                self.info['port'],
                                                'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_pid_exists.assert_called_once_with(12345)
        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_once_with()

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(os, 'read', autospec=True)
    @mock.patch.object(fcntl, 'fcntl', autospec=True)
    @mock.patch.object(subprocess, 'Popen')
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console_fail(
            self, mock_stop, mock_dir_exists, mock_popen, mock_fcntl,
            mock_os_read, mock_sleep):
        mock_popen.return_value.poll.return_value = 1
        stdout = mock_popen.return_value.stdout
        stderr = mock_popen.return_value.stderr
        stdout.return_value.fileno.return_value = 0
        stderr.return_value.fileno.return_value = 1
        err_output = b'error output'
        mock_os_read.side_effect = [err_output] * 2 + [OSError] * 2
        mock_fcntl.side_effect = [1, mock.Mock()] * 2

        self.assertRaisesRegex(
            exception.ConsoleSubprocessFailed, "Stdout: %r" % err_output,
            console_utils.start_shellinabox_console, self.info['uuid'],
            self.info['port'], 'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        mock_dir_exists.assert_called_once_with()
        for obj in (stdout, stderr):
            mock_fcntl.assert_has_calls([
                mock.call(obj, fcntl.F_GETFL),
                mock.call(obj, fcntl.F_SETFL, 1 | os.O_NONBLOCK)])
        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_with()

    @mock.patch.object(fcntl, 'fcntl', autospec=True)
    @mock.patch.object(subprocess, 'Popen')
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console_timeout(
            self, mock_stop, mock_dir_exists, mock_popen, mock_fcntl):
        self.config(subprocess_timeout=0, group='console')
        self.config(subprocess_checking_interval=0, group='console')
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.stdout.return_value.fileno.return_value = 0
        mock_popen.return_value.stderr.return_value.fileno.return_value = 1

        self.assertRaisesRegex(
            exception.ConsoleSubprocessFailed, 'Timeout or error',
            console_utils.start_shellinabox_console, self.info['uuid'],
            self.info['port'], 'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_with()
        self.assertEqual(0, mock_popen.return_value.communicate.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(os, 'read', autospec=True)
    @mock.patch.object(fcntl, 'fcntl', autospec=True)
    @mock.patch.object(console_utils, 'open',
                       mock.mock_open(read_data='12345\n'))
    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(subprocess, 'Popen')
    @mock.patch.object(psutil, 'pid_exists', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console_fail_no_pid(
            self, mock_stop, mock_dir_exists, mock_pid_exists, mock_popen,
            mock_path_exists, mock_fcntl, mock_os_read, mock_sleep):
        mock_popen.return_value.poll.return_value = 0
        stdout = mock_popen.return_value.stdout
        stderr = mock_popen.return_value.stderr
        stdout.return_value.fileno.return_value = 0
        stderr.return_value.fileno.return_value = 1
        mock_pid_exists.return_value = False
        mock_os_read.side_effect = [b'error output'] * 2 + [OSError] * 2
        mock_fcntl.side_effect = [1, mock.Mock()] * 2
        mock_path_exists.return_value = True

        self.assertRaises(exception.ConsoleSubprocessFailed,
                          console_utils.start_shellinabox_console,
                          self.info['uuid'],
                          self.info['port'],
                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_sleep.assert_has_calls([mock.call(1), mock.call(1)])
        mock_dir_exists.assert_called_once_with()
        for obj in (stdout, stderr):
            mock_fcntl.assert_has_calls([
                mock.call(obj, fcntl.F_GETFL),
                mock.call(obj, fcntl.F_SETFL, 1 | os.O_NONBLOCK)])
        mock_pid_exists.assert_called_with(12345)
        mock_popen.assert_called_once_with(mock.ANY,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)
        mock_popen.return_value.poll.assert_called_with()

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_shellinabox_console_fail_nopiddir(self, mock_stop,
                                                     mock_dir_exists,
                                                     mock_popen):
        mock_dir_exists.side_effect = exception.ConsoleError(message='fail')
        mock_popen.return_value.poll.return_value = 0

        self.assertRaises(exception.ConsoleError,
                          console_utils.start_shellinabox_console,
                          self.info['uuid'],
                          self.info['port'],
                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        self.assertFalse(mock_popen.called)

    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_stop_shellinabox_console(self, mock_stop):

        console_utils.stop_shellinabox_console(self.info['uuid'])

        mock_stop.assert_called_once_with(self.info['uuid'])

    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_stop_shellinabox_console_fail_nopid(self, mock_stop):
        mock_stop.side_effect = exception.NoConsolePid('/tmp/blah')

        console_utils.stop_shellinabox_console(self.info['uuid'])

        mock_stop.assert_called_once_with(self.info['uuid'])

    def test_get_socat_console_url_tcp(self):
        self.config(my_ip="10.0.0.1")
        url = console_utils.get_socat_console_url(self.info['port'])
        self.assertEqual("tcp://10.0.0.1:%s" % self.info['port'], url)

    def test_get_socat_console_url_tcp6(self):
        self.config(my_ip='::1')
        url = console_utils.get_socat_console_url(self.info['port'])
        self.assertEqual("tcp://[::1]:%s" % self.info['port'], url)

    def test_get_socat_console_url_tcp_with_address_conf(self):
        self.config(socat_address="10.0.0.1", group='console')
        url = console_utils.get_socat_console_url(self.info['port'])
        self.assertEqual("tcp://10.0.0.1:%s" % self.info['port'], url)

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid_file', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    @mock.patch.object(loopingcall.FixedIntervalLoopingCall, 'start',
                       autospec=True)
    def _test_start_socat_console_check_arg(self, mock_timer_start,
                                            mock_stop, mock_dir_exists,
                                            mock_get_pid, mock_popen):
        mock_timer_start.return_value = mock.Mock()
        mock_get_pid.return_value = '/tmp/%s.pid' % self.info['uuid']

        console_utils.start_socat_console(self.info['uuid'],
                                          self.info['port'],
                                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_get_pid.assert_called_once_with(self.info['uuid'])
        mock_timer_start.assert_called_once_with(mock.ANY, interval=mock.ANY)
        mock_popen.assert_called_once_with(mock.ANY, stderr=subprocess.PIPE)
        return mock_popen.call_args[0][0]

    def test_start_socat_console_check_arg_default_timeout(self):
        args = self._test_start_socat_console_check_arg()
        self.assertIn('-T600', args)

    def test_start_socat_console_check_arg_timeout(self):
        self.config(terminal_timeout=1, group='console')
        args = self._test_start_socat_console_check_arg()
        self.assertIn('-T1', args)

    def test_start_socat_console_check_arg_timeout_disabled(self):
        self.config(terminal_timeout=0, group='console')
        args = self._test_start_socat_console_check_arg()
        self.assertNotIn('-T0', args)

    def test_start_socat_console_check_arg_bind_addr_default_ipv4(self):
        self.config(my_ip='10.0.0.1')
        args = self._test_start_socat_console_check_arg()
        self.assertIn('TCP4-LISTEN:%s,bind=10.0.0.1,reuseaddr,fork,'
                      'max-children=1' %
                      self.info['port'], args)

    def test_start_socat_console_check_arg_bind_addr_ipv4(self):
        self.config(socat_address='10.0.0.1', group='console')
        args = self._test_start_socat_console_check_arg()
        self.assertIn('TCP4-LISTEN:%s,bind=10.0.0.1,reuseaddr,fork,'
                      'max-children=1' %
                      self.info['port'], args)

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(psutil, 'pid_exists', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_socat_console(self, mock_stop,
                                 mock_dir_exists,
                                 mock_get_pid,
                                 mock_pid_exists,
                                 mock_popen,
                                 mock_path_exists):
        mock_popen.return_value.pid = 23456
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.communicate.return_value = (None, None)

        mock_get_pid.return_value = 23456
        mock_path_exists.return_value = True

        console_utils.start_socat_console(self.info['uuid'],
                                          self.info['port'],
                                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_get_pid.assert_called_with(self.info['uuid'])
        mock_path_exists.assert_called_with(mock.ANY)
        mock_popen.assert_called_once_with(mock.ANY, stderr=subprocess.PIPE)

    @mock.patch.object(os.path, 'exists', autospec=True)
    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(psutil, 'pid_exists', autospec=True)
    @mock.patch.object(console_utils, '_get_console_pid', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_socat_console_nopid(self, mock_stop,
                                       mock_dir_exists,
                                       mock_get_pid,
                                       mock_pid_exists,
                                       mock_popen,
                                       mock_path_exists):
        # no existing PID file before starting
        mock_stop.side_effect = exception.NoConsolePid('/tmp/blah')
        mock_popen.return_value.pid = 23456
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.communicate.return_value = (None, None)

        mock_get_pid.return_value = 23456
        mock_path_exists.return_value = True

        console_utils.start_socat_console(self.info['uuid'],
                                          self.info['port'],
                                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_get_pid.assert_called_with(self.info['uuid'])
        mock_path_exists.assert_called_with(mock.ANY)
        mock_popen.assert_called_once_with(mock.ANY, stderr=subprocess.PIPE)

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_socat_console_fail(self, mock_stop, mock_dir_exists,
                                      mock_popen):
        mock_popen.side_effect = OSError()
        mock_popen.return_value.pid = 23456
        mock_popen.return_value.poll.return_value = 1
        mock_popen.return_value.communicate.return_value = (None, 'error')

        self.assertRaises(exception.ConsoleSubprocessFailed,
                          console_utils.start_socat_console,
                          self.info['uuid'],
                          self.info['port'],
                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        mock_popen.assert_called_once_with(mock.ANY, stderr=subprocess.PIPE)

    @mock.patch.object(subprocess, 'Popen', autospec=True)
    @mock.patch.object(console_utils, '_ensure_console_pid_dir_exists',
                       autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_start_socat_console_fail_nopiddir(self, mock_stop,
                                               mock_dir_exists,
                                               mock_popen):
        mock_dir_exists.side_effect = exception.ConsoleError(message='fail')

        self.assertRaises(exception.ConsoleError,
                          console_utils.start_socat_console,
                          self.info['uuid'],
                          self.info['port'],
                          'ls&')

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_dir_exists.assert_called_once_with()
        self.assertEqual(0, mock_popen.call_count)

    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_stop_socat_console(self, mock_stop):
        console_utils.stop_socat_console(self.info['uuid'])
        mock_stop.assert_called_once_with(self.info['uuid'])

    @mock.patch.object(console_utils.LOG, 'warning', autospec=True)
    @mock.patch.object(console_utils, '_stop_console', autospec=True)
    def test_stop_socat_console_fail_nopid(self, mock_stop, mock_log_warning):
        mock_stop.side_effect = exception.NoConsolePid('/tmp/blah')
        console_utils.stop_socat_console(self.info['uuid'])
        mock_stop.assert_called_once_with(self.info['uuid'])
        # LOG.warning() is called when _stop_console() raises NoConsolePid
        self.assertTrue(mock_log_warning.called)

    def test_valid_console_port_range(self):
        self.config(port_range='10000:20000', group='console')
        start, stop = console_utils._get_port_range()
        self.assertEqual((start, stop), (10000, 20000))

    def test_invalid_console_port_range(self):
        self.config(port_range='20000:10000', group='console')
        self.assertRaises(exception.InvalidParameterValue,
                          console_utils._get_port_range)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_success(self, mock_verify, mock_ports):
        self.config(port_range='10000:10001', group='console')
        port = console_utils.acquire_port()
        mock_verify.assert_called_once_with(10000)
        self.assertEqual(port, 10000)
        mock_ports.add.assert_called_once_with(10000)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_range_retry(self, mock_verify, mock_ports):
        self.config(port_range='10000:10003', group='console')
        mock_verify.side_effect = (exception.Conflict, exception.Conflict,
                                   None)
        port = console_utils.acquire_port()
        verify_calls = [mock.call(10000), mock.call(10001), mock.call(10002)]
        mock_verify.assert_has_calls(verify_calls)
        self.assertEqual(port, 10002)
        mock_ports.add.assert_called_once_with(10002)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_no_free_ports(self, mock_verify, mock_ports):
        self.config(port_range='10000:10005', group='console')
        mock_verify.side_effect = exception.Conflict
        self.assertRaises(exception.NoFreeIPMITerminalPorts,
                          console_utils.acquire_port)
        verify_calls = [mock.call(p) for p in range(10000, 10005)]
        mock_verify.assert_has_calls(verify_calls)
