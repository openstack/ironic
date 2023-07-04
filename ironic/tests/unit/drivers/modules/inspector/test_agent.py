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

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.inspector import agent as inspector
from ironic.drivers.modules.inspector import interface as common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch.object(inspect_utils, 'create_ports_if_not_exist', autospec=True)
class InspectHardwareTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.iface = inspector.AgentInspect()
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = mock.Mock(
            spec=['boot', 'network', 'inspect', 'power', 'management'],
            inspect=self.iface)
        self.driver = self.task.driver

    def test_unmanaged_ok(self, mock_create_ports_if_not_exist):
        self.driver.boot.validate_inspection.side_effect = (
            exception.UnsupportedDriverExtension(''))
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_create_ports_if_not_exist.assert_called_once_with(self.task)
        self.assertFalse(self.driver.boot.prepare_ramdisk.called)
        self.assertFalse(self.driver.network.add_inspection_network.called)
        self.driver.management.set_boot_device.assert_called_once_with(
            self.task, device=boot_devices.PXE, persistent=False)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    def test_managed_ok(self, mock_get_url, mock_create_ports_if_not_exist):
        endpoint = 'http://192.169.0.42:6385/v1'
        mock_get_url.return_value = endpoint
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url':
                f'{endpoint}/continue_inspection',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    def test_managed_unversion_url(self, mock_get_url,
                                   mock_create_ports_if_not_exist):
        endpoint = 'http://192.169.0.42:6385/'
        mock_get_url.return_value = endpoint
        self.assertEqual(states.INSPECTWAIT,
                         self.iface.inspect_hardware(self.task))
        mock_create_ports_if_not_exist.assert_called_once_with(self.task)
        self.driver.boot.prepare_ramdisk.assert_called_once_with(
            self.task, ramdisk_params={
                'ipa-inspection-callback-url':
                f'{endpoint}v1/continue_inspection',
            })
        self.driver.network.add_inspection_network.assert_called_once_with(
            self.task)
        self.driver.power.set_power_state.assert_has_calls([
            mock.call(self.task, states.POWER_OFF, timeout=None),
            mock.call(self.task, states.POWER_ON, timeout=None),
        ])
        self.assertFalse(self.driver.network.remove_inspection_network.called)
        self.assertFalse(self.driver.boot.clean_up_ramdisk.called)


@mock.patch.object(common, 'tear_down_managed_boot', autospec=True)
@mock.patch.object(inspector, 'run_inspection_hooks', autospec=True)
class ContinueInspectionTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.config(hooks='ramdisk-error,architecture,validate-interfaces,'
                          'ports',
                    group='inspector')
        self.node = obj_utils.create_test_node(
            self.context,
            inspect_interface='agent',
            provision_state=states.INSPECTING)
        self.iface = inspector.AgentInspect()

    def test(self, mock_inspection_hooks, mock_tear_down):
        mock_tear_down.return_value = None
        with task_manager.acquire(self.context, self.node.id) as task:
            result = self.iface.continue_inspection(
                task, mock.sentinel.inventory, mock.sentinel.plugin_data)
            mock_inspection_hooks.assert_called_once_with(
                task, mock.sentinel.inventory, mock.sentinel.plugin_data,
                self.iface.hooks)
            mock_tear_down.assert_called_once_with(task)
            self.assertEqual(states.INSPECTING, task.node.provision_state)

        self.assertIsNone(result)
