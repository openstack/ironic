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

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import components
from ironic.common import exception
from ironic.common import indicator_states
from ironic.conductor import task_manager
from ironic.drivers.modules.redfish import management as redfish_mgmt
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


class RedfishManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishManagementTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

        self.system_uuid = 'ZZZ--XXX-YYY'
        self.chassis_uuid = 'XXX-YYY-ZZZ'
        self.drive_uuid = 'ZZZ-YYY-XXX'

    @mock.patch.object(redfish_mgmt, 'sushy', None)
    def test_loading_error(self):
        self.assertRaisesRegex(
            exception.DriverLoadError,
            'Unable to import the sushy library',
            redfish_mgmt.RedfishManagement)

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
            task.driver.management.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    def test_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_boot_devices = (
                task.driver.management.get_supported_boot_devices(task))
            self.assertEqual(list(redfish_mgmt.BOOT_DEVICE_MAP_REV),
                             supported_boot_devices)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_boot_device(self, mock_get_system):
        fake_system = mock.Mock()
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (boot_devices.PXE, sushy.BOOT_SOURCE_TARGET_PXE),
                (boot_devices.DISK, sushy.BOOT_SOURCE_TARGET_HDD),
                (boot_devices.CDROM, sushy.BOOT_SOURCE_TARGET_CD),
                (boot_devices.BIOS, sushy.BOOT_SOURCE_TARGET_BIOS_SETUP)
            ]

            for target, expected in expected_values:
                task.driver.management.set_boot_device(task, target)

                # Asserts
                fake_system.set_system_boot_source.assert_called_once_with(
                    expected, enabled=sushy.BOOT_SOURCE_ENABLED_ONCE)
                mock_get_system.assert_called_once_with(task.node)

                # Reset mocks
                fake_system.set_system_boot_source.reset_mock()
                mock_get_system.reset_mock()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_boot_device_persistency(self, mock_get_system):
        fake_system = mock.Mock()
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (True, sushy.BOOT_SOURCE_ENABLED_CONTINUOUS),
                (False, sushy.BOOT_SOURCE_ENABLED_ONCE)
            ]

            for target, expected in expected_values:
                task.driver.management.set_boot_device(
                    task, boot_devices.PXE, persistent=target)

                fake_system.set_system_boot_source.assert_called_once_with(
                    sushy.BOOT_SOURCE_TARGET_PXE, enabled=expected)
                mock_get_system.assert_called_once_with(task.node)

                # Reset mocks
                fake_system.set_system_boot_source.reset_mock()
                mock_get_system.reset_mock()

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_boot_device_fail(self, mock_get_system, mock_sushy):
        fake_system = mock.Mock()
        fake_system.set_system_boot_source.side_effect = (
            sushy.exceptions.SushyError()
        )
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.RedfishError, 'Redfish set boot device',
                task.driver.management.set_boot_device, task, boot_devices.PXE)
            fake_system.set_system_boot_source.assert_called_once_with(
                sushy.BOOT_SOURCE_TARGET_PXE,
                enabled=sushy.BOOT_SOURCE_ENABLED_ONCE)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_boot_device(self, mock_get_system):
        boot_attribute = {
            'target': sushy.BOOT_SOURCE_TARGET_PXE,
            'enabled': sushy.BOOT_SOURCE_ENABLED_CONTINUOUS
        }
        fake_system = mock.Mock(boot=boot_attribute)
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            response = task.driver.management.get_boot_device(task)
            expected = {'boot_device': boot_devices.PXE,
                        'persistent': True}
            self.assertEqual(expected, response)

    def test_get_supported_boot_modes(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_boot_modes = (
                task.driver.management.get_supported_boot_modes(task))
            self.assertEqual(list(redfish_mgmt.BOOT_MODE_MAP_REV),
                             supported_boot_modes)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_boot_mode(self, mock_get_system):
        fake_system = mock.Mock()
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (boot_modes.LEGACY_BIOS, sushy.BOOT_SOURCE_MODE_BIOS),
                (boot_modes.UEFI, sushy.BOOT_SOURCE_MODE_UEFI)
            ]

            for mode, expected in expected_values:
                task.driver.management.set_boot_mode(task, mode=mode)

                # Asserts
                fake_system.set_system_boot_source.assert_called_once_with(
                    mock.ANY, enabled=mock.ANY, mode=mode)
                mock_get_system.assert_called_once_with(task.node)

                # Reset mocks
                fake_system.set_system_boot_source.reset_mock()
                mock_get_system.reset_mock()

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_boot_mode_fail(self, mock_get_system, mock_sushy):
        fake_system = mock.Mock()
        fake_system.set_system_boot_source.side_effect = (
            sushy.exceptions.SushyError)
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.RedfishError, 'Setting boot mode',
                task.driver.management.set_boot_mode, task, boot_modes.UEFI)
            fake_system.set_system_boot_source.assert_called_once_with(
                mock.ANY, enabled=mock.ANY, mode=boot_modes.UEFI)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_boot_mode(self, mock_get_system):
        boot_attribute = {
            'target': sushy.BOOT_SOURCE_TARGET_PXE,
            'enabled': sushy.BOOT_SOURCE_ENABLED_CONTINUOUS,
            'mode': sushy.BOOT_SOURCE_MODE_BIOS,
        }
        fake_system = mock.Mock(boot=boot_attribute)
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            response = task.driver.management.get_boot_mode(task)
            expected = boot_modes.LEGACY_BIOS
            self.assertEqual(expected, response)

    def test__get_sensors_fan(self):
        attributes = {
            "identity": "XXX-YYY-ZZZ",
            "name": "CPU Fan",
            "status": {
                "state": "enabled",
                "health": "OK"
            },
            "reading": 6000,
            "reading_units": "RPM",
            "lower_threshold_fatal": 2000,
            "min_reading_range": 0,
            "max_reading_range": 10000,
            "serial_number": "SN010203040506",
            "physical_context": "CPU"
        }

        mock_chassis = mock.MagicMock(identity='ZZZ-YYY-XXX')

        mock_fan = mock.MagicMock(**attributes)
        mock_fan.name = attributes['name']
        mock_fan.status = mock.MagicMock(**attributes['status'])
        mock_chassis.thermal.fans = [mock_fan]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            sensors = task.driver.management._get_sensors_fan(mock_chassis)

        expected = {
            'XXX-YYY-ZZZ@ZZZ-YYY-XXX': {
                'identity': 'XXX-YYY-ZZZ',
                'max_reading_range': 10000,
                'min_reading_range': 0,
                'physical_context': 'CPU',
                'reading': 6000,
                'reading_units': 'RPM',
                'serial_number': 'SN010203040506',
                'health': 'OK',
                'state': 'enabled'
            }
        }

        self.assertEqual(expected, sensors)

    def test__get_sensors_temperatures(self):
        attributes = {
            "identity": "XXX-YYY-ZZZ",
            "name": "CPU Temp",
            "status": {
                "state": "enabled",
                "health": "OK"
            },
            "reading_celsius": 62,
            "upper_threshold_non_critical": 75,
            "upper_threshold_critical": 90,
            "upperThresholdFatal": 95,
            "min_reading_range_temp": 0,
            "max_reading_range_temp": 120,
            "physical_context": "CPU",
            "sensor_number": 1
        }

        mock_chassis = mock.MagicMock(identity='ZZZ-YYY-XXX')

        mock_temperature = mock.MagicMock(**attributes)
        mock_temperature.name = attributes['name']
        mock_temperature.status = mock.MagicMock(**attributes['status'])
        mock_chassis.thermal.temperatures = [mock_temperature]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            sensors = task.driver.management._get_sensors_temperatures(
                mock_chassis)

        expected = {
            'XXX-YYY-ZZZ@ZZZ-YYY-XXX': {
                'identity': 'XXX-YYY-ZZZ',
                'max_reading_range_temp': 120,
                'min_reading_range_temp': 0,
                'physical_context': 'CPU',
                'reading_celsius': 62,
                'sensor_number': 1,
                'health': 'OK',
                'state': 'enabled'
            }
        }

        self.assertEqual(expected, sensors)

    def test__get_sensors_power(self):
        attributes = {
            'identity': 0,
            'name': 'Power Supply 0',
            'power_capacity_watts': 1450,
            'last_power_output_watts': 650,
            'line_input_voltage': 220,
            'input_ranges': {
                'minimum_voltage': 185,
                'maximum_voltage': 250,
                'minimum_frequency_hz': 47,
                'maximum_frequency_hz': 63,
                'output_wattage': 1450
            },
            'serial_number': 'SN010203040506',
            "status": {
                "state": "enabled",
                "health": "OK"
            }
        }

        mock_chassis = mock.MagicMock(identity='ZZZ-YYY-XXX')
        mock_power = mock_chassis.power
        mock_power.identity = 'Power'
        mock_psu = mock.MagicMock(**attributes)
        mock_psu.name = attributes['name']
        mock_psu.status = mock.MagicMock(**attributes['status'])
        mock_psu.input_ranges = mock.MagicMock(**attributes['input_ranges'])
        mock_power.power_supplies = [mock_psu]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            sensors = task.driver.management._get_sensors_power(mock_chassis)

        expected = {
            '0:Power@ZZZ-YYY-XXX': {
                'health': 'OK',
                'last_power_output_watts': 650,
                'line_input_voltage': 220,
                'maximum_frequency_hz': 63,
                'maximum_voltage': 250,
                'minimum_frequency_hz': 47,
                'minimum_voltage': 185,
                'output_wattage': 1450,
                'power_capacity_watts': 1450,
                'serial_number': 'SN010203040506',
                'state': 'enabled'
            }
        }

        self.assertEqual(expected, sensors)

    def test__get_sensors_data_drive(self):
        attributes = {
            'name': '32ADF365C6C1B7BD',
            'manufacturer': 'IBM',
            'model': 'IBM 350A',
            'capacity_bytes': 3750000000,
            'status': {
                'health': 'OK',
                'state': 'enabled'
            }
        }

        mock_system = mock.MagicMock(identity='ZZZ-YYY-XXX')
        mock_drive = mock.MagicMock(**attributes)
        mock_drive.name = attributes['name']
        mock_drive.status = mock.MagicMock(**attributes['status'])
        mock_storage = mock.MagicMock()
        mock_storage.devices = [mock_drive]
        mock_storage.identity = 'XXX-YYY-ZZZ'
        mock_system.simple_storage.get_members.return_value = [mock_storage]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            sensors = task.driver.management._get_sensors_drive(mock_system)

        expected = {
            '32ADF365C6C1B7BD:XXX-YYY-ZZZ@ZZZ-YYY-XXX': {
                'capacity_bytes': 3750000000,
                'health': 'OK',
                'name': '32ADF365C6C1B7BD',
                'model': 'IBM 350A',
                'state': 'enabled'
            }
        }

        self.assertEqual(expected, sensors)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_sensors_data(self, mock_system):
        mock_chassis = mock.MagicMock()
        mock_system.return_value.chassis = [mock_chassis]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            sensors = task.driver.management.get_sensors_data(task)

        expected = {
            'Fan': {},
            'Temperature': {},
            'Power': {},
            'Drive': {}
        }

        self.assertEqual(expected, sensors)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inject_nmi(self, mock_get_system):
        fake_system = mock.Mock()
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.inject_nmi(task)
            fake_system.reset_system.assert_called_once_with(sushy.RESET_NMI)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inject_nmi_fail(self, mock_get_system, mock_sushy):
        fake_system = mock.Mock()
        fake_system.reset_system.side_effect = (
            sushy.exceptions.SushyError)
        mock_get_system.return_value = fake_system
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.RedfishError, 'Redfish inject NMI',
                task.driver.management.inject_nmi, task)
            fake_system.reset_system.assert_called_once_with(
                sushy.RESET_NMI)
            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_supported_indicators(self, mock_get_system):
        fake_chassis = mock.Mock(
            uuid=self.chassis_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_drive = mock.Mock(
            uuid=self.drive_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_system = mock.Mock(
            uuid=self.system_uuid,
            chassis=[fake_chassis],
            simple_storage=mock.MagicMock(drives=[fake_drive]),
            indicator_led=sushy.INDICATOR_LED_LIT)

        mock_get_system.return_value = fake_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            supported_indicators = (
                task.driver.management.get_supported_indicators(task))

            expected = {
                components.CHASSIS: {
                    'XXX-YYY-ZZZ': {
                        "readonly": False,
                        "states": [
                            indicator_states.BLINKING,
                            indicator_states.OFF,
                            indicator_states.ON
                        ]
                    }
                },
                components.SYSTEM: {
                    'ZZZ--XXX-YYY': {
                        "readonly": False,
                        "states": [
                            indicator_states.BLINKING,
                            indicator_states.OFF,
                            indicator_states.ON
                        ]
                    }
                },
                components.DISK: {
                    'ZZZ-YYY-XXX': {
                        "readonly": False,
                        "states": [
                            indicator_states.BLINKING,
                            indicator_states.OFF,
                            indicator_states.ON
                        ]
                    }
                }
            }

            self.assertEqual(expected, supported_indicators)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_set_indicator_state(self, mock_get_system):
        fake_chassis = mock.Mock(
            uuid=self.chassis_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_drive = mock.Mock(
            uuid=self.drive_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_system = mock.Mock(
            uuid=self.system_uuid,
            chassis=[fake_chassis],
            simple_storage=mock.MagicMock(drives=[fake_drive]),
            indicator_led=sushy.INDICATOR_LED_LIT)

        mock_get_system.return_value = fake_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_indicator_state(
                task, components.SYSTEM, self.system_uuid, indicator_states.ON)

            fake_system.set_indicator_led.assert_called_once_with(
                sushy.INDICATOR_LED_LIT)

            mock_get_system.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_indicator_state(self, mock_get_system):
        fake_chassis = mock.Mock(
            uuid=self.chassis_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_drive = mock.Mock(
            uuid=self.drive_uuid,
            indicator_led=sushy.INDICATOR_LED_LIT)
        fake_system = mock.Mock(
            uuid=self.system_uuid,
            chassis=[fake_chassis],
            simple_storage=mock.MagicMock(drives=[fake_drive]),
            indicator_led=sushy.INDICATOR_LED_LIT)

        mock_get_system.return_value = fake_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            state = task.driver.management.get_indicator_state(
                task, components.SYSTEM, self.system_uuid)

            mock_get_system.assert_called_once_with(task.node)

            self.assertEqual(indicator_states.ON, state)
