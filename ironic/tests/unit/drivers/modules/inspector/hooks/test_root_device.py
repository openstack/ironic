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

from oslo_utils import units

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import root_device as \
    root_device_hook
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class RootDeviceTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {'disks': [
            {'name': '/dev/sda', 'model': 'Model 1', 'size': 1000 * units.Gi,
             'serial': '1111'},
            {'name': '/dev/sdb', 'model': 'Model 2', 'size': 10 * units.Gi,
             'serial': '2222'},
            {'name': '/dev/sdc', 'model': 'Model 1', 'size': 20 * units.Gi,
             'serial': '3333'},
            {'name': '/dev/sdd', 'model': 'Model 3', 'size': 0,
             'serial': '4444'}]}
        self.plugin_data = {}

    def test_no_hints(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            self.assertNotIn('root_disk', self.plugin_data)
            self.assertEqual(self.plugin_data['local_gb'], 0)
            self.assertEqual(task.node.properties.get('local_gb'), '0')

    def test_root_device_skip_list(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'serial': '1111'}
            task.node.properties['skip_block_devices'] = [{'size': 1000}]

            self.assertRaisesRegex(exception.HardwareInspectionFailure,
                                   'No disks satisfied root device hints for '
                                   'node %s' % self.node.id,
                                   root_device_hook.RootDeviceHook().__call__,
                                   task, self.inventory, self.plugin_data)
            self.assertNotIn('root_disk', self.plugin_data)
            self.assertNotIn('local_gb', self.plugin_data)
            # The default value of the `local_gb` property is left unchanged
            self.assertEqual(task.node.properties.get('local_gb'), '10')

    def test_first_match_on_skip_list_use_second(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'model': 'Model 1'}
            task.node.properties['skip_block_devices'] = [{'size': 1000}]
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()

            expected_root_device = self.inventory['disks'][2].copy()
            self.assertEqual(self.plugin_data['root_disk'],
                             expected_root_device)

            expected_local_gb = (expected_root_device['size'] // units.Gi) - 1
            self.assertEqual(self.plugin_data['local_gb'],
                             expected_local_gb)
            self.assertEqual(task.node.properties.get('local_gb'),
                             str(expected_local_gb))

    def test_one_matches(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'serial': '1111'}

            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()

            self.assertEqual(self.plugin_data['root_disk'],
                             self.inventory['disks'][0])
            self.assertEqual(self.plugin_data['local_gb'], 999)
            self.assertEqual(task.node.properties.get('local_gb'), '999')

    def test_local_gb_without_spacing(self):
        CONF.set_override('disk_partitioning_spacing', False, 'inspector')
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'serial': '1111'}
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()

            self.assertEqual(self.plugin_data['root_disk'],
                             self.inventory['disks'][0])
            self.assertEqual(self.plugin_data['local_gb'], 1000)
            self.assertEqual(task.node.properties.get('local_gb'), '1000')

    def test_zero_size(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'name': '/dev/sdd'}
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()
            self.assertEqual(self.plugin_data['root_disk'],
                             self.inventory['disks'][3])
            self.assertEqual(self.plugin_data['local_gb'], 0)
            self.assertEqual(task.node.properties.get('local_gb'), '0')

    def test_all_match(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'size': 20,
                                                   'model': 'Model 1'}
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()
            self.assertEqual(self.plugin_data['root_disk'],
                             self.inventory['disks'][2])
            self.assertEqual(self.plugin_data['local_gb'], 19)
            self.assertEqual(task.node.properties.get('local_gb'), '19')

    def test_incorrect_hint(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'size': 20,
                                                   'model': 'Model 42'}
            self.assertRaisesRegex(exception.HardwareInspectionFailure,
                                   'No disks satisfied root device hints for '
                                   'node %s' % task.node.uuid,
                                   root_device_hook.RootDeviceHook().__call__,
                                   task, self.inventory, self.plugin_data)
            self.assertNotIn('root_disk', self.plugin_data)
            self.assertNotIn('local_gb', self.plugin_data)
            # The default value of the `local_gb` property is unchanged
            self.assertEqual(task.node.properties.get('local_gb'), '10')

    def test_size_string(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.properties['root_device'] = {'size': '20'}
            root_device_hook.RootDeviceHook().__call__(task,
                                                       self.inventory,
                                                       self.plugin_data)
            task.node.refresh()
            self.assertEqual(self.plugin_data['root_disk'],
                             self.inventory['disks'][2])
            self.assertEqual(self.plugin_data['local_gb'], 19)
            self.assertEqual(task.node.properties.get('local_gb'), '19')

    def test_size_invalid(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            for bad_size in ('foo', None, {}):
                task.node.properties['root_device'] = {'size': bad_size}
                self.assertRaisesRegex(
                    exception.HardwareInspectionFailure,
                    'No disks could be found using root device hints',
                    root_device_hook.RootDeviceHook().__call__,
                    task, self.inventory, self.plugin_data)

                self.assertNotIn('root_disk', self.plugin_data)
                self.assertNotIn('local_gb', self.plugin_data)
                # The default value of the `local_gb` property is left
                # unchanged
                self.assertEqual(task.node.properties.get('local_gb'), '10')
