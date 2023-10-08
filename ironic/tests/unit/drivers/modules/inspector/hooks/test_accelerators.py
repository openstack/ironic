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

from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import accelerators as \
    accelerators_hook
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

_PLUGIN_DATA = {
    'pci_devices': [
        {
            'vendor_id': '8086',
            'product_id': '2922',
            'class': '010601',
            'revision': '02',
            'bus': '0000:00:1f.2'
        },
        {
            'vendor_id': '0de',
            'product_id': '1eb8',
            'class': '060400',
            'revision': '00',
            'bus': '0000:00:01.2'
        }
    ]
}

_KNOWN_DEVICES = {
    'pci_devices': [
        {
            'vendor_id': '0de',
            'device_id': '1eb8',
            'type': 'GPU',
            'device_info': 'NVIDIA Corporation Tesla T4'
        },
        {
            'vendor_id': '10de',
            'device_id': '1df6',
            'type': 'GPU',
            'device_info': 'NVIDIA Corporation GV100GL'
        }
    ]
}


class AcceleratorsTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {'inventory': 'test_inventory'}
        self.plugin_data = _PLUGIN_DATA
        self.accelerators_hook = accelerators_hook.AcceleratorsHook()
        self.accelerators_hook._known_devices = _KNOWN_DEVICES

    def test_accelerators(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.accelerators_hook.__call__(task, self.inventory,
                                            self.plugin_data)
            self.node.refresh()
            result = self.node.properties.get('accelerators', [])
            expected = [{'vendor_id': '0de',
                         'device_id': '1eb8',
                         'type': 'GPU',
                         'device_info': 'NVIDIA Corporation Tesla T4',
                         'pci_address': '0000:00:01.2'}]
            self.assertEqual(result, expected)
