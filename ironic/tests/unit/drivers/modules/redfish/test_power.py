# Copyright 2017 Red Hat, Inc.
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

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.redfish import power as redfish_power
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


@mock.patch('eventlet.greenthread.sleep', lambda _t: None)
class RedfishPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishPowerTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_power, 'sushy', None)
    def test_loading_error(self):
        self.assertRaisesRegex(
            exception.DriverLoadError,
            'Unable to import the sushy library',
            redfish_power.RedfishPower)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in redfish_utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_power_state(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_values = [
                (sushy.SYSTEM_POWER_STATE_ON, states.POWER_ON),
                (sushy.SYSTEM_POWER_STATE_POWERING_ON, states.POWER_ON),
                (sushy.SYSTEM_POWER_STATE_OFF, states.POWER_OFF),
                (sushy.SYSTEM_POWER_STATE_POWERING_OFF, states.POWER_OFF)
            ]
            for current, expected in expected_values:
                mock_get_system.return_value = mock.Mock(power_state=current)
                self.assertEqual(expected,
                                 task.driver.power.get_power_state(task))
                mock_get_system.assert_called_once_with(task.node)
                mock_get_system.reset_mock()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (states.POWER_ON, sushy.RESET_ON),
                (states.POWER_OFF, sushy.RESET_FORCE_OFF),
                (states.REBOOT, sushy.RESET_FORCE_RESTART),
                (states.SOFT_REBOOT, sushy.RESET_GRACEFUL_RESTART),
                (states.SOFT_POWER_OFF, sushy.RESET_GRACEFUL_SHUTDOWN)
            ]

            for target, expected in expected_values:
                if target in (states.POWER_OFF, states.SOFT_POWER_OFF):
                    final = sushy.SYSTEM_POWER_STATE_OFF
                    transient = sushy.SYSTEM_POWER_STATE_ON
                else:
                    final = sushy.SYSTEM_POWER_STATE_ON
                    transient = sushy.SYSTEM_POWER_STATE_OFF

                system_result = [
                    mock.Mock(power_state=transient)
                ] * 3 + [mock.Mock(power_state=final)]
                mock_get_system.side_effect = system_result

                task.driver.power.set_power_state(task, target)

                # Asserts
                system_result[0].reset_system.assert_called_once_with(expected)
                mock_get_system.assert_called_with(task.node)
                self.assertEqual(4, mock_get_system.call_count)

                # Reset mocks
                mock_get_system.reset_mock()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state_not_reached(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.config(power_state_change_timeout=2, group='conductor')
            expected_values = [
                (states.POWER_ON, sushy.RESET_ON),
                (states.POWER_OFF, sushy.RESET_FORCE_OFF),
                (states.REBOOT, sushy.RESET_FORCE_RESTART),
                (states.SOFT_REBOOT, sushy.RESET_GRACEFUL_RESTART),
                (states.SOFT_POWER_OFF, sushy.RESET_GRACEFUL_SHUTDOWN)
            ]

            for target, expected in expected_values:
                fake_system = mock_get_system.return_value
                if target in (states.POWER_OFF, states.SOFT_POWER_OFF):
                    fake_system.power_state = sushy.SYSTEM_POWER_STATE_ON
                else:
                    fake_system.power_state = sushy.SYSTEM_POWER_STATE_OFF

                self.assertRaises(exception.PowerStateFailure,
                                  task.driver.power.set_power_state,
                                  task, target)

                # Asserts
                fake_system.reset_system.assert_called_once_with(expected)
                mock_get_system.assert_called_with(task.node)

                # Reset mocks
                mock_get_system.reset_mock()

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state_fail(self, mock_get_system, mock_sushy):
        fake_system = mock_get_system.return_value
        fake_system.reset_system.side_effect = (
            sushy.exceptions.SushyError())

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.RedfishError, 'Redfish set power state',
                task.driver.power.set_power_state, task, states.POWER_ON)
            fake_system.reset_system.assert_called_once_with(
                sushy.RESET_ON)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (sushy.SYSTEM_POWER_STATE_ON, sushy.RESET_FORCE_RESTART),
                (sushy.SYSTEM_POWER_STATE_OFF, sushy.RESET_ON)
            ]

            for current, expected in expected_values:
                system_result = [
                    # Initial state
                    mock.Mock(power_state=current),
                    # Transient state - powering off
                    mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                    # Final state - down powering off
                    mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
                ]
                mock_get_system.side_effect = system_result

                task.driver.power.reboot(task)

                # Asserts
                system_result[0].reset_system.assert_called_once_with(expected)
                mock_get_system.assert_called_with(task.node)
                self.assertEqual(3, mock_get_system.call_count)

                # Reset mocks
                mock_get_system.reset_mock()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_not_reached(self, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            fake_system = mock_get_system.return_value
            fake_system.power_state = sushy.SYSTEM_POWER_STATE_OFF

            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.reboot, task)

            # Asserts
            fake_system.reset_system.assert_called_once_with(sushy.RESET_ON)
            mock_get_system.assert_called_with(task.node)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_fail(self, mock_get_system, mock_sushy):
        fake_system = mock_get_system.return_value
        fake_system.reset_system.side_effect = (
            sushy.exceptions.SushyError())

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            fake_system.power_state = sushy.SYSTEM_POWER_STATE_ON
            self.assertRaisesRegex(
                exception.RedfishError, 'Redfish reboot failed',
                task.driver.power.reboot, task)
            fake_system.reset_system.assert_called_once_with(
                sushy.RESET_FORCE_RESTART)
            mock_get_system.assert_called_once_with(task.node)

    def test_get_supported_power_states(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_power_states = (
                task.driver.power.get_supported_power_states(task))
            self.assertEqual(list(redfish_power.SET_POWER_STATE_MAP),
                             supported_power_states)
