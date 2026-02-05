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

import os
import random
import signal
import socket
import string
import subprocess
import tempfile
from unittest import mock

from oslo_config import cfg
from oslo_service import loopingcall
import psutil

from ironic.common import exception
from ironic.common import utils
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
        self.mock_stdout = tempfile.NamedTemporaryFile(delete=False)
        self.mock_stderr = tempfile.NamedTemporaryFile(delete=False)

    def tearDown(self):
        super(ConsoleUtilsTestCase, self).tearDown()
        self.mock_stdout.close()
        self.mock_stderr.close()
        os.remove(self.mock_stdout.name)
        os.remove(self.mock_stderr.name)

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

    @mock.patch.object(utils, 'unlink_without_raise', autospec=True)
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

    @mock.patch.object(utils, 'unlink_without_raise', autospec=True)
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

    @mock.patch.object(utils, 'unlink_without_raise', autospec=True)
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

    @mock.patch.object(utils, 'unlink_without_raise', autospec=True)
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
    def test_start_socat_console_with_env_variables(
            self, mock_stop, mock_dir_exists, mock_get_pid,
            mock_pid_exists, mock_popen, mock_path_exists):
        """Test start_socat_console passes env_variables to Popen."""
        mock_get_pid.return_value = 23456
        mock_popen.return_value.pid = 23456
        mock_popen.return_value.poll.return_value = None
        mock_popen.return_value.communicate.return_value = (None, None)
        mock_pid_exists.return_value = True
        mock_path_exists.return_value = True

        console_utils.start_socat_console(
            self.info['uuid'], self.info['port'], 'ls&',
            env_variables={'SOME_VAR': 'value'})

        mock_popen.assert_called_once()
        call_kwargs = mock_popen.call_args[1]
        self.assertIn('env', call_kwargs)
        env = call_kwargs['env']
        self.assertEqual(env.get('SOME_VAR'), 'value')
        # Should be a copy of os.environ plus our var
        for key, value in os.environ.items():
            self.assertEqual(env.get(key), value,
                             'env should contain os.environ')

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

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_success(self, mock_verify, mock_ports):
        self.config(port_range=['10000:10001'], group='console')
        port = console_utils.acquire_port()
        mock_verify.assert_called_once_with(10000, host=None)
        self.assertEqual(port, 10000)
        mock_ports.add.assert_called_once_with(10000)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_range_retry(self, mock_verify, mock_ports):
        self.config(port_range=['10000:10003'], group='console')
        mock_verify.side_effect = (exception.Conflict, exception.Conflict,
                                   None)
        port = console_utils.acquire_port()
        verify_calls = [mock.call(10000, host=None),
                        mock.call(10001, host=None),
                        mock.call(10002, host=None)]
        mock_verify.assert_has_calls(verify_calls)
        self.assertEqual(port, 10002)
        mock_ports.add.assert_called_once_with(10002)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_no_free_ports(self, mock_verify, mock_ports):
        self.config(port_range=['10000:10005'], group='console')
        mock_verify.side_effect = exception.Conflict
        self.assertRaises(exception.NoFreeIPMITerminalPorts,
                          console_utils.acquire_port)
        verify_calls = [mock.call(p, host=None) for p in range(10000, 10005)]
        mock_verify.assert_has_calls(verify_calls)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_segmented_range_first_range(self, mock_verify,
                                                       mock_ports):
        self.config(port_range=['1000:1001', '2000:2001'], group='console')
        port = console_utils.acquire_port()
        mock_verify.assert_called_once_with(1000, host=None)
        self.assertEqual(port, 1000)
        mock_ports.add.assert_called_once_with(1000)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_segmented_range_second_range(self, mock_verify,
                                                        mock_ports):
        self.config(port_range=['1000:1001', '2000:2001'], group='console')
        # Port 1000 is already allocated
        mock_ports.__contains__ = mock.Mock(side_effect=lambda x: x == 1000)
        mock_verify.side_effect = (None,)
        port = console_utils.acquire_port()
        mock_verify.assert_called_once_with(2000, host=None)
        self.assertEqual(port, 2000)
        mock_ports.add.assert_called_once_with(2000)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_segmented_range_exhausted_first(self, mock_verify,
                                                           mock_ports):
        self.config(port_range=['1000:1002', '2000:2002'], group='console')
        # First range ports are in ALLOCATED_PORTS
        mock_ports.__contains__ = mock.Mock(
            side_effect=lambda x: x in (1000, 1001))
        mock_verify.side_effect = (None,)
        port = console_utils.acquire_port()
        # Should skip first range and get port from second range
        mock_verify.assert_called_once_with(2000, host=None)
        self.assertEqual(port, 2000)
        mock_ports.add.assert_called_once_with(2000)

    @mock.patch.object(console_utils, 'ALLOCATED_PORTS', autospec=True)
    @mock.patch.object(console_utils, '_verify_port', autospec=True)
    def test_allocate_port_segmented_range_no_free_ports(self, mock_verify,
                                                         mock_ports):
        self.config(port_range=['1000:1002', '2000:2002'], group='console')
        mock_verify.side_effect = exception.Conflict
        self.assertRaises(exception.NoFreeIPMITerminalPorts,
                          console_utils.acquire_port)
        # Should try all ports in both ranges
        verify_calls = (
            [mock.call(p, host=None) for p in range(1000, 1002)]
            + [mock.call(p, host=None) for p in range(2000, 2002)])

        mock_verify.assert_has_calls(verify_calls)

    @mock.patch.object(socket, 'socket', autospec=True)
    def test__verify_port_default(self, mock_socket):
        self.config(host='localhost.localdomain')
        mock_sock = mock.MagicMock()
        mock_socket.return_value = mock_sock
        console_utils._verify_port(10000)
        mock_sock.bind.assert_called_once_with(('localhost.localdomain',
                                                10000))

    @mock.patch.object(socket, 'socket', autospec=True)
    def test__verify_port_hostname(self, mock_socket):
        mock_sock = mock.MagicMock()
        mock_socket.return_value = mock_sock
        console_utils._verify_port(10000, host='localhost.localdomain')
        mock_socket.assert_called_once_with()
        mock_sock.bind.assert_called_once_with(('localhost.localdomain',
                                                10000))

    @mock.patch.object(socket, 'socket', autospec=True)
    def test__verify_port_ipv4(self, mock_socket):
        mock_sock = mock.MagicMock()
        mock_socket.return_value = mock_sock
        console_utils._verify_port(10000, host='1.2.3.4')
        mock_socket.assert_called_once_with()
        mock_sock.bind.assert_called_once_with(('1.2.3.4', 10000))

    @mock.patch.object(socket, 'socket', autospec=True)
    def test__verify_port_ipv6(self, mock_socket):
        mock_sock = mock.MagicMock()
        mock_socket.return_value = mock_sock
        console_utils._verify_port(10000, host='2001:dead:beef::1')
        mock_socket.assert_called_once_with(socket.AF_INET6)
        mock_sock.bind.assert_called_once_with(('2001:dead:beef::1', 10000))
