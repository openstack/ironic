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

import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import fake
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import utils as mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class UtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(UtilsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.node = obj_utils.create_test_node(self.context)

    def test_vendor_interface_get_properties(self):
        expected = {'A1': 'A1 description. Required.',
                    'A2': 'A2 description. Optional.',
                    'B1': 'B1 description. Required.',
                    'B2': 'B2 description. Required.'}
        props = self.driver.vendor.get_properties()
        self.assertEqual(expected, props)

    @mock.patch.object(fake.FakeVendorA, 'validate', autospec=True)
    def test_vendor_interface_validate_valid_methods(self,
                                                     mock_fakea_validate):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task, method='first_method')
            mock_fakea_validate.assert_called_once_with(
                self.driver.vendor.mapping['first_method'],
                task, method='first_method')

    def test_vendor_interface_validate_bad_method(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.vendor.validate,
                              task, method='fake_method')

    def test_get_node_mac_addresses(self):
        ports = []
        ports.append(
            obj_utils.create_test_port(
                self.context,
                address='aa:bb:cc:dd:ee:ff',
                uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                node_id=self.node.id)
        )
        ports.append(
            obj_utils.create_test_port(
                self.context,
                address='dd:ee:ff:aa:bb:cc',
                uuid='4fc26c0b-03f2-4d2e-ae87-c02d7f33c234',
                node_id=self.node.id)
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            node_macs = driver_utils.get_node_mac_addresses(task)
        self.assertEqual(sorted([p.address for p in ports]), sorted(node_macs))

    def test_get_node_capability(self):
        properties = {'capabilities': 'cap1:value1, cap2: value2'}
        self.node.properties = properties
        expected = 'value1'
        expected2 = 'value2'

        result = driver_utils.get_node_capability(self.node, 'cap1')
        result2 = driver_utils.get_node_capability(self.node, 'cap2')
        self.assertEqual(expected, result)
        self.assertEqual(expected2, result2)

    def test_get_node_capability_returns_none(self):
        properties = {'capabilities': 'cap1:value1,cap2:value2'}
        self.node.properties = properties

        result = driver_utils.get_node_capability(self.node, 'capX')
        self.assertIsNone(result)

    def test_add_node_capability(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = ''
            driver_utils.add_node_capability(task, 'boot_mode', 'bios')
            self.assertEqual('boot_mode:bios',
                             task.node.properties['capabilities'])

    def test_add_node_capability_append(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b,c:d'
            driver_utils.add_node_capability(task, 'boot_mode', 'bios')
            self.assertEqual('a:b,c:d,boot_mode:bios',
                             task.node.properties['capabilities'])

    def test_add_node_capability_append_duplicate(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b,c:d'
            driver_utils.add_node_capability(task, 'a', 'b')
            self.assertEqual('a:b,c:d,a:b',
                             task.node.properties['capabilities'])

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_ensure_next_boot_device(self, node_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            driver_utils.ensure_next_boot_device(
                task,
                {'force_boot_device': True}
            )
            node_set_boot_device_mock.assert_called_once_with(task, 'pxe')

    def test_ensure_next_boot_device_clears_is_next_boot_persistent(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            task.node.driver_internal_info['is_next_boot_persistent'] = False
            driver_utils.ensure_next_boot_device(
                task,
                {'force_boot_device': True}
            )
            task.node.refresh()
            self.assertNotIn('is_next_boot_persistent',
                             task.node.driver_internal_info)

    def test_force_persistent_boot_true(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            ret = driver_utils.force_persistent_boot(task, 'pxe', True)
            self.assertEqual(None, ret)
            task.node.refresh()
            self.assertIn('persistent_boot_device',
                          task.node.driver_internal_info)

    def test_force_persistent_boot_false(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = driver_utils.force_persistent_boot(task, 'pxe', False)
            self.assertEqual(None, ret)
            task.node.refresh()
            self.assertEqual(
                False,
                task.node.driver_internal_info.get('is_next_boot_persistent')
            )
