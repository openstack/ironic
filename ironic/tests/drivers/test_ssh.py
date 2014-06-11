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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers.modules import ssh
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import context
from ironic.openstack.common import processutils
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

from oslo.config import cfg

CONF = cfg.CONF


class SSHValidateParametersTestCase(base.TestCase):
    def setUp(self):
        super(SSHValidateParametersTestCase, self).setUp()
        self.context = context.get_admin_context()

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
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_user(self):
        # make sure error is raised when info is missing
        info = db_utils.get_test_ssh_info()
        del info['ssh_username']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_creds(self):
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
        self.assertRaises(exception.InvalidParameterValue,
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
        expected_base_cmd = "/usr/bin/virsh --connect qemu:///foo"

        node = obj_utils.get_test_node(
                    self.context,
                    driver='fake_ssh',
                    driver_info=db_utils.get_test_ssh_info())
        node['driver_info']['ssh_virt_type'] = 'virsh'
        info = ssh._parse_driver_info(node)
        self.assertEqual(expected_base_cmd, info['cmd_set']['base_cmd'])


class SSHPrivateMethodsTestCase(base.TestCase):

    def setUp(self):
        super(SSHPrivateMethodsTestCase, self).setUp()
        self.context = context.get_admin_context()
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

        with mock.patch.object(self.sshclient, 'exec_command') \
                as exec_command_mock:
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

        with mock.patch.object(self.sshclient, 'exec_command') \
                as exec_command_mock:
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
        self.dbapi = dbapi.get_instance()
        self.port = self.dbapi.create_port(db_utils.get_test_port(
                                                         node_id=self.node.id))
        self.sshclient = paramiko.SSHClient()

    @mock.patch.object(utils, 'ssh_connect')
    def test__validate_info_ssh_connect_failed(self, ssh_connect_mock):
        info = ssh._parse_driver_info(self.node)

        ssh_connect_mock.side_effect = exception.SSHConnectFailed(host='fake')
        with task_manager.acquire(self.context, info['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task, self.node)
            driver_info = ssh._parse_driver_info(self.node)
            ssh_connect_mock.assert_called_once_with(driver_info)

    def test_validate_fail_no_port(self):
        new_node = obj_utils.create_test_node(
                self.context,
                id=321,
                uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                driver='fake_ssh',
                driver_info=db_utils.get_test_ssh_info())
        with task_manager.acquire(self.context, new_node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task, new_node)

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
