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
from ironic.drivers.modules.inspector.hooks import extra_hardware as hook
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


_PLUGIN_DATA = {
    'data': [
        ['disk', 'logical', 'count', '1'],
        ['disk', 'vda', 'size', '11'],
        ['disk', 'vda', 'vendor', '0x1af4'],
        ['disk', 'vda', 'physical_block_size', '512'],
        ['disk', 'vda', 'rotational', '1'],
        ['system', 'product', 'name', 'RHEL'],
        ['system', 'product', 'vendor', 'Red Hat'],
        ['system', 'product', 'version', 'RHEL-9.2.0 PC'],
        ['system', 'product', 'uuid', 'afdd3896-de8d-4585-8214-627071e13552'],
        ['system', 'motherboard', 'name', 'RHEL'],
        ['system', 'motherboard', 'vendor', 'Red Hat'],
        ['system', 'motherboard', 'version', 'RHEL-9.2.0 PC']
    ]
}

_EXPECTED_PLUGIN_DATA = {
    'extra': {
        'disk': {
            'logical': {
                'count': 1
            },
            'vda': {
                'size': 11,
                'vendor': '0x1af4',
                'physical_block_size': 512,
                'rotational': 1,
            }
        },
        'system': {
            'product': {
                'name': 'RHEL',
                'vendor': 'Red Hat',
                'version': 'RHEL-9.2.0 PC',
                'uuid': 'afdd3896-de8d-4585-8214-627071e13552'
            },
            'motherboard': {
                'name': 'RHEL',
                'vendor': 'Red Hat',
                'version': 'RHEL-9.2.0 PC'
            }
        }
    }
}


@mock.patch.object(hook.LOG, 'warning', autospec=True)
class ExtraHardwareTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {'inventory': 'fake-inventory'}
        self.plugin_data = _PLUGIN_DATA

    def test_valid_extra_hardware(self, mock_warn):
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ExtraHardwareHook().__call__(task, self.inventory,
                                              self.plugin_data)
            self.assertFalse(mock_warn.called)
            self.assertEqual(self.plugin_data, _EXPECTED_PLUGIN_DATA)

    def test_no_data_received(self, mock_warn):
        self.plugin_data = {'cats': 'meow'}
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ExtraHardwareHook().__call__(task, self.inventory,
                                              self.plugin_data)
            mock_warn.assert_called_once_with(
                'No extra hardware information was received from the ramdisk '
                'for node %s', task.node.uuid)
            self.assertEqual(self.plugin_data, {'cats': 'meow'})

    @mock.patch.object(hook.LOG, 'debug', autospec=True)
    def test_extra_hardware_with_errors(self, mock_debug, mock_warn):
        self.plugin_data = {'data':
                            [['memory', 'total', 'size', '4294967296'],
                             [],
                             ['cpu', 'physical', 'number', '1'],
                             ['cpu', 'physical', 'WUT'],
                             ['cpu', 'logical', 'number', '1']]
                            }
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ExtraHardwareHook().__call__(task, self.inventory,
                                              self.plugin_data)
            expected = {'extra': {
                'memory': {
                    'total': {
                        'size': 4294967296
                    }
                },
                'cpu': {
                    'physical': {
                        'number': 1
                    },
                    'logical': {
                        'number': 1
                    },
                }
            }}

            self.assertEqual(expected, self.plugin_data)
            # An empty list is not a warning, a bad record is.
            self.assertEqual(1, mock_warn.call_count)
            mock_debug.assert_called_once_with(
                'Deleting \"data\" key from plugin data of node %s as it is '
                'assumed unusable by inspection rules.', task.node.uuid)

    def test_invalid_data_strict_mode_off(self, mock_warn):
        invalid_plugin_data = {
            'data': [['memory', 'total', 'size', '4294967296'],
                     ['cpu', 'physical', 'number', '1'],
                     {'interface': 'eth1'}]}
        self.plugin_data = invalid_plugin_data
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ExtraHardwareHook().__call__(task, self.inventory,
                                              self.plugin_data)

            self.assertEqual(invalid_plugin_data, self.plugin_data)
            mock_warn.assert_called_once_with(
                'Extra hardware data was not in a recognised format, and will '
                'not be forwarded to inspection rules for node %s',
                task.node.uuid)

    @mock.patch.object(hook.LOG, 'debug', autospec=True)
    def test_invalid_data_strict_mode_on(self, mock_debug, mock_warn):
        CONF.set_override('extra_hardware_strict', True, group='inspector')
        self.plugin_data = {
            'data': [['memory', 'total', 'size', '4294967296'],
                     ['cpu', 'physical', 'WUT']]
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ExtraHardwareHook().__call__(task, self.inventory,
                                              self.plugin_data)
            self.assertEqual({}, self.plugin_data)
            mock_warn.assert_called_once_with(
                'Extra hardware data was not in a recognised format, and will '
                'not be forwarded to inspection rules for node %s',
                task.node.uuid)
            mock_debug.assert_called_once_with(
                'Deleting \"data\" key from plugin data of node %s as it is '
                'malformed and strict mode is on.', task.node.uuid)
