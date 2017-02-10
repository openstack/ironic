#    Copyright 2015, Cisco Systems.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Test class for UCS ManagementInterface
"""

import mock
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.ucs import helper as ucs_helper
from ironic.drivers.modules.ucs import management as ucs_mgmt
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

ucs_error = importutils.try_import('UcsSdk.utils.exception')

INFO_DICT = db_utils.get_test_ucs_info()


class UcsManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(UcsManagementTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_ucs')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ucs',
                                               driver_info=INFO_DICT)
        self.interface = ucs_mgmt.UcsManagement()
        self.task = mock.Mock()
        self.task.node = self.node

    def test_get_properties(self):
        expected = ucs_helper.COMMON_PROPERTIES
        self.assertEqual(expected, self.interface.get_properties())

    def test_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM]
            self.assertEqual(
                sorted(expected),
                sorted(self.interface.get_supported_boot_devices(task)))

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch(
        'ironic.drivers.modules.ucs.management.ucs_mgmt.BootDeviceHelper',
        spec_set=True, autospec=True)
    def test_get_boot_device(self, mock_ucs_mgmt, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_mgmt = mock_ucs_mgmt.return_value
        mock_mgmt.get_boot_device.return_value = {
            'boot_device': 'disk',
            'persistent': False
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_device = boot_devices.DISK
            expected_response = {'boot_device': expected_device,
                                 'persistent': False}
            self.assertEqual(expected_response,
                             self.interface.get_boot_device(task))
        mock_mgmt.get_boot_device.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch(
        'ironic.drivers.modules.ucs.management.ucs_mgmt.BootDeviceHelper',
        spec_set=True, autospec=True)
    def test_get_boot_device_fail(self, mock_ucs_mgmt, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        mock_mgmt = mock_ucs_mgmt.return_value
        side_effect = ucs_error.UcsOperationError(
            operation='getting boot device',
            error='failed',
        )
        mock_mgmt.get_boot_device.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.UcsOperationError,
                              self.interface.get_boot_device,
                              task)
        mock_mgmt.get_boot_device.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch(
        'ironic.drivers.modules.ucs.management.ucs_mgmt.BootDeviceHelper',
        spec_set=True, autospec=True)
    def test_set_boot_device(self, mock_mgmt, mock_helper):
        mc_mgmt = mock_mgmt.return_value
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.interface.set_boot_device(task, boot_devices.CDROM)

        mc_mgmt.set_boot_device.assert_called_once_with('cdrom', False)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    @mock.patch(
        'ironic.drivers.modules.ucs.management.ucs_mgmt.BootDeviceHelper',
        spec_set=True, autospec=True)
    def test_set_boot_device_fail(self, mock_mgmt, mock_helper):
        mc_mgmt = mock_mgmt.return_value
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        side_effect = exception.UcsOperationError(
            operation='setting boot device',
            error='failed',
            node=self.node.uuid)
        mc_mgmt.set_boot_device.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              self.interface.set_boot_device,
                              task, boot_devices.PXE)
            mc_mgmt.set_boot_device.assert_called_once_with(
                boot_devices.PXE, False)

    def test_get_sensors_data(self):
        self.assertRaises(NotImplementedError,
                          self.interface.get_sensors_data, self.task)
