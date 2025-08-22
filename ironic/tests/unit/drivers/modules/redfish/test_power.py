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

from unittest import mock

import sushy

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.redfish import management as redfish_mgmt
from ironic.drivers.modules.redfish import power as redfish_power
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_redfish_info()


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

    @mock.patch('time.sleep', autospec=True)
    @mock.patch.object(redfish_mgmt.RedfishManagement, 'restore_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state(self, mock_get_system, mock_restore_bootdev,
                             mock_sleep):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (states.POWER_ON, sushy.RESET_ON, True),
                (states.POWER_OFF, sushy.RESET_FORCE_OFF, False),
                (states.REBOOT, sushy.RESET_FORCE_RESTART, True),
                (states.SOFT_REBOOT, sushy.RESET_GRACEFUL_RESTART, True),
                (states.SOFT_POWER_OFF, sushy.RESET_GRACEFUL_SHUTDOWN, False)
            ]
            mock_sleep.reset_mock()

            for target, expected, restore_bootdev in expected_values:
                sleeps = target == states.REBOOT
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
                if restore_bootdev:
                    mock_restore_bootdev.assert_called_once_with(
                        task.driver.management, task, system_result[0])
                else:
                    self.assertFalse(mock_restore_bootdev.called)
                if sleeps:
                    mock_sleep.assert_called_with(15)
                else:
                    mock_sleep.assert_not_called()

                # Reset mocks
                mock_get_system.reset_mock()
                mock_restore_bootdev.reset_mock()
                mock_sleep.reset_mock()

    @mock.patch('time.sleep', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state_not_reached(self, mock_get_system, mock_sleep):
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
                exception.RedfishError, 'power on failed',
                task.driver.power.set_power_state, task, states.POWER_ON)
            fake_system.reset_system.assert_called_once_with(
                sushy.RESET_ON)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_power_state_race_condition_handling(
            self, mock_get_system):

        fake_system = mock_get_system.return_value
        mock_response = mock.Mock(status_code=400)
        mock_response.json.return_value = {
            'error': {
                'message': 'Host is powered OFF. Power On host and try again',
            }
        }

        fake_system.reset_system.side_effect = (
            sushy.exceptions.BadRequestError(
                method='POST', url='test', response=mock_response))

        success_scenarios = [
            (
                states.SOFT_POWER_OFF,
                states.POWER_OFF,
                sushy.RESET_GRACEFUL_SHUTDOWN,
            ),
            (
                states.SOFT_REBOOT,
                states.POWER_ON,
                sushy.RESET_GRACEFUL_RESTART
            ),
            (states.POWER_OFF, states.POWER_OFF, sushy.RESET_FORCE_OFF),
            (states.POWER_ON, states.POWER_ON, sushy.RESET_ON),
            (states.REBOOT, states.POWER_ON, sushy.RESET_FORCE_RESTART),
            (states.POWER_OFF, None, sushy.RESET_FORCE_OFF),
        ]

        failure_scenarios = [
            (states.POWER_OFF, states.POWER_ON),
            (states.POWER_ON, states.POWER_OFF),
        ]

        for target_state, final_state, expected_reset in success_scenarios:
            fake_system.power_state = None
            if final_state == states.POWER_OFF:
                fake_system.power_state = sushy.SYSTEM_POWER_STATE_OFF
            elif final_state == states.POWER_ON:
                fake_system.power_state = sushy.SYSTEM_POWER_STATE_ON

            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                task.driver.power.set_power_state(task, target_state)

                fake_system.reset_system.assert_called_with(expected_reset)

            fake_system.reset_mock()

        for target_state, actual_state in failure_scenarios:
            fake_system.power_state = None
            if actual_state == states.POWER_OFF:
                fake_system.power_state = sushy.SYSTEM_POWER_STATE_OFF
            elif actual_state == states.POWER_ON:
                fake_system.power_state = sushy.SYSTEM_POWER_STATE_ON

            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                self.assertRaises(
                    sushy.exceptions.BadRequestError,
                    task.driver.power.set_power_state, task, target_state)

            fake_system.reset_mock()

    @mock.patch.object(redfish_mgmt.RedfishManagement, 'restore_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_from_power_off(self, mock_get_system,
                                   mock_restore_bootdev):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            system_result = [
                # Initial state
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Transient state - still powered off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Final state - down powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
            ]
            mock_get_system.side_effect = system_result

            task.driver.power.reboot(task)

            # Asserts
            system_result[0].reset_system.assert_called_once_with(
                sushy.RESET_ON)
            mock_get_system.assert_called_with(task.node)
            self.assertEqual(3, mock_get_system.call_count)
            mock_restore_bootdev.assert_called_once_with(
                task.driver.management, task, system_result[0])

    @mock.patch.object(redfish_mgmt.RedfishManagement, 'restore_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_from_power_off_with_disable_power_off(
            self, mock_get_system, mock_restore_bootdev):
        # NOTE(dtantsur): if a node with disable_power_off is powered off, we
        # probably cannot do anything about it. This unit test is only here
        # for consistent coverage.
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.disable_power_off = True
            system_result = [
                # Initial state
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Transient state - still powered off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Final state - down powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
            ]
            mock_get_system.side_effect = system_result

            task.driver.power.reboot(task)

            # Asserts
            system_result[0].reset_system.assert_called_once_with(
                sushy.RESET_ON)
            mock_get_system.assert_called_with(task.node)
            self.assertEqual(3, mock_get_system.call_count)
            mock_restore_bootdev.assert_called_once_with(
                task.driver.management, task, system_result[0])

    @mock.patch.object(redfish_mgmt.RedfishManagement, 'restore_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_from_power_on(self, mock_get_system, mock_restore_bootdev):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            system_result = [
                # Initial state
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON),
                # Transient state - powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Final state - down powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
            ]
            mock_get_system.side_effect = system_result

            task.driver.power.reboot(task)

            # Asserts
            system_result[0].reset_system.assert_has_calls([
                mock.call(sushy.RESET_FORCE_OFF),
                mock.call(sushy.RESET_ON),
            ])
            mock_get_system.assert_called_with(task.node)
            self.assertEqual(3, mock_get_system.call_count)
            mock_restore_bootdev.assert_called_once_with(
                task.driver.management, task, system_result[0])

    @mock.patch('time.sleep', autospec=True)
    @mock.patch.object(redfish_mgmt.RedfishManagement, 'restore_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_from_power_on_with_disable_power_off(
            self, mock_get_system, mock_restore_bootdev, mock_sleep):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.disable_power_off = True
            system_result = [
                # Initial state
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON),
                # Transient state - powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
                # Final state - down powering off
                mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
            ]
            mock_get_system.side_effect = system_result

            task.driver.power.reboot(task)

            # Asserts
            system_result[0].reset_system.assert_called_once_with(
                sushy.RESET_FORCE_RESTART)
            mock_get_system.assert_called_with(task.node)
            self.assertEqual(3, mock_get_system.call_count)
            mock_restore_bootdev.assert_called_once_with(
                task.driver.management, task, system_result[0])
            mock_sleep.assert_called_with(15)

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
                exception.RedfishError, 'Reboot failed.*power off',
                task.driver.power.reboot, task)
            fake_system.reset_system.assert_called_once_with(
                sushy.RESET_FORCE_OFF)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_reboot_fail_on_power_on(self, mock_get_system, mock_sushy):
        system_result = [
            # Initial state
            mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON),
            # Transient state - powering off
            mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_OFF),
            # Final state - down powering off
            mock.Mock(power_state=sushy.SYSTEM_POWER_STATE_ON)
        ]
        mock_get_system.side_effect = system_result
        fake_system = system_result[0]
        fake_system.reset_system.side_effect = [
            None,
            sushy.exceptions.SushyError(),
        ]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.RedfishError, 'Reboot failed.*power on',
                task.driver.power.reboot, task)
            fake_system.reset_system.assert_has_calls([
                mock.call(sushy.RESET_FORCE_OFF),
                mock.call(sushy.RESET_ON),
            ])
            mock_get_system.assert_called_with(task.node)

    def test_get_supported_power_states(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_power_states = (
                task.driver.power.get_supported_power_states(task))
            self.assertEqual(list(redfish_power.SET_POWER_STATE_MAP),
                             supported_power_states)
