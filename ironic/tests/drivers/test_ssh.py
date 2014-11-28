# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Test class for Ironic SSH power driver."""

import fixtures
import mock
import paramiko

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import ssh
from ironic.drivers import utils as driver_utils
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

from oslo.concurrency import processutils
from oslo.config import cfg

CONF = cfg.CONF


class SSHValidateParametersTestCase(db_base.DbTestCase):

    def test__parse_driver_info_good_password(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=db_utils.get_test_ssh_info('password'))
        info = ssh._parse_driver_info(node)
        self.assertIsNotNone(info.get('host'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('port'))
        self.assertIsNotNone(info.get('virt_type'))
        self.assertIsNotNone(info.get('cmd_set'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_good_key(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=db_utils.get_test_ssh_info('key'))
        info = ssh._parse_driver_info(node)
        self.assertIsNotNone(info.get('host'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('key_contents'))
        self.assertIsNotNone(info.get('port'))
        self.assertIsNotNone(info.get('virt_type'))
        self.assertIsNotNone(info.get('cmd_set'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_good_file(self):
        # make sure we get back the expected things
        d_info = db_utils.get_test_ssh_info('file')
        tempdir = self.useFixture(fixtures.TempDir())
        key_path = tempdir.path + '/foo'
        open(key_path, 'wt').close()
        d_info['ssh_key_filename'] = key_path
        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=d_info)
        info = ssh._parse_driver_info(node)
        self.assertIsNotNone(info.get('host'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('key_filename'))
        self.assertIsNotNone(info.get('port'))
        self.assertIsNotNone(info.get('virt_type'))
        self.assertIsNotNone(info.get('cmd_set'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_bad_file(self):
        # A filename that doesn't exist errors.
        info = db_utils.get_test_ssh_info('file')
        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=info)
        self.assertRaises(
            exception.InvalidParameterValue, ssh._parse_driver_info, node)

    def test__parse_driver_info_too_many(self):
        info = db_utils.get_test_ssh_info('too_many')
        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=info)
        self.assertRaises(
            exception.InvalidParameterValue, ssh._parse_driver_info, node)

    def test__parse_driver_info_missing_host(self):
        # make sure error is raised when info is missing
        info = db_utils.get_test_ssh_info()
        del info['ssh_address']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_user(self):
        # make sure error is raised when info is missing
        info = db_utils.get_test_ssh_info()
        del info['ssh_username']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_invalid_creds(self):
        # make sure error is raised when info is missing
        info = db_utils.get_test_ssh_info('no-creds')
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_virt_type(self):
        # make sure error is raised when info is missing
        info = db_utils.get_test_ssh_info()
        del info['ssh_virt_type']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_ssh_port_wrong_type(self):
        # make sure error is raised when ssh_port is not integer
        info = db_utils.get_test_ssh_info()
        info['ssh_port'] = 'wrong_port_value'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__normalize_mac_string(self):
        mac_raw = "0A:1B-2C-3D:4F"
        mac_clean = ssh._normalize_mac(mac_raw)
        self.assertEqual("0a1b2c3d4f", mac_clean)

    def test__normalize_mac_unicode(self):
        mac_raw = u"0A:1B-2C-3D:4F"
        mac_clean = ssh._normalize_mac(mac_raw)
        self.assertEqual("0a1b2c3d4f", mac_clean)

    def test__parse_driver_info_with_custom_libvirt_uri(self):
        CONF.set_override('libvirt_uri', 'qemu:///foo', 'ssh')
        expected_base_cmd = "LC_ALL=C /usr/bin/virsh --connect qemu:///foo"

        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=db_utils.get_test_ssh_info())
        node['driver_info']['ssh_virt_type'] = 'virsh'
        info = ssh._parse_driver_info(node)
        self.assertEqual(expected_base_cmd, info['cmd_set']['base_cmd'])

    def test__get_boot_device_map_parallels(self):
        boot_map = ssh._get_boot_device_map('parallels')
        self.assertEqual('net0', boot_map[boot_devices.PXE])

    def test__get_boot_device_map_vbox(self):
        boot_map = ssh._get_boot_device_map('vbox')
        self.assertEqual('net', boot_map[boot_devices.PXE])

    def test__get_boot_device_map_exception(self):
        self.assertRaises(exception.InvalidParameterValue,
                          ssh._get_boot_device_map,
                          'this_doesn_t_exist')


class SSHPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SSHPrivateMethodsTestCase, self).setUp()
        self.node = obj_utils.get_test_node(
                        self.context,
                        driver='fake_ssh',
                        driver_info=db_utils.get_test_ssh_info())
        self.sshclient = paramiko.SSHClient()

    @mock.patch.object(utils, 'ssh_connect')
    def test__get_connection_client(self, ssh_connect_mock):
        ssh_connect_mock.return_value = self.sshclient
        client = ssh._get_connection(self.node)
        self.assertEqual(self.sshclient, client)
        driver_info = ssh._parse_driver_info(self.node)
        ssh_connect_mock.assert_called_once_with(driver_info)

    @mock.patch.object(utils, 'ssh_connect')
    def test__get_connection_exception(self, ssh_connect_mock):
        ssh_connect_mock.side_effect = exception.SSHConnectFailed(host='fake')
        self.assertRaises(exception.SSHConnectFailed,
                          ssh._get_connection,
                          self.node)
        driver_info = ssh._parse_driver_info(self.node)
        ssh_connect_mock.assert_called_once_with(driver_info)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__ssh_execute(self, exec_ssh_mock):
        ssh_cmd = "somecmd"
        expected = ['a', 'b', 'c']
        exec_ssh_mock.return_value = ('\n'.join(expected), '')
        lst = ssh._ssh_execute(self.sshclient, ssh_cmd)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        self.assertEqual(expected, lst)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__ssh_execute_exception(self, exec_ssh_mock):
        ssh_cmd = "somecmd"
        exec_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.SSHCommandFailed,
                          ssh._ssh_execute,
                          self.sshclient,
                          ssh_cmd)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__get_power_status_on(self, get_hosts_name_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.return_value = (
            '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}', '')
        get_hosts_name_mock.return_value = "NodeName"

        pstate = ssh._get_power_status(self.sshclient, info)

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])
        self.assertEqual(states.POWER_ON, pstate)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__get_power_status_off(self, get_hosts_name_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.return_value = (
            '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}', '')
        get_hosts_name_mock.return_value = "NotNodeName"

        pstate = ssh._get_power_status(self.sshclient, info)

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])
        self.assertEqual(states.POWER_OFF, pstate)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__get_power_status_error(self, get_hosts_name_mock, exec_ssh_mock):

        info = ssh._parse_driver_info(self.node)

        exec_ssh_mock.return_value = (
            '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}', '')
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_hosts_name_mock.return_value = None
        self.assertRaises(exception.NodeNotFound,
                          ssh._get_power_status,
                          self.sshclient,
                          info)

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])

        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__get_power_status_exception(self, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.SSHCommandFailed,
                          ssh._get_power_status,
                          self.sshclient,
                          info)
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])
        exec_ssh_mock.assert_called_once_with(
                self.sshclient, ssh_cmd)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__get_hosts_name_for_node_match(self, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        exec_ssh_mock.side_effect = [('NodeName', ''),
                                          ('52:54:00:cf:2d:31', '')]
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)]

        found_name = ssh._get_hosts_name_for_node(self.sshclient, info)

        self.assertEqual('NodeName', found_name)
        self.assertEqual(expected, exec_ssh_mock.call_args_list)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__get_hosts_name_for_node_no_match(self, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "22:22:22:22:22:22"]
        exec_ssh_mock.side_effect = [('NodeName', ''),
                                          ('52:54:00:cf:2d:31', '')]

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])

        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)]

        found_name = ssh._get_hosts_name_for_node(self.sshclient, info)

        self.assertIsNone(found_name)
        self.assertEqual(expected, exec_ssh_mock.call_args_list)

    @mock.patch.object(processutils, 'ssh_execute')
    def test__get_hosts_name_for_node_exception(self, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')

        exec_ssh_mock.side_effect = [('NodeName', ''),
                                     processutils.ProcessExecutionError]
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)]

        self.assertRaises(exception.SSHCommandFailed,
                          ssh._get_hosts_name_for_node,
                          self.sshclient,
                          info)
        self.assertEqual(expected, exec_ssh_mock.call_args_list)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_on_good(self, get_hosts_name_mock, get_power_status_mock,
                            exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        get_power_status_mock.side_effect = [states.POWER_OFF,
                                             states.POWER_ON]
        get_hosts_name_mock.return_value = "NodeName"
        expected = [mock.call(self.sshclient, info),
                    mock.call(self.sshclient, info)]

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['start_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        current_state = ssh._power_on(self.sshclient, info)

        self.assertEqual(states.POWER_ON, current_state)
        self.assertEqual(expected, get_power_status_mock.call_args_list)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_on_fail(self, get_hosts_name_mock, get_power_status_mock,
                            exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_power_status_mock.side_effect = [states.POWER_OFF,
                                             states.POWER_OFF]
        get_hosts_name_mock.return_value = "NodeName"
        expected = [mock.call(self.sshclient, info),
                    mock.call(self.sshclient, info)]

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['start_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        current_state = ssh._power_on(self.sshclient, info)

        self.assertEqual(states.ERROR, current_state)
        self.assertEqual(expected, get_power_status_mock.call_args_list)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_on_exception(self, get_hosts_name_mock,
                                 get_power_status_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        exec_ssh_mock.side_effect = processutils.ProcessExecutionError
        get_power_status_mock.side_effect = [states.POWER_OFF,
                                             states.POWER_ON]
        get_hosts_name_mock.return_value = "NodeName"

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['start_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')

        self.assertRaises(exception.SSHCommandFailed,
                          ssh._power_on,
                          self.sshclient,
                          info)
        get_power_status_mock.assert_called_once_with(self.sshclient, info)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_off_good(self, get_hosts_name_mock,
                             get_power_status_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_power_status_mock.side_effect = [states.POWER_ON,
                                             states.POWER_OFF]
        get_hosts_name_mock.return_value = "NodeName"
        expected = [mock.call(self.sshclient, info),
                    mock.call(self.sshclient, info)]

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['stop_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        current_state = ssh._power_off(self.sshclient, info)

        self.assertEqual(states.POWER_OFF, current_state)
        self.assertEqual(expected, get_power_status_mock.call_args_list)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_off_fail(self, get_hosts_name_mock,
                             get_power_status_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_power_status_mock.side_effect = [states.POWER_ON,
                                             states.POWER_ON]
        get_hosts_name_mock.return_value = "NodeName"
        expected = [mock.call(self.sshclient, info),
                    mock.call(self.sshclient, info)]

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['stop_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        current_state = ssh._power_off(self.sshclient, info)

        self.assertEqual(states.ERROR, current_state)
        self.assertEqual(expected, get_power_status_mock.call_args_list)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    @mock.patch.object(processutils, 'ssh_execute')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test__power_off_exception(self, get_hosts_name_mock,
                                  get_power_status_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        exec_ssh_mock.side_effect = processutils.ProcessExecutionError
        get_power_status_mock.side_effect = [states.POWER_ON,
                                             states.POWER_OFF]
        get_hosts_name_mock.return_value = "NodeName"

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['stop_cmd'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')

        self.assertRaises(exception.SSHCommandFailed, ssh._power_off,
                          self.sshclient, info)
        get_power_status_mock.assert_called_once_with(self.sshclient, info)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)
        exec_ssh_mock.assert_called_once_with(self.sshclient, cmd_to_exec)

    def test_exec_ssh_command_good(self):
        class Channel(object):
            def recv_exit_status(self):
                return 0

        class Stream(object):
            def __init__(self, buffer=''):
                self.buffer = buffer
                self.channel = Channel()

            def read(self):
                return self.buffer

            def close(self):
                pass

        with mock.patch.object(self.sshclient,
                               'exec_command') as exec_command_mock:
            exec_command_mock.return_value = (Stream(),
                                              Stream('hello'),
                                              Stream())
            stdout, stderr = processutils.ssh_execute(self.sshclient,
                                                      "command")

            self.assertEqual('hello', stdout)
            exec_command_mock.assert_called_once_with("command")

    def test_exec_ssh_command_fail(self):
        class Channel(object):
            def recv_exit_status(self):
                return 127

        class Stream(object):
            def __init__(self, buffer=''):
                self.buffer = buffer
                self.channel = Channel()

            def read(self):
                return self.buffer

            def close(self):
                pass

        with mock.patch.object(self.sshclient,
                               'exec_command') as exec_command_mock:
            exec_command_mock.return_value = (Stream(),
                                              Stream('hello'),
                                              Stream())
            self.assertRaises(processutils.ProcessExecutionError,
                              processutils.ssh_execute,
                              self.sshclient,
                              "command")
            exec_command_mock.assert_called_once_with("command")


class SSHDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SSHDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_ssh")
        self.driver = driver_factory.get_driver("fake_ssh")
        self.node = obj_utils.create_test_node(
                self.context, driver='fake_ssh',
                driver_info=db_utils.get_test_ssh_info())
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)
        self.sshclient = paramiko.SSHClient()

    @mock.patch.object(utils, 'ssh_connect')
    def test__validate_info_ssh_connect_failed(self, ssh_connect_mock):
        info = ssh._parse_driver_info(self.node)

        ssh_connect_mock.side_effect = exception.SSHConnectFailed(host='fake')
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate, task)
            driver_info = ssh._parse_driver_info(task.node)
            ssh_connect_mock.assert_called_once_with(driver_info)

    def test_get_properties(self):
        expected = ssh.COMMON_PROPERTIES
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.power.get_properties())
            self.assertEqual(expected, task.driver.get_properties())
            self.assertEqual(expected, task.driver.management.get_properties())

    def test_validate_fail_no_port(self):
        new_node = obj_utils.create_test_node(
                self.context,
                uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                driver='fake_ssh',
                driver_info=db_utils.get_test_ssh_info())
        with task_manager.acquire(self.context, new_node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_power_off')
    @mock.patch.object(ssh, '_power_on')
    def test_reboot_good(self, power_on_mock, power_off_mock,
                         get_power_stat_mock, get_conn_mock,
                         get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        get_power_stat_mock.return_value = states.POWER_ON
        power_off_mock.return_value = None
        power_on_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.reboot(task)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                get_power_stat_mock.assert_called_once_with(self.sshclient,
                                                            info)
                power_off_mock.assert_called_once_with(self.sshclient, info)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_power_status')
    @mock.patch.object(ssh, '_power_off')
    @mock.patch.object(ssh, '_power_on')
    def test_reboot_fail(self, power_on_mock, power_off_mock,
                         get_power_stat_mock, get_conn_mock,
                         get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        get_power_stat_mock.return_value = states.POWER_ON
        power_off_mock.return_value = None
        power_on_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                self.assertRaises(exception.PowerStateFailure,
                                  task.driver.power.reboot, task)
                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                get_power_stat_mock.assert_called_once_with(self.sshclient,
                                                            info)
                power_off_mock.assert_called_once_with(self.sshclient, info)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    def test_set_power_state_bad_state(self, get_conn_mock,
                                       get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                self.assertRaises(
                    exception.InvalidParameterValue,
                    task.driver.power.set_power_state,
                    task,
                    "BAD_PSTATE")

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_power_on')
    def test_set_power_state_on_good(self, power_on_mock, get_conn_mock,
                                     get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.set_power_state(task, states.POWER_ON)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_power_on')
    def test_set_power_state_on_fail(self, power_on_mock, get_conn_mock,
                                     get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                self.assertRaises(
                    exception.PowerStateFailure,
                    task.driver.power.set_power_state,
                    task,
                    states.POWER_ON)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_power_off')
    def test_set_power_state_off_good(self, power_off_mock, get_conn_mock,
                                      get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_off_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.set_power_state(task, states.POWER_OFF)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_off_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses')
    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_power_off')
    def test_set_power_state_off_fail(self, power_off_mock, get_conn_mock,
                                      get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_off_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh,
                               '_parse_driver_info') as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                self.assertRaises(
                    exception.PowerStateFailure,
                    task.driver.power.set_power_state,
                    task,
                    states.POWER_OFF)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_off_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_set_boot_device_vbox_ok(self, mock_exc,
                                                          mock_h,
                                                          mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vbox'
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        expected_cmd = ('LC_ALL=C /usr/bin/VBoxManage modifyvm %s '
                        '--boot1 net') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_set_boot_device_parallels_ok(self, mock_exc,
                                                               mock_h,
                                                               mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'parallels'
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        expected_cmd = ('LC_ALL=C /usr/bin/prlctl set %s '
                        '--device-bootorder "net0"') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_set_boot_device_virsh_ok(self, mock_exc,
                                                           mock_h,
                                                           mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'virsh'
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        expected_cmd = ('EDITOR="sed -i \'/<boot \\(dev\\|order\\)=*\\>'
                        '/d;/<\\/os>/i\\<boot dev=\\"network\\"/>\'" '
                        'LC_ALL=C /usr/bin/virsh --connect qemu:///system '
                        'edit %s') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.management.set_boot_device,
                    task, 'invalid-device')

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test_set_boot_device_not_supported(self, mock_h, mock_get_conn):
        mock_h.return_value = 'NodeName'
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # vmware does not support set_boot_device()
            task.node['driver_info']['ssh_virt_type'] = 'vmware'
            self.assertRaises(NotImplementedError,
                              self.driver.management.set_boot_device,
                              task, boot_devices.PXE)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices()))

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_get_boot_device_vbox(self, mock_exc,
                                                       mock_h,
                                                       mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_exc.return_value = ('net', '')
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vbox'
            result = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.PXE, result['boot_device'])
        expected_cmd = ('LC_ALL=C /usr/bin/VBoxManage showvminfo '
                        '--machinereadable %s '
                        '| awk -F \'"\' \'/boot1/{print $2}\'') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_get_boot_device_parallels(self, mock_exc,
                                                            mock_h,
                                                            mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_exc.return_value = ('net0', '')
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'parallels'
            result = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.PXE, result['boot_device'])
        expected_cmd = ('LC_ALL=C /usr/bin/prlctl list -i %s '
                        '| awk \'/^Boot order:/ {print $3}\'') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    @mock.patch.object(ssh, '_ssh_execute')
    def test_management_interface_get_boot_device_virsh(self, mock_exc,
                                                        mock_h,
                                                        mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_exc.return_value = ('network', '')
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'virsh'
            result = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.PXE, result['boot_device'])
        expected_cmd = ('LC_ALL=C /usr/bin/virsh --connect '
                        'qemu:///system dumpxml %s | awk \'/boot dev=/ '
                        '{ gsub( ".*dev=" Q, "" ); gsub( Q ".*", "" ); '
                        'print; }\' Q="\'" RS="[<>]" | head -1') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection')
    @mock.patch.object(ssh, '_get_hosts_name_for_node')
    def test_get_boot_device_not_supported(self, mock_h, mock_get_conn):
        mock_h.return_value = 'NodeName'
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # vmware does not support get_boot_device()
            task.node['driver_info']['ssh_virt_type'] = 'vmware'
            expected = {'boot_device': None, 'persistent': None}
            self.assertEqual(expected,
                             self.driver.management.get_boot_device(task))

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing SSH driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=utils.generate_uuid(),
                                          driver='fake_ssh')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)
