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

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import raid_device \
    as raid_device_hook
from ironic.objects.node_inventory import NodeInventory
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class RaidDeviceTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory_1 = {'disks': [{'name': '/dev/sda', 'serial': '1111'},
                                      {'name': '/dev/sdb', 'serial': '2222'}]}
        self.inventory_2 = {'disks': [{'name': '/dev/sdb', 'serial': '2222'},
                                      {'name': '/dev/sdc', 'serial': '3333'}]}
        self.plugin_data = {'plugin_data': 'fake-plugin-data'}

    def test_root_device_already_set(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.node.properties = {'root_device': 'any'}
            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_1,
                                                       self.plugin_data)
            self.assertEqual(self.node.properties.get('root_device'), 'any')

    def test_no_serials(self):
        self.inventory_1['disks'][0]['serial'] = None
        with task_manager.acquire(self.context, self.node.id) as task:
            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_1,
                                                       self.plugin_data)
            self.node.refresh()
            self.assertIsNone(self.node.properties.get('root_device'))

    @mock.patch.object(NodeInventory, 'get_by_node_id', autospec=True)
    def test_no_previous_inventory(self, mock_get_by_node_id):
        with task_manager.acquire(self.context, self.node.id) as task:
            mock_get_by_node_id.side_effect = exception.NodeInventoryNotFound()
            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_1,
                                                       self.plugin_data)
            self.node.refresh()
            self.assertIsNone(self.node.properties.get('root_device'))

    @mock.patch.object(NodeInventory, 'get_by_node_id', autospec=True)
    def test_no_new_root_devices(self, mock_get_by_node_id):
        with task_manager.acquire(self.context, self.node.id) as task:

            mock_get_by_node_id.return_value = NodeInventory(
                task.context, id=1, node_id=self.node.id,
                inventory_data=self.inventory_1, plugin_data=self.plugin_data)

            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_1,
                                                       self.plugin_data)
            self.node.refresh()
            result = self.node.properties.get('root_device')
            self.assertIsNone(result)

    @mock.patch.object(NodeInventory, 'get_by_node_id', autospec=True)
    def test_root_device_found(self, mock_get_by_node_id):
        with task_manager.acquire(self.context, self.node.id) as task:
            mock_get_by_node_id.return_value = NodeInventory(
                task.context, id=1, node_id=self.node.id,
                inventory_data=self.inventory_1, plugin_data=self.plugin_data)
            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_2,
                                                       self.plugin_data)
            self.node.refresh()
            result = self.node.properties.get('root_device')
            self.assertEqual(result, {'serial': '3333'})

    @mock.patch.object(NodeInventory, 'get_by_node_id', autospec=True)
    def test_multiple_new_root_devices(self, mock_get_by_node_id):
        with task_manager.acquire(self.context, self.node.id) as task:
            mock_get_by_node_id.return_value = NodeInventory(
                task.context, id=1, node_id=self.node.id,
                inventory_data=self.inventory_1, plugin_data=self.plugin_data)
            self.inventory_2['disks'].append({'name': '/dev/sdd',
                                              'serial': '4444'})
            raid_device_hook.RaidDeviceHook().__call__(task,
                                                       self.inventory_2,
                                                       self.plugin_data)
            self.node.refresh()
            result = self.node.properties.get('root_device')
            self.assertIsNone(result)
