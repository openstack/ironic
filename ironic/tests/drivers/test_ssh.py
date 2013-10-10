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

import mock
import paramiko

from ironic.openstack.common import jsonutils as json

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers.modules import ssh
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils

INFO_DICT = json.loads(db_utils.ssh_info)


class SSHValidateParametersTestCase(base.TestCase):

    def test__parse_driver_info_good(self):
        # make sure we get back the expected things
        node = db_utils.get_test_node(
                    driver='fake_ssh',
                    driver_info=INFO_DICT)
        info = ssh._parse_driver_info(node)
        self.assertIsNotNone(info.get('host'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('port'))
        self.assertIsNotNone(info.get('virt_type'))
        self.assertIsNotNone(info.get('cmd_set'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_missing_host(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['ssh_address']
        del info['ssh_key_filename']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_user(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['ssh_username']
        del info['ssh_key_filename']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_pass(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['ssh_password']
        del info['ssh_key_filename']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_virt_type(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['ssh_virt_type']
        del info['ssh_key_filename']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_driver_info,
                node)

    def test__parse_driver_info_missing_key(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['ssh_password']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.FileNotFound,
                ssh._parse_driver_info,
                node)

    def test__normalize_mac(self):
        mac_raw = "0A:1B-2C-3D:4F"
        mac_clean = ssh._normalize_mac(mac_raw)
        self.assertEqual(mac_clean, "0a1b2c3d4f")


class SSHPrivateMethodsTestCase(base.TestCase):

    def setUp(self):
        super(SSHPrivateMethodsTestCase, self).setUp()
        self.node = db_utils.get_test_node(
                        driver='fake_ssh',
                        driver_info=INFO_DICT)
        self.sshclient = paramiko.SSHClient()

        #setup the mock for _exec_ssh_command because most tests use it
        self.ssh_patcher = mock.patch.object(ssh, '_exec_ssh_command')
        self.exec_ssh_mock = self.ssh_patcher.start()

        def stop_patcher():
            if self.ssh_patcher:
                self.ssh_patcher.stop()

        self.addCleanup(stop_patcher)

    def test__get_power_status_on(self):
        info = ssh._parse_driver_info(self.node)
        with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                as get_hosts_name_mock:
            self.exec_ssh_mock.return_value = [
                    '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}']
            get_hosts_name_mock.return_value = "NodeName"

            pstate = ssh._get_power_status(self.sshclient, info)

            ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['list_running'])
            self.assertEqual(pstate, states.POWER_ON)
            self.exec_ssh_mock.assert_called_once_with(
                    self.sshclient, ssh_cmd)
            get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                        info)

    def test__get_power_status_off(self):
        info = ssh._parse_driver_info(self.node)
        with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                as get_hosts_name_mock:
            self.exec_ssh_mock.return_value = [
                    '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}']
            get_hosts_name_mock.return_value = "NotNodeName"

            pstate = ssh._get_power_status(self.sshclient, info)

            ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['list_running'])
            self.assertEqual(pstate, states.POWER_OFF)
            self.exec_ssh_mock.assert_called_once_with(self.sshclient,
                    ssh_cmd)
            get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                        info)

    def test__get_power_status_error(self):
        info = ssh._parse_driver_info(self.node)

        with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                as get_hosts_name_mock:
            self.exec_ssh_mock.return_value = [
                    '"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}']
            get_hosts_name_mock.return_value = None
            pstate = ssh._get_power_status(self.sshclient, info)

            ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['list_running'])

            self.assertEqual(pstate, states.ERROR)
            self.exec_ssh_mock.assert_called_once_with(
                    self.sshclient, ssh_cmd)
            get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                        info)

    def test__get_hosts_name_for_node_match(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        self.exec_ssh_mock.side_effect = [['NodeName'], ['52:54:00:cf:2d:31']]
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)]

        found_name = ssh._get_hosts_name_for_node(self.sshclient, info)

        self.assertEqual(found_name, 'NodeName')
        self.assertEqual(self.exec_ssh_mock.call_args_list, expected)

    def test__get_hosts_name_for_node_no_match(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "22:22:22:22:22:22"]
        self.exec_ssh_mock.side_effect = [['NodeName'], ['52:54:00:cf:2d:31']]

        ssh_cmd = "%s %s" % (info['cmd_set']['base_cmd'],
                             info['cmd_set']['list_all'])

        cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                 info['cmd_set']['get_node_macs'])

        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        expected = [mock.call(self.sshclient, ssh_cmd),
                    mock.call(self.sshclient, cmd_to_exec)]

        found_name = ssh._get_hosts_name_for_node(self.sshclient, info)

        self.assertEqual(found_name, None)
        self.assertEqual(self.exec_ssh_mock.call_args_list, expected)

    def test__power_on_good(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_status_mock:
            with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                    as get_hosts_name_mock:
                get_power_status_mock.side_effect = [states.POWER_OFF,
                                                     states.POWER_ON]
                get_hosts_name_mock.return_value = "NodeName"
                self.exec_ssh_mock.return_value = None
                expected = [mock.call(self.sshclient, info),
                            mock.call(self.sshclient, info)]

                cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                         info['cmd_set']['start_cmd'])
                cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
                current_state = ssh._power_on(self.sshclient, info)

                self.assertEqual(current_state, states.POWER_ON)
                self.assertEqual(get_power_status_mock.call_args_list,
                                 expected)
                get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                            info)
                self.exec_ssh_mock.assert_called_once_with(self.sshclient,
                                                           cmd_to_exec)

    def test__power_on_fail(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_status_mock:
            with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                    as get_hosts_name_mock:
                get_power_status_mock.side_effect = [states.POWER_OFF,
                                                     states.POWER_OFF]
                get_hosts_name_mock.return_value = "NodeName"
                self.exec_ssh_mock.return_value = None
                expected = [mock.call(self.sshclient, info),
                            mock.call(self.sshclient, info)]

                cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                         info['cmd_set']['start_cmd'])
                cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
                current_state = ssh._power_on(self.sshclient, info)

                self.assertEqual(current_state, states.ERROR)
                self.assertEqual(get_power_status_mock.call_args_list,
                                 expected)
                get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                            info)
                self.exec_ssh_mock.assert_called_once_with(self.sshclient,
                                                           cmd_to_exec)

    def test__power_off_good(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_status_mock:
            with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                    as get_hosts_name_mock:
                get_power_status_mock.side_effect = [states.POWER_ON,
                                                     states.POWER_OFF]
                get_hosts_name_mock.return_value = "NodeName"
                self.exec_ssh_mock.return_value = None
                expected = [mock.call(self.sshclient, info),
                            mock.call(self.sshclient, info)]

                cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                         info['cmd_set']['stop_cmd'])
                cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
                current_state = ssh._power_off(self.sshclient, info)

                self.assertEqual(current_state, states.POWER_OFF)
                self.assertEqual(get_power_status_mock.call_args_list,
                                 expected)
                get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                            info)
                self.exec_ssh_mock.assert_called_once_with(self.sshclient,
                                                           cmd_to_exec)

    def test__power_off_fail(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_status_mock:
            with mock.patch.object(ssh, '_get_hosts_name_for_node') \
                    as get_hosts_name_mock:
                get_power_status_mock.side_effect = [states.POWER_ON,
                                                     states.POWER_ON]
                get_hosts_name_mock.return_value = "NodeName"
                self.exec_ssh_mock.return_value = None
                expected = [mock.call(self.sshclient, info),
                            mock.call(self.sshclient, info)]

                cmd_to_exec = "%s %s" % (info['cmd_set']['base_cmd'],
                                         info['cmd_set']['stop_cmd'])
                cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
                current_state = ssh._power_off(self.sshclient, info)

                self.assertEqual(current_state, states.ERROR)
                self.assertEqual(get_power_status_mock.call_args_list,
                                 expected)
                get_hosts_name_mock.assert_called_once_with(self.sshclient,
                                                            info)
                self.exec_ssh_mock.assert_called_once_with(self.sshclient,
                                                           cmd_to_exec)

    def test_exec_ssh_command_good(self):
        #stop mocking the _exec_ssh_command because we are testing it here
        self.ssh_patcher.stop()
        self.ssh_patcher = None

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
            stdout, stderr = ssh._exec_ssh_command(self.sshclient, "command")

            self.assertEqual(stdout, 'hello')
            exec_command_mock.assert_called_once_with("command")

    def test_exec_ssh_command_fail(self):
        #stop mocking the _exec_ssh_command because we are testing it here
        self.ssh_patcher.stop()
        self.ssh_patcher = None

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
            self.assertRaises(exception.ProcessExecutionError,
                              ssh._exec_ssh_command,
                              self.sshclient,
                              "command")
            exec_command_mock.assert_called_once_with("command")


class SSHDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SSHDriverTestCase, self).setUp()
        self.driver = mgr_utils.get_mocked_node_manager(driver='fake_ssh')
        self.node = db_utils.get_test_node(
                        driver='fake_ssh',
                        driver_info=INFO_DICT)
        self.dbapi = dbapi.get_instance()
        self.dbapi.create_node(self.node)
        self.sshclient = paramiko.SSHClient()

        #setup these mocks because most tests use them
        self.parse_drv_info_patcher = mock.patch.object(ssh,
                                                        '_parse_driver_info')
        self.parse_drv_info_mock = None
        self.get_mac_addr_patcher = mock.patch.object(
                ssh,
                '_get_nodes_mac_addresses')
        self.get_mac_addr_mock = self.get_mac_addr_patcher.start()
        self.get_conn_patcher = mock.patch.object(ssh, '_get_connection')
        self.get_conn_mock = self.get_conn_patcher.start()

        def stop_patchers():
            if self.parse_drv_info_mock:
                self.parse_drv_info_patcher.stop()
            if self.get_mac_addr_mock:
                self.get_mac_addr_patcher.stop()
            if self.get_conn_mock:
                self.get_conn_patcher.stop()

        self.addCleanup(stop_patchers)

    def test__get_nodes_mac_addresses(self):
        #stop all the mocks because this test does not use them
        self.get_mac_addr_patcher.stop()
        self.get_mac_addr_mock = None
        self.get_conn_patcher.stop()
        self.get_conn_mock = None

        ports = []
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=6,
                    node_id=self.node['id'],
                    address='aa:bb:cc',
                    uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53')))
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=7,
                    node_id=self.node['id'],
                    address='dd:ee:ff',
                    uuid='4fc26c0b-03f2-4d2e-ae87-c02d7f33c234')))

        with task_manager.acquire([self.node['uuid']]) as task:
            node_macs = ssh._get_nodes_mac_addresses(task, self.node)
        self.assertEqual(node_macs, ['aa:bb:cc', 'dd:ee:ff'])

    def test_reboot_good(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_stat_mock:
            with mock.patch.object(ssh, '_power_off') as power_off_mock:
                with mock.patch.object(ssh, '_power_on') as power_on_mock:
                    get_power_stat_mock.return_value = states.POWER_ON
                    power_off_mock.return_value = None
                    power_on_mock.return_value = states.POWER_ON

                    with task_manager.acquire([info['uuid']], shared=False) \
                            as task:
                        task.resources[0].driver.power.reboot(task, self.node)

                    self.parse_drv_info_mock.assert_called_once_with(self.node)
                    self.get_mac_addr_mock.assert_called_once_with(mock.ANY,
                                                                   self.node)
                    self.get_conn_mock.assert_called_once_with(self.node)
                    get_power_stat_mock.assert_called_once_with(self.sshclient,
                                                                info)
                    power_off_mock.assert_called_once_with(self.sshclient,
                                                           info)
                    power_on_mock.assert_called_once_with(self.sshclient, info)

    def test_reboot_fail(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with mock.patch.object(ssh, '_get_power_status') \
                as get_power_stat_mock:
            with mock.patch.object(ssh, '_power_off') as power_off_mock:
                with mock.patch.object(ssh, '_power_on') as power_on_mock:
                    get_power_stat_mock.return_value = states.POWER_ON
                    power_off_mock.return_value = None
                    power_on_mock.return_value = states.POWER_OFF

                    with task_manager.acquire([info['uuid']], shared=False) \
                            as task:
                        self.assertRaises(
                                exception.PowerStateFailure,
                                task.resources[0].driver.power.reboot,
                                task,
                                self.node)
                    self.parse_drv_info_mock.assert_called_once_with(self.node)
                    self.get_mac_addr_mock.assert_called_once_with(mock.ANY,
                                                                   self.node)
                    self.get_conn_mock.assert_called_once_with(self.node)
                    get_power_stat_mock.assert_called_once_with(self.sshclient,
                                                                info)
                    power_off_mock.assert_called_once_with(self.sshclient,
                                                           info)
                    power_on_mock.assert_called_once_with(self.sshclient, info)

    def test_set_power_state_bad_state(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with task_manager.acquire([info['uuid']], shared=False) as task:
            self.assertRaises(
                    exception.IronicException,
                    task.resources[0].driver.power.set_power_state,
                    task,
                    self.node,
                    "BAD_PSTATE")

        self. parse_drv_info_mock.assert_called_once_with(self.node)
        self.get_mac_addr_mock.assert_called_once_with(mock.ANY, self.node)
        self.get_conn_mock.assert_called_once_with(self.node)

    def test_set_power_state_on_good(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient
        with mock.patch.object(ssh, '_power_on') as power_on_mock:
            power_on_mock.return_value = states.POWER_ON

            with task_manager.acquire([info['uuid']], shared=False) as task:
                task.resources[0].driver.power.set_power_state(task,
                                                               self.node,
                                                               states.POWER_ON)

            self.assert_(True)
            self.parse_drv_info_mock.assert_called_once_with(self.node)
            self.get_mac_addr_mock.assert_called_once_with(mock.ANY, self.node)
            self.get_conn_mock.assert_called_once_with(self.node)
            power_on_mock.assert_called_once_with(self.sshclient, info)

    def test_set_power_state_on_fail(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with mock.patch.object(ssh, '_power_on') as power_on_mock:
            power_on_mock.return_value = states.POWER_OFF

            with task_manager.acquire([info['uuid']], shared=False) as task:
                self.assertRaises(
                        exception.PowerStateFailure,
                        task.resources[0].driver.power.set_power_state,
                        task,
                        self.node,
                        states.POWER_ON)

            self.parse_drv_info_mock.assert_called_once_with(self.node)
            self.get_mac_addr_mock.assert_called_once_with(mock.ANY, self.node)
            self.get_conn_mock.assert_called_once_with(self.node)
            power_on_mock.assert_called_once_with(self.sshclient, info)

    def test_set_power_state_off_good(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with mock.patch.object(ssh, '_power_off') as power_off_mock:
            power_off_mock.return_value = states.POWER_OFF

            with task_manager.acquire([info['uuid']], shared=False) as task:
                task.resources[0].driver.power.set_power_state(task,
                        self.node, states.POWER_OFF)

            self.assert_(True)
            self.parse_drv_info_mock.assert_called_once_with(self.node)
            self.get_mac_addr_mock.assert_called_once_with(mock.ANY, self.node)
            self.get_conn_mock.assert_called_once_with(self.node)
            power_off_mock.assert_called_once_with(self.sshclient, info)

    def test_set_power_state_off_fail(self):
        info = ssh._parse_driver_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.parse_drv_info_mock = self.parse_drv_info_patcher.start()
        self.parse_drv_info_mock.return_value = info
        self.get_mac_addr_mock.return_value = info['macs']
        self.get_conn_mock.return_value = self.sshclient

        with mock.patch.object(ssh, '_power_off') as power_off_mock:
            power_off_mock.return_value = states.POWER_ON

            with task_manager.acquire([info['uuid']], shared=False) as task:
                self.assertRaises(
                        exception.PowerStateFailure,
                        task.resources[0].driver.power.set_power_state,
                        task,
                        self.node,
                        states.POWER_OFF)

            self.parse_drv_info_mock.assert_called_once_with(self.node)
            self.get_mac_addr_mock.assert_called_once_with(mock.ANY, self.node)
            self.get_conn_mock.assert_called_once_with(self.node)
            power_off_mock.assert_called_once_with(self.sshclient, info)
