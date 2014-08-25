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
from ironic.db import api as db_api
from ironic.drivers.modules import fake
from ironic.drivers import utils as driver_utils
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.objects import utils as obj_utils


class UtilsTestCase(base.TestCase):

    def setUp(self):
        super(UtilsTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = db_api.get_instance()
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

    @mock.patch.object(fake.FakeVendorA, 'validate')
    def test_vendor_interface_validate_valid_methods(self,
                                                     mock_fakea_validate):
        self.driver.vendor.validate(method='first_method')
        mock_fakea_validate.assert_called_once_with(method='first_method')

    def test_vendor_interface_validate_bad_method(self):
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.driver.vendor.validate, method='fake_method')

    def test_vendor_interface_validate_none_method(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.driver.vendor.validate)

    @mock.patch.object(fake.FakeVendorA, 'vendor_passthru')
    @mock.patch.object(fake.FakeVendorB, 'vendor_passthru')
    def test_vendor_interface_route_valid_method(self, mock_fakeb_vendor,
                                                 mock_fakea_vendor):
        self.driver.vendor.vendor_passthru('task',
                                           method='first_method',
                                           param1='fake1', param2='fake2')
        mock_fakea_vendor.assert_called_once_with('task',
                                            method='first_method',
                                            param1='fake1', param2='fake2')
        self.driver.vendor.vendor_passthru('task',
                                           method='second_method',
                                           param1='fake1', param2='fake2')
        mock_fakeb_vendor.assert_called_once_with('task',
                                            method='second_method',
                                            param1='fake1', param2='fake2')

    def test_driver_passthru_mixin_success(self):
        vendor_a = fake.FakeVendorA()
        vendor_a.driver_vendor_passthru = mock.Mock()
        vendor_b = fake.FakeVendorB()
        vendor_b.driver_vendor_passthru = mock.Mock()
        driver_vendor_mapping = {
            'method_a': vendor_a,
            'method_b': vendor_b,
        }
        mixed_vendor = driver_utils.MixinVendorInterface(
            {},
            driver_vendor_mapping)
        mixed_vendor.driver_vendor_passthru('context',
                                            'method_a',
                                            param1='p1')
        vendor_a.driver_vendor_passthru.assert_called_once_with(
            'context',
            'method_a',
            param1='p1')

    def test_driver_passthru_mixin_unsupported(self):
        mixed_vendor = driver_utils.MixinVendorInterface({}, {})
        self.assertRaises(exception.UnsupportedDriverExtension,
                          mixed_vendor.driver_vendor_passthru,
                          'context',
                          'fake_method',
                          param='p1')

    def test_driver_passthru_mixin_unspecified(self):
        mixed_vendor = driver_utils.MixinVendorInterface({})
        self.assertRaises(exception.UnsupportedDriverExtension,
                          mixed_vendor.driver_vendor_passthru,
                          'context',
                          'fake_method',
                          param='p1')

    def test_get_node_mac_addresses(self):
        ports = []
        ports.append(
            obj_utils.create_test_port(self.context,
                    id=6, address='aa:bb:cc',
                    uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                    node_id=self.node.id)
        )
        ports.append(
            obj_utils.create_test_port(self.context,
                    id=7, address='dd:ee:ff',
                    uuid='4fc26c0b-03f2-4d2e-ae87-c02d7f33c234',
                    node_id=self.node.id)
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            node_macs = driver_utils.get_node_mac_addresses(task)
        self.assertEqual(sorted([p.address for p in ports]), sorted(node_macs))

    def test_get_node_capability(self):
        properties = {'capabilities': 'cap1:value1,cap2:value2'}
        self.node.properties = properties
        expected = 'value1'

        result = driver_utils.get_node_capability(self.node, 'cap1')
        self.assertEqual(expected, result)

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

    def test_rm_node_capability(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b'
            driver_utils.rm_node_capability(task, 'a')
            self.assertIsNone(task.node.properties['capabilities'])

    def test_rm_node_capability_exists(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b,c:d,x:y'
            self.assertIsNone(driver_utils.rm_node_capability(task, 'c'))
            self.assertEqual('a:b,x:y', task.node.properties['capabilities'])

    def test_rm_node_capability_non_existent(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'a:b'
            self.assertIsNone(driver_utils.rm_node_capability(task, 'x'))
            self.assertEqual('a:b', task.node.properties['capabilities'])

    def test_validate_boot_mode_capability(self):
        properties = {'capabilities': 'boot_mode:uefi,cap2:value2'}
        self.node.properties = properties

        result = driver_utils.validate_boot_mode_capability(self.node)
        self.assertIsNone(result)

    def test_validate_boot_mode_capability_with_exception(self):
        properties = {'capabilities': 'boot_mode:foo,cap2:value2'}
        self.node.properties = properties

        self.assertRaises(exception.InvalidParameterValue,
                   driver_utils.validate_boot_mode_capability, self.node)
