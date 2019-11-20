#
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
"""Test class for iBMC Power interface."""

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.ibmc import mappings
from ironic.drivers.modules.ibmc import utils
from ironic.tests.unit.drivers.modules.ibmc import base

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')
ibmc_error = importutils.try_import('ibmc_client.exceptions')


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class IBMCPowerTestCase(base.IBMCTestCase):

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_get_power_state(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_values = mappings.GET_POWER_STATE_MAP
            for current, expected in expected_values.items():
                # Mock
                conn.system.get.return_value = mock.Mock(
                    power_state=current
                )

                # Asserts
                self.assertEqual(expected,
                                 task.driver.power.get_power_state(task))

                conn.system.get.assert_called_once()
                connect_ibmc.assert_called_once_with(**self.ibmc)

                # Reset Mock
                conn.system.get.reset_mock()
                connect_ibmc.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_power_state(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            state_mapping = mappings.SET_POWER_STATE_MAP
            for (expect_state, reset_type) in state_mapping.items():
                if expect_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
                    final = constants.SYSTEM_POWER_STATE_OFF
                    transient = constants.SYSTEM_POWER_STATE_ON
                else:
                    final = constants.SYSTEM_POWER_STATE_ON
                    transient = constants.SYSTEM_POWER_STATE_OFF

                # Mocks
                mock_system_get_results = (
                    [mock.Mock(power_state=transient)] * 3 +
                    [mock.Mock(power_state=final)])
                conn.system.get.side_effect = mock_system_get_results

                task.driver.power.set_power_state(task, expect_state)

                # Asserts
                connect_ibmc.assert_called_with(**self.ibmc)
                conn.system.reset.assert_called_once_with(reset_type)
                self.assertEqual(4, conn.system.get.call_count)

                # Reset Mocks
                # TODO(Qianbiao.NG) why reset_mock does not reset call_count
                connect_ibmc.reset_mock()
                conn.system.get.reset_mock()
                conn.system.reset.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_power_state_not_reached(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.config(power_state_change_timeout=2, group='conductor')

            state_mapping = mappings.SET_POWER_STATE_MAP
            for (expect_state, reset_type) in state_mapping.items():
                if expect_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
                    final = constants.SYSTEM_POWER_STATE_OFF
                    transient = constants.SYSTEM_POWER_STATE_ON
                else:
                    final = constants.SYSTEM_POWER_STATE_ON
                    transient = constants.SYSTEM_POWER_STATE_OFF

                # Mocks
                mock_system_get_results = (
                    [mock.Mock(power_state=transient)] * 5 +
                    [mock.Mock(power_state=final)])
                conn.system.get.side_effect = mock_system_get_results

                self.assertRaises(exception.PowerStateFailure,
                                  task.driver.power.set_power_state,
                                  task, expect_state)

                # Asserts
                connect_ibmc.assert_called_with(**self.ibmc)
                conn.system.reset.assert_called_once_with(reset_type)

                # Reset Mocks
                connect_ibmc.reset_mock()
                conn.system.get.reset_mock()
                conn.system.reset.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_power_state_fail(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)

        # Mocks
        conn.system.reset.side_effect = (
            ibmc_error.IBMCClientError
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Asserts
            self.assertRaisesRegex(
                exception.IBMCError, 'set iBMC power state',
                task.driver.power.set_power_state, task, states.POWER_ON)
            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(constants.RESET_ON)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_power_state_timeout(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.config(power_state_change_timeout=2, group='conductor')

            # Mocks
            conn.system.get.side_effect = (
                [mock.Mock(power_state=constants.SYSTEM_POWER_STATE_OFF)] * 3
            )

            # Asserts
            self.assertRaisesRegex(
                exception.PowerStateFailure,
                'Failed to set node power state to power on',
                task.driver.power.set_power_state, task, states.POWER_ON)

            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(constants.RESET_ON)

    def test_get_supported_power_states(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_power_states = (
                task.driver.power.get_supported_power_states(task))
            self.assertEqual(sorted(list(mappings.SET_POWER_STATE_MAP)),
                             sorted(supported_power_states))


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class IBMCPowerRebootTestCase(base.IBMCTestCase):

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_reboot(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        expected_values = [
            (constants.SYSTEM_POWER_STATE_OFF, constants.RESET_ON),
            (constants.SYSTEM_POWER_STATE_ON,
             constants.RESET_FORCE_RESTART)
        ]

        # for (expect_state, reset_type) in state_mapping.items():
        for current, reset_type in expected_values:
            mock_system_get_results = [
                # Initial state
                mock.Mock(power_state=current),
                # Transient state - powering off
                mock.Mock(power_state=constants.SYSTEM_POWER_STATE_OFF),
                # Final state - down powering off
                mock.Mock(power_state=constants.SYSTEM_POWER_STATE_ON)
            ]
            conn.system.get.side_effect = mock_system_get_results
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                task.driver.power.reboot(task)

            # Asserts
            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(reset_type)

            # Reset Mocks
            connect_ibmc.reset_mock()
            conn.system.get.reset_mock()
            conn.system.reset.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_reboot_not_reached(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            # Mocks
            conn.system.get.return_value = mock.Mock(
                power_state=constants.SYSTEM_POWER_STATE_OFF)
            self.assertRaisesRegex(
                exception.PowerStateFailure,
                'Failed to set node power state to power on',
                task.driver.power.reboot, task)

            # Asserts
            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(constants.RESET_ON)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_reboot_fail(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)

        # Mocks
        conn.system.reset.side_effect = (
            ibmc_error.IBMCClientError
        )
        conn.system.get.return_value = mock.Mock(
            power_state=constants.SYSTEM_POWER_STATE_ON
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Asserts
            self.assertRaisesRegex(
                exception.IBMCError, 'reboot iBMC',
                task.driver.power.reboot, task)
            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.get.assert_called_once()
            conn.system.reset.assert_called_once_with(
                constants.RESET_FORCE_RESTART)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_reboot_timeout(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)

        # Mocks
        conn.system.get.side_effect = [mock.Mock(
            power_state=constants.SYSTEM_POWER_STATE_OFF
        )] * 5

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.config(power_state_change_timeout=2, group='conductor')

            # Asserts
            self.assertRaisesRegex(
                exception.PowerStateFailure,
                'Failed to set node power state to power on',
                task.driver.power.reboot, task)

            # Asserts
            connect_ibmc.assert_called_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(
                constants.RESET_ON)
