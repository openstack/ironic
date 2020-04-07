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
"""Test class for iBMC Management interface."""

import itertools
from unittest import mock

from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.ibmc import mappings
from ironic.drivers.modules.ibmc import utils
from ironic.tests.unit.drivers.modules.ibmc import base

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')
ibmc_error = importutils.try_import('ibmc_client.exceptions')


class IBMCManagementTestCase(base.IBMCTestCase):

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.management.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_get_supported_boot_devices(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock return value
        _supported_boot_devices = list(mappings.GET_BOOT_DEVICE_MAP)
        conn.system.get.return_value = mock.Mock(
            boot_source_override=mock.Mock(
                supported_boot_devices=_supported_boot_devices
            )
        )
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_boot_devices = (
                task.driver.management.get_supported_boot_devices(task))
            connect_ibmc.assert_called_once_with(**self.ibmc)
            expect = sorted(list(mappings.GET_BOOT_DEVICE_MAP.values()))
            self.assertEqual(expect, sorted(supported_boot_devices))

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_boot_device(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock return value
        conn.system.set_boot_source.return_value = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            device_mapping = [
                (boot_devices.PXE, constants.BOOT_SOURCE_TARGET_PXE),
                (boot_devices.DISK, constants.BOOT_SOURCE_TARGET_HDD),
                (boot_devices.CDROM, constants.BOOT_SOURCE_TARGET_CD),
                (boot_devices.BIOS,
                 constants.BOOT_SOURCE_TARGET_BIOS_SETUP),
                ('floppy', constants.BOOT_SOURCE_TARGET_FLOPPY),
            ]

            persistent_mapping = [
                (True, constants.BOOT_SOURCE_ENABLED_CONTINUOUS),
                (False, constants.BOOT_SOURCE_ENABLED_ONCE)
            ]

            data_source = list(itertools.product(device_mapping,
                                                 persistent_mapping))
            for (device, persistent) in data_source:
                task.driver.management.set_boot_device(
                    task, device[0], persistent=persistent[0])
                connect_ibmc.assert_called_once_with(**self.ibmc)
                conn.system.set_boot_source.assert_called_once_with(
                    device[1],
                    enabled=persistent[1])
                # Reset mocks
                connect_ibmc.reset_mock()
                conn.system.set_boot_source.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_boot_device_fail(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock return value
        conn.system.set_boot_source.side_effect = (
            ibmc_error.IBMCClientError
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.IBMCError, 'set iBMC boot device',
                task.driver.management.set_boot_device, task,
                boot_devices.PXE)
            connect_ibmc.assert_called_once_with(**self.ibmc)
            conn.system.set_boot_source.assert_called_once_with(
                constants.BOOT_SOURCE_TARGET_PXE,
                enabled=constants.BOOT_SOURCE_ENABLED_ONCE)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_get_boot_device(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock return value
        conn.system.get.return_value = mock.Mock(
            boot_source_override=mock.Mock(
                target=constants.BOOT_SOURCE_TARGET_PXE,
                enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS
            )
        )
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result_boot_device = task.driver.management.get_boot_device(task)
            conn.system.get.assert_called_once()
            connect_ibmc.assert_called_once_with(**self.ibmc)
            expected = {'boot_device': boot_devices.PXE,
                        'persistent': True}
            self.assertEqual(expected, result_boot_device)

    def test_get_supported_boot_modes(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_boot_modes = (
                task.driver.management.get_supported_boot_modes(task))
            self.assertEqual(list(mappings.SET_BOOT_MODE_MAP),
                             supported_boot_modes)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_boot_mode(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock system boot source override return value
        conn.system.get.return_value = mock.Mock(
            boot_source_override=mock.Mock(
                target=constants.BOOT_SOURCE_TARGET_PXE,
                enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS
            )
        )
        conn.system.set_boot_source.return_value = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (boot_modes.LEGACY_BIOS, constants.BOOT_SOURCE_MODE_BIOS),
                (boot_modes.UEFI, constants.BOOT_SOURCE_MODE_UEFI)
            ]

            for ironic_boot_mode, ibmc_boot_mode in expected_values:
                task.driver.management.set_boot_mode(task,
                                                     mode=ironic_boot_mode)

                conn.system.get.assert_called_once()
                connect_ibmc.assert_called_once_with(**self.ibmc)

                conn.system.set_boot_source.assert_called_once_with(
                    constants.BOOT_SOURCE_TARGET_PXE,
                    enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS,
                    mode=ibmc_boot_mode)

                # Reset
                connect_ibmc.reset_mock()
                conn.system.set_boot_source.reset_mock()
                conn.system.get.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_set_boot_mode_fail(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock system boot source override return value
        conn.system.get.return_value = mock.Mock(
            boot_source_override=mock.Mock(
                target=constants.BOOT_SOURCE_TARGET_PXE,
                enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS
            )
        )
        conn.system.set_boot_source.side_effect = (
            ibmc_error.IBMCClientError
        )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_values = [
                (boot_modes.LEGACY_BIOS, constants.BOOT_SOURCE_MODE_BIOS),
                (boot_modes.UEFI, constants.BOOT_SOURCE_MODE_UEFI)
            ]

            for ironic_boot_mode, ibmc_boot_mode in expected_values:
                self.assertRaisesRegex(
                    exception.IBMCError, 'set iBMC boot mode',
                    task.driver.management.set_boot_mode, task,
                    ironic_boot_mode)

                conn.system.set_boot_source.assert_called_once_with(
                    constants.BOOT_SOURCE_TARGET_PXE,
                    enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS,
                    mode=ibmc_boot_mode)

                conn.system.get.assert_called_once()
                connect_ibmc.assert_called_once_with(**self.ibmc)

                # Reset
                connect_ibmc.reset_mock()
                conn.system.set_boot_source.reset_mock()
                conn.system.get.reset_mock()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_get_boot_mode(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock system boot source override return value
        conn.system.get.return_value = mock.Mock(
            boot_source_override=mock.Mock(
                target=constants.BOOT_SOURCE_TARGET_PXE,
                enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS,
                mode=constants.BOOT_SOURCE_MODE_BIOS,
            )
        )
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            response = task.driver.management.get_boot_mode(task)

            conn.system.get.assert_called_once()
            connect_ibmc.assert_called_once_with(**self.ibmc)

            expected = boot_modes.LEGACY_BIOS
            self.assertEqual(expected, response)

    def test_get_sensors_data(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(NotImplementedError,
                              task.driver.management.get_sensors_data, task)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_inject_nmi(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock system boot source override return value
        conn.system.reset.return_value = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.inject_nmi(task)

            connect_ibmc.assert_called_once_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(constants.RESET_NMI)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_inject_nmi_fail(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        # mock system boot source override return value
        conn.system.reset.side_effect = (
            ibmc_error.IBMCClientError
        )
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.IBMCError, 'inject iBMC NMI',
                task.driver.management.inject_nmi, task)

            connect_ibmc.assert_called_once_with(**self.ibmc)
            conn.system.reset.assert_called_once_with(constants.RESET_NMI)
