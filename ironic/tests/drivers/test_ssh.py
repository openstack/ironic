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

import mox
import paramiko

from oslo.config import cfg

from ironic.openstack.common import jsonutils as json

from ironic.common import exception
from ironic.common import states
from ironic.db import api as dbapi
from ironic.drivers import ssh
from ironic.manager import task_manager
from ironic.tests import base
from ironic.tests.db import utils as db_utils
from ironic.tests.manager import utils as mgr_utils


CONF = cfg.CONF


class IronicSSHTestCase(base.TestCase):

    def setUp(self):
        super(IronicSSHTestCase, self).setUp()
        (self.controller, self.deployer) = mgr_utils.get_mocked_node_manager(
                                                control_driver="ssh")
        self.node = db_utils.get_test_node(**{'control_driver': 'ssh',
            'deploy_driver': 'fake'})
        self.dbapi = dbapi.get_instance()
        self.dbapi.create_node(self.node)
        self.ifports = [db_utils.get_test_port(id=6, address='aa:bb:cc'),
                        db_utils.get_test_port(id=7, address='dd:ee:ff')]
        self.dbapi.create_port(self.ifports[0])
        self.dbapi.create_port(self.ifports[1])
        self.ssh = ssh.SSHPowerDriver()
        self.test_control_info_dict = {
            "ssh_host": "1.2.3.4",
            "ssh_user": "admin",
            "ssh_pass": "fake",
            "ssh_port": 22,
            "virt_type": "vbox",
            "ssh_key": "/not/real/file"}

    def test__parse_control_info_good(self):
        # make sure we get back the expected things
        info = ssh._parse_control_info(self.node)
        self.assertIsNotNone(info.get('host'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('port'))
        self.assertIsNotNone(info.get('virt_type'))
        self.assertIsNotNone(info.get('cmd_set'))
        self.assertIsNotNone(info.get('uuid'))
        self.mox.VerifyAll()

    def test__parse_control_info_missing_host(self):
        # make sure error is raised when info is missing
        tmp_dict = self.test_control_info_dict
        del tmp_dict['ssh_host']
        del tmp_dict['ssh_key']
        _ssh_control_info = json.dumps(tmp_dict)
        node = db_utils.get_test_node(control_info=_ssh_control_info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_control_info,
                node)
        self.mox.VerifyAll()

    def test__parse_control_info_missing_user(self):
        # make sure error is raised when info is missing
        tmp_dict = self.test_control_info_dict
        del tmp_dict['ssh_user']
        del tmp_dict['ssh_key']
        _ssh_control_info = json.dumps(tmp_dict)
        node = db_utils.get_test_node(control_info=_ssh_control_info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_control_info,
                node)
        self.mox.VerifyAll()

    def test__parse_control_info_missing_pass(self):
        # make sure error is raised when info is missing
        tmp_dict = self.test_control_info_dict
        del tmp_dict['ssh_pass']
        del tmp_dict['ssh_key']
        _ssh_control_info = json.dumps(tmp_dict)
        node = db_utils.get_test_node(control_info=_ssh_control_info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_control_info,
                node)
        self.mox.VerifyAll()

    def test__parse_control_info_missing_virt_type(self):
        # make sure error is raised when info is missing
        tmp_dict = self.test_control_info_dict
        del tmp_dict['virt_type']
        del tmp_dict['ssh_key']
        _ssh_control_info = json.dumps(tmp_dict)
        node = db_utils.get_test_node(control_info=_ssh_control_info)
        self.assertRaises(exception.InvalidParameterValue,
                ssh._parse_control_info,
                node)
        self.mox.VerifyAll()

    def test__parse_control_info_missing_key(self):
        # make sure error is raised when info is missing
        tmp_dict = self.test_control_info_dict
        del tmp_dict['ssh_pass']
        _ssh_control_info = json.dumps(tmp_dict)
        node = db_utils.get_test_node(control_info=_ssh_control_info)
        self.assertRaises(exception.FileNotFound,
                ssh._parse_control_info,
                node)
        self.mox.VerifyAll()

    def test__normalize_mac(self):
        mac_raw = "0A:1B-2C-3D:4F"
        mac_clean = ssh._normalize_mac(mac_raw)
        self.assertEqual(mac_clean, "0a1b2c3d4f")
        self.mox.VerifyAll()

    def test__get_power_status_on(self):
        info = ssh._parse_control_info(self.node)
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')

        ssh._exec_ssh_command(
            ssh_obj, info['cmd_set']['list_running']).AndReturn(
            ['"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}'])
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NodeName")

        self.mox.ReplayAll()
        pstate = ssh._get_power_status(ssh_obj, info)
        self.assertEqual(pstate, states.POWER_ON)
        self.mox.VerifyAll()

    def test__get_power_status_off(self):
        info = ssh._parse_control_info(self.node)
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')

        ssh._exec_ssh_command(
            ssh_obj, info['cmd_set']['list_running']).AndReturn(
            ['"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}'])
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NotNodeName")

        self.mox.ReplayAll()
        pstate = ssh._get_power_status(ssh_obj, info)
        self.assertEqual(pstate, states.POWER_OFF)
        self.mox.VerifyAll()

    def test__get_power_status_error(self):
        info = ssh._parse_control_info(self.node)
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')

        ssh._exec_ssh_command(
            ssh_obj, info['cmd_set']['list_running']).AndReturn(
            ['"NodeName" {b43c4982-110c-4c29-9325-d5f41b053513}'])
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn(None)

        self.mox.ReplayAll()
        pstate = ssh._get_power_status(ssh_obj, info)
        self.assertEqual(pstate, states.ERROR)
        self.mox.VerifyAll()

    def test__get_hosts_name_for_node_match(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')
        ssh._exec_ssh_command(ssh_obj, info['cmd_set']['list_all']).AndReturn(
            ['NodeName'])
        cmd_to_exec = info['cmd_set']['get_node_macs']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(
            ['52:54:00:cf:2d:31'])
        self.mox.ReplayAll()
        found_name = ssh._get_hosts_name_for_node(ssh_obj, info)
        self.assertEqual(found_name, 'NodeName')
        self.mox.VerifyAll()

    def test__get_hosts_name_for_node_no_match(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "22:22:22:22:22:22"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')
        ssh._exec_ssh_command(ssh_obj, info['cmd_set']['list_all']).AndReturn(
            ['NodeName'])
        cmd_to_exec = info['cmd_set']['get_node_macs']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(
            ['52:54:00:cf:2d:31'])

        self.mox.ReplayAll()
        found_name = ssh._get_hosts_name_for_node(ssh_obj, info)
        self.assertEqual(found_name, None)
        self.mox.VerifyAll()

    def test__power_on_good(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')

        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_OFF)
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NodeName")
        cmd_to_exec = info['cmd_set']['start_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(None)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()
        current_state = ssh._power_on(ssh_obj, info)
        self.assertEqual(current_state, states.POWER_ON)
        self.mox.VerifyAll()

    def test__power_on_fail(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')

        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_OFF)
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NodeName")
        cmd_to_exec = info['cmd_set']['start_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(None)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()
        current_state = ssh._power_on(ssh_obj, info)
        self.assertEqual(current_state, states.ERROR)
        self.mox.VerifyAll()

    def test__power_off_good(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')

        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NodeName")
        cmd_to_exec = info['cmd_set']['stop_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(None)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()
        current_state = ssh._power_off(ssh_obj, info)
        self.assertEqual(current_state, states.POWER_OFF)
        self.mox.VerifyAll()

    def test__power_off_fail(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_get_hosts_name_for_node')
        self.mox.StubOutWithMock(ssh, '_exec_ssh_command')

        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        ssh._get_hosts_name_for_node(ssh_obj, info).AndReturn("NodeName")
        cmd_to_exec = info['cmd_set']['stop_cmd']
        cmd_to_exec = cmd_to_exec.replace('{_NodeName_}', 'NodeName')
        ssh._exec_ssh_command(ssh_obj, cmd_to_exec).AndReturn(None)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()
        current_state = ssh._power_off(ssh_obj, info)
        self.assertEqual(current_state, states.ERROR)
        self.mox.VerifyAll()

    def test_reboot_good(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_power_off')
        self.mox.StubOutWithMock(ssh, '_power_on')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        ssh._power_off(ssh_obj, info).AndReturn(None)
        ssh._power_on(ssh_obj, info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            task.resources[0].controller.reboot(task, self.node)
        self.mox.VerifyAll()

    def test_reboot_fail(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_get_power_status')
        self.mox.StubOutWithMock(ssh, '_power_off')
        self.mox.StubOutWithMock(ssh, '_power_on')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._get_power_status(ssh_obj, info).AndReturn(states.POWER_ON)
        ssh._power_off(ssh_obj, info).AndReturn(None)
        ssh._power_on(ssh_obj, info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                task.resources[0].controller.reboot,
                task,
                self.node)
        self.mox.VerifyAll()

    def test_exec_ssh_command_good(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh_obj, 'exec_command')

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

        ssh_obj.exec_command("command").AndReturn(
                (Stream(), Stream('hello'), Stream()))
        self.mox.ReplayAll()
        stdout, stderr = ssh._exec_ssh_command(ssh_obj, "command")
        self.assertEqual(stdout, 'hello')
        self.mox.VerifyAll()

    def test_exec_ssh_command_fail(self):
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]
        ssh_obj = paramiko.SSHClient()
        self.mox.StubOutWithMock(ssh_obj, 'exec_command')

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

        ssh_obj.exec_command("command").AndReturn(
                (Stream(), Stream('hello'), Stream()))
        self.mox.ReplayAll()
        self.assertRaises(exception.ProcessExecutionError,
                ssh._exec_ssh_command,
                ssh_obj,
                "command")
        self.mox.VerifyAll()

    def test_start_console(self):
        self.assertRaises(exception.IronicException,
            self.ssh.start_console,
            None,
            self.node)
        self.mox.VerifyAll()

    def test_stop_console(self):
        self.assertRaises(exception.IronicException,
            self.ssh.start_console,
            None,
            self.node)
        self.mox.VerifyAll()

    def test_set_power_state_bad_state(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            self.assertRaises(exception.IronicException,
                task.resources[0].controller.set_power_state,
                task,
                self.node,
                "BAD_PSTATE")
        self.mox.VerifyAll()

    def test_set_power_state_on_good(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_power_on')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._power_on(ssh_obj, info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            task.resources[0].controller.set_power_state(
                task,
                self.node,
                states.POWER_ON)
        self.assert_(True)
        self.mox.VerifyAll()

    def test_set_power_state_on_fail(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_power_on')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._power_on(ssh_obj, info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                task.resources[0].controller.set_power_state,
                task,
                self.node,
                states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_state_off_good(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_power_off')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._power_off(ssh_obj, info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            task.resources[0].controller.set_power_state(
                task,
                self.node,
                states.POWER_OFF)
        self.assert_(True)
        self.mox.VerifyAll()

    def test_set_power_state_off_fail(self):
        ssh_obj = paramiko.SSHClient()
        info = ssh._parse_control_info(self.node)
        info['macs'] = ["11:11:11:11:11:11", "52:54:00:cf:2d:31"]

        self.mox.StubOutWithMock(ssh, '_parse_control_info')
        self.mox.StubOutWithMock(ssh, '_get_nodes_mac_addresses')
        self.mox.StubOutWithMock(ssh, '_get_connection')
        self.mox.StubOutWithMock(ssh, '_power_off')
        ssh._parse_control_info(self.node).AndReturn(info)
        ssh._get_nodes_mac_addresses(mox.IgnoreArg(), self.node).AndReturn(
            info['macs'])
        ssh._get_connection(self.node).AndReturn(ssh_obj)
        ssh._power_off(ssh_obj, info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']], shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                task.resources[0].controller.set_power_state,
                task,
                self.node,
                states.POWER_OFF)
        self.mox.VerifyAll()

    def test__get_nodes_mac_addresses(self):
        info = ssh._parse_control_info(self.node)

        self.mox.StubOutWithMock(self.dbapi, 'get_ports_by_node')
        self.dbapi.get_ports_by_node(self.node.get('uuid')).\
            AndReturn(self.ifports)
        self.dbapi.get_ports_by_node(self.node.get('id')).\
            AndReturn(self.ifports)
        self.mox.ReplayAll()

        with task_manager.acquire([info['uuid']]) as task:
            node_macs = ssh._get_nodes_mac_addresses(task, self.node)
        self.assertEqual(node_macs, ['aa:bb:cc', 'dd:ee:ff'])
        self.mox.VerifyAll()
