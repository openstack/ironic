# Copyright 2022 Hewlett Packard Enterprise Development LP
# Copyright 2015 Hewlett-Packard Development Company, L.P.
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

"""Test class for vendor methods used by iLO modules."""

from unittest import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import vendor as ilo_vendor
from ironic.tests.unit.drivers.modules.ilo import test_common


class VendorPassthruTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'
    vendor_interface = 'ilo'

    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia', spec_set=True,
                       autospec=True)
    def test_boot_into_iso(self, setup_vmedia_mock, power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.boot_into_iso(task, boot_iso_href='foo')
            setup_vmedia_mock.assert_called_once_with(task, 'foo',
                                                      ramdisk_options=None)
            power_action_mock.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(ilo_vendor.VendorPassthru, '_validate_boot_into_iso',
                       spec_set=True, autospec=True)
    def test_validate_boot_into_iso(self, validate_boot_into_iso_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vendor = ilo_vendor.VendorPassthru()
            vendor.validate(task, method='boot_into_iso', foo='bar')
            validate_boot_into_iso_mock.assert_called_once_with(
                vendor, task, {'foo': 'bar'})

    def test__validate_boot_into_iso_invalid_state(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.AVAILABLE
            self.assertRaises(
                exception.InvalidStateRequested,
                task.driver.vendor._validate_boot_into_iso,
                task, {})

    def test__validate_boot_into_iso_missing_boot_iso_href(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.MANAGEABLE
            self.assertRaises(
                exception.MissingParameterValue,
                task.driver.vendor._validate_boot_into_iso,
                task, {})

    @mock.patch.object(deploy_utils, 'get_image_properties',
                       spec_set=True, autospec=True)
    def test__validate_boot_into_iso_manage(self, validate_image_prop_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            info = {'boot_iso_href': 'foo'}
            task.node.provision_state = states.MANAGEABLE
            task.driver.vendor._validate_boot_into_iso(
                task, info)
            validate_image_prop_mock.assert_called_once_with(
                task.context, 'foo')

    @mock.patch.object(deploy_utils, 'get_image_properties',
                       spec_set=True, autospec=True)
    def test__validate_boot_into_iso_maintenance(
            self, validate_image_prop_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            info = {'boot_iso_href': 'foo'}
            task.node.maintenance = True
            task.driver.vendor._validate_boot_into_iso(
                task, info)
            validate_image_prop_mock.assert_called_once_with(
                task.context, 'foo')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__validate_is_it_a_supported_system(
            self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.maintenance = True
            ilo_mock_object = get_ilo_object_mock.return_value
            ilo_mock_object.get_product_name.return_value = (
                'ProLiant DL380 Gen10')
            task.driver.vendor._validate_is_it_a_supported_system(task)
            get_ilo_object_mock.assert_called_once_with(task.node)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__validate_is_it_a_supported_system_exception(
            self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.maintenance = True
            ilo_mock_object = get_ilo_object_mock.return_value
            ilo_mock_object.get_product_name.return_value = (
                'ProLiant DL380 Gen8')
            self.assertRaises(
                exception.IloOperationNotSupported,
                task.driver.vendor._validate_is_it_a_supported_system, task)

    @mock.patch.object(ilo_common, 'parse_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_redfish_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_vendor.VendorPassthru,
                       '_validate_is_it_a_supported_system',
                       spec_set=True, autospec=True)
    def test_validate_create_subscription(self, validate_redfish_system_mock,
                                          redfish_properties_mock,
                                          driver_info_mock):
        self.node.vendor_interface = 'ilo'
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            d_info = {'ilo_address': '1.1.1.1',
                      'ilo_username': 'user',
                      'ilo_password': 'password',
                      'ilo_verify_ca': False}
            driver_info_mock.return_value = d_info
            redfish_properties = {'redfish_address': '1.1.1.1',
                                  'redfish_username': 'user',
                                  'redfish_password': 'password',
                                  'redfish_system_id': '/redfish/v1/Systems/1',
                                  'redfish_verify_ca': False}
            redfish_properties_mock.return_value = redfish_properties
            kwargs = {'Destination': 'https://someulr',
                      'Context': 'MyProtocol'}
            task.driver.vendor.validate(task, 'create_subscription', **kwargs)
            driver_info_mock.assert_called_once_with(task.node)
            redfish_properties_mock.assert_called_once_with(task)
            validate_redfish_system_mock.assert_called_once_with(
                task.driver.vendor, task)

    def test_validate_operation_exeption(self):
        self.node.vendor_interface = 'ilo'
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.IloOperationNotSupported,
                task.driver.vendor.validate, task, 'eject_vmedia')
