# Copyright 2019 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2019-2021 Dell Inc. or its subsidiaries.
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

from unittest import mock

import sushy

from ironic.common import boot_devices
from ironic.conductor import task_manager
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import boot as idrac_boot
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = dict(db_utils.get_test_redfish_info(), **test_utils.INFO_DICT)


@mock.patch.object(redfish_utils, 'get_system', autospec=True)
class DracBootTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracBootTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='idrac', driver_info=INFO_DICT)

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_correct_vendor(self, mock_get_system,
                                     mock_validate_image_properties):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info.update(
                {'kernel': 'kernel',
                 'ramdisk': 'ramdisk',
                 'image_source': 'http://image/source'}
            )

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            task.node.properties['vendor'] = "Dell Inc."

            task.driver.boot.validate(task)

    def test__set_boot_device_persistent(self, mock_get_system):
        mock_manager = mock.MagicMock()
        mock_system = mock_get_system.return_value
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(
                task, boot_devices.CDROM, persistent=True)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                sushy.VIRTUAL_MEDIA_CD, persistent=True, system=mock_system)

    def test__set_boot_device_cd(self, mock_get_system):
        mock_system = mock_get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.CDROM)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                sushy.VIRTUAL_MEDIA_CD, persistent=False, system=mock_system)

    def test__set_boot_device_floppy(self, mock_get_system):
        mock_system = mock_get_system.return_value
        mock_manager = mock.MagicMock()
        mock_system.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.FLOPPY)

            mock_manager_oem.set_virtual_boot_device.assert_called_once_with(
                sushy.VIRTUAL_MEDIA_FLOPPY, persistent=False,
                system=mock_system)

    def test__set_boot_device_disk(self, mock_get_system):
        mock_system = mock_get_system.return_value

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot._set_boot_device(task, boot_devices.DISK)

            self.assertFalse(mock_system.called)

    @mock.patch.object(idrac_boot.LOG, 'debug', autospec=True)
    def test__get_idrac_version_from_model(self, mock_log_debug,
                                           mock_get_system):
        # Use shorter alias for readability and line length
        idrac_redfish_boot = idrac_boot.DracRedfishVirtualMediaBoot

        # Test cases that should return None without logging
        none_models = [None, "", "10G", "10ABC", "10G1XPT"]
        for model in none_models:
            version = idrac_redfish_boot._get_idrac_version_from_model(model)
            self.assertIsNone(version)

        # Test cases causing TypeError/ValueError and should log debug message
        error_models = [(5, 6, 7), [1, 2], "ABC", "X1Z", "9GTP"]

        for model in error_models:
            version = idrac_redfish_boot._get_idrac_version_from_model(model)
            self.assertIsNone(version)
        # Verify that debug logging was called for each error model
        self.assertEqual(mock_log_debug.call_count, len(error_models))
        # Verify the debug log calls have the correct format
        expected_calls = [
            mock.call(
                "Unable to parse iDRAC version from model string: %s", model)
            for model in error_models
        ]
        mock_log_debug.assert_has_calls(expected_calls)

        idrac8 = ["12G Modular", "13G Modular"]
        idrac9 = ["14G Monolithic", "15G Monolithic", "16G Monolithic",
                  "16G DCS"]
        idrac10 = ["17G Monolithic", "18G Monolithic"]
        for model in idrac8:
            version = idrac_redfish_boot._get_idrac_version_from_model(model)
            self.assertEqual(version, 8)
        for model in idrac9:
            version = idrac_redfish_boot._get_idrac_version_from_model(model)
            self.assertEqual(version, 9)
        for model in idrac10:
            version = idrac_redfish_boot._get_idrac_version_from_model(model)
            self.assertEqual(version, 10)

    def test__get_acceptable_media_id(self, mock_get_system):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            # Case 1: System resource with manager model "17G Monolithic"
            # (iDRAC 10) returns "1"
            mock_manager_idrac10 = mock.Mock()
            mock_manager_idrac10.model = "17G Monolithic"
            mock_system_resource = mock.Mock()
            mock_system_resource.managers = [mock_manager_idrac10]

            result = task.driver.boot._get_acceptable_media_id(
                task, mock_system_resource)
            self.assertEqual("1", result)

            # Case 2: System resource with manager model "16G Monolithic"
            # (iDRAC 9) returns None
            mock_manager_idrac9 = mock.Mock()
            mock_manager_idrac9.model = "16G Monolithic"
            mock_system_resource_idrac9 = mock.Mock()
            mock_system_resource_idrac9.managers = [mock_manager_idrac9]

            result = task.driver.boot._get_acceptable_media_id(
                task, mock_system_resource_idrac9)
            self.assertIsNone(result)

            # Case 3: Manager resource with model "15G Monolithic"
            # Should return None (Manager resources)
            mock_manager_resource = mock.Mock()
            mock_manager_resource.model = "15G Monolithic"
            # Simulate Manager resource by setting managers to None
            mock_manager_resource.managers = None

            result = task.driver.boot._get_acceptable_media_id(
                task, mock_manager_resource)
            self.assertIsNone(result)
