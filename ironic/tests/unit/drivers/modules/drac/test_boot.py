# Copyright 2019 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2019 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test class for DRAC boot interface
"""

import mock
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import boot as drac_boot
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = test_utils.INFO_DICT


@mock.patch.object(drac_boot, 'redfish_utils', autospec=True)
class DracBootTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracBootTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='idrac', driver_info=INFO_DICT)

    def test__set_boot_device_persistent(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_manager = mock.MagicMock()

        mock_system.managers = [mock_manager]

        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(
                task, boot_devices.CDROM, persistent=True)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                'cd', persistent=True, manager=mock_manager,
                system=mock_system)

    def test__set_boot_device_cd(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_manager = mock.MagicMock()

        mock_system.managers = [mock_manager]

        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.CDROM)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                'cd', persistent=False, manager=mock_manager,
                system=mock_system)

    def test__set_boot_device_floppy(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_manager = mock.MagicMock()

        mock_system.managers = [mock_manager]

        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.FLOPPY)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                'floppy', persistent=False, manager=mock_manager,
                system=mock_system)

    def test__set_boot_device_disk(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.DISK)

            self.assertFalse(mock_system.called)

    def test__set_boot_device_missing_oem(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_manager = mock.MagicMock()

        mock_system.managers = [mock_manager]

        mock_manager.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.RedfishError,
                              task.driver.boot._set_boot_device,
                              task, boot_devices.CDROM)

    def test__set_boot_device_failover(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_manager_fail = mock.MagicMock()
        mock_manager_ok = mock.MagicMock()

        mock_system.managers = [mock_manager_fail, mock_manager_ok]

        mock_svbd_fail = (mock_manager_fail.get_oem_extension
                          .return_value.set_virtual_boot_device)

        mock_svbd_ok = (mock_manager_ok.get_oem_extension
                        .return_value.set_virtual_boot_device)

        mock_svbd_fail.side_effect = sushy.exceptions.SushyError

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.CDROM)

            self.assertFalse(mock_system.called)

        mock_svbd_fail.assert_called_once_with(
            'cd', manager=mock_manager_fail, persistent=False,
            system=mock_system)

        mock_svbd_ok.assert_called_once_with(
            'cd', manager=mock_manager_ok, persistent=False,
            system=mock_system)

    def test__set_boot_device_no_manager(self, mock_redfish_utils):

        mock_system = mock_redfish_utils.get_system.return_value

        mock_system.managers = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.RedfishError,
                              task.driver.boot._set_boot_device,
                              task, boot_devices.CDROM)
