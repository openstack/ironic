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
from oslo.config import cfg
from pyghmi import exceptions as pyghmi_exception

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import ipminative
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF

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
        self.assertIsNotNone(self.info.get('address'))
        self.assertIsNotNone(self.info.get('username'))
        self.assertIsNotNone(self.info.get('password'))
        self.assertIsNotNone(self.info.get('uuid'))

        # make sure error is raised when info, eg. username, is missing
        info = dict(INFO_DICT)
        del info['ipmi_username']

        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          ipminative._parse_driver_info,
                          node)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test__power_status_on(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'on'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_ON, state)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test__power_status_off(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'off'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test__power_status_error(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'Error'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.ERROR, state)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test__power_on(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'on'}

        self.config(retry_timeout=400, group='ipmi')
        state = ipminative._power_on(self.info)
        ipmicmd.set_power.assert_called_once_with('on', 400)
        self.assertEqual(states.POWER_ON, state)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test__power_off(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'off'}

        self.config(retry_timeout=500, group='ipmi')
        state = ipminative._power_off(self.info)
        ipmicmd.set_power.assert_called_once_with('off', 500)
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch('pyghmi.ipmi.command.Command')
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
        return type('Reading', (object, ), {'value': value, 'type': type_,
                                     'name': name, 'states': states,
                                     'units': units, 'health': health})()

    @mock.patch('pyghmi.ipmi.command.Command')
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

    @mock.patch('pyghmi.ipmi.command.Command')
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

        expected = ipminative.COMMON_PROPERTIES.keys()
        expected += ipminative.CONSOLE_PROPERTIES.keys()
        self.assertEqual(sorted(expected),
                         sorted(self.driver.console.get_properties().keys()))
        self.assertEqual(sorted(expected),
                         sorted(self.driver.get_properties().keys()))

    @mock.patch('pyghmi.ipmi.command.Command')
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

    @mock.patch.object(ipminative, '_power_on')
    def test_set_power_on_ok(self, power_on_mock):
        power_on_mock.return_value = states.POWER_ON

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(
                task, states.POWER_ON)
        power_on_mock.assert_called_once_with(self.info)

    @mock.patch.object(ipminative, '_power_off')
    def test_set_power_off_ok(self, power_off_mock):
        power_off_mock.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(
                task, states.POWER_OFF)
        power_off_mock.assert_called_once_with(self.info)

    @mock.patch('pyghmi.ipmi.command.Command')
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

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_set_boot_device_ok(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_bootdev.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        # PXE is converted to 'network' internally by ipminative
        ipmicmd.set_bootdev.assert_called_once_with('network', persist=False)

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.management.set_boot_device,
                    task,
                    'fake-device')

    @mock.patch.object(ipminative, '_reboot')
    def test_reboot_ok(self, reboot_mock):
        reboot_mock.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.reboot(task)
        reboot_mock.assert_called_once_with(self.info)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_reboot_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'error'}

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
                             get_supported_boot_devices()))

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_management_interface_get_boot_device_good(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'hd'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.DISK, bootdev['boot_device'])
            self.assertIsNone(bootdev['persistent'])

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_management_interface_get_boot_device_persistent(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'hd',
                                            'persistent': True}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual(boot_devices.DISK, bootdev['boot_device'])
            self.assertTrue(bootdev['persistent'])

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_management_interface_get_boot_device_fail(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.side_effect = pyghmi_exception.IpmiException
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.management.get_boot_device, task)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_management_interface_get_boot_device_fail_dict(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'error': 'boooom'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.management.get_boot_device, task)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_management_interface_get_boot_device_unknown(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_bootdev.return_value = {'bootdev': 'unknown'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = {'boot_device': None, 'persistent': None}
            self.assertEqual(expected,
                             self.driver.management.get_boot_device(task))

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing IPMI driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=utils.generate_uuid(),
                                          driver='fake_ipminative')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch('pyghmi.ipmi.command.Command')
    def test_get_sensors_data(self, ipmi_mock):
        ipmicmd = ipmi_mock.return_value
        ipmicmd.get_sensor_data.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.management.get_sensors_data(task)
        ipmicmd.get_sensor_data.assert_called_once_with()

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console(self, mock_exec):
        mock_exec.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'],
                                          self.info['port'],
                                          mock.ANY)
        self.assertTrue(mock_exec.called)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail(self, mock_exec):
        mock_exec.side_effect = exception.ConsoleSubprocessFailed(
                error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console.start_console,
                              task)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_exec):
        mock_exec.return_value = None

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.console.stop_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'])
        self.assertTrue(mock_exec.called)

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
    def test_get_console(self, mock_exec):
        url = 'http://localhost:4201'
        mock_exec.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_exec.assert_called_once_with(self.info['port'])
        self.assertTrue(mock_exec.called)
