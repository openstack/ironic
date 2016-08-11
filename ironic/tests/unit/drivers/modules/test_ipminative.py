# coding=utf-8

# Copyright 2013 International Business Machines Corporation
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

"""
Test class for Native IPMI power driver module.
"""

import mock
from oslo_utils import uuidutils
from pyghmi import exceptions as pyghmi_exception

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import ipminative
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_ipmi_info()


class IPMINativePrivateMethodTestCase(db_base.DbTestCase):
    """Test cases for ipminative private methods."""

    def setUp(self):
        super(IPMINativePrivateMethodTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ipminative',
                                               driver_info=INFO_DICT)
        self.info = ipminative._parse_driver_info(self.node)

    def test__parse_driver_info(self):
        # make sure we get back the expected things
        self.assertEqual('1.2.3.4', self.info['address'])
        self.assertEqual('admin', self.info['username'])
        self.assertEqual('fake', self.info['password'])
        self.assertEqual('1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                         self.info['uuid'])
        self.assertEqual(False, self.info['force_boot_device'])

        # make sure error is raised when info, eg. username, is missing
        info = dict(INFO_DICT)
        del info['ipmi_username']

        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          ipminative._parse_driver_info,
                          node)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__power_status_on(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'on'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_ON, state)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__power_status_off(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'off'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__power_status_error(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'Error'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.ERROR, state)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__power_on(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'on'}

        self.config(retry_timeout=400, group='ipmi')
        state = ipminative._power_on(self.info)
        ipmicmd.set_power.assert_called_once_with('on', 400)
        self.assertEqual(states.POWER_ON, state)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__power_off(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'off'}

        self.config(retry_timeout=500, group='ipmi')
        state = ipminative._power_off(self.info)
        ipmicmd.set_power.assert_called_once_with('off', 500)
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__reboot(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'on'}

        self.config(retry_timeout=600, group='ipmi')
        state = ipminative._reboot(self.info)
        ipmicmd.set_power.assert_called_once_with('boot', 600)
        self.assertEqual(states.POWER_ON, state)

    def _create_sensor_object(self, value, type_, name, states=None,
                              units='fake_units', health=0):
        if states is None:
            states = []
        return type('Reading', (object, ), {
            'value': value, 'type': type_, 'name': name,
            'states': states, 'units': units, 'health': health})()

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__get_sensors_data(self, ipmi_mock):
        reading_1 = self._create_sensor_object('fake_value1',
                                               'fake_type_A',
                                               'fake_name1')
        reading_2 = self._create_sensor_object('fake_value2',
                                               'fake_type_A',
                                               'fake_name2')
        reading_3 = self._create_sensor_object('fake_value3',
                                               'fake_type_B',
                                               'fake_name3')
        readings = [reading_1, reading_2, reading_3]
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_sensor_data.return_value = readings
        expected = {
            'fake_type_A': {
                'fake_name1': {
                    'Health': '0',
                    'Sensor ID': 'fake_name1',
                    'Sensor Reading': 'fake_value1 fake_units',
                    'States': '[]',
                    'Units': 'fake_units'
                },
                'fake_name2': {
                    'Health': '0',
                    'Sensor ID': 'fake_name2',
                    'Sensor Reading': 'fake_value2 fake_units',
                    'States': '[]',
                    'Units': 'fake_units'
                }
            },
            'fake_type_B': {
                'fake_name3': {
                    'Health': '0',
                    'Sensor ID': 'fake_name3',
                    'Sensor Reading': 'fake_value3 fake_units',
                    'States': '[]', 'Units': 'fake_units'
                }
            }
        }
        ret = ipminative._get_sensors_data(self.info)
        self.assertEqual(expected, ret)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__get_sensors_data_missing_values(self, ipmi_mock):
        reading_1 = self._create_sensor_object('fake_value1',
                                               'fake_type_A',
                                               'fake_name1')
        reading_2 = self._create_sensor_object(None,
                                               'fake_type_A',
                                               'fake_name2')
        reading_3 = self._create_sensor_object(None,
                                               'fake_type_B',
                                               'fake_name3')
        readings = [reading_1, reading_2, reading_3]
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_sensor_data.return_value = readings

        expected = {
            'fake_type_A': {
                'fake_name1': {
                    'Health': '0',
                    'Sensor ID': 'fake_name1',
                    'Sensor Reading': 'fake_value1 fake_units',
                    'States': '[]',
                    'Units': 'fake_units'
                }
            }
        }
        ret = ipminative._get_sensors_data(self.info)
        self.assertEqual(expected, ret)

    def test__parse_raw_bytes_ok(self):
        bytes_string = '0x11 0x12 0x25 0xFF'
        netfn, cmd, data = ipminative._parse_raw_bytes(bytes_string)
        self.assertEqual(0x11, netfn)
        self.assertEqual(0x12, cmd)
        self.assertEqual([0x25, 0xFF], data)

    def test__parse_raw_bytes_invalid_value(self):
        bytes_string = '0x11 oops'
        self.assertRaises(exception.InvalidParameterValue,
                          ipminative._parse_raw_bytes,
                          bytes_string)

    def test__parse_raw_bytes_missing_byte(self):
        bytes_string = '0x11'
        self.assertRaises(exception.InvalidParameterValue,
                          ipminative._parse_raw_bytes,
                          bytes_string)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__send_raw(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipminative._send_raw(self.info, '0x01 0x02 0x03 0x04')
        ipmicmd.xraw_command.assert_called_once_with(1, 2, data=[3, 4])

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test__send_raw_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.xraw_command.side_effect = pyghmi_exception.IpmiException()
        self.assertRaises(exception.IPMIFailure, ipminative._send_raw,
                          self.info, '0x01 0x02')


class IPMINativeDriverTestCase(db_base.DbTestCase):
    """Test cases for ipminative.NativeIPMIPower class functions."""

    def setUp(self):
        super(IPMINativeDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_ipminative")
        self.driver = driver_factory.get_driver("fake_ipminative")

        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ipminative',
                                               driver_info=INFO_DICT)
        self.info = ipminative._parse_driver_info(self.node)

    def test_get_properties(self):
        expected = ipminative.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.power.get_properties())
        self.assertEqual(expected, self.driver.management.get_properties())
        self.assertEqual(expected, self.driver.vendor.get_properties())

        expected = list(ipminative.COMMON_PROPERTIES)
        expected += list(ipminative.CONSOLE_PROPERTIES)
        self.assertEqual(sorted(expected),
                         sorted(self.driver.console.get_properties().keys()))
        self.assertEqual(sorted(expected),
                         sorted(self.driver.get_properties().keys()))

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_get_power_state(self, ipmi_mock):
        # Getting the mocked command.
        cmd_mock = ipmi_mock.return_value
        # Getting the get power mock.
        get_power_mock = cmd_mock.get_power

        return_values = [{'powerstate': 'error'},
                         {'powerstate': 'on'},
                         {'powerstate': 'off'}]

        get_power_mock.side_effect = lambda: return_values.pop()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_OFF, pstate)

            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, pstate)

            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.ERROR, pstate)
            self.assertEqual(3, get_power_mock.call_count,
                             "pyghmi.ipmi.command.Command.get_power was not"
                             " called 3 times.")

    @mock.patch.object(ipminative, '_power_on', autospec=True)
    def test_set_power_on_ok(self, power_on_mock):
        power_on_mock.return_value = states.POWER_ON

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(
                task, states.POWER_ON)
        power_on_mock.assert_called_once_with(self.info)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipminative, '_power_on', autospec=True)
    def test_set_power_on_with_next_boot(self, power_on_mock, mock_next_boot):
        power_on_mock.return_value = states.POWER_ON

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(
                task, states.POWER_ON)
            mock_next_boot.assert_called_once_with(task, self.info)
        power_on_mock.assert_called_once_with(self.info)

    @mock.patch.object(ipminative, '_power_off', autospec=True)
    def test_set_power_off_ok(self, power_off_mock):
        power_off_mock.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(
                task, states.POWER_OFF)
        power_off_mock.assert_called_once_with(self.info)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_set_power_on_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'error'}

        self.config(retry_timeout=500, group='ipmi')
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.set_power_state,
                              task,
                              states.POWER_ON)
        ipmicmd.set_power.assert_called_once_with('on', 500)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_set_boot_device_ok(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_bootdev.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=False,
                                                    uefiboot=False)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_force_set_boot_device_ok(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_bootdev.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            self.driver.management.set_boot_device(task, boot_devices.PXE)
            task.node.refresh()
            self.assertEqual(
                False,
                task.node.driver_internal_info['is_next_boot_persistent']
            )
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=False,
                                                    uefiboot=False)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_set_boot_device_with_persistent(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_bootdev.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            self.driver.management.set_boot_device(task,
                                                   boot_devices.PXE,
                                                   True)
            self.assertEqual(
                boot_devices.PXE,
                task.node.driver_internal_info['persistent_boot_device'])
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=False,
                                                    uefiboot=False)

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.management.set_boot_device,
                              task,
                              'fake-device')

    @mock.patch.object(deploy_utils, 'get_boot_mode_for_deploy')
    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_set_boot_device_uefi(self, ipmi_mock, boot_mode_mock):
        ipmicmd = ipmi_mock.return_value
        boot_mode_mock.return_value = 'uefi'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=False,
                                                    uefiboot=True)

    @mock.patch.object(deploy_utils, 'get_boot_mode_for_deploy')
    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_set_boot_device_uefi_and_persistent(
            self, ipmi_mock, boot_mode_mock):
        ipmicmd = ipmi_mock.return_value
        boot_mode_mock.return_value = 'uefi'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE,
                                                   persistent=True)
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=True,
                                                    uefiboot=True)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipminative, '_reboot', autospec=True)
    def test_reboot_ok(self, reboot_mock, mock_next_boot):
        reboot_mock.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.reboot(task)
            mock_next_boot.assert_called_once_with(task, self.info)
        reboot_mock.assert_called_once_with(self.info)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_reboot_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'error': 'Some IPMI error'}

        self.config(retry_timeout=500, group='ipmi')
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.reboot,
                              task)
        ipmicmd.set_power.assert_called_once_with('boot', 500)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM, boot_devices.BIOS]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices(task)))

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_management_interface_get_boot_device_good(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'hd'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.DISK, bootdev['boot_device'])
            self.assertIsNone(bootdev['persistent'])

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_management_interface_get_boot_device_persistent(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'hd',
                                            'persistent': True}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.DISK, bootdev['boot_device'])
            self.assertTrue(bootdev['persistent'])

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_management_interface_get_boot_device_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.side_effect = pyghmi_exception.IpmiException
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.management.get_boot_device, task)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_management_interface_get_boot_device_fail_dict(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'error': 'boooom'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.management.get_boot_device, task)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_management_interface_get_boot_device_unknown(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'unknown'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = {'boot_device': None, 'persistent': None}
            self.assertEqual(expected,
                             self.driver.management.get_boot_device(task))

    def test_get_force_boot_device_persistent(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual('pxe', bootdev['boot_device'])
            self.assertTrue(bootdev['persistent'])

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing IPMI driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_ipminative')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch('pyghmi.ipmi.command.Command', autospec=True)
    def test_get_sensors_data(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_sensor_data.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.management.get_sensors_data(task)
        ipmicmd.get_sensor_data.assert_called_once_with()

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console(self, mock_start):
        mock_start.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)

        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)
        self.assertTrue(mock_start.called)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail(self, mock_start):
        mock_start.side_effect = exception.ConsoleSubprocessFailed(
            error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console.start_console,
                              task)

        self.assertTrue(mock_start.called)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_stop):
        mock_stop.return_value = None

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.console.stop_console(task)

        mock_stop.assert_called_once_with(self.info['uuid'])

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console_fail(self, mock_stop):
        mock_stop.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.stop_console,
                              task)

        mock_stop.assert_called_once_with(self.node.uuid)

    @mock.patch.object(console_utils, 'get_shellinabox_console_url',
                       autospec=True)
    def test_get_console(self, mock_get_url):
        url = 'http://localhost:4201'
        mock_get_url.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_get_url.assert_called_once_with(self.info['port'])

    @mock.patch.object(ipminative, '_parse_driver_info', autospec=True)
    @mock.patch.object(ipminative, '_parse_raw_bytes', autospec=True)
    def test_vendor_passthru_validate__send_raw_bytes_good(self, mock_raw,
                                                           mock_driver):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task,
                                        method='send_raw',
                                        http_method='POST',
                                        raw_bytes='0x00 0x01')
            mock_raw.assert_called_once_with('0x00 0x01')
            mock_driver.assert_called_once_with(task.node)

    def test_vendor_passthru_validate__send_raw_bytes_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.vendor.validate,
                              task, method='send_raw')

    def test_vendor_passthru_vendor_routes(self):
        expected = ['send_raw', 'bmc_reset']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(sorted(expected), sorted(vendor_routes))

    @mock.patch.object(ipminative, '_send_raw', autospec=True)
    def test_send_raw(self, send_raw_mock):
        bytes = '0x00 0x01'
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.vendor.send_raw(task, http_method='POST',
                                        raw_bytes=bytes)

        send_raw_mock.assert_called_once_with(self.info, bytes)

    @mock.patch.object(ipminative, '_send_raw', autospec=True)
    def _test_bmc_reset(self, warm, expected_bytes, send_raw_mock):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.vendor.bmc_reset(task, http_method='POST', warm=warm)

        send_raw_mock.assert_called_once_with(self.info, expected_bytes)

    def test_bmc_reset_cold(self):
        for param in (False, 'false', 'off', 'n', 'no'):
            self._test_bmc_reset(param, '0x06 0x02')

    def test_bmc_reset_warm(self):
        for param in (True, 'true', 'on', 'y', 'yes'):
            self._test_bmc_reset(param, '0x06 0x03')
