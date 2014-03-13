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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as db_api
from ironic.drivers.modules import ipminative
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from oslo.config import cfg

CONF = cfg.CONF

INFO_DICT = db_utils.get_test_ipmi_info()


class IPMINativePrivateMethodTestCase(base.TestCase):
    """Test cases for ipminative private methods."""

    def setUp(self):
        super(IPMINativePrivateMethodTestCase, self).setUp()
        n = db_utils.get_test_node(
                driver='fake_ipminative',
                driver_info=INFO_DICT)
        self.dbapi = db_api.get_instance()
        self.node = self.dbapi.create_node(n)
        self.info = ipminative._parse_driver_info(self.node)
        ipmi_patch = mock.patch('pyghmi.ipmi.command.Command')
        self.ipmi_mock = ipmi_patch.start()
        self.addCleanup(ipmi_patch.stop)

    def test__parse_driver_info(self):
        # make sure we get back the expected things
        self.assertIsNotNone(self.info.get('address'))
        self.assertIsNotNone(self.info.get('username'))
        self.assertIsNotNone(self.info.get('password'))
        self.assertIsNotNone(self.info.get('uuid'))

        # make sure error is raised when info, eg. username, is missing
        info = dict(INFO_DICT)
        del info['ipmi_username']

        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipminative._parse_driver_info,
                          node)

    def test__power_status_on(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'on'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_ON, state)

    def test__power_status_off(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'off'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.POWER_OFF, state)

    def test__power_status_error(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.get_power.return_value = {'powerstate': 'Error'}

        state = ipminative._power_status(self.info)
        ipmicmd.get_power.assert_called_once_with()
        self.assertEqual(states.ERROR, state)

    def test__power_on(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'on'}

        self.config(retry_timeout=400, group='ipmi')
        state = ipminative._power_on(self.info)
        ipmicmd.set_power.assert_called_once_with('on', 400)
        self.assertEqual(states.POWER_ON, state)

    def test__power_off(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'off'}

        self.config(retry_timeout=500, group='ipmi')
        state = ipminative._power_off(self.info)
        ipmicmd.set_power.assert_called_once_with('off', 500)
        self.assertEqual(states.POWER_OFF, state)

    def test__reboot(self):
        ipmicmd = self.ipmi_mock.return_value
        ipmicmd.set_power.return_value = {'powerstate': 'on'}

        self.config(retry_timeout=600, group='ipmi')
        state = ipminative._reboot(self.info)
        ipmicmd.set_power.assert_called_once_with('boot', 600)
        self.assertEqual(states.POWER_ON, state)


class IPMINativeDriverTestCase(db_base.DbTestCase):
    """Test cases for ipminative.NativeIPMIPower class functions.
    """

    def setUp(self):
        super(IPMINativeDriverTestCase, self).setUp()
        self.context = context.get_admin_context()
        mgr_utils.mock_the_extension_manager(driver="fake_ipminative")
        self.driver = driver_factory.get_driver("fake_ipminative")

        n = db_utils.get_test_node(
                driver='fake_ipminative',
                driver_info=INFO_DICT)
        self.dbapi = db_api.get_instance()
        self.node = self.dbapi.create_node(n)
        self.info = ipminative._parse_driver_info(self.node)

    def test_get_power_state(self):
        with mock.patch('pyghmi.ipmi.command.Command') as ipmi_mock:
            # Getting the mocked command.
            cmd_mock = ipmi_mock.return_value
            # Getting the get power mock.
            get_power_mock = cmd_mock.get_power

            return_values = [{'powerstate': 'error'},
                             {'powerstate': 'on'},
                             {'powerstate': 'off'}]

            get_power_mock.side_effect = lambda: return_values.pop()

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(states.POWER_OFF, pstate)

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(states.POWER_ON, pstate)

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(states.ERROR, pstate)
            self.assertEqual(3, get_power_mock.call_count,
                             "pyghmi.ipmi.command.Command.get_power was not"
                             " called 3 times.")

    def test_set_power_on_ok(self):
        with mock.patch.object(ipminative, '_power_on') as power_on_mock:
            power_on_mock.return_value = states.POWER_ON

            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.driver.power.set_power_state(
                    task, self.node, states.POWER_ON)
            power_on_mock.assert_called_once_with(self.info)

    def test_set_power_off_ok(self):
        with mock.patch.object(ipminative, '_power_off') as power_off_mock:
            power_off_mock.return_value = states.POWER_OFF

            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.driver.power.set_power_state(
                    task, self.node, states.POWER_OFF)
            power_off_mock.assert_called_once_with(self.info)

    def test_set_power_on_fail(self):
        with mock.patch('pyghmi.ipmi.command.Command') as ipmi_mock:
            ipmicmd = ipmi_mock.return_value
            ipmicmd.set_power.return_value = {'powerstate': 'error'}

            self.config(retry_timeout=500, group='ipmi')
            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.assertRaises(exception.PowerStateFailure,
                                  self.driver.power.set_power_state,
                                  task,
                                  self.node,
                                  states.POWER_ON)
            ipmicmd.set_power.assert_called_once_with('on', 500)

    def test_set_boot_device_ok(self):
        with mock.patch('pyghmi.ipmi.command.Command') as ipmi_mock:
            ipmicmd = ipmi_mock.return_value
            ipmicmd.set_bootdev.return_value = None

            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.driver.vendor._set_boot_device(task,
                                                   self.node,
                                                   'pxe')
            ipmicmd.set_bootdev.assert_called_once_with('pxe')

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, [self.node['uuid']]) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.vendor._set_boot_device,
                    task,
                    self.node,
                    'fake-device')

    def test_reboot_ok(self):
        with mock.patch.object(ipminative, '_reboot') as reboot_mock:
            reboot_mock.return_value = None

            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.driver.power.reboot(task, self.node)
            reboot_mock.assert_called_once_with(self.info)

    def test_reboot_fail(self):
        with mock.patch('pyghmi.ipmi.command.Command') as ipmi_mock:
            ipmicmd = ipmi_mock.return_value
            ipmicmd.set_power.return_value = {'powerstate': 'error'}

            self.config(retry_timeout=500, group='ipmi')
            with task_manager.acquire(self.context,
                                     [self.node['uuid']]) as task:
                self.assertRaises(exception.PowerStateFailure,
                                  self.driver.power.reboot,
                                  task,
                                  self.node)
            ipmicmd.set_power.assert_called_once_with('boot', 500)

    def test_vendor_passthru_validate__set_boot_device_good(self):
        self.driver.vendor.validate(self.node,
                                    method='set_boot_device',
                                    device='pxe')

    def test_vendor_passthru_val__set_boot_device_fail_unknown_device(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate,
                          self.node, method='set_boot_device',
                          device='non-existent')

    def test_vendor_passthru_val__set_boot_device_fail_missed_device_arg(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate,
                          self.node, method='set_boot_device')

    def test_vendor_passthru_validate_method_notmatch(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate,
                          self.node, method='non-existent-method')

    def test_vendor_passthru_call__set_boot_device(self):
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=False) as task:
            with mock.patch.object(ipminative.VendorPassthru,
                                   '_set_boot_device') as boot_mock:
                self.driver.vendor.vendor_passthru(task,
                                                   self.node,
                                                   method='set_boot_device',
                                                   device='pxe')
                boot_mock.assert_called_once_with(task, self.node,
                                                  'pxe', False)
