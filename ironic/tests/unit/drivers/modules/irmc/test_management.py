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
Test class for iRMC Management Driver
"""

import os
from unittest import mock
import xml.etree.ElementTree as ET

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import ipmitool
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules.irmc import management as irmc_management
from ironic.drivers.modules.irmc import power as irmc_power
from ironic.drivers.modules.redfish import management as redfish_management
from ironic.drivers.modules.redfish import utils as redfish_util
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.drivers.modules.irmc import test_common
from ironic.tests.unit.drivers import third_party_driver_mock_specs \
    as mock_specs


@mock.patch.object(irmc_management.irmc, 'elcm',
                   spec_set=mock_specs.SCCICLIENT_IRMC_ELCM_SPEC)
@mock.patch.object(manager_utils, 'node_power_action',
                   specset=True, autospec=True)
@mock.patch.object(irmc_power.IRMCPower, 'get_power_state',
                   return_value=states.POWER_ON,
                   specset=True, autospec=True)
class IRMCManagementFunctionsTestCase(test_common.BaseIRMCTest):
    def setUp(self):
        super(IRMCManagementFunctionsTestCase, self).setUp()
        self.info = irmc_common.parse_driver_info(self.node)

        irmc_management.irmc.scci.SCCIError = Exception
        irmc_management.irmc.scci.SCCIInvalidInputError = ValueError

    def test_backup_bios_config(self, mock_get_power, mock_power_action,
                                mock_elcm):
        self.config(clean_priority_restore_irmc_bios_config=10, group='irmc')
        bios_config = {'Server': {'System': {'BiosConfig': {'key1': 'val1'}}}}
        mock_elcm.backup_bios_config.return_value = {
            'bios_config': bios_config}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            irmc_management.backup_bios_config(task)

            self.assertEqual(bios_config, task.node.driver_internal_info[
                'irmc_bios_config'])
            self.assertEqual(1, mock_elcm.backup_bios_config.call_count)

    def test_backup_bios_config_skipped(self, mock_get_power,
                                        mock_power_action, mock_elcm):
        self.config(clean_priority_restore_irmc_bios_config=0, group='irmc')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            irmc_management.backup_bios_config(task)

            self.assertNotIn('irmc_bios_config',
                             task.node.driver_internal_info)
            self.assertFalse(mock_elcm.backup_bios_config.called)

    def test_backup_bios_config_failed(self, mock_get_power,
                                       mock_power_action, mock_elcm):
        self.config(clean_priority_restore_irmc_bios_config=10, group='irmc')
        mock_elcm.backup_bios_config.side_effect = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_management.backup_bios_config,
                              task)
            self.assertNotIn('irmc_bios_config',
                             task.node.driver_internal_info)
            self.assertEqual(1, mock_elcm.backup_bios_config.call_count)

    def test__restore_bios_config(self, mock_get_power, mock_power_action,
                                  mock_elcm):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set bios data for the node info
            task.node.driver_internal_info['irmc_bios_config'] = 'data'
            irmc_management._restore_bios_config(task)

            self.assertEqual(1, mock_elcm.restore_bios_config.call_count)

    def test__restore_bios_config_failed(self, mock_get_power,
                                         mock_power_action,
                                         mock_elcm):
        mock_elcm.restore_bios_config.side_effect = Exception

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set bios data for the node info
            task.node.driver_internal_info['irmc_bios_config'] = 'data'

            self.assertRaises(exception.IRMCOperationError,
                              irmc_management._restore_bios_config,
                              task)
            # Backed up BIOS config is still in the node object
            self.assertEqual('data', task.node.driver_internal_info[
                'irmc_bios_config'])
            self.assertTrue(mock_elcm.restore_bios_config.called)

    def test__restore_bios_config_corrupted(self, mock_get_power,
                                            mock_power_action,
                                            mock_elcm):
        mock_elcm.restore_bios_config.side_effect = \
            irmc_management.irmc.scci.SCCIInvalidInputError

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # Set bios data for the node info
            task.node.driver_internal_info['irmc_bios_config'] = 'data'

            self.assertRaises(exception.IRMCOperationError,
                              irmc_management._restore_bios_config,
                              task)
            # Backed up BIOS config is removed from the node object
            self.assertNotIn('irmc_bios_config',
                             task.node.driver_internal_info)
            self.assertTrue(mock_elcm.restore_bios_config.called)


class IRMCManagementTestCase(test_common.BaseIRMCTest):
    def setUp(self):
        super(IRMCManagementTestCase, self).setUp()
        self.info = irmc_common.parse_driver_info(self.node)

    def test_get_properties(self):
        expected = irmc_common.COMMON_PROPERTIES
        expected.update(ipmitool.COMMON_PROPERTIES)
        expected.update(ipmitool.CONSOLE_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            # Remove the boot and deploy interfaces properties
            task.driver.boot = fake.FakeBoot()
            task.driver.deploy = fake.FakeDeploy()
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_ipmi_success(self, mock_drvinfo, redfish_parsedr_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.management.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)
            redfish_parsedr_mock.assert_not_called()

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_ipmi_fail(self, mock_drvinfo, redfish_parsedr_mock):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        mock_drvinfo.side_effect = side_effect
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate,
                              task)
            mock_drvinfo.assert_called_once_with(task.node)
            redfish_parsedr_mock.assert_not_called()

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_redfish_success(
            self, mock_drvinfo, redfish_parsedr_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.management.validate(task)
            redfish_parsedr_mock.assert_called_once_with(task.node)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(redfish_util, 'parse_driver_info', autospec=True)
    @mock.patch.object(irmc_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_redfish_fail(self, mock_drvinfo, redfish_parsedr_mock):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        redfish_parsedr_mock.side_effect = side_effect
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_drvinfo.assert_not_called()
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate,
                              task)
            redfish_parsedr_mock.assert_called_once_with(task.node)

    def test_management_interface_get_supported_boot_devices_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM, boot_devices.BIOS,
                        boot_devices.SAFE]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices(task)))

    def test_management_interface_get_supported_boot_devices_redfish(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = list(redfish_management.BOOT_DEVICE_MAP_REV)
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices(task)))

    @mock.patch.object(irmc_management.ipmitool, "send_raw", spec_set=True,
                       autospec=True)
    def _test_management_interface_set_boot_device_ok(
            self, boot_mode, params, expected_raw_code, send_raw_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        send_raw_mock.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = ''
            if boot_mode:
                driver_utils.add_node_capability(task, 'boot_mode', boot_mode)
            irmc_management.IRMCManagement().set_boot_device(task, **params)
            send_raw_mock.assert_has_calls([
                mock.call(task, "0x00 0x08 0x03 0x08"),
                mock.call(task, expected_raw_code)])

    def test_management_interface_set_boot_device_ok_pxe_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        params = {'device': boot_devices.PXE, 'persistent': False}
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xa0 0x04 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0x80 0x04 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xa0 0x04 0x00 0x00 0x00")

        params['persistent'] = True
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xe0 0x04 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0xc0 0x04 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xe0 0x04 0x00 0x00 0x00")

    def test_management_interface_set_boot_device_ok_disk_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        params = {'device': boot_devices.DISK, 'persistent': False}
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xa0 0x08 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0x80 0x08 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xa0 0x08 0x00 0x00 0x00")

        params['persistent'] = True
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xe0 0x08 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0xc0 0x08 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xe0 0x08 0x00 0x00 0x00")

    def test_management_interface_set_boot_device_ok_cdrom_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        params = {'device': boot_devices.CDROM, 'persistent': False}
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xa0 0x20 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0x80 0x20 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xa0 0x20 0x00 0x00 0x00")

        params['persistent'] = True
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xe0 0x20 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0xc0 0x20 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xe0 0x20 0x00 0x00 0x00")

    def test_management_interface_set_boot_device_ok_bios_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        params = {'device': boot_devices.BIOS, 'persistent': False}
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xa0 0x18 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0x80 0x18 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xa0 0x18 0x00 0x00 0x00")

        params['persistent'] = True
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xe0 0x18 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0xc0 0x18 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xe0 0x18 0x00 0x00 0x00")

    def test_management_interface_set_boot_device_ok_safe_ipmi(self):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        params = {'device': boot_devices.SAFE, 'persistent': False}
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xa0 0x0c 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0x80 0x0c 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xa0 0x0c 0x00 0x00 0x00")

        params['persistent'] = True
        self._test_management_interface_set_boot_device_ok(
            None,
            params,
            "0x00 0x08 0x05 0xe0 0x0c 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'bios',
            params,
            "0x00 0x08 0x05 0xc0 0x0c 0x00 0x00 0x00")
        self._test_management_interface_set_boot_device_ok(
            'uefi',
            params,
            "0x00 0x08 0x05 0xe0 0x0c 0x00 0x00 0x00")

    @mock.patch.object(irmc_management.ipmitool, "send_raw", spec_set=True,
                       autospec=True)
    def test_management_interface_set_boot_device_ng_ipmi(self, send_raw_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()

        """uefi mode, next boot only, unknown device."""
        send_raw_mock.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_utils.add_node_capability(task, 'boot_mode', 'uefi')
            self.assertRaises(exception.InvalidParameterValue,
                              irmc_management.IRMCManagement().set_boot_device,
                              task,
                              "unknown")

    @mock.patch.object(irmc_management.ipmitool, 'send_raw', autospec=True)
    @mock.patch.object(redfish_management.RedfishManagement, 'set_boot_device',
                       autospec=True)
    def test_management_interfase_set_boot_device_success_redfish(
            self, redfish_set_boot_dev_mock, ipmi_raw_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        ipmi_raw_mock.side_effect = exception.IPMIFailure
        management_inst = irmc_management.IRMCManagement()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            params = ['pxe', True]
            management_inst.set_boot_device(task, *params)
            redfish_set_boot_dev_mock.assert_called_once_with(
                management_inst, task, *params)

    @mock.patch.object(redfish_management.RedfishManagement, 'set_boot_device',
                       autospec=True)
    def test_management_interfase_set_boot_device_fail_redfish(
            self, redfish_set_boot_dev_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        management_inst = irmc_management.IRMCManagement()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            params = [task, 'safe', True]
            self.assertRaises(exception.InvalidParameterValue,
                              management_inst.set_boot_device, *params)
            redfish_set_boot_dev_mock.assert_not_called()

    @mock.patch.object(irmc_management.irmc, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test_management_interface_get_sensors_data_scci_ok_ipmi(
            self, mock_get_irmc_report, mock_scci):
        """'irmc_sensor_method' = 'scci' specified and OK data."""
        with open(os.path.join(os.path.dirname(__file__),
                               'fake_sensors_data_ok.xml'), "r") as report:
            fake_txt = report.read()
        fake_xml = ET.fromstring(fake_txt)

        mock_get_irmc_report.return_value = fake_xml
        mock_scci.get_sensor_data.return_value = fake_xml.find(
            "./System/SensorDataRecords")

        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'scci'
            sensor_dict = irmc_management.IRMCManagement().get_sensors_data(
                task)

        expected = {
            'Fan (4)': {
                'FAN1 SYS (29)': {
                    'Units': 'RPM',
                    'Sensor ID': 'FAN1 SYS (29)',
                    'Sensor Reading': '600 RPM'
                },
                'FAN2 SYS (29)': {
                    'Units': 'None',
                    'Sensor ID': 'FAN2 SYS (29)',
                    'Sensor Reading': 'None None'
                }
            },
            'Temperature (1)': {
                'Systemboard 1 (7)': {
                    'Units': 'degree C',
                    'Sensor ID': 'Systemboard 1 (7)',
                    'Sensor Reading': '80 degree C'
                },
                'Ambient (55)': {
                    'Units': 'degree C',
                    'Sensor ID': 'Ambient (55)',
                    'Sensor Reading': '42 degree C'
                }
            }
        }
        self.assertEqual(expected, sensor_dict)

    @mock.patch.object(irmc_management.irmc, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test_management_interface_get_sensors_data_scci_ok_redfish(
            self, mock_get_irmc_report, mock_scci):
        """'irmc_sensor_method' = 'scci' specified and OK data."""
        with open(os.path.join(os.path.dirname(__file__),
                               'fake_sensors_data_ok.xml'), "r") as report:
            fake_txt = report.read()
        fake_xml = ET.fromstring(fake_txt)

        mock_get_irmc_report.return_value = fake_xml
        mock_scci.get_sensor_data.return_value = fake_xml.find(
            "./System/SensorDataRecords")

        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'scci'
            sensor_dict = irmc_management.IRMCManagement().get_sensors_data(
                task)

        expected = {
            'Fan (4)': {
                'FAN1 SYS (29)': {
                    'Units': 'RPM',
                    'Sensor ID': 'FAN1 SYS (29)',
                    'Sensor Reading': '600 RPM'
                },
                'FAN2 SYS (29)': {
                    'Units': 'None',
                    'Sensor ID': 'FAN2 SYS (29)',
                    'Sensor Reading': 'None None'
                }
            },
            'Temperature (1)': {
                'Systemboard 1 (7)': {
                    'Units': 'degree C',
                    'Sensor ID': 'Systemboard 1 (7)',
                    'Sensor Reading': '80 degree C'
                },
                'Ambient (55)': {
                    'Units': 'degree C',
                    'Sensor ID': 'Ambient (55)',
                    'Sensor Reading': '42 degree C'
                }
            }
        }
        self.assertEqual(expected, sensor_dict)

    @mock.patch.object(irmc_management.irmc, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test_management_interface_get_sensors_data_scci_ng_ipmi(
            self, mock_get_irmc_report, mock_scci):
        """'irmc_sensor_method' = 'scci' specified and NG data."""
        with open(os.path.join(os.path.dirname(__file__),
                               'fake_sensors_data_ng.xml'), "r") as report:
            fake_txt = report.read()
        fake_xml = ET.fromstring(fake_txt)

        mock_get_irmc_report.return_value = fake_xml
        mock_scci.get_sensor_data.return_value = fake_xml.find(
            "./System/SensorDataRecords")

        self.node.set_driver_internal_info('irmc_fw_version', 'iRMC S5/2.00S')
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'scci'
            sensor_dict = irmc_management.IRMCManagement().get_sensors_data(
                task)

        self.assertEqual(len(sensor_dict), 0)

    @mock.patch.object(irmc_management.irmc, 'scci',
                       spec_set=mock_specs.SCCICLIENT_IRMC_SCCI_SPEC)
    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test_management_interface_get_sensors_data_scci_ng_redfish(
            self, mock_get_irmc_report, mock_scci):
        """'irmc_sensor_method' = 'scci' specified and NG data."""
        with open(os.path.join(os.path.dirname(__file__),
                               'fake_sensors_data_ng.xml'), "r") as report:
            fake_txt = report.read()
        fake_xml = ET.fromstring(fake_txt)

        mock_get_irmc_report.return_value = fake_xml
        mock_scci.get_sensor_data.return_value = fake_xml.find(
            "./System/SensorDataRecords")

        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'scci'
            sensor_dict = irmc_management.IRMCManagement().get_sensors_data(
                task)

        self.assertEqual(len(sensor_dict), 0)

    @mock.patch.object(ipmitool.IPMIManagement, 'get_sensors_data',
                       spec_set=True, autospec=True)
    def test_management_interface_get_sensors_data_ipmitool_ok_ipmi(
            self,
            get_sensors_data_mock):
        """'irmc_sensor_method' = 'ipmitool' specified."""
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'ipmitool'
            task.driver.management.get_sensors_data(task)
            get_sensors_data_mock.assert_called_once_with(
                task.driver.management, task)

    @mock.patch.object(ipmitool.IPMIManagement, 'get_sensors_data',
                       spec_set=True, autospec=True)
    def test_management_interface_get_sensors_data_ipmitool_ng_redfish(
            self,
            get_sensors_data_mock):
        """'irmc_sensor_method' = 'ipmitool' specified."""
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'ipmitool'
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.get_sensors_data, task)

    @mock.patch.object(irmc_common, 'get_irmc_report', spec_set=True,
                       autospec=True)
    def test_management_interface_get_sensors_data_exception(
            self,
            get_irmc_report_mock):
        """'FailedToGetSensorData Exception."""

        get_irmc_report_mock.side_effect = exception.InvalidParameterValue(
            "Fake Error")
        irmc_management.irmc.scci.SCCIInvalidInputError = Exception
        irmc_management.irmc.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['irmc_sensor_method'] = 'scci'
            e = self.assertRaises(
                exception.FailedToGetSensorData,
                irmc_management.IRMCManagement().get_sensors_data, task)
        self.assertEqual("Failed to get sensor data for node %s. "
                         "Error: Fake Error" % self.node.uuid, str(e))

    @mock.patch.object(redfish_management.RedfishManagement, 'detect_vendor',
                       spec_set=True, autospec=True)
    @mock.patch.object(ipmitool.IPMIManagement, 'detect_vendor',
                       spec_set=True, autospec=True)
    def test_management_interface_detect_vendor_ipmi(self,
                                                     ipmimgmt_detectv_mock,
                                                     redfishmgmt_detectv_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', True)
        self.node.save()
        irmc_mgmt_inst = irmc_management.IRMCManagement()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mgmt_inst.detect_vendor(task)
            ipmimgmt_detectv_mock.assert_called_once_with(irmc_mgmt_inst, task)
            redfishmgmt_detectv_mock.assert_not_called()

    @mock.patch.object(redfish_management.RedfishManagement, 'detect_vendor',
                       spec_set=True, autospec=True)
    @mock.patch.object(ipmitool.IPMIManagement, 'detect_vendor',
                       spec_set=True, autospec=True)
    def test_management_interface_detect_vendor_redfish(
            self, ipmimgmt_detectv_mock, redfishmgmt_detectv_mock):
        self.node.set_driver_internal_info('irmc_ipmi_succeed', False)
        self.node.save()
        ipmimgmt_detectv_mock.side_effect = exception.IPMIFailure
        irmc_mgmt_inst = irmc_management.IRMCManagement()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mgmt_inst.detect_vendor(task)
            redfishmgmt_detectv_mock.assert_called_once_with(
                irmc_mgmt_inst, task)

    @mock.patch.object(irmc_management.LOG, 'error', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    def test_management_interface_inject_nmi_ok(self, mock_get_irmc_client,
                                                mock_log):
        irmc_client = mock_get_irmc_client.return_value
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_management.IRMCManagement().inject_nmi(task)

            irmc_client.assert_called_once_with(
                irmc_management.irmc.scci.POWER_RAISE_NMI)
            self.assertFalse(mock_log.called)

    @mock.patch.object(irmc_management.LOG, 'error', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_common, 'get_irmc_client', spec_set=True,
                       autospec=True)
    def test_management_interface_inject_nmi_fail(self, mock_get_irmc_client,
                                                  mock_log):
        irmc_client = mock_get_irmc_client.return_value
        irmc_client.side_effect = Exception()
        irmc_management.irmc.scci.SCCIClientError = Exception

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IRMCOperationError,
                              irmc_management.IRMCManagement().inject_nmi,
                              task)

            irmc_client.assert_called_once_with(
                irmc_management.irmc.scci.POWER_RAISE_NMI)
            self.assertTrue(mock_log.called)

    @mock.patch.object(irmc_management, '_restore_bios_config',
                       spec_set=True, autospec=True)
    def test_management_interface_restore_irmc_bios_config(self,
                                                           mock_restore_bios):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.management.restore_irmc_bios_config(task)
            self.assertIsNone(result)
            mock_restore_bios.assert_called_once_with(task)

    @mock.patch.object(irmc_common, 'set_irmc_version', autospec=True)
    @mock.patch.object(irmc_common, 'check_elcm_license', autospec=True)
    def test_verify_http_s_connection_and_fw_ver_success(self,
                                                         check_elcm_mock,
                                                         set_irmc_ver_mock):
        check_elcm_mock.return_value = {'active': True,
                                        'status_code': 200}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mng = irmc_management.IRMCManagement()
            irmc_mng.verify_http_https_connection_and_fw_version(task)
            check_elcm_mock.assert_called_with(task.node)
            set_irmc_ver_mock.assert_called_with(task)

    @mock.patch.object(irmc_common, 'set_irmc_version', autospec=True)
    @mock.patch.object(irmc_common, 'check_elcm_license', autospec=True)
    def test_verify_http_s_connection_and_fw_ver_raise_http_success(
            self, check_elcm_mock, set_irmc_ver_mock):
        error_msg_http = ('iRMC establishing connection to REST API '
                          'failed. Reason: '
                          'Access to REST API returns unexpected '
                          'status code. Check driver_info parameter '
                          'or version of iRMC because iRMC does not '
                          'support HTTP connection to iRMC REST API '
                          'since iRMC S6 2.00.')

        check_elcm_mock.return_value = {'active': False,
                                        'status_code': 404}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mng = irmc_management.IRMCManagement()

            task.node.driver_info['irmc_port'] = 80
            self.assertRaisesRegex(
                exception.IRMCOperationError,
                error_msg_http,
                irmc_mng.verify_http_https_connection_and_fw_version,
                task)
            check_elcm_mock.assert_called_with(task.node)
            set_irmc_ver_mock.assert_not_called()

    @mock.patch.object(irmc_common, 'set_irmc_version', autospec=True)
    @mock.patch.object(irmc_common, 'check_elcm_license', autospec=True)
    def test_verify_http_s_connection_and_fw_ver_raise_https_success(
            self, check_elcm_mock, set_irmc_ver_mock):
        error_msg_https = ('iRMC establishing connection to REST API '
                           'failed. Reason: '
                           'Access to REST API returns unexpected '
                           'status code. Check driver_info parameter '
                           'related to iRMC driver')

        check_elcm_mock.return_value = {'active': False,
                                        'status_code': 404}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mng = irmc_management.IRMCManagement()
            task.node.driver_info['irmc_port'] = 443
            self.assertRaisesRegex(
                exception.IRMCOperationError,
                error_msg_https,
                irmc_mng.verify_http_https_connection_and_fw_version,
                task)
            check_elcm_mock.assert_called_with(task.node)
            set_irmc_ver_mock.assert_not_called()

    @mock.patch.object(irmc_common, 'set_irmc_version', autospec=True)
    @mock.patch.object(irmc_common, 'check_elcm_license', autospec=True)
    def test_verify_http_s_connection_and_fw_ver_fail_invalid(
            self, check_elcm_mock, set_irmc_ver_mock):
        check_elcm_mock.side_effect = exception.InvalidParameterValue
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mng = irmc_management.IRMCManagement()
            self.assertRaises(
                exception.IRMCOperationError,
                irmc_mng.verify_http_https_connection_and_fw_version,
                task)
            check_elcm_mock.assert_called_with(task.node)

    @mock.patch.object(irmc_common, 'set_irmc_version', autospec=True)
    @mock.patch.object(irmc_common, 'check_elcm_license', autospec=True)
    def test_verify_http_s_connection_and_fw_ver_fail_missing(
            self, check_elcm_mock, set_irmc_ver_mock):
        check_elcm_mock.side_effect = exception.MissingParameterValue
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_mng = irmc_management.IRMCManagement()
            self.assertRaises(
                exception.IRMCOperationError,
                irmc_mng.verify_http_https_connection_and_fw_version,
                task)
            check_elcm_mock.assert_called_with(task.node)
