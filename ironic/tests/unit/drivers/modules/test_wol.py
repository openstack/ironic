# Copyright 2015 Red Hat, Inc.
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

"""Test class for Wake-On-Lan driver module."""

import socket
import time

import mock
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import wol
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch.object(time, 'sleep', lambda *_: None)
class WakeOnLanPrivateMethodTestCase(db_base.DbTestCase):

    def setUp(self):
        super(WakeOnLanPrivateMethodTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_wol')
        self.driver = driver_factory.get_driver('fake_wol')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_wol')
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

    def test__parse_parameters(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            params = wol._parse_parameters(task)
            self.assertEqual('255.255.255.255', params['host'])
            self.assertEqual(9, params['port'])

    def test__parse_parameters_non_default_params(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info = {'wol_host': '1.2.3.4',
                                     'wol_port': 7}
            params = wol._parse_parameters(task)
            self.assertEqual('1.2.3.4', params['host'])
            self.assertEqual(7, params['port'])

    def test__parse_parameters_no_ports_fail(self):
        node = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake_wol')
        with task_manager.acquire(
                self.context, node.uuid, shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              wol._parse_parameters, task)

    @mock.patch.object(socket, 'socket', autospec=True, spec_set=True)
    def test_send_magic_packets(self, mock_socket):
        fake_socket = mock.Mock(spec=socket, spec_set=True)
        mock_socket.return_value = fake_socket()
        obj_utils.create_test_port(self.context,
                                   uuid=uuidutils.generate_uuid(),
                                   address='aa:bb:cc:dd:ee:ff',
                                   node_id=self.node.id)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            wol._send_magic_packets(task, '255.255.255.255', 9)

            expected_calls = [
                mock.call(),
                mock.call().setsockopt(socket.SOL_SOCKET,
                                       socket.SO_BROADCAST, 1),
                mock.call().sendto(mock.ANY, ('255.255.255.255', 9)),
                mock.call().sendto(mock.ANY, ('255.255.255.255', 9)),
                mock.call().close()]

            fake_socket.assert_has_calls(expected_calls)
            self.assertEqual(1, mock_socket.call_count)

    @mock.patch.object(socket, 'socket', autospec=True, spec_set=True)
    def test_send_magic_packets_network_sendto_error(self, mock_socket):
        fake_socket = mock.Mock(spec=socket, spec_set=True)
        fake_socket.return_value.sendto.side_effect = socket.error('boom')
        mock_socket.return_value = fake_socket()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            self.assertRaises(exception.WolOperationError,
                              wol._send_magic_packets,
                              task, '255.255.255.255', 9)
            self.assertEqual(1, mock_socket.call_count)
            # assert sendt0() was invoked
            fake_socket.return_value.sendto.assert_called_once_with(
                mock.ANY, ('255.255.255.255', 9))

    @mock.patch.object(socket, 'socket', autospec=True, spec_set=True)
    def test_magic_packet_format(self, mock_socket):
        fake_socket = mock.Mock(spec=socket, spec_set=True)
        mock_socket.return_value = fake_socket()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            wol._send_magic_packets(task, '255.255.255.255', 9)

            expct_packet = (b'\xff\xff\xff\xff\xff\xffRT\x00\xcf-1RT\x00'
                            b'\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT'
                            b'\x00\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT\x00'
                            b'\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT'
                            b'\x00\xcf-1RT\x00\xcf-1RT\x00\xcf-1RT\x00\xcf-1')
            mock_socket.return_value.sendto.assert_called_once_with(
                expct_packet, ('255.255.255.255', 9))


@mock.patch.object(time, 'sleep', lambda *_: None)
class WakeOnLanDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(WakeOnLanDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_wol')
        self.driver = driver_factory.get_driver('fake_wol')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_wol')
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

    def test_get_properties(self):
        expected = wol.COMMON_PROPERTIES
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    def test_get_power_state(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.power_state = states.POWER_ON
            pstate = task.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, pstate)

    def test_get_power_state_nostate(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.power_state = states.NOSTATE
            pstate = task.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(wol, '_send_magic_packets', autospec=True,
                       spec_set=True)
    def test_set_power_state_power_on(self, mock_magic):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
            mock_magic.assert_called_once_with(task, '255.255.255.255', 9)

    @mock.patch.object(wol.LOG, 'info', autospec=True, spec_set=True)
    @mock.patch.object(wol, '_send_magic_packets', autospec=True,
                       spec_set=True)
    def test_set_power_state_power_off(self, mock_magic, mock_log):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)
            mock_log.assert_called_once_with(mock.ANY, self.node.uuid)
            # assert magic packets weren't sent
            self.assertFalse(mock_magic.called)

    @mock.patch.object(wol, '_send_magic_packets', autospec=True,
                       spec_set=True)
    def test_set_power_state_power_fail(self, mock_magic):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.set_power_state,
                              task, 'wrong-state')
            # assert magic packets weren't sent
            self.assertFalse(mock_magic.called)

    @mock.patch.object(wol.LOG, 'info', autospec=True, spec_set=True)
    @mock.patch.object(wol.WakeOnLanPower, 'set_power_state', autospec=True,
                       spec_set=True)
    def test_reboot(self, mock_power, mock_log):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.reboot(task)
            mock_log.assert_called_once_with(mock.ANY, self.node.uuid)
            mock_power.assert_called_once_with(task.driver.power, task,
                                               states.POWER_ON)
