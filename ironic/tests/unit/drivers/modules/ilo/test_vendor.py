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

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    def test__validate_boot_into_iso_manage(self, validate_image_prop_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            info = {'boot_iso_href': 'foo'}
            task.node.provision_state = states.MANAGEABLE
            task.driver.vendor._validate_boot_into_iso(
                task, info)
            validate_image_prop_mock.assert_called_once_with(
                task.context, {'image_source': 'foo'}, [])

    @mock.patch.object(deploy_utils, 'validate_image_properties',
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
                task.context, {'image_source': 'foo'}, [])
