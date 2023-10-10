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


from unittest import mock

from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import physical_network as \
    physical_network_hook
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_INTERFACE_1 = {
    'name': 'em0',
    'mac_address': '11:11:11:11:11:11',
    'ipv4_address': '192.168.10.1',
    'ipv6_address': '2001:db8::1'
}

_INTERFACE_2 = {
    'name': 'em1',
    'mac_address': '22:22:22:22:22:22',
    'ipv4_address': '192.168.12.2',
    'ipv6_address': 'fe80:5054::',
}

_INTERFACE_3 = {
    'name': 'em2',
    'mac_address': '33:33:33:33:33:33',
    'ipv4_address': '192.168.12.3',
    'ipv6_address': 'fe80::5054:ff:fea7:87:6482',
}

_INVENTORY = {
    'interfaces': [_INTERFACE_1, _INTERFACE_2, _INTERFACE_3]
}

_PLUGIN_DATA = {
    'all_interfaces': {'em0': _INTERFACE_1, 'em1': _INTERFACE_2}
}


class PhysicalNetworkTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        CONF.set_override('physical_network_cidr_map',
                          '192.168.10.0/24:network-a,fe80::/16:network-b',
                          'inspector')
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = _INVENTORY
        self.plugin_data = _PLUGIN_DATA

    @mock.patch.object(objects.Port, 'list_by_node_id', autospec=True)
    def test_physical_network(self, mock_list_by_nodeid):
        with task_manager.acquire(self.context, self.node.id) as task:
            port1 = obj_utils.create_test_port(self.context,
                                               address='11:11:11:11:11:11',
                                               node_id=self.node.id)
            port2 = obj_utils.create_test_port(
                self.context, id=988,
                uuid='2be26c0b-03f2-4d2e-ae87-c02d7f33c781',
                address='22:22:22:22:22:22', node_id=self.node.id)
            ports = [port1, port2]

            mock_list_by_nodeid.return_value = ports
            physical_network_hook.PhysicalNetworkHook().__call__(
                task, self.inventory, self.plugin_data)
            port1.refresh()
            port2.refresh()
            self.assertEqual(port1.physical_network, 'network-a')
            self.assertEqual(port2.physical_network, 'network-b')
