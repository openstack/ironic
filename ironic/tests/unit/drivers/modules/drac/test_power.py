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

"""
Test class for DRAC power interface
"""

from dracclient import constants as drac_constants
from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import power as drac_power
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracPowerTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracPowerTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

    def test_get_properties(self, mock_get_drac_client):
        expected = drac_common.COMMON_PROPERTIES
        driver = drac_power.DracPower()
        self.assertEqual(expected, driver.get_properties())

    def test_get_power_state(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_ON

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            power_state = task.driver.power.get_power_state(task)

        self.assertEqual(states.POWER_ON, power_state)
        mock_client.get_power_state.assert_called_once_with()

    def test_get_power_state_fail(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.get_power_state.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.power.get_power_state, task)

        mock_client.get_power_state.assert_called_once_with()

    @mock.patch.object(drac_power.LOG, 'warning')
    def test_set_power_state(self, mock_log, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_OFF]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)
        self.assertFalse(mock_log.called)

    def test_set_power_state_fail(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.set_power_state.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.power.set_power_state, task,
                              states.POWER_OFF)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_OFF]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)

    @mock.patch.object(drac_power.LOG, 'warning')
    def test_set_power_state_timeout(self, mock_log, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF,
                                              timeout=11)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_OFF]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)
        self.assertTrue(mock_log.called)

    @mock.patch.object(drac_power.LOG, 'warning')
    def test_reboot_while_powered_on(self, mock_log, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_ON

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.REBOOT]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)
        self.assertFalse(mock_log.called)

    @mock.patch.object(drac_power.LOG, 'warning')
    def test_reboot_while_powered_on_timeout(self, mock_log,
                                             mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_ON

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task, timeout=42)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.REBOOT]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)
        self.assertTrue(mock_log.called)

    def test_reboot_while_powered_off(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_OFF

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_ON]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)

    @mock.patch('time.sleep')
    def test_reboot_retries_success(self, mock_sleep, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_OFF
        exc = drac_exceptions.DRACOperationFailed(
            drac_messages=['The command failed to set RequestedState'])
        mock_client.set_power_state.side_effect = [exc, None]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_ON]
        self.assertEqual(2, mock_client.set_power_state.call_count)
        mock_client.set_power_state.assert_has_calls(
            [mock.call(drac_power_state),
             mock.call(drac_power_state)])

    @mock.patch('time.sleep')
    def test_reboot_retries_fail(self, mock_sleep, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_OFF
        exc = drac_exceptions.DRACOperationFailed(
            drac_messages=['The command failed to set RequestedState'])
        mock_client.set_power_state.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.power.reboot, task)

        self.assertEqual(drac_power.POWER_STATE_TRIES,
                         mock_client.set_power_state.call_count)

    @mock.patch('time.sleep')
    def test_reboot_retries_power_change_success(self, mock_sleep,
                                                 mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.side_effect = [drac_constants.POWER_OFF,
                                                   drac_constants.POWER_ON]
        exc = drac_exceptions.DRACOperationFailed(
            drac_messages=['The command failed to set RequestedState'])
        mock_client.set_power_state.side_effect = [exc, None]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        self.assertEqual(2, mock_client.set_power_state.call_count)
        drac_power_state1 = drac_power.REVERSE_POWER_STATES[states.POWER_ON]
        drac_power_state2 = drac_power.REVERSE_POWER_STATES[states.REBOOT]
        mock_client.set_power_state.assert_has_calls(
            [mock.call(drac_power_state1),
             mock.call(drac_power_state2)])
