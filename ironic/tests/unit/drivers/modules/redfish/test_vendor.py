# Copyright 2018 DMTF. All rights reserved.
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

from unittest import mock

from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import vendor as redfish_vendor
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


class RedfishVendorPassthruTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishVendorPassthruTestCase, self).setUp()
        self.config(enabled_bios_interfaces=['redfish'],
                    enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_vendor_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_boot, 'eject_vmedia', autospec=True)
    def test_eject_vmedia_all(self, mock_eject_vmedia):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.vendor.eject_vmedia(task)
            mock_eject_vmedia.assert_called_once_with(task, None)

    @mock.patch.object(redfish_boot, 'eject_vmedia', autospec=True)
    def test_eject_vmedia_cd(self, mock_eject_vmedia):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.vendor.eject_vmedia(task,
                                            boot_device=sushy.VIRTUAL_MEDIA_CD)
            mock_eject_vmedia.assert_called_once_with(task,
                                                      sushy.VIRTUAL_MEDIA_CD)

    @mock.patch.object(redfish_vendor, 'redfish_utils', autospec=True)
    def test_validate_invalid_dev(self, mock_redfish_utils):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_CD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            kwargs = {'boot_device': 'foo'}
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.vendor.validate, task, 'eject_vmedia', **kwargs)
