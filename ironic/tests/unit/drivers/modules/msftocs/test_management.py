# Copyright 2015 Cloudbase Solutions Srl
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
Test class for MSFT OCS ManagementInterface
"""

import mock

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.msftocs import common as msftocs_common
from ironic.drivers.modules.msftocs import msftocsclient
from ironic.drivers import utils as drivers_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_msftocs_info()


class MSFTOCSManagementTestCase(db_base.DbTestCase):
    def setUp(self):
        super(MSFTOCSManagementTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_msftocs')
        self.info = INFO_DICT
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_msftocs',
                                               driver_info=self.info)

    def test_get_properties(self):
        expected = msftocs_common.REQUIRED_PROPERTIES
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(msftocs_common, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(msftocs_common, 'parse_driver_info', autospec=True)
    def test_validate_fail(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_drvinfo.side_effect = exception.InvalidParameterValue('x')
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    def test_get_supported_boot_devices(self):
        expected = [boot_devices.PXE, boot_devices.DISK, boot_devices.BIOS]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(
                sorted(expected),
                sorted(task.driver.management.
                       get_supported_boot_devices(task)))

    @mock.patch.object(msftocs_common, 'get_client_info', autospec=True)
    def _test_set_boot_device_one_time(self, persistent, uefi,
                                       mock_gci):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_c = mock.MagicMock(spec=msftocsclient.MSFTOCSClientApi)
            blade_id = task.node.driver_info['msftocs_blade_id']
            mock_gci.return_value = (mock_c, blade_id)

            if uefi:
                drivers_utils.add_node_capability(task, 'boot_mode', 'uefi')

            task.driver.management.set_boot_device(
                task, boot_devices.PXE, persistent)

            mock_gci.assert_called_once_with(task.node.driver_info)
            mock_c.set_next_boot.assert_called_once_with(
                blade_id, msftocsclient.BOOT_TYPE_FORCE_PXE, persistent, uefi)

    def test_set_boot_device_one_time(self):
        self._test_set_boot_device_one_time(False, False)

    def test_set_boot_device_persistent(self):
        self._test_set_boot_device_one_time(True, False)

    def test_set_boot_device_uefi(self):
        self._test_set_boot_device_one_time(True, True)

    def test_set_boot_device_fail(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, 'fake-device')

    @mock.patch.object(msftocs_common, 'get_client_info', autospec=True)
    def test_get_boot_device(self, mock_gci):
        expected = {'boot_device': boot_devices.DISK, 'persistent': None}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_c = mock.MagicMock(spec=msftocsclient.MSFTOCSClientApi)
            blade_id = task.node.driver_info['msftocs_blade_id']
            mock_gci.return_value = (mock_c, blade_id)
            force_hdd = msftocsclient.BOOT_TYPE_FORCE_DEFAULT_HDD
            mock_c.get_next_boot.return_value = force_hdd

            self.assertEqual(expected,
                             task.driver.management.get_boot_device(task))
            mock_gci.assert_called_once_with(task.node.driver_info)
            mock_c.get_next_boot.assert_called_once_with(blade_id)

    def test_get_sensor_data(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(NotImplementedError,
                              task.driver.management.get_sensors_data,
                              task)
