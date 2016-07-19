# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Test class for Fake driver."""

import mock

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers import base as driver_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class FakeDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(FakeDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.node = obj_utils.get_test_node(self.context)
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = self.driver

    def test_driver_interfaces(self):
        self.assertIsInstance(self.driver.power, driver_base.PowerInterface)
        self.assertIsInstance(self.driver.deploy, driver_base.DeployInterface)
        self.assertIsInstance(self.driver.boot, driver_base.BootInterface)
        self.assertIsInstance(self.driver.vendor, driver_base.VendorInterface)
        self.assertIsInstance(self.driver.console,
                              driver_base.ConsoleInterface)
        self.assertIsNone(self.driver.rescue)

    def test_get_properties(self):
        expected = ['A1', 'A2', 'B1', 'B2']
        properties = self.driver.get_properties()
        self.assertEqual(sorted(expected), sorted(properties.keys()))

    def test_power_interface(self):
        self.assertEqual({}, self.driver.power.get_properties())
        self.driver.power.validate(self.task)
        self.driver.power.get_power_state(self.task)
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.power.set_power_state,
                          self.task, states.NOSTATE)
        self.driver.power.set_power_state(self.task, states.POWER_ON)
        self.driver.power.reboot(self.task)

    def test_deploy_interface(self):
        self.assertEqual({}, self.driver.deploy.get_properties())
        self.driver.deploy.validate(None)

        self.driver.deploy.prepare(None)
        self.driver.deploy.deploy(None)

        self.driver.deploy.take_over(None)

        self.driver.deploy.clean_up(None)
        self.driver.deploy.tear_down(None)

    def test_boot_interface(self):
        self.assertEqual({}, self.driver.boot.get_properties())
        self.driver.boot.validate(self.task)
        self.driver.boot.prepare_ramdisk(self.task, {})
        self.driver.boot.clean_up_ramdisk(self.task)
        self.driver.boot.prepare_instance(self.task)
        self.driver.boot.clean_up_instance(self.task)

    def test_console_interface(self):
        self.assertEqual({}, self.driver.console.get_properties())
        self.driver.console.validate(self.task)
        self.driver.console.start_console(self.task)
        self.driver.console.stop_console(self.task)
        self.driver.console.get_console(self.task)

    def test_management_interface_get_properties(self):
        self.assertEqual({}, self.driver.management.get_properties())

    def test_management_interface_validate(self):
        self.driver.management.validate(self.task)

    def test_management_interface_set_boot_device_good(self):
            self.driver.management.set_boot_device(self.task, boot_devices.PXE)

    def test_management_interface_set_boot_device_fail(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.management.set_boot_device, self.task,
                          'not-supported')

    def test_management_interface_get_supported_boot_devices(self):
        expected = [boot_devices.PXE]
        self.assertEqual(
            expected,
            self.driver.management.get_supported_boot_devices(self.task))

    def test_management_interface_get_boot_device(self):
        expected = {'boot_device': boot_devices.PXE, 'persistent': False}
        self.assertEqual(expected,
                         self.driver.management.get_boot_device(self.task))

    def test_inspect_interface(self):
        self.assertEqual({}, self.driver.inspect.get_properties())
        self.driver.inspect.validate(self.task)
        self.driver.inspect.inspect_hardware(self.task)
