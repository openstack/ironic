# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""Test class for Management Interface used by iLO modules."""

from unittest import mock

import ddt
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules import ipmitool
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.ilo import test_common
from ironic.tests.unit.objects import utils as obj_utils

ilo_error = importutils.try_import('proliantutils.exception')

INFO_DICT = db_utils.get_test_ilo_info()


@ddt.ddt
class IloManagementTestCase(test_common.BaseIloTest):

    def setUp(self):
        super(IloManagementTestCase, self).setUp()
        port_1 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:66', uuid=uuidutils.generate_uuid())
        port_2 = obj_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:67', uuid=uuidutils.generate_uuid())
        self.ports = [port_1, port_2]

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected = ilo_management.MANAGEMENT_PROPERTIES
            self.assertEqual(expected,
                             task.driver.management.get_properties())

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, driver_info_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.validate(task)
            driver_info_mock.assert_called_once_with(task.node)

    def test_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM, boot_devices.ISCSIBOOT]
            self.assertEqual(
                sorted(expected),
                sorted(task.driver.management.
                       get_supported_boot_devices(task)))

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_device_next_boot(self, get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        ilo_object_mock.get_one_time_boot.return_value = 'CDROM'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_device = boot_devices.CDROM
            expected_response = {'boot_device': expected_device,
                                 'persistent': False}
            self.assertEqual(expected_response,
                             task.driver.management.get_boot_device(task))
            ilo_object_mock.get_one_time_boot.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_device_persistent(self, get_ilo_object_mock):
        ilo_mock = get_ilo_object_mock.return_value
        ilo_mock.get_one_time_boot.return_value = 'Normal'
        ilo_mock.get_persistent_boot_device.return_value = 'NETWORK'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_device = boot_devices.PXE
            expected_response = {'boot_device': expected_device,
                                 'persistent': True}
            self.assertEqual(expected_response,
                             task.driver.management.get_boot_device(task))
            ilo_mock.get_one_time_boot.assert_called_once_with()
            ilo_mock.get_persistent_boot_device.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_device_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.get_one_time_boot.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.get_boot_device,
                              task)
        ilo_mock_object.get_one_time_boot.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_device_persistent_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        ilo_mock_object.get_one_time_boot.return_value = 'Normal'
        exc = ilo_error.IloError('error')
        ilo_mock_object.get_persistent_boot_device.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.get_boot_device,
                              task)
        ilo_mock_object.get_one_time_boot.assert_called_once_with()
        ilo_mock_object.get_persistent_boot_device.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_device_ok(self, get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_devices.CDROM,
                                                   False)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_object_mock.set_one_time_boot.assert_called_once_with('CDROM')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_device_persistent_true(self, get_ilo_object_mock):
        ilo_mock = get_ilo_object_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_boot_device(task, boot_devices.PXE,
                                                   True)
            get_ilo_object_mock.assert_called_once_with(task.node)
            ilo_mock.update_persistent_boot.assert_called_once_with(
                ['NETWORK'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_device_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.set_one_time_boot.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.set_boot_device,
                              task, boot_devices.PXE)
        ilo_mock_object.set_one_time_boot.assert_called_once_with('NETWORK')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_boot_device_persistent_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.update_persistent_boot.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.set_boot_device,
                              task, boot_devices.PXE, True)
        ilo_mock_object.update_persistent_boot.assert_called_once_with(
            ['NETWORK'])

    def test_set_boot_device_invalid_device(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, 'fake-device')

    @mock.patch.object(ilo_common, 'update_ipmi_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipmitool.IPMIManagement, 'get_sensors_data',
                       spec_set=True, autospec=True)
    def test_get_sensor_data(self, get_sensors_data_mock, update_ipmi_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.get_sensors_data(task)
            update_ipmi_mock.assert_called_once_with(task)
            get_sensors_data_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_ilo_step_ok(self, get_ilo_object_mock):
        ilo_mock = get_ilo_object_mock.return_value
        step_mock = getattr(ilo_mock, 'fake-step')
        ilo_management._execute_ilo_step(
            self.node, 'fake-step', 'args', kwarg='kwarg')
        step_mock.assert_called_once_with('args', kwarg='kwarg')

    @mock.patch.object(ilo_management, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_ilo_step_not_supported(self, get_ilo_object_mock,
                                             log_mock):
        ilo_mock = get_ilo_object_mock.return_value
        exc = ilo_error.IloCommandNotSupportedError("error")
        step_mock = getattr(ilo_mock, 'fake-step')
        step_mock.side_effect = exc
        ilo_management._execute_ilo_step(
            self.node, 'fake-step', 'args', kwarg='kwarg')
        step_mock.assert_called_once_with('args', kwarg='kwarg')
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_ilo_step_fail(self, get_ilo_object_mock):
        if self.node.clean_step:
            step = self.node.clean_step
            step_name = step['step']
            exept = exception.NodeCleaningFailure
        else:
            step = self.node.deploy_step
            step_name = step['step']
            exept = exception.InstanceDeployFailure
        ilo_mock = get_ilo_object_mock.return_value
        exc = ilo_error.IloError("error")
        step_mock = getattr(ilo_mock, step_name)
        step_mock.side_effect = exc
        self.assertRaises(exept,
                          ilo_management._execute_ilo_step,
                          self.node, step_name, 'args', kwarg='kwarg')
        step_mock.assert_called_once_with('args', kwarg='kwarg')

    def test__execute_ilo_step_fail_clean(self):
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'fake-step',
                                'argsinfo': {}}
        self.node.save()
        self._test__execute_ilo_step_fail()

    def test__execute_ilo_step_fail_deploy(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'fake-step',
                                 'argsinfo': {}}
        self.node.save()
        self._test__execute_ilo_step_fail()

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'clean_up_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_ilo(
            self, execute_step_mock, prepare_mock, cleanup_mock, build_mock):
        build_mock.return_value = {'a': 'b'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_ilo(task)
            execute_step_mock.assert_called_once_with(task.node, 'reset_ilo')
            cleanup_mock.assert_called_once_with(mock.ANY, task)
            build_mock.assert_called_once_with(task.node)
            prepare_mock.assert_called_once_with(
                mock.ANY, mock.ANY, {'a': 'b'})

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_ilo_credential_ok(self, step_mock):
        info = self.node.driver_info
        info['ilo_change_password'] = "fake-password"
        self.node.driver_info = info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_ilo_credential(task)
            step_mock.assert_called_once_with(
                task.node, 'reset_ilo_credential', 'fake-password')
            self.assertNotIn('ilo_change_password', task.node.driver_info)
            self.assertEqual('fake-password',
                             task.node.driver_info['ilo_password'])

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_ilo_credential_pass_as_arg_ok(self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_ilo_credential(
                task, change_password='fake-password')
            step_mock.assert_called_once_with(
                task.node, 'reset_ilo_credential', 'fake-password')
            self.assertNotIn('ilo_change_password', task.node.driver_info)
            self.assertEqual('fake-password',
                             task.node.driver_info['ilo_password'])

    @mock.patch.object(ilo_management, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_ilo_credential_no_password(self, step_mock,
                                              log_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_ilo_credential(task)
            self.assertFalse(step_mock.called)
            self.assertTrue(log_mock.info.called)

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_bios_to_default(self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_bios_to_default(task)
            step_mock.assert_called_once_with(task.node,
                                              'reset_bios_to_default')

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_reset_secure_boot_keys_to_default(self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.reset_secure_boot_keys_to_default(task)
            step_mock.assert_called_once_with(task.node,
                                              'reset_secure_boot_keys')

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_clear_secure_boot_keys(self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.clear_secure_boot_keys(task)
            step_mock.assert_called_once_with(task.node,
                                              'clear_secure_boot_keys')

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_activate_license(self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            activate_license_args = {
                'ilo_license_key': 'XXXXX-YYYYY-ZZZZZ-XYZZZ-XXYYZ'}
            task.driver.management.activate_license(task,
                                                    **activate_license_args)
            step_mock.assert_called_once_with(
                task.node, 'activate_license', 'XXXXX-YYYYY-ZZZZZ-XYZZZ-XXYYZ')

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    def test_activate_license_no_or_invalid_format_license_key(
            self, step_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            for license_key_value in (None, [], {}):
                activate_license_args = {'ilo_license_key': license_key_value}
                self.assertRaises(exception.InvalidParameterValue,
                                  task.driver.management.activate_license,
                                  task,
                                  **activate_license_args)
                self.assertFalse(step_mock.called)

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'clean_up_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management, 'LOG', autospec=True)
    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.firmware_processor, 'FirmwareProcessor',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'remove_single_or_list_of_files',
                       spec_set=True, autospec=True)
    def _test_update_firmware_calls_step_foreach_url(
            self, remove_file_mock, FirmwareProcessor_mock, execute_step_mock,
            LOG_mock, prepare_mock, cleanup_mock, build_mock):
        if self.node.clean_step:
            step = self.node.clean_step
        else:
            step = self.node.deploy_step
        build_mock.return_value = {'a': 'b'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            FirmwareProcessor_mock.return_value.process_fw_on.side_effect = [
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'fw_location_for_filepath', 'filepath'),
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'fw_location_for_httppath', 'httppath'),
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'fw_location_for_httpspath', 'httpspath'),
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'fw_location_for_swiftpath', 'swiftpath'),
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'fw_location_for_another_filepath', 'filepath2')
            ]
            task.driver.management.update_firmware(task,
                                                   **firmware_update_args)
            calls = [mock.call(task.node, 'update_firmware',
                               'fw_location_for_filepath', 'ilo'),
                     mock.call(task.node, 'update_firmware',
                               'fw_location_for_httppath', 'cpld'),
                     mock.call(task.node, 'update_firmware',
                               'fw_location_for_httpspath', 'power_pic'),
                     mock.call(task.node, 'update_firmware',
                               'fw_location_for_swiftpath', 'bios'),
                     mock.call(task.node, 'update_firmware',
                               'fw_location_for_another_filepath', 'chassis'),
                     ]
            execute_step_mock.assert_has_calls(calls)
            self.assertEqual(5, execute_step_mock.call_count)
            cleanup_mock.assert_called_once_with(mock.ANY, task)
            build_mock.assert_called_once_with(task.node)
            prepare_mock.assert_called_once_with(
                mock.ANY, mock.ANY, {'a': 'b'})

    def test_update_firmware_calls_step_foreach_url_clean(self):
        firmware_images = [
            {
                'url': 'file:///any_path',
                'checksum': 'xxxx',
                'component': 'ilo'
            },
            {
                'url': 'http://any_url',
                'checksum': 'xxxx',
                'component': 'cpld'
            },
            {
                'url': 'https://any_url',
                'checksum': 'xxxx',
                'component': 'power_pic'
            },
            {
                'url': 'swift://container/object',
                'checksum': 'xxxx',
                'component': 'bios'
            },
            {
                'url': 'file:///any_path',
                'checksum': 'xxxx',
                'component': 'chassis'
            }
        ]
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': firmware_images}
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_calls_step_foreach_url()

    def test_update_firmware_calls_step_foreach_url_deploy(self):
        firmware_images = [
            {
                'url': 'file:///any_path',
                'checksum': 'xxxx',
                'component': 'ilo'
            },
            {
                'url': 'http://any_url',
                'checksum': 'xxxx',
                'component': 'cpld'
            },
            {
                'url': 'https://any_url',
                'checksum': 'xxxx',
                'component': 'power_pic'
            },
            {
                'url': 'swift://container/object',
                'checksum': 'xxxx',
                'component': 'bios'
            },
            {
                'url': 'file:///any_path',
                'checksum': 'xxxx',
                'component': 'chassis'
            }
        ]
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': firmware_images}
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_calls_step_foreach_url()

    def _test_update_firmware_invalid_update_mode_provided(self):
        if self.node.clean_step:
            step = self.node.clean_step
        else:
            step = self.node.deploy_step
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            firmware_update_args = {'firmware_update_mode': 'invalid_mode',
                                    'firmware_images': None}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)

    def test_update_firmware_invalid_update_mode_provided_clean(self):
        firmware_update_args = {'firmware_update_mode': 'invalid_mode',
                                'firmware_images': None}
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_invalid_update_mode_provided()

    def test_update_firmware_invalid_update_mode_provided_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'invalid_mode',
                                'firmware_images': None}
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_invalid_update_mode_provided()

    def _test_update_firmware_error_for_no_firmware_url(self):
        if self.node.clean_step:
            step = self.node.clean_step
        else:
            step = self.node.deploy_step
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            firmware_update_args = {'firmware_update_mode': 'ilo',
                                    'firmware_images': []}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)

    def test_update_firmware_error_for_no_firmware_url_clean(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': []}
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_error_for_no_firmware_url()

    def test_update_firmware_error_for_no_firmware_url_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': []}
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_error_for_no_firmware_url()

    def _test_update_firmware_throws_error_for_invalid_component_type(self):
        if self.node.clean_step:
            step = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step = self.node.deploy_step
            exept = exception.InstanceDeployFailure
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            self.assertRaises(exept,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)

    def test_update_firmware_error_for_invalid_component_type_clean(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'xyz'
                                    }
                                ]}
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_throws_error_for_invalid_component_type()

    def test_update_firmware_error_for_invalid_component_type_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'xyz'
                                    }
                                ]}
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_throws_error_for_invalid_component_type()

    @mock.patch.object(ilo_management, 'LOG', autospec=True)
    @mock.patch.object(ilo_management.firmware_processor.FirmwareProcessor,
                       'process_fw_on', spec_set=True, autospec=True)
    def _test_update_firmware_throws_error_for_checksum_validation_error(
            self, process_fw_on_mock, LOG_mock):
        if self.node.clean_step:
            step = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step = self.node.deploy_step
            exept = exception.InstanceDeployFailure
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # | GIVEN |
            firmware_update_args = step['argsinfo']
            process_fw_on_mock.side_effect = exception.ImageRefValidationFailed
            # | WHEN & THEN |
            self.assertRaises(exept,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)

    def test_update_firmware_error_for_checksum_validation_error_clean(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'invalid_checksum',
                                        'component': 'bios'
                                    }
                                ]}
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_throws_error_for_checksum_validation_error()

    def test_update_firmware_error_for_checksum_validation_error_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'invalid_checksum',
                                        'component': 'bios'
                                    }
                                ]}
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_throws_error_for_checksum_validation_error()

    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.firmware_processor, 'FirmwareProcessor',
                       spec_set=True, autospec=True)
    def _test_update_firmware_doesnt_update_any_if_any_url_fails(
            self, FirmwareProcessor_mock, clean_step_mock):
        """update_firmware throws error for failure in processing any url

        update_firmware doesn't invoke firmware update of proliantutils
        for any url if processing on any firmware url fails.
        """
        if self.node.clean_step:
            step = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step = self.node.deploy_step
            exept = exception.InstanceDeployFailure
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            FirmwareProcessor_mock.return_value.process_fw_on.side_effect = [
                ilo_management.firmware_processor.FirmwareImageLocation(
                    'extracted_firmware_url_of_any_valid_url', 'filename'),
                exception.IronicException
            ]
            self.assertRaises(exept,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)
            self.assertFalse(clean_step_mock.called)

    def test_update_firmware_doesnt_update_any_if_any_url_fails_clean(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'ilo'
                                    },
                                    {
                                        'url': 'any_invalid_url',
                                        'checksum': 'xxxx',
                                        'component': 'bios'
                                    }]
                                }
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_doesnt_update_any_if_any_url_fails()

    def test_update_firmware_doesnt_update_any_if_any_url_fails_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'ilo'
                                    },
                                    {
                                        'url': 'any_invalid_url',
                                        'checksum': 'xxxx',
                                        'component': 'bios'
                                    }]
                                }
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_doesnt_update_any_if_any_url_fails()

    @mock.patch.object(ilo_management, 'LOG', autospec=True)
    @mock.patch.object(ilo_management, '_execute_ilo_step',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.firmware_processor, 'FirmwareProcessor',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.firmware_processor.FirmwareImageLocation,
                       'remove', spec_set=True, autospec=True)
    def _test_update_firmware_cleans_all_files_if_exc_thrown(
            self, remove_mock, FirmwareProcessor_mock, clean_step_mock,
            LOG_mock):
        if self.node.clean_step:
            step = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step = self.node.deploy_step
            exept = exception.InstanceDeployFailure
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            firmware_update_args = step['argsinfo']
            fw_loc_obj_1 = (ilo_management.firmware_processor.
                            FirmwareImageLocation('extracted_firmware_url_1',
                                                  'filename_1'))
            fw_loc_obj_2 = (ilo_management.firmware_processor.
                            FirmwareImageLocation('extracted_firmware_url_2',
                                                  'filename_2'))
            FirmwareProcessor_mock.return_value.process_fw_on.side_effect = [
                fw_loc_obj_1, fw_loc_obj_2
            ]
            clean_step_mock.side_effect = exept(
                node=self.node.uuid, reason='ilo_exc')
            self.assertRaises(exept,
                              task.driver.management.update_firmware,
                              task,
                              **firmware_update_args)
            clean_step_mock.assert_called_once_with(
                task.node, 'update_firmware',
                'extracted_firmware_url_1', 'ilo')
            self.assertTrue(LOG_mock.error.called)
            remove_mock.assert_has_calls([mock.call(fw_loc_obj_1),
                                          mock.call(fw_loc_obj_2)])

    def test_update_firmware_cleans_all_files_if_exc_thrown_clean(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'ilo'
                                    },
                                    {
                                        'url': 'any_invalid_url',
                                        'checksum': 'xxxx',
                                        'component': 'bios'
                                    }]
                                }
        self.node.clean_step = {'priority': 100, 'interface': 'management',
                                'step': 'update_firmware',
                                'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_cleans_all_files_if_exc_thrown()

    def test_update_firmware_cleans_all_files_if_exc_thrown_deploy(self):
        firmware_update_args = {'firmware_update_mode': 'ilo',
                                'firmware_images': [
                                    {
                                        'url': 'any_valid_url',
                                        'checksum': 'xxxx',
                                        'component': 'ilo'
                                    },
                                    {
                                        'url': 'any_invalid_url',
                                        'checksum': 'xxxx',
                                        'component': 'bios'
                                    }]
                                }
        self.node.deploy_step = {'priority': 100, 'interface': 'management',
                                 'step': 'update_firmware',
                                 'argsinfo': firmware_update_args}
        self.node.save()
        self._test_update_firmware_cleans_all_files_if_exc_thrown()

    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def _test_write_firmware_sum_mode_with_component(
            self, execute_mock, attach_vmedia_mock, step_type='clean'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # | GIVEN |
            firmware_update_args = {
                'url': 'http://any_url',
                'checksum': 'xxxx',
                'component': ['CP02345.scexe', 'CP02567.exe']}
            step = {'interface': 'management',
                    'args': firmware_update_args}
            if step_type == 'clean':
                step['step'] = 'update_firmware_sum'
                task.node.provision_state = states.CLEANING
                execute_mock.return_value = states.CLEANWAIT
                task.node.clean_step = step
                func = task.driver.management.update_firmware_sum
                exp_ret_state = states.CLEANWAIT
            else:
                step['step'] = 'flash_firmware_sum'
                task.node.provision_state = states.DEPLOYING
                execute_mock.return_value = states.DEPLOYWAIT
                task.node.deploy_step = step
                func = task.driver.management.flash_firmware_sum
                exp_ret_state = states.DEPLOYWAIT
            # | WHEN |
            return_value = func(task, **firmware_update_args)
            # | THEN |
            attach_vmedia_mock.assert_any_call(
                task.node, 'CDROM', 'http://any_url')
            self.assertEqual(exp_ret_state, return_value)
            execute_mock.assert_called_once_with(task, step, step_type)

    def test_update_firmware_sum_mode_with_component(self):
        self._test_write_firmware_sum_mode_with_component(step_type='clean')

    def test_flash_firmware_sum_mode_with_component(self):
        self._test_write_firmware_sum_mode_with_component(step_type='deploy')

    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_management.firmware_processor,
                       'get_swift_url', autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def _test_write_firmware_sum_mode_swift_url(
            self, execute_mock, swift_url_mock, attach_vmedia_mock,
            step_type='clean'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # | GIVEN |
            swift_url_mock.return_value = "http://path-to-file"
            firmware_update_args = {
                'url': 'swift://container/object',
                'checksum': 'xxxx',
                'components': ['CP02345.scexe', 'CP02567.exe']}
            step = {'interface': 'management',
                    'args': firmware_update_args}
            if step_type == 'clean':
                task.node.provision_state = states.CLEANING
                execute_mock.return_value = states.CLEANWAIT
                step['step'] = 'update_firmware_sum',
                task.node.clean_step = step
                func = task.driver.management.update_firmware_sum
                exp_ret_state = states.CLEANWAIT
                args_data = task.node.clean_step['args']
            else:
                task.node.provision_state = states.DEPLOYING
                execute_mock.return_value = states.DEPLOYWAIT
                step['step'] = 'flash_firmware_sum',
                task.node.deploy_step = step
                func = task.driver.management.flash_firmware_sum
                exp_ret_state = states.DEPLOYWAIT
                args_data = task.node.deploy_step['args']
            # | WHEN |
            return_value = func(task, **firmware_update_args)
            # | THEN |
            attach_vmedia_mock.assert_any_call(
                task.node, 'CDROM', 'http://path-to-file')
            self.assertEqual(exp_ret_state, return_value)
            self.assertEqual(args_data['url'], "http://path-to-file")

    def test_write_firmware_sum_mode_swift_url_clean(self):
        self._test_write_firmware_sum_mode_swift_url(step_type='clean')

    def test_write_firmware_sum_mode_swift_url_deploy(self):
        self._test_write_firmware_sum_mode_swift_url(step_type='deploy')

    @mock.patch.object(ilo_common, 'attach_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def _test_write_firmware_sum_mode_without_component(
            self, execute_mock, attach_vmedia_mock, step_type='clean'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # | GIVEN |
            firmware_update_args = {
                'url': 'any_valid_url',
                'checksum': 'xxxx'}
            step = {'interface': 'management',
                    'args': firmware_update_args}
            if step_type == 'clean':
                task.node.provision_state = states.CLEANING
                execute_mock.return_value = states.CLEANWAIT
                step['step'] = 'update_firmware_sum'
                task.node.clean_step = step
                func = task.driver.management.update_firmware_sum
                exp_ret_state = states.CLEANWAIT
            else:
                task.node.provision_state = states.DEPLOYING
                execute_mock.return_value = states.DEPLOYWAIT
                step['step'] = 'flash_firmware_sum'
                task.node.deploy_step = step
                func = task.driver.management.flash_firmware_sum
                exp_ret_state = states.DEPLOYWAIT
            # | WHEN |
            return_value = func(task, **firmware_update_args)
            # | THEN |
            attach_vmedia_mock.assert_any_call(
                task.node, 'CDROM', 'any_valid_url')
            self.assertEqual(exp_ret_state, return_value)
            execute_mock.assert_called_once_with(task, step, step_type)

    def test_write_firmware_sum_mode_without_component_clean(self):
        self._test_write_firmware_sum_mode_without_component(
            step_type='clean')

    def test_write_firmware_sum_mode_without_component_deploy(self):
        self._test_write_firmware_sum_mode_without_component(
            step_type='deploy')

    def _test_write_firmware_sum_mode_invalid_component(self,
                                                        step_type='clean'):
        # | GIVEN |
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx',
            'components': ['CP02345']}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            # | WHEN & THEN |
            if step_type == 'clean':
                func = task.driver.management.update_firmware_sum
            else:
                func = task.driver.management.flash_firmware_sum
            self.assertRaises(exception.InvalidParameterValue,
                              func, task, **firmware_update_args)

    def test_write_firmware_sum_mode_invalid_component_clean(self):
        self._test_write_firmware_sum_mode_invalid_component(
            step_type='clean')

    def test_write_firmware_sum_mode_invalid_component_deploy(self):
        self._test_write_firmware_sum_mode_invalid_component(
            step_type='deploy')

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    def _test__write_firmware_sum_final_with_logs(self, store_mock,
                                                  step_type='clean'):
        self.config(deploy_logs_collect='always', group='agent')
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx'}
        step = {'interface': 'management',
                'args': firmware_update_args}
        if step_type == 'clean':
            step['step'] = 'update_firmware_sum'
            node_state = states.CLEANWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'clean_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'clean_step': step,
                }
            }
            exp_label = 'update_firmware_sum'
        else:
            step['step'] = 'flash_firmware_sum'
            node_state = states.DEPLOYWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'deploy_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'deploy_step': step,
                }
            }
            exp_label = 'flash_firmware_sum'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = node_state
            task.driver.management._update_firmware_sum_final(
                task, command)
            store_mock.assert_called_once_with(task.node, 'aaaabbbbcccdddd',
                                               label=exp_label)

    def test__write_firmware_sum_final_with_logs_clean(self):
        self._test__write_firmware_sum_final_with_logs(step_type='clean')

    def test__write_firmware_sum_final_with_logs_deploy(self):
        self._test__write_firmware_sum_final_with_logs(step_type='deploy')

    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    def _test__write_firmware_sum_final_without_logs(self, store_mock,
                                                     step_type='clean'):
        self.config(deploy_logs_collect='on_failure', group='agent')
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx'}
        step = {'interface': 'management',
                'args': firmware_update_args}
        if step_type == 'clean':
            step['step'] = 'update_firmware_sum'
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'clean_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'clean_step': step,
                }
            }
        else:
            step['step'] = 'flash_firmware_sum'
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'deploy_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'deploy_step': step,
                }
            }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management._update_firmware_sum_final(
                task, command)
        self.assertFalse(store_mock.called)

    def test__write_firmware_sum_final_without_logs_clean(self):
        self._test__write_firmware_sum_final_without_logs(step_type='clean')

    def test__write_firmware_sum_final_without_logs_deploy(self):
        self._test__write_firmware_sum_final_without_logs(step_type='deploy')

    @mock.patch.object(ilo_management, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    def _test__write_firmware_sum_final_swift_error(self, store_mock,
                                                    log_mock,
                                                    step_type='clean'):
        self.config(deploy_logs_collect='always', group='agent')
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx'}
        step = {'interface': 'management',
                'args': firmware_update_args}
        if step_type == 'clean':
            step['step'] = 'update_firmware_sum'
            node_state = states.CLEANWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'clean_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'clean_step': step,
                }
            }
        else:
            step['step'] = 'flash_firmware_sum'
            node_state = states.DEPLOYWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'deploy_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'deploy_step': step,
                }
            }
        store_mock.side_effect = exception.SwiftOperationError('Error')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = node_state
            task.driver.management._update_firmware_sum_final(
                task, command)
        self.assertTrue(log_mock.error.called)

    def test__write_firmware_sum_final_swift_error_clean(self):
        self._test__write_firmware_sum_final_swift_error(step_type='clean')

    def test__write_firmware_sum_final_swift_error_deploy(self):
        self._test__write_firmware_sum_final_swift_error(step_type='deploy')

    @mock.patch.object(ilo_management, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    def _test__write_firmware_sum_final_environment_error(self, store_mock,
                                                          log_mock,
                                                          step_type='clean'):
        self.config(deploy_logs_collect='always', group='agent')
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx'}
        step = {'interface': 'management',
                'args': firmware_update_args}
        if step_type == 'clean':
            step['step'] = 'update_firmware_sum'
            node_state = states.CLEANWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'clean_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'clean_step': step,
                }
            }
        else:
            step['step'] = 'flash_firmware_sum'
            node_state = states.DEPLOYWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'deploy_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'deploy_step': step,
                }
            }
        store_mock.side_effect = EnvironmentError('Error')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = node_state
            task.driver.management._update_firmware_sum_final(
                task, command)
        self.assertTrue(log_mock.exception.called)

    def test__write_firmware_sum_final_environment_error_clean(self):
        self._test__write_firmware_sum_final_environment_error(
            step_type='clean')

    def test__write_firmware_sum_final_environment_error_deploy(self):
        self._test__write_firmware_sum_final_environment_error(
            step_type='deploy')

    @mock.patch.object(ilo_management, 'LOG', spec_set=True, autospec=True)
    @mock.patch.object(driver_utils, 'store_ramdisk_logs', autospec=True)
    def _test__write_firmware_sum_final_unknown_exception(self, store_mock,
                                                          log_mock,
                                                          step_type='clean'):
        self.config(deploy_logs_collect='always', group='agent')
        firmware_update_args = {
            'url': 'any_valid_url',
            'checksum': 'xxxx'}
        step = {'interface': 'management',
                'args': firmware_update_args}
        if step_type == 'clean':
            step['step'] = 'update_firmware_sum'
            node_state = states.CLEANWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'clean_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'clean_step': step,
                }
            }
        else:
            step['step'] = 'flash_firmware_sum'
            node_state = states.DEPLOYWAIT
            command = {
                'command_status': 'SUCCEEDED',
                'command_result': {
                    'deploy_result': {'Log Data': 'aaaabbbbcccdddd'},
                    'deploy_step': step,
                }
            }
        store_mock.side_effect = Exception('Error')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = node_state
            task.driver.management._update_firmware_sum_final(
                task, command)
        self.assertTrue(log_mock.exception.called)

    def test__write_firmware_sum_final_unknown_exception_clean(self):
        self._test__write_firmware_sum_final_unknown_exception(
            step_type='clean')

    def test__write_firmware_sum_final_unknown_exception_deploy(self):
        self._test__write_firmware_sum_final_unknown_exception(
            step_type='deploy')

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_iscsi_boot_target_with_auth(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vol_id = uuidutils.generate_uuid()
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id, volume_type='iscsi',
                boot_index=0, volume_id='1234', uuid=vol_id,
                properties={'target_lun': 0,
                            'target_portal': 'fake_host:3260',
                            'target_iqn': 'fake_iqn',
                            'auth_username': 'fake_username',
                            'auth_password': 'fake_password'})
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_from_volume'] = vol_id
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            task.driver.management.set_iscsi_boot_target(task)
            ilo_object_mock.set_iscsi_info.assert_called_once_with(
                'fake_iqn', 0, 'fake_host', '3260',
                auth_method='CHAP', username='fake_username',
                password='fake_password',
                macs=['11:22:33:44:55:66', '11:22:33:44:55:67'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_iscsi_boot_target_without_auth(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vol_id = uuidutils.generate_uuid()
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id, volume_type='iscsi',
                boot_index=0, volume_id='1234', uuid=vol_id,
                properties={'target_lun': 0,
                            'target_portal': 'fake_host:3260',
                            'target_iqn': 'fake_iqn'})
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_from_volume'] = vol_id
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            task.driver.management.set_iscsi_boot_target(task)
            ilo_object_mock.set_iscsi_info.assert_called_once_with(
                'fake_iqn', 0, 'fake_host', '3260', auth_method=None,
                password=None, username=None,
                macs=['11:22:33:44:55:66', '11:22:33:44:55:67'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_iscsi_boot_target_failed(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vol_id = uuidutils.generate_uuid()
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id, volume_type='iscsi',
                boot_index=0, volume_id='1234', uuid=vol_id,
                properties={'target_lun': 0,
                            'target_portal': 'fake_host:3260',
                            'target_iqn': 'fake_iqn',
                            'auth_username': 'fake_username',
                            'auth_password': 'fake_password'})
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_from_volume'] = vol_id
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.set_iscsi_info.side_effect = (
                ilo_error.IloError('error'))
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.set_iscsi_boot_target,
                              task)

    def test_set_iscsi_boot_target_missed_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vol_id = uuidutils.generate_uuid()
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id, volume_type='iscsi',
                boot_index=0, volume_id='1234', uuid=vol_id,
                properties={'target_iqn': 'fake_iqn',
                            'auth_username': 'fake_username',
                            'auth_password': 'fake_password'})
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_from_volume'] = vol_id
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.set_iscsi_boot_target,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_set_iscsi_boot_target_in_bios(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            vol_id = uuidutils.generate_uuid()
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id, volume_type='iscsi',
                boot_index=0, volume_id='1234', uuid=vol_id,
                properties={'target_lun': 0,
                            'target_portal': 'fake_host:3260',
                            'target_iqn': 'fake_iqn',
                            'auth_username': 'fake_username',
                            'auth_password': 'fake_password'})
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['boot_from_volume'] = vol_id
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.set_iscsi_info.side_effect = (
                ilo_error.IloCommandNotSupportedInBiosError('error'))
            self.assertRaises(exception.IloOperationNotSupported,
                              task.driver.management.set_iscsi_boot_target,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_clear_iscsi_boot_target(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value

            task.driver.management.clear_iscsi_boot_target(task)
            ilo_object_mock.unset_iscsi_info.assert_called_once_with(
                macs=['11:22:33:44:55:66', '11:22:33:44:55:67'])

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_clear_iscsi_boot_target_failed(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.unset_iscsi_info.side_effect = (
                ilo_error.IloError('error'))
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.clear_iscsi_boot_target,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_clear_iscsi_boot_target_in_bios(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.unset_iscsi_info.side_effect = (
                ilo_error.IloCommandNotSupportedInBiosError('error'))
            self.assertRaises(exception.IloOperationNotSupported,
                              task.driver.management.clear_iscsi_boot_target,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inject_nmi(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value

            task.driver.management.inject_nmi(task)
            ilo_object_mock.inject_nmi.assert_called_once()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inject_nmi_failed(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.inject_nmi.side_effect = (
                ilo_error.IloError('error'))
            self.assertRaises(exception.IloOperationError,
                              task.driver.management.inject_nmi,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_inject_nmi_not_supported(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.inject_nmi.side_effect = (
                ilo_error.IloCommandNotSupportedError('error'))
            self.assertRaises(exception.IloOperationNotSupported,
                              task.driver.management.inject_nmi,
                              task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    @ddt.data((ilo_common.SUPPORTED_BOOT_MODE_LEGACY_BIOS_ONLY,
               ['bios']),
              (ilo_common.SUPPORTED_BOOT_MODE_UEFI_ONLY,
               ['uefi']),
              (ilo_common.SUPPORTED_BOOT_MODE_LEGACY_BIOS_AND_UEFI,
               ['uefi', 'bios']))
    @ddt.unpack
    def test_get_supported_boot_modes(self, boot_modes_val,
                                      exp_boot_modes,
                                      get_ilo_object_mock):
        ilo_object_mock = get_ilo_object_mock.return_value
        ilo_object_mock.get_supported_boot_mode.return_value = boot_modes_val
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            supported_boot_modes = (
                task.driver.management.get_supported_boot_modes(task))
            self.assertEqual(exp_boot_modes, supported_boot_modes)

    @mock.patch.object(ilo_common, 'set_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_management.IloManagement,
                       'get_supported_boot_modes',
                       spec_set=True, autospec=True)
    def test_set_boot_mode(self, supp_boot_modes_mock,
                           set_boot_mode_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            exp_boot_modes = [boot_modes.UEFI, boot_modes.LEGACY_BIOS]
            supp_boot_modes_mock.return_value = exp_boot_modes

            for mode in exp_boot_modes:
                task.driver.management.set_boot_mode(task, mode=mode)
                supp_boot_modes_mock.assert_called_once_with(mock.ANY, task)
                set_boot_mode_mock.assert_called_once_with(task.node, mode)
                set_boot_mode_mock.reset_mock()
                supp_boot_modes_mock.reset_mock()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_management.IloManagement,
                       'get_supported_boot_modes',
                       spec_set=True, autospec=True)
    def test_set_boot_mode_fail(self, supp_boot_modes_mock,
                                get_ilo_object_mock):
        ilo_mock_obj = get_ilo_object_mock.return_value
        ilo_mock_obj.get_pending_boot_mode.return_value = 'legacy'
        exc = ilo_error.IloError('error')
        ilo_mock_obj.set_pending_boot_mode.side_effect = exc
        exp_boot_modes = [boot_modes.UEFI, boot_modes.LEGACY_BIOS]
        supp_boot_modes_mock.return_value = exp_boot_modes
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(
                exception.IloOperationError, 'uefi as boot mode failed',
                task.driver.management.set_boot_mode, task, boot_modes.UEFI)
            supp_boot_modes_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_mode(self, get_ilo_object_mock):
        expected = 'bios'
        ilo_mock_obj = get_ilo_object_mock.return_value
        ilo_mock_obj.get_current_boot_mode.return_value = 'LEGACY'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            response = task.driver.management.get_boot_mode(task)
            self.assertEqual(expected, response)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_get_boot_mode_fail(self, get_ilo_object_mock):
        ilo_mock_obj = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_obj.get_current_boot_mode.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaisesRegex(
                exception.IloOperationError, 'Get current boot mode',
                task.driver.management.get_boot_mode, task)


class Ilo5ManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(Ilo5ManagementTestCase, self).setUp()
        self.driver = mock.Mock(management=ilo_management.Ilo5Management())
        self.clean_step = {'step': 'erase_devices',
                           'interface': 'management'}
        n = {
            'driver': 'ilo5',
            'driver_info': INFO_DICT,
            'clean_step': self.clean_step,
        }
        self.config(enabled_hardware_types=['ilo5'],
                    enabled_boot_interfaces=['ilo-virtual-media'],
                    enabled_console_interfaces=['ilo'],
                    enabled_deploy_interfaces=['iscsi'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_management_interfaces=['ilo5'],
                    enabled_power_interfaces=['ilo'],
                    enabled_raid_interfaces=['ilo5'])
        self.node = obj_utils.create_test_node(self.context, **n)

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_erase_devices_hdd(self, mock_power, ilo_mock, build_agent_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['HDD']
        build_agent_mock.return_value = []
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.management.erase_devices(task)
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'cleaning_reboot'))
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'skip_current_clean_step'))
            ilo_mock_object.do_disk_erase.assert_called_once_with(
                'HDD', 'overwrite')
            self.assertEqual(states.CLEANWAIT, result)
            mock_power.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_erase_devices_ssd(self, mock_power, ilo_mock, build_agent_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['SSD']
        build_agent_mock.return_value = []
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.management.erase_devices(task)
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_ssd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'cleaning_reboot'))
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'skip_current_clean_step'))
            ilo_mock_object.do_disk_erase.assert_called_once_with(
                'SSD', 'block')
            self.assertEqual(states.CLEANWAIT, result)
            mock_power.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_erase_devices_ssd_when_hdd_done(self, mock_power, ilo_mock,
                                             build_agent_mock):
        build_agent_mock.return_value = []
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['HDD', 'SSD']
        self.node.driver_internal_info = {'ilo_disk_erase_hdd_check': True}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.management.erase_devices(task)
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_ssd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'cleaning_reboot'))
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'skip_current_clean_step'))
            ilo_mock_object.do_disk_erase.assert_called_once_with(
                'SSD', 'block')
            self.assertEqual(states.CLEANWAIT, result)
            mock_power.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(ilo_management.LOG, 'info', autospec=True)
    @mock.patch.object(ilo_management.Ilo5Management,
                       '_wait_for_disk_erase_status', autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_erase_devices_completed(self, ilo_mock, disk_status_mock,
                                     log_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['HDD', 'SSD']
        disk_status_mock.return_value = True
        self.node.driver_internal_info = {'ilo_disk_erase_hdd_check': True,
                                          'ilo_disk_erase_ssd_check': True}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.erase_devices(task)
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertTrue(log_mock.called)

    @mock.patch.object(deploy_utils, 'build_agent_options',
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_erase_devices_hdd_with_erase_pattern_zero(
            self, mock_power, ilo_mock, build_agent_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['HDD']
        build_agent_mock.return_value = []
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.management.erase_devices(
                task, erase_pattern={'hdd': 'zero', 'ssd': 'zero'})
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'ilo_disk_erase_hdd_check'))
            self.assertTrue(
                task.node.driver_internal_info.get(
                    'cleaning_reboot'))
            self.assertFalse(
                task.node.driver_internal_info.get(
                    'skip_current_clean_step'))
            ilo_mock_object.do_disk_erase.assert_called_once_with(
                'HDD', 'zero')
            self.assertEqual(states.CLEANWAIT, result)
            mock_power.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(ilo_management.LOG, 'info', autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_erase_devices_when_no_drive_available(
            self, ilo_mock, log_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = []
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.erase_devices(task)
            self.assertTrue(log_mock.called)

    def test_erase_devices_hdd_with_invalid_format_erase_pattern(
            self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.erase_devices,
                              task, erase_pattern=123)

    def test_erase_devices_hdd_with_invalid_device_type_erase_pattern(
            self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.erase_devices,
                              task, erase_pattern={'xyz': 'block'})

    def test_erase_devices_hdd_with_invalid_erase_pattern(
            self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.erase_devices,
                              task, erase_pattern={'ssd': 'xyz'})

    @mock.patch.object(ilo_management.LOG, 'error', autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(ilo_management.Ilo5Management, '_set_clean_failed',
                       autospec=True)
    def test_erase_devices_hdd_ilo_error(self, set_clean_failed_mock,
                                         ilo_mock, log_mock):
        ilo_mock_object = ilo_mock.return_value
        ilo_mock_object.get_available_disk_types.return_value = ['HDD']
        exc = ilo_error.IloError('error')
        ilo_mock_object.do_disk_erase.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.erase_devices(task)
            ilo_mock_object.do_disk_erase.assert_called_once_with(
                'HDD', 'overwrite')
            self.assertNotIn('ilo_disk_erase_hdd_check',
                             task.node.driver_internal_info)
            self.assertNotIn('ilo_disk_erase_ssd_check',
                             task.node.driver_internal_info)
            self.assertNotIn('cleaning_reboot',
                             task.node.driver_internal_info)
            self.assertNotIn('skip_current_clean_step',
                             task.node.driver_internal_info)
            self.assertTrue(log_mock.called)
            set_clean_failed_mock.assert_called_once_with(
                mock.ANY, task, exc)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_one_button_secure_erase(self, ilo_mock, mock_power):
        ilo_mock_object = ilo_mock.return_value
        self.node.clean_step = {'step': 'one_button_secure_erase',
                                'interface': 'management'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = task.driver.management.one_button_secure_erase(task)
            self.assertTrue(
                ilo_mock_object.do_one_button_secure_erase.called)
            self.assertEqual(states.CLEANWAIT, result)
            mock_power.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(task.node.maintenance, True)

    @mock.patch.object(ilo_management.LOG, 'error', autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    @mock.patch.object(ilo_management.Ilo5Management, '_set_clean_failed',
                       autospec=True)
    def test_one_button_secure_erase_ilo_error(
            self, set_clean_failed_mock, ilo_mock, log_mock):
        ilo_mock_object = ilo_mock.return_value
        self.node.clean_step = {'step': 'one_button_secure_erase',
                                'interface': 'management'}
        self.node.save()
        exc = ilo_error.IloError('error')
        ilo_mock_object.do_one_button_secure_erase.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.one_button_secure_erase(task)
            set_clean_failed_mock.assert_called_once_with(mock.ANY,
                                                          task, exc)
            self.assertTrue(
                ilo_mock_object.do_one_button_secure_erase.called)
            self.assertTrue(log_mock.called)
