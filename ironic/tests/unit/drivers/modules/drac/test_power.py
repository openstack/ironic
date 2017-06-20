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
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracPowerTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
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

    def test_set_power_state(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_OFF)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_OFF]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)

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

    def test_reboot_while_powered_on(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_ON

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.REBOOT]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)

    def test_reboot_while_powered_off(self, mock_get_drac_client):
        mock_client = mock_get_drac_client.return_value
        mock_client.get_power_state.return_value = drac_constants.POWER_OFF

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)

        drac_power_state = drac_power.REVERSE_POWER_STATES[states.POWER_ON]
        mock_client.set_power_state.assert_called_once_with(drac_power_state)
