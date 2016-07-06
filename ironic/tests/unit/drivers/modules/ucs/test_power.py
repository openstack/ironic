#    Copyright 2015, Cisco Systems.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Test class for UcsPower module."""
import mock
from oslo_config import cfg
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.ucs import helper as ucs_helper
from ironic.drivers.modules.ucs import power as ucs_power
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

ucs_error = importutils.try_import('UcsSdk.utils.exception')

INFO_DICT = db_utils.get_test_ucs_info()
CONF = cfg.CONF


class UcsPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(UcsPowerTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_ucs")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ucs',
                                               driver_info=driver_info)
        CONF.set_override('max_retry', 2, 'cisco_ucs')
        CONF.set_override('action_interval', 0, 'cisco_ucs')
        self.interface = ucs_power.Power()

    def test_get_properties(self):
        expected = ucs_helper.COMMON_PROPERTIES
        expected.update(ucs_helper.COMMON_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(ucs_helper, 'parse_driver_info',
                       spec_set=True, autospec=True)
    def test_validate(self, mock_parse_driver_info):
        mock_parse_driver_info.return_value = {}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.interface.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(ucs_helper, 'parse_driver_info',
                       spec_set=True, autospec=True)
    def test_validate_fail(self, mock_parse_driver_info):
        side_effect = exception.InvalidParameterValue('Invalid Input')
        mock_parse_driver_info.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.validate,
                              task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_get_power_state_up(self, mock_power_helper, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_power.get_power_state.return_value = 'up'
            self.assertEqual(states.POWER_ON,
                             self.interface.get_power_state(task))
            mock_power.get_power_state.assert_called_once_with()
            mock_power.get_power_state.reset_mock()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_get_power_state_down(self, mock_power_helper, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_power.get_power_state.return_value = 'down'
            self.assertEqual(states.POWER_OFF,
                             self.interface.get_power_state(task))
            mock_power.get_power_state.assert_called_once_with()
            mock_power.get_power_state.reset_mock()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_get_power_state_error(self, mock_power_helper, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_power.get_power_state.return_value = states.ERROR
            self.assertEqual(states.ERROR,
                             self.interface.get_power_state(task))
            mock_power.get_power_state.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_get_power_state_fail(self,
                                  mock_ucs_power,
                                  mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        power = mock_ucs_power.return_value
        power.get_power_state.side_effect = (
            ucs_error.UcsOperationError(operation='getting power state',
                                        error='failed'))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UcsOperationError,
                              self.interface.get_power_state,
                              task)
        power.get_power_state.assert_called_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power._wait_for_state_change',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_set_power_state(self, mock_power_helper, mock__wait, mock_helper):
        target_state = states.POWER_ON
        mock_power = mock_power_helper.return_value
        mock_power.get_power_state.side_effect = ['down', 'up']
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock__wait.return_value = target_state
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(self.interface.set_power_state(task,
                                                             target_state))

        mock_power.set_power_state.assert_called_once_with('up')
        mock_power.get_power_state.assert_called_once_with()
        mock__wait.assert_called_once_with(target_state, mock_power)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_set_power_state_fail(self, mock_power_helper, mock_helper):
        mock_power = mock_power_helper.return_value
        mock_power.set_power_state.side_effect = (
            ucs_error.UcsOperationError(operation='setting power state',
                                        error='failed'))
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.UcsOperationError,
                              self.interface.set_power_state,
                              task, states.POWER_OFF)
        mock_power.set_power_state.assert_called_once_with('down')

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    def test_set_power_state_invalid_state(self, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.interface.set_power_state,
                              task, states.ERROR)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test__wait_for_state_change_already_target_state(
            self,
            mock_ucs_power,
            mock_helper):
        mock_power = mock_ucs_power.return_value
        target_state = states.POWER_ON
        mock_power.get_power_state.return_value = 'up'
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        self.assertEqual(states.POWER_ON,
                         ucs_power._wait_for_state_change(
                             target_state, mock_power))
        mock_power.get_power_state.assert_called_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test__wait_for_state_change_exceed_iterations(
            self,
            mock_power_helper,
            mock_helper):
        mock_power = mock_power_helper.return_value
        target_state = states.POWER_ON
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power.get_power_state.side_effect = (
            ['down', 'down', 'down', 'down'])
        self.assertEqual(states.ERROR,
                         ucs_power._wait_for_state_change(
                             target_state, mock_power)
                         )
        mock_power.get_power_state.assert_called_with()
        self.assertEqual(4, mock_power.get_power_state.call_count)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power._wait_for_state_change',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_set_and_wait_for_state_change_fail(
            self,
            mock_power_helper,
            mock__wait,
            mock_helper):
        target_state = states.POWER_ON
        mock_power = mock_power_helper.return_value
        mock_power.get_power_state.return_value = 'down'
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock__wait.return_value = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.interface.set_power_state,
                              task,
                              target_state)

        mock_power.set_power_state.assert_called_once_with('up')
        mock_power.get_power_state.assert_called_once_with()
        mock__wait.assert_called_once_with(target_state, mock_power)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power._wait_for_state_change',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_reboot(self, mock_power_helper, mock__wait, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        mock__wait.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(self.interface.reboot(task))
            mock_power.reboot.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_reboot_fail(self, mock_power_helper,
                         mock_ucs_helper):
        mock_ucs_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        mock_power.reboot.side_effect = (
            ucs_error.UcsOperationError(operation='rebooting', error='failed'))
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.UcsOperationError,
                              self.interface.reboot,
                              task
                              )
            mock_power.reboot.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power._wait_for_state_change',
                spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.power.ucs_power.UcsPower',
                spec_set=True, autospec=True)
    def test_reboot__wait_state_change_fail(self, mock_power_helper,
                                            mock__wait,
                                            mock_ucs_helper):
        mock_ucs_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_power = mock_power_helper.return_value
        mock__wait.return_value = states.ERROR
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.interface.reboot,
                              task)
            mock_power.reboot.assert_called_once_with()
