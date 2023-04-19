# Copyright 2015 FUJITSU LIMITED
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

from unittest import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules.redfish import power as redfish_power
from ironic.drivers.modules.redfish import utils as redfish_util
from ironic.tests.unit.drivers.modules.irmc import test_common


class IRMCPowerInternalMethodsTestCase(test_common.BaseIRMCTest):

    def test__is_expected_power_state(self):
        target_state = states.SOFT_POWER_OFF
        boot_status_value = irmc_power.BOOT_STATUS_VALUE['unknown']
        self.assertTrue(irmc_power._is_expected_power_state(
            target_state, boot_status_value))

        target_state = states.SOFT_POWER_OFF
        boot_status_value = irmc_power.BOOT_STATUS_VALUE['off']
        self.assertTrue(irmc_power._is_expected_power_state(
            target_state, boot_status_value))

        target_state = states.SOFT_REBOOT
        boot_status_value = irmc_power.BOOT_STATUS_VALUE['os-running']
        self.assertTrue(irmc_power._is_expected_power_state(
            target_state, boot_status_value))

        target_state = states.SOFT_POWER_OFF
        boot_status_value = irmc_power.BOOT_STATUS_VALUE['os-running']
        self.assertFalse(irmc_power._is_expected_power_state(
            target_state, boot_status_value))

    @mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
                lambda *args, **kwargs: None)
    @mock.patch('ironic.drivers.modules.irmc.power.snmp.SNMPClient',
                spec_set=True, autospec=True)
    def test__wait_power_state_soft_power_off(self, snmpclient_mock):
        target_state = states.SOFT_POWER_OFF
        self.config(snmp_polling_interval=1, group='irmc')
        self.config(soft_power_off_timeout=3, group='conductor')
        snmpclient_mock.return_value = mock.Mock(
            **{'get.side_effect': [8, 8, 2]})

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._wait_power_state(task, target_state)

            task.node.refresh()
            self.assertIsNone(task.node.last_error)
            self.assertEqual(states.POWER_OFF, task.node.power_state)
            self.assertEqual(states.NOSTATE, task.node.target_power_state)

    @mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
                lambda *args, **kwargs: None)
    @mock.patch('ironic.drivers.modules.irmc.power.snmp.SNMPClient',
                spec_set=True, autospec=True)
    def test__wait_power_state_soft_reboot(self, snmpclient_mock):
        target_state = states.SOFT_REBOOT
        self.config(snmp_polling_interval=1, group='irmc')
        self.config(soft_power_off_timeout=3, group='conductor')
        snmpclient_mock.return_value = mock.Mock(
            **{'get.side_effect': [10, 6, 8]})

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._wait_power_state(task, target_state)

            task.node.refresh()
            self.assertIsNone(task.node.last_error)
            self.assertEqual(states.POWER_ON, task.node.power_state)
            self.assertEqual(states.NOSTATE, task.node.target_power_state)

    @mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
                lambda *args, **kwargs: None)
    @mock.patch('ironic.drivers.modules.irmc.power.snmp.SNMPClient',
                spec_set=True, autospec=True)
    def test__wait_power_state_timeout(self, snmpclient_mock):
        target_state = states.SOFT_POWER_OFF
        self.config(snmp_polling_interval=1, group='irmc')
        self.config(soft_power_off_timeout=2, group='conductor')
        snmpclient_mock.return_value = mock.Mock(
            **{'get.side_effect': [8, 8, 8]})

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_power._wait_power_state,
                              task,
                              target_state,
                              timeout=None)

            task.node.refresh()
            self.assertIsNotNone(task.node.last_error)
            self.assertEqual(states.ERROR, task.node.power_state)
            self.assertEqual(states.NOSTATE, task.node.target_power_state)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_power_on_ok(
            self,
            attach_boot_iso_if_needed_mock,
            get_irmc_client_mock,
            _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
            attach_boot_iso_if_needed_mock.assert_called_once_with(task)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_ON)
        self.assertFalse(_wait_power_state_mock.called)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    def test__set_power_state_power_off_ok(self,
                                           get_irmc_client_mock,
                                           _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_OFF)
        self.assertFalse(_wait_power_state_mock.called)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_reboot_ok(
            self,
            attach_boot_iso_if_needed_mock,
            get_irmc_client_mock,
            _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.REBOOT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
            attach_boot_iso_if_needed_mock.assert_called_once_with(task)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_RESET)
        self.assertFalse(_wait_power_state_mock.called)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_soft_reboot_ok(
            self,
            attach_boot_iso_if_needed_mock,
            get_irmc_client_mock,
            _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.SOFT_REBOOT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
            attach_boot_iso_if_needed_mock.assert_called_once_with(task)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_SOFT_CYCLE)
        _wait_power_state_mock.assert_has_calls(
            [mock.call(task, states.SOFT_POWER_OFF, timeout=None),
             mock.call(task, states.SOFT_REBOOT, timeout=None)])

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_soft_power_off_ok(self,
                                                attach_boot_iso_if_needed_mock,
                                                get_irmc_client_mock,
                                                _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        target_state = states.SOFT_POWER_OFF
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            irmc_power._set_power_state(task, target_state)
        self.assertFalse(attach_boot_iso_if_needed_mock.called)
        irmc_client.assert_called_once_with(irmc_power.scci.POWER_SOFT_OFF)
        _wait_power_state_mock.assert_called_once_with(task, target_state,
                                                       timeout=None)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_invalid_target_state(
            self,
            attach_boot_iso_if_needed_mock,
            _wait_power_state_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              irmc_power._set_power_state,
                              task,
                              states.ERROR)
            self.assertFalse(attach_boot_iso_if_needed_mock.called)
            self.assertFalse(_wait_power_state_mock.called)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_scci_exception(self,
                                             attach_boot_iso_if_needed_mock,
                                             get_irmc_client_mock,
                                             _wait_power_state_mock):
        irmc_client = get_irmc_client_mock.return_value
        irmc_client.side_effect = Exception()
        irmc_power.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_power._set_power_state,
                              task,
                              states.POWER_ON)
            attach_boot_iso_if_needed_mock.assert_called_once_with(
                task)
            self.assertFalse(_wait_power_state_mock.called)

    @mock.patch.object(irmc_power, '_wait_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'attach_boot_iso_if_needed',
                       autospec=True)
    def test__set_power_state_snmp_exception(self,
                                             attach_boot_iso_if_needed_mock,
                                             get_irmc_client_mock,
                                             _wait_power_state_mock):
        target_state = states.SOFT_REBOOT
        _wait_power_state_mock.side_effect = exception.SNMPFailure(
            "fake exception")

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_power._set_power_state,
                              task,
                              target_state)
            attach_boot_iso_if_needed_mock.assert_called_once_with(
                task)
            get_irmc_client_mock.return_value.assert_called_once_with(
                irmc_power.STATES_MAP[target_state])
            _wait_power_state_mock.assert_called_once_with(
                task, states.SOFT_POWER_OFF, timeout=None)


class IRMCPowerTestCase(test_common.BaseIRMCTest):

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in irmc_common.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_default(self, mock_drvinfo, redfish_parsedr_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)
            redfish_parsedr_mock.assert_not_called()

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_ipmi(self, mock_drvinfo, redfish_parsedr_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)
            redfish_parsedr_mock.assert_not_called()

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail_ipmi(self, mock_drvinfo, redfish_parsedr_mock):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        mock_drvinfo.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)
            redfish_parsedr_mock.assert_not_called()

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_redfish(self, mock_drvinfo, redfish_parsedr_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)
            redfish_parsedr_mock.assert_called_once_with(task.node)

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail_redfish(self, mock_drvinfo, redfish_parsedr_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        side_effect = exception.InvalidParameterValue("Invalid Input")
        redfish_parsedr_mock.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(redfish_power.RedfishPower, 'get_power_state',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.power.ipmitool.IPMIPower',
                spec_set=True, autospec=True)
    def test_get_power_state_default(self, mock_IPMIPower, redfish_getpw_mock):
        ipmi_power = mock_IPMIPower.return_value
        ipmi_power.get_power_state.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            ipmi_power.get_power_state.assert_called_once_with(task)
            redfish_getpw_mock.assert_not_called()

    @mock.patch.object(redfish_power.RedfishPower, 'get_power_state',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.power.ipmitool.IPMIPower',
                spec_set=True, autospec=True)
    def test_get_power_state_ipmi(self, mock_IPMIPower, redfish_getpw_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        ipmi_power = mock_IPMIPower.return_value
        ipmi_power.get_power_state.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            ipmi_power.get_power_state.assert_called_once_with(task)
            redfish_getpw_mock.assert_not_called()

    @mock.patch.object(redfish_power.RedfishPower, 'get_power_state',
                       autospec=True)
    @mock.patch('ironic.drivers.modules.irmc.power.ipmitool.IPMIPower',
                spec_set=True, autospec=True)
    def test_get_power_state_redfish(self, mock_IPMIPower, redfish_getpw_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        ipmipw_instance = mock_IPMIPower()
        ipmipw_instance.get_power_state.side_effect = exception.IPMIFailure
        redfish_getpw_mock.return_value = states.POWER_ON
        irmc_power_inst = irmc_power.IRMCPower()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             irmc_power_inst.get_power_state(task))
            ipmipw_instance.get_power_state.assert_called()
            redfish_getpw_mock.assert_called_once_with(irmc_power_inst, task)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test_set_power_state(self, mock_set_power):
        mock_set_power.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
        mock_set_power.assert_called_once_with(task, states.POWER_ON,
                                               timeout=None)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test_set_power_state_timeout(self, mock_set_power):
        mock_set_power.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON,
                                              timeout=2)
        mock_set_power.assert_called_once_with(task, states.POWER_ON,
                                               timeout=2)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_reboot_reboot(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_ON
            task.driver.power.reboot(task)
            mock_get_power.assert_called_once_with(
                task.driver.power, task)
        mock_set_power.assert_called_once_with(task, states.REBOOT,
                                               timeout=None)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_reboot_reboot_timeout(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_ON
            task.driver.power.reboot(task, timeout=2)
            mock_get_power.assert_called_once_with(
                task.driver.power, task)
        mock_set_power.assert_called_once_with(task, states.REBOOT,
                                               timeout=2)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_reboot_power_on(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_OFF
            task.driver.power.reboot(task)
            mock_get_power.assert_called_once_with(
                task.driver.power, task)
        mock_set_power.assert_called_once_with(task, states.POWER_ON,
                                               timeout=None)

    @mock.patch.object(irmc_power, '_set_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_power.IRMCPower, 'get_power_state', spec_set=True,
                       autospec=True)
    def test_reboot_power_on_timeout(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_OFF
            task.driver.power.reboot(task, timeout=2)
            mock_get_power.assert_called_once_with(
                task.driver.power, task)
        mock_set_power.assert_called_once_with(task, states.POWER_ON,
                                               timeout=2)
