# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

import mock
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import management
from ironic.drivers.modules.oneview import power
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

client_exception = importutils.try_import('hpOneView.exceptions')


class OneViewPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewPowerDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')
        self.config(tls_cacert_file='ca_file', group='oneview')
        self.config(allow_insecure_connections=False, group='oneview')

        mgr_utils.mock_the_extension_manager(driver='fake_oneview')
        self.driver = driver_factory.get_driver('fake_oneview')

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)
        deploy_utils.is_node_in_use_by_oneview = mock.Mock(return_value=False)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate(self, mock_validate):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.validate(task)
            self.assertTrue(mock_validate.called)

    def test_validate_missing_parameter(self):
        node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            id=999, driver='fake_oneview')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(
                exception.MissingParameterValue,
                task.driver.power.validate,
                task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate_exception(self, mock_validate):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.power.validate,
                task)

    def test_validate_node_in_use_by_oneview(self):
        deploy_utils.is_node_in_use_by_oneview.return_value = True
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.power.validate,
                task)

    def test_get_properties(self):
        expected = common.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.power.get_properties())

    @mock.patch.object(common, 'get_hponeview_client')
    def test_get_power_state(self, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'On'}
        client.server_hardware.get.return_value = server_hardware
        with task_manager.acquire(self.context, self.node.uuid) as task:
            power_state = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, power_state)

    @mock.patch.object(common, 'get_hponeview_client')
    def test_get_power_state_fail(self, mock_get_ov_client):
        client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        client.server_hardware.get.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.get_power_state,
                task)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_on(self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.POWER_ON)
            self.assertTrue(mock_set_boot_device.called)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_ON, server_hardware,
                                           timeout=-1)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_on_with_timeout(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.POWER_ON, timeout=2)
            self.assertTrue(mock_set_boot_device.called)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_ON, server_hardware,
                                           timeout=2)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_off(self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.POWER_OFF)
            self.assertFalse(mock_set_boot_device.called)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_OFF, server_hardware,
                                           timeout=-1)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_off_with_timeout(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.POWER_OFF,
                                              timeout=2)
            self.assertFalse(mock_set_boot_device.called)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_OFF, server_hardware,
                                           timeout=2)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_reboot(self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.REBOOT)
            calls = [mock.call(power.POWER_OFF, server_hardware, timeout=-1),
                     mock.call(power.POWER_ON, server_hardware, timeout=-1)]
            update = client.server_hardware.update_power_state
            update.assert_has_calls(calls)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_soft_reboot(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        self.driver.power.client = client
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.set_power_state(task, states.SOFT_REBOOT)
            calls = [mock.call(power.SOFT_POWER_OFF, server_hardware,
                               timeout=-1),
                     mock.call(power.POWER_ON, server_hardware, timeout=-1)]
            update = client.server_hardware.update_power_state
            update.assert_has_calls(calls)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_on_fail(self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        client.server_hardware.update_power_state.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.set_power_state,
                task,
                states.POWER_ON)
            mock_set_boot_device.assert_called_once_with(task)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_off_fail(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        client.server_hardware.update_power_state.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.set_power_state,
                task,
                states.POWER_OFF)
            self.assertFalse(mock_set_boot_device.called)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_reboot_fail_with_hardware_on(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'On'}
        client.server_hardware.get.return_value = server_hardware
        exc = client_exception.HPOneViewException()
        client.server_hardware.update_power_state.side_effect = exc
        self.driver.power.client = client
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.reboot,
                task)
            self.assertFalse(mock_set_boot_device.called)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_reboot_fail_with_hardware_off(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'Off'}
        client.server_hardware.get.return_value = server_hardware
        exc = client_exception.HPOneViewException()
        client.server_hardware.update_power_state.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.reboot,
                task)
            mock_set_boot_device.assert_called_once_with(task)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_invalid_state(self, mock_set_boot_device):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                self.driver.power.set_power_state,
                task,
                'fake_state')
            self.assertFalse(mock_set_boot_device.called)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_reboot_with_hardware_on(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'On'}
        client.server_hardware.get.return_value = server_hardware
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.reboot(task)
            calls = [mock.call(power.POWER_OFF, server_hardware, timeout=-1),
                     mock.call(power.POWER_ON, server_hardware, timeout=-1)]
            update = client.server_hardware.update_power_state
            update.assert_has_calls(calls)
            mock_set_boot_device.assert_called_once_with(task)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_reboot_with_hardware_off(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'Off'}
        client.server_hardware.get.return_value = server_hardware
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.reboot(task, timeout=-1)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_ON, server_hardware,
                                           timeout=-1)
            mock_set_boot_device.assert_called_once_with(task)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_reboot_with_hardware_off_with_timeout(
            self, mock_set_boot_device, mock_get_ov_client):
        client = mock_get_ov_client()
        server_hardware = {'powerState': 'Off'}
        client.server_hardware.get.return_value = server_hardware
        server_hardware = self.node.driver_info.get('server_hardware_uri')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.reboot(task, timeout=2)
            update = client.server_hardware.update_power_state
            update.assert_called_once_with(power.POWER_ON, server_hardware,
                                           timeout=2)
            mock_set_boot_device.assert_called_once_with(task)

    def test_get_supported_power_states(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_power_states = (
                task.driver.power.get_supported_power_states(task))
            self.assertEqual(set(power.SET_POWER_STATE_MAP),
                             set(supported_power_states))
