# Copyright 2015, Cisco Systems.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from oslo_config import cfg
from oslo_utils import importutils

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.cimc import common
from ironic.drivers.modules.cimc import power
from ironic.tests.unit.drivers.modules.cimc import test_common

imcsdk = importutils.try_import('ImcSdk')

CONF = cfg.CONF


@mock.patch.object(common, 'cimc_handle', autospec=True)
class WaitForStateChangeTestCase(test_common.CIMCBaseTestCase):

    def setUp(self):
        super(WaitForStateChangeTestCase, self).setUp()
        CONF.set_override('max_retry', 2, 'cimc')
        CONF.set_override('action_interval', 0, 'cimc')

    def test__wait_for_state_change(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.return_value = (
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON)

                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                state = power._wait_for_state_change(states.POWER_ON, task)

                handle.get_imc_managedobject.assert_called_once_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

                self.assertEqual(state, states.POWER_ON)

    def test__wait_for_state_change_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.return_value = (
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_OFF)

                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                state = power._wait_for_state_change(states.POWER_ON, task)

                calls = [
                    mock.call(None, None, params={"Dn": "sys/rack-unit-1"}),
                    mock.call(None, None, params={"Dn": "sys/rack-unit-1"})
                ]
                handle.get_imc_managedobject.assert_has_calls(calls)
                self.assertEqual(state, states.ERROR)

    def test__wait_for_state_change_imc_exception(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.get_imc_managedobject.side_effect = (
                    imcsdk.ImcException('Boom'))

                self.assertRaises(
                    exception.CIMCException,
                    power._wait_for_state_change, states.POWER_ON, task)

                handle.get_imc_managedobject.assert_called_once_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})


@mock.patch.object(common, 'cimc_handle', autospec=True)
class PowerTestCase(test_common.CIMCBaseTestCase):

    def test_get_properties(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertEqual(common.COMMON_PROPERTIES,
                             task.driver.power.get_properties())

    @mock.patch.object(common, "parse_driver_info", autospec=True)
    def test_validate(self, mock_driver_info, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.validate(task)
            mock_driver_info.assert_called_once_with(task.node)

    def test_get_power_state(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.return_value = (
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON)

                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                state = task.driver.power.get_power_state(task)

                handle.get_imc_managedobject.assert_called_once_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})
                self.assertEqual(states.POWER_ON, state)

    def test_get_power_state_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.return_value = (
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON)

                handle.get_imc_managedobject.side_effect = (
                    imcsdk.ImcException("boom"))

                self.assertRaises(exception.CIMCException,
                                  task.driver.power.get_power_state, task)

                handle.get_imc_managedobject.assert_called_once_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_invalid_state(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.set_power_state,
                              task, states.ERROR)

    def test_set_power_state_reboot_ok(self, mock_handle):
        hri = imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_HARD_RESET_IMMEDIATE

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.side_effect = [
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_OFF,
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON
                ]
                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                task.driver.power.set_power_state(task, states.REBOOT)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER: hri,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_reboot_fail(self, mock_handle):
        hri = imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_HARD_RESET_IMMEDIATE
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.get_imc_managedobject.side_effect = (
                    imcsdk.ImcException("boom"))

                self.assertRaises(exception.CIMCException,
                                  task.driver.power.set_power_state,
                                  task, states.REBOOT)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER: hri,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_on_ok(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.side_effect = [
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_OFF,
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON
                ]
                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                task.driver.power.set_power_state(task, states.POWER_ON)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER:
                            imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_UP,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_on_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.get_imc_managedobject.side_effect = (
                    imcsdk.ImcException("boom"))

                self.assertRaises(exception.CIMCException,
                                  task.driver.power.set_power_state,
                                  task, states.POWER_ON)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER:
                            imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_UP,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_off_ok(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                mock_rack_unit = mock.MagicMock()
                mock_rack_unit.get_attr.side_effect = [
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_ON,
                    imcsdk.ComputeRackUnit.CONST_OPER_POWER_OFF
                ]
                handle.get_imc_managedobject.return_value = [mock_rack_unit]

                task.driver.power.set_power_state(task, states.POWER_OFF)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER:
                            imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_DOWN,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    def test_set_power_state_off_fail(self, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.get_imc_managedobject.side_effect = (
                    imcsdk.ImcException("boom"))

                self.assertRaises(exception.CIMCException,
                                  task.driver.power.set_power_state,
                                  task, states.POWER_OFF)

                handle.set_imc_managedobject.assert_called_once_with(
                    None, class_id="ComputeRackUnit",
                    params={
                        imcsdk.ComputeRackUnit.ADMIN_POWER:
                            imcsdk.ComputeRackUnit.CONST_ADMIN_POWER_DOWN,
                        imcsdk.ComputeRackUnit.DN: "sys/rack-unit-1"
                    })

                handle.get_imc_managedobject.assert_called_with(
                    None, None, params={"Dn": "sys/rack-unit-1"})

    @mock.patch.object(power.Power, "set_power_state", autospec=True)
    @mock.patch.object(power.Power, "get_power_state", autospec=True)
    def test_reboot_on(self, mock_get_state, mock_set_state, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_state.return_value = states.POWER_ON
            task.driver.power.reboot(task)
            mock_set_state.assert_called_with(mock.ANY, task, states.REBOOT)

    @mock.patch.object(power.Power, "set_power_state", autospec=True)
    @mock.patch.object(power.Power, "get_power_state", autospec=True)
    def test_reboot_off(self, mock_get_state, mock_set_state, mock_handle):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_state.return_value = states.POWER_OFF
            task.driver.power.reboot(task)
            mock_set_state.assert_called_with(mock.ANY, task, states.POWER_ON)
