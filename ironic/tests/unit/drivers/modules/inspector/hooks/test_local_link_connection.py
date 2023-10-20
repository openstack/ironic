# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy
from unittest import mock

from oslo_utils import uuidutils

from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import local_link_connection as \
    hook
from ironic.objects import port
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_INVENTORY = {
    'interfaces': [{
        'name': 'em1',
        'mac_address': '11:11:11:11:11:11',
        'ipv4_address': '1.1.1.1',
        'lldp': [(0, ''),
                 (1, '04885a92ec5459'),
                 (2, '0545746865726e6574312f3138'),
                 (3, '0078')]
    }]
}


class LocalLinkConnectionTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = copy.deepcopy(_INVENTORY)
        self.plugin_data = {'all_interfaces': {'em1': {}}}
        self.port = obj_utils.create_test_port(
            self.context, uuid=uuidutils.generate_uuid(), node_id=self.node.id,
            address='11:11:11:11:11:11', local_link_connection={})

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_valid_data(self, mock_get_port, mock_port_save):
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertTrue(mock_port_save.called)
            self.assertEqual({'switch_id': '88:5a:92:ec:54:59',
                              'port_id': 'Ethernet1/18'},
                             self.port.local_link_connection)

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_lldp_none(self, mock_get_port, mock_port_save):
        self.inventory['interfaces'][0]['lldp'] = None
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertFalse(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection, {})

    @mock.patch.object(port.Port, 'save', autospec=True)
    def test_interface_not_in_all_interfaces(self, mock_port_save):
        self.plugin_data['all_interfaces'] = {}
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertFalse(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection, {})

    @mock.patch.object(hook.LOG, 'debug', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    @mock.patch.object(port.Port, 'save', autospec=True)
    def test_no_port_in_ironic(self, mock_port_save, mock_get_port, mock_log):
        mock_get_port.return_value = None
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertFalse(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection, {})
            mock_log.assert_called_once_with(
                'Skipping LLDP processing for interface %s of node %s: '
                'matching port not found in Ironic.',
                self.inventory['interfaces'][0]['mac_address'],
                task.node.uuid)

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_port_local_link_connection_already_exists(self,
                                                       mock_get_port,
                                                       mock_port_save):
        self.port['local_link_connection'] = {'switch_id': '11:11:11:11:11:11',
                                              'port_id': 'Ether'}
        mock_get_port.return_value = self.port

        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertTrue(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection,
                             {'switch_id': '11:11:11:11:11:11',
                              'port_id': 'Ether'})

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(hook.LOG, 'warning', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_invalid_tlv_value_hex_format(self, mock_get_port, mock_log,
                                          mock_port_save):
        self.inventory['interfaces'][0]['lldp'] = [(2, 'weee')]
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            mock_log.assert_called_once_with(
                'TLV value for TLV type %d is not in correct format. Ensure '
                'that the TLV value is in hexidecimal format when sent to '
                'ironic. Node: %s', 2, task.node.uuid)
            self.assertFalse(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection, {})

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_invalid_port_id_subtype(self, mock_get_port, mock_port_save):
        # First byte of TLV value is processed to calculate the subtype for
        # the port ID, Subtype 6 ('06...') isn't a subtype supported by this
        # hook, so we expect it to skip this TLV.
        self.inventory['interfaces'][0]['lldp'][2] = (
            2, '0645746865726e6574312f3138')
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertTrue(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection,
                             {'switch_id': '88:5a:92:ec:54:59'})

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_port_id_subtype_mac(self, mock_get_port, mock_port_save):
        self.inventory['interfaces'][0]['lldp'][2] = (
            2, '03885a92ec5458')
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertTrue(mock_port_save.called)
            self.assertEqual(self.port.local_link_connection,
                             {'port_id': '88:5a:92:ec:54:58',
                              'switch_id': '88:5a:92:ec:54:59'})

    @mock.patch.object(port.Port, 'save', autospec=True)
    @mock.patch.object(port.Port, 'get_by_address', autospec=True)
    def test_invalid_chassis_id_subtype(self, mock_get_port, mock_port_save):
        # First byte of TLV value is processed to calculate the subtype for
        # the chassis ID, Subtype 5 ('05...') isn't a subtype supported by
        # this hook, so we expect it to skip this TLV.
        self.inventory['interfaces'][0]['lldp'][1] = (1, '05885a92ec5459')
        mock_get_port.return_value = self.port
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.LocalLinkConnectionHook().__call__(task, self.inventory,
                                                    self.plugin_data)
            self.assertTrue(mock_port_save.called)
            self.assertEqual({'port_id': 'Ethernet1/18'},
                             self.port.local_link_connection)
