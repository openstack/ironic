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
Test class for iRMC Power Driver
"""

import mock
from oslo_config import cfg

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_irmc_info()
CONF = cfg.CONF


@mock.patch.object(irmc_common, 'get_irmc_client')
class IRMCPowerInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IRMCPowerInternalMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_irmc')
        driver_info = INFO_DICT
        self.node = db_utils.create_test_node(
            driver='fake_irmc',
            driver_info=driver_info,
            instance_uuid='instance_uuid_123')

    def test__set_power_state_power_on_ok(self,
                                          get_irmc_client_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_ON)

    def test__set_power_state_power_off_ok(self,
                                           get_irmc_client_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_OFF)

    def test__set_power_state_power_reboot_ok(self,
                                              get_irmc_client_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.REBOOT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_RESET)

    def test__set_power_state_invalid_target_state(self,
                                                   get_irmc_client_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              irmc_power._set_power_state,
                              task,
                              states.ERROR)

    def test__set_power_state_scci_exception(self,
                                             get_irmc_client_mock):
        irmc_client = get_irmc_client_mock.return_value
        irmc_client.side_effect = Exception()
        irmc_power.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_power._set_power_state,
                              task,
                              states.POWER_ON)


class IRMCPowerTestCase(db_base.DbTestCase):
    def setUp(self):
        super(IRMCPowerTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_irmc")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_irmc',
                                               driver_info=driver_info)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in irmc_common.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(irmc_common, 'parse_driver_info')
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(irmc_common, 'parse_driver_info')
    def test_validate_fail(self, mock_drvinfo):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        mock_drvinfo.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch('ironic.drivers.modules.irmc.power.ipmitool.IPMIPower')
    def test_get_power_state(self, mock_IPMIPower):
        ipmi_power = mock_IPMIPower.return_value
        ipmi_power.get_power_state.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            ipmi_power.get_power_state.assert_called_once_with(task)

    @mock.patch.object(irmc_power, '_set_power_state')
    def test_set_power_state(self, mock_set_power):
        mock_set_power.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
        mock_set_power.assert_called_once_with(task, states.POWER_ON)

    @mock.patch.object(irmc_power, '_set_power_state')
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state')
    def test_reboot(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)
        mock_set_power.assert_called_once_with(task, states.REBOOT)
