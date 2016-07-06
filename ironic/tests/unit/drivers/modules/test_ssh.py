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

import tempfile

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import uuidutils
import paramiko

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import ssh
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF


class SSHValidateParametersTestCase(db_base.DbTestCase):

    def test__parse_driver_info_good_password(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
            self.context,
            driver='fake_ssh',
            driver_info=db_utils.get_test_ssh_info('password'))
        info = ssh._parse_driver_info(node)
        self.assertEqual('1.2.3.4', info['host'])
        self.assertEqual('admin', info['username'])
        self.assertEqual('fake', info['password'])
        self.assertEqual(22, info['port'])
        self.assertEqual('virsh', info['virt_type'])
        self.assertIsNotNone(info['cmd_set'])
        self.assertEqual('1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                         info['uuid'])

    def test__parse_driver_info_good_key(self):
        # make sure we get back the expected things
        node = obj_utils.get_test_node(
            self.context,
            driver='fake_ssh',
            driver_info=db_utils.get_test_ssh_info('key'))
        info = ssh._parse_driver_info(node)
        self.assertEqual('1.2.3.4', info['host'])
        self.assertEqual('admin', info['username'])
        self.assertEqual('--BEGIN PRIVATE ...blah', info['key_contents'])
        self.assertEqual(22, info['port'])
        self.assertEqual('virsh', info['virt_type'])
        self.assertIsNotNone(info['cmd_set'])
        self.assertEqual('1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                         info['uuid'])

    def test__parse_driver_info_good_file(self):
        # make sure we get back the expected things
        d_info = db_utils.get_test_ssh_info('file')
        tempdir = tempfile.mkdtemp()
        key_path = tempdir + '/foo'
        open(key_path, 'wt').close()
        d_info['ssh_key_filename'] = key_path
        node = obj_utils.get_test_node(
            self.context,
            driver='fake_ssh',
            driver_info=d_info)
        info = ssh._parse_driver_info(node)
        self.assertEqual('1.2.3.4', info['host'])
        self.assertEqual('admin', info['username'])
        self.assertEqual(key_path, info['key_filename'])
        self.assertEqual(22, info['port'])
        self.assertEqual('virsh', info['virt_type'])
        self.assertIsNotNone(info['cmd_set'])
        self.assertEqual('1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                         info['uuid'])

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

    def test__get_boot_device_map_xenserver(self):
        boot_map = ssh._get_boot_device_map('xenserver')
        self.assertEqual('n', boot_map[boot_devices.PXE])

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

    @mock.patch.object(utils, 'ssh_connect', autospec=True)
    def test__get_connection_client(self, ssh_connect_mock):
        ssh_connect_mock.return_value = self.sshclient
        client = ssh._get_connection(self.node)
        self.assertEqual(self.sshclient, client)
        driver_info = ssh._parse_driver_info(self.node)
        ssh_connect_mock.assert_called_once_with(driver_info)

    @mock.patch.object(utils, 'ssh_connect', autospec=True)
    def test__get_connection_exception(self, ssh_connect_mock):
        ssh_connect_mock.side_effect = exception.SSHConnectFailed(host='fake')
        self.assertRaises(exception.SSHConnectFailed,
                          ssh._get_connection,
                          self.node)
        driver_info = ssh._parse_driver_info(self.node)
        ssh_connect_mock.assert_called_once_with(driver_info)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    def test__ssh_execute(self, exec_ssh_mock):
        ssh_cmd = "somecmd"
        expected = ['a', 'b', 'c']
        exec_ssh_mock.return_value = ('\n'.join(expected), '')
        lst = ssh._ssh_execute(self.sshclient, ssh_cmd)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        self.assertEqual(expected, lst)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    def test__ssh_execute_exception(self, exec_ssh_mock):
        ssh_cmd = "somecmd"
        exec_ssh_mock.side_effect = processutils.ProcessExecutionError
        self.assertRaises(exception.SSHCommandFailed,
                          ssh._ssh_execute,
                          self.sshclient,
                          ssh_cmd)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    def test__get_power_status_on_unquoted(self, get_hosts_name_mock,
                                           exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.return_value = (
            'ExactNodeName', '')
        get_hosts_name_mock.return_value = "ExactNodeName"

        pstate = ssh._get_power_status(self.sshclient, info)

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])
        self.assertEqual(states.POWER_ON, pstate)
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)
        get_hosts_name_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    def test__get_power_status_exception(self, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.side_effect = processutils.ProcessExecutionError

        self.assertRaises(exception.SSHCommandFailed,
                          ssh._get_power_status,
                          self.sshclient,
                          info)
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])
        exec_ssh_mock.assert_called_once_with(
            self.sshclient, ssh_cmd)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    def test__get_power_status_correct_node(self, get_hosts_name_mock,
                                            exec_ssh_mock):
        # Bug: #1397834 test that get_power_status return status of
        # baremeta_1 (off) and not baremetal_11 (on)
        info = ssh._parse_driver_info(self.node)
        exec_ssh_mock.return_value = ('"baremetal_11"\n"seed"\n', '')
        get_hosts_name_mock.return_value = "baremetal_1"

        pstate = ssh._get_power_status(self.sshclient, info)
        self.assertEqual(states.POWER_OFF, pstate)
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_running'])
        exec_ssh_mock.assert_called_once_with(self.sshclient, ssh_cmd)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    def test__get_hosts_name_for_node_no_match(self, exec_ssh_mock):
        self.config(group='ssh', get_vm_name_attempts=2)
        self.config(group='ssh', get_vm_name_retry_interval=0)
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "22:22:22:22:22:22"]
        exec_ssh_mock.side_effect = ([('NodeName', ''),
                                      ('52:54:00:cf:2d:31', '')] * 2)

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])

        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)] * 2

        self.assertRaises(exception.NodeNotFound,
                          ssh._get_hosts_name_for_node, self.sshclient, info)
        self.assertEqual(expected, exec_ssh_mock.call_args_list)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    def test__get_hosts_name_for_node_match_after_retry(self, exec_ssh_mock):
        self.config(group='ssh', get_vm_name_attempts=2)
        self.config(group='ssh', get_vm_name_retry_interval=0)
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "22:22:22:22:22:22"]
        exec_ssh_mock.side_effect = [('NodeName', ''),
                                     ('', ''),
                                     ('NodeName', ''),
                                     ('11:11:11:11:11:11', '')]

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])

        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)] * 2

        found_name = ssh._get_hosts_name_for_node(self.sshclient, info)

        self.assertEqual('NodeName', found_name)
        self.assertEqual(expected, exec_ssh_mock.call_args_list)

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    def test__power_on_fail(self, get_hosts_name_mock, get_power_status_mock,
                            exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_power_status_mock.side_effect = ([states.POWER_OFF,
                                              states.POWER_OFF])
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    def test__power_on_exception(self, get_hosts_name_mock,
                                 get_power_status_mock, exec_ssh_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        exec_ssh_mock.side_effect = processutils.ProcessExecutionError
        get_power_status_mock.side_effect = ([states.POWER_OFF,
                                              states.POWER_ON])
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(processutils, 'ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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

    @mock.patch.object(utils, 'ssh_connect', autospec=True)
    def test__validate_info_ssh_connect_failed(self, ssh_connect_mock):
        ssh_connect_mock.side_effect = exception.SSHConnectFailed(host='fake')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate, task)
            driver_info = ssh._parse_driver_info(task.node)
            ssh_connect_mock.assert_called_once_with(driver_info)

    def test_get_properties(self):
        expected = ssh.COMMON_PROPERTIES
        expected2 = list(ssh.COMMON_PROPERTIES) + list(ssh.CONSOLE_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.power.get_properties())
            self.assertEqual(expected, task.driver.management.get_properties())
            self.assertEqual(
                sorted(expected2),
                sorted(task.driver.console.get_properties().keys()))
            self.assertEqual(
                sorted(expected2),
                sorted(task.driver.get_properties().keys()))

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

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_on', autospec=True)
    def test_reboot_good(self, power_on_mock, get_conn_mock,
                         get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.reboot(task)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_on', autospec=True)
    def test_reboot_fail(self, power_on_mock, get_conn_mock,
                         get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                self.assertRaises(exception.PowerStateFailure,
                                  task.driver.power.reboot, task)
                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    def test_set_power_state_bad_state(self, get_conn_mock,
                                       get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
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

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_on', autospec=True)
    def test_set_power_state_on_good(self, power_on_mock, get_conn_mock,
                                     get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.set_power_state(task, states.POWER_ON)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_on_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_on', autospec=True)
    def test_set_power_state_on_fail(self, power_on_mock, get_conn_mock,
                                     get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_on_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
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

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_off', autospec=True)
    def test_set_power_state_off_good(self, power_off_mock, get_conn_mock,
                                      get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_off_mock.return_value = states.POWER_OFF
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
            parse_drv_info_mock.return_value = info
            with task_manager.acquire(self.context, info['uuid'],
                                      shared=False) as task:
                task.driver.power.set_power_state(task, states.POWER_OFF)

                parse_drv_info_mock.assert_called_once_with(task.node)
                get_mac_addr_mock.assert_called_once_with(mock.ANY)
                get_conn_mock.assert_called_once_with(task.node)
                power_off_mock.assert_called_once_with(self.sshclient, info)

    @mock.patch.object(driver_utils, 'get_node_mac_addresses', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_power_off', autospec=True)
    def test_set_power_state_off_fail(self, power_off_mock, get_conn_mock,
                                      get_mac_addr_mock):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        get_mac_addr_mock.return_value = info['macs']
        get_conn_mock.return_value = self.sshclient
        power_off_mock.return_value = states.POWER_ON
        with mock.patch.object(ssh, '_parse_driver_info',
                               autospec=True) as parse_drv_info_mock:
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    def test_management_interface_set_boot_device_vbox_with_power_on(
            self, mock_exc, mock_h, mock_get_conn, mock_get_power):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_get_conn.return_value = self.sshclient
        # NOTE(jroll) _power_off calls _get_power_state twice
        mock_get_power.side_effect = [
            states.POWER_ON, states.POWER_ON, states.POWER_OFF
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vbox'
            task.node['driver_info']['vbox_use_headless'] = True
            self.driver.management.set_boot_device(task, boot_devices.PXE)

        expected_cmds = [
            mock.call(mock.ANY,
                      'LC_ALL=C /usr/bin/VBoxManage '
                      'controlvm %s poweroff' % fake_name),
            mock.call(mock.ANY,
                      'LC_ALL=C /usr/bin/VBoxManage '
                      'modifyvm %s --boot1 net' % fake_name)
        ]
        self.assertEqual(expected_cmds, mock_exc.call_args_list)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    def test_management_interface_set_boot_device_xenserver_ok(self,
                                                               mock_exc,
                                                               mock_h,
                                                               mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'xenserver'
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        expected_cmd = ("LC_ALL=C /opt/xensource/bin/xe vm-param-set uuid=%s "
                        "HVM-boot-params:order='n'") % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.management.set_boot_device,
                              task, 'invalid-device')

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
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
                             get_supported_boot_devices(task)))

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
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

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    def test_management_interface_get_boot_device_xenserver(self, mock_exc,
                                                            mock_h,
                                                            mock_get_conn):
        fake_name = 'fake-name'
        mock_h.return_value = fake_name
        mock_exc.return_value = ('n', '')
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'xenserver'
            result = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.PXE, result['boot_device'])
        expected_cmd = ('LC_ALL=C /opt/xensource/bin/xe vm-param-get '
                        'uuid=%s --param-name=HVM-boot-params '
                        'param-key=order | cut -b 1') % fake_name
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    def test_get_boot_device_not_supported(self, mock_h, mock_get_conn):
        mock_h.return_value = 'NodeName'
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # vmware does not support get_boot_device()
            task.node['driver_info']['ssh_virt_type'] = 'vmware'
            expected = {'boot_device': None, 'persistent': None}
            self.assertEqual(expected,
                             self.driver.management.get_boot_device(task))

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    def test_get_power_state_vmware(self, mock_exc, mock_h, mock_get_conn):
        # To see replacing {_NodeName_} in vmware's list_running
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        # list_running quotes names
        mock_exc.return_value = ('"%s"' % nodename, '')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vmware'
            power_state = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, power_state)
        expected_cmd = ("LC_ALL=C /bin/vim-cmd vmsvc/power.getstate "
                        "%(node)s | grep 'Powered on' >/dev/null && "
                        "echo '\"%(node)s\"' || true") % {'node': nodename}
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    def test_get_power_state_xenserver(self, mock_exc, mock_h, mock_get_conn):
        # To see replacing {_NodeName_} in xenserver's list_running
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        mock_exc.return_value = (nodename, '')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'xenserver'
            power_state = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, power_state)
        expected_cmd = ("LC_ALL=C /opt/xensource/bin/xe "
                        "vm-list power-state=running --minimal | tr ',' '\n'")
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    def test_start_command_xenserver(self, mock_power, mock_exc, mock_h,
                                     mock_get_conn):
        mock_power.side_effect = [states.POWER_OFF, states.POWER_ON]
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'xenserver'
            self.driver.power.set_power_state(task, states.POWER_ON)
        expected_cmd = ("LC_ALL=C /opt/xensource/bin/xe "
                        "vm-start uuid=fakevm && sleep 10s")
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    def test_stop_command_xenserver(self, mock_power, mock_exc, mock_h,
                                    mock_get_conn):
        mock_power.side_effect = [states.POWER_ON, states.POWER_OFF]
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'xenserver'
            self.driver.power.set_power_state(task, states.POWER_OFF)
        expected_cmd = ("LC_ALL=C /opt/xensource/bin/xe "
                        "vm-shutdown uuid=fakevm force=true")
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    def test_start_command_vbox(self, mock_power, mock_exc, mock_h,
                                mock_get_conn):
        mock_power.side_effect = [states.POWER_OFF, states.POWER_ON]
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vbox'
            self.driver.power.set_power_state(task, states.POWER_ON)
        expected_cmd = 'LC_ALL=C /usr/bin/VBoxManage startvm fakevm'
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(ssh, '_ssh_execute', autospec=True)
    @mock.patch.object(ssh, '_get_power_status', autospec=True)
    def test_start_command_vbox_headless(self, mock_power, mock_exc, mock_h,
                                         mock_get_conn):
        mock_power.side_effect = [states.POWER_OFF, states.POWER_ON]
        nodename = 'fakevm'
        mock_h.return_value = nodename
        mock_get_conn.return_value = self.sshclient
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node['driver_info']['ssh_virt_type'] = 'vbox'
            task.node['driver_info']['vbox_use_headless'] = True
            self.driver.power.set_power_state(task, states.POWER_ON)
        expected_cmd = ('LC_ALL=C /usr/bin/VBoxManage '
                        'startvm fakevm --type headless')
        mock_exc.assert_called_once_with(mock.ANY, expected_cmd)

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing SSH driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_ssh')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    def test_console_validate(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ssh_virt_type'] = 'virsh'
            task.node.driver_info['ssh_terminal_port'] = 123
            task.driver.console.validate(task)

    def test_console_validate_missing_port(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ssh_virt_type'] = 'virsh'
            task.node.driver_info.pop('ssh_terminal_port', None)
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.console.validate, task)

    def test_console_validate_not_virsh(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info = db_utils.get_test_ssh_info(
                virt_type='vbox')
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'not supported for non-virsh types',
                                   task.driver.console.validate, task)

    def test_console_validate_invalid_port(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ssh_terminal_port'] = ''
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'is not a valid integer',
                                   task.driver.console.validate, task)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console(self, mock_exec,
                           get_hosts_name_mock, mock_get_conn):
        info = ssh._parse_driver_info(self.node)
        mock_exec.return_value = None
        get_hosts_name_mock.return_value = "NodeName"
        mock_get_conn.return_value = self.sshclient

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)

        mock_exec.assert_called_once_with(info['uuid'],
                                          info['terminal_port'],
                                          mock.ANY)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail(self, mock_exec,
                                get_hosts_name_mock, mock_get_conn):
        get_hosts_name_mock.return_value = "NodeName"
        mock_get_conn.return_value = self.sshclient
        mock_exec.side_effect = exception.ConsoleSubprocessFailed(
            error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console.start_console,
                              task)
        mock_exec.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(ssh, '_get_connection', autospec=True)
    @mock.patch.object(ssh, '_get_hosts_name_for_node', autospec=True)
    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail_nodir(self, mock_exec,
                                      get_hosts_name_mock, mock_get_conn):
        get_hosts_name_mock.return_value = "NodeName"
        mock_get_conn.return_value = self.sshclient
        mock_exec.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.start_console,
                              task)
        mock_exec.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_exec):
        mock_exec.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.stop_console(task)

        mock_exec.assert_called_once_with(self.node.uuid)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console_fail(self, mock_stop):
        mock_stop.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.stop_console,
                              task)

        mock_stop.assert_called_once_with(self.node.uuid)

    @mock.patch.object(console_utils, 'get_shellinabox_console_url',
                       autospec=True)
    def test_get_console(self, mock_exec):
        url = 'http://localhost:4201'
        mock_exec.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            task.node.driver_info['ssh_terminal_port'] = 6900
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_exec.assert_called_once_with(6900)
