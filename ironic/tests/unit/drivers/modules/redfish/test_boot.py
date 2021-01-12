# Copyright 2019 Red Hat, Inc.
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

from unittest import mock

from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_utils
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class RedfishVirtualMediaBootTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishVirtualMediaBootTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_boot, 'sushy', None)
    def test_loading_error(self):
        self.assertRaisesRegex(
            exception.DriverLoadError,
            'Unable to import the sushy library',
            redfish_boot.RedfishVirtualMediaBoot)

    def test_parse_driver_info_deploy(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            actual_driver_info = redfish_boot._parse_driver_info(task.node)

            self.assertIn('kernel', actual_driver_info['deploy_kernel'])
            self.assertIn('ramdisk', actual_driver_info['deploy_ramdisk'])
            self.assertIn('bootloader', actual_driver_info['bootloader'])

    def test_parse_driver_info_rescue(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.RESCUING
            task.node.driver_info.update(
                {'rescue_kernel': 'kernel',
                 'rescue_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            actual_driver_info = redfish_boot._parse_driver_info(task.node)

            self.assertIn('kernel', actual_driver_info['rescue_kernel'])
            self.assertIn('ramdisk', actual_driver_info['rescue_ramdisk'])
            self.assertIn('bootloader', actual_driver_info['bootloader'])

    def test_parse_driver_info_exc(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              redfish_boot._parse_driver_info,
                              task.node)

    def _test_parse_driver_info_from_conf(self, mode='deploy'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            expected = {
                '%s_ramdisk' % mode: 'glance://%s_ramdisk_uuid' % mode,
                '%s_kernel' % mode: 'glance://%s_kernel_uuid' % mode
            }

            self.config(group='conductor', **expected)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_from_conf_deploy(self):
        self._test_parse_driver_info_from_conf()

    def test_parse_driver_info_from_conf_rescue(self):
        self._test_parse_driver_info_from_conf(mode='rescue')

    def _test_parse_driver_info_mixed_source(self, mode='deploy'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            kernel_config = {
                '%s_kernel' % mode: 'glance://%s_kernel_uuid' % mode
            }

            ramdisk_config = {
                '%s_ramdisk' % mode: 'glance://%s_ramdisk_uuid' % mode,
            }

            self.config(group='conductor', **kernel_config)

            task.node.driver_info.update(ramdisk_config)

            self.assertRaises(exception.MissingParameterValue,
                              redfish_boot._parse_driver_info, task.node)

    def test_parse_driver_info_mixed_source_deploy(self):
        self._test_parse_driver_info_mixed_source()

    def test_parse_driver_info_mixed_source_rescue(self):
        self._test_parse_driver_info_mixed_source(mode='rescue')

    def test_parse_deploy_info(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            task.node.instance_info.update(
                {'image_source': 'http://boot/iso',
                 'kernel': 'http://kernel/img',
                 'ramdisk': 'http://ramdisk/img'})

            actual_instance_info = redfish_boot._parse_deploy_info(task.node)

            self.assertEqual(
                'http://boot/iso', actual_instance_info['image_source'])
            self.assertEqual(
                'http://kernel/img', actual_instance_info['kernel'])
            self.assertEqual(
                'http://ramdisk/img', actual_instance_info['ramdisk'])

    def test_parse_deploy_info_exc(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              redfish_boot._parse_deploy_info,
                              task.node)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_validate_uefi_boot(self, mock_get_boot_mode,
                                mock_validate_image_properties,
                                mock_parse_driver_info):
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

            mock_get_boot_mode.return_value = 'uefi'

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_validate_bios_boot(self, mock_get_boot_mode,
                                mock_validate_image_properties,
                                mock_parse_driver_info):
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

            mock_get_boot_mode.return_value = 'bios'

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_validate_bios_boot_iso(self, mock_get_boot_mode,
                                    mock_validate_image_properties,
                                    mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info.update(
                {'boot_iso': 'http://localhost/file.iso'}
            )

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )
            # NOTE(TheJulia): Boot mode doesn't matter for this
            # test scenario.
            mock_get_boot_mode.return_value = 'bios'

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_validate_bios_boot_iso_conflicting_image_source(
            self, mock_get_boot_mode,
            mock_validate_image_properties,
            mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info.update(
                {'boot_iso': 'http://localhost/file.iso',
                 'image_source': 'http://localhost/file.img'}
            )

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )
            # NOTE(TheJulia): Boot mode doesn't matter for this
            # test scenario.
            mock_get_boot_mode.return_value = 'bios'

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                mock.ANY, mock.ANY, mock.ANY)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_missing(self, mock_validate_image_properties,
                              mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate_inspection(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            task.driver.boot.validate_inspection(task)

            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate_inspection_missing(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.boot.validate_inspection, task)

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_ramdisk_with_params(
            self, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            expected_params = {
                'ipa-agent-token': mock.ANY,
                'ipa-debug': '1',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_ramdisk_no_debug(
            self, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_deploy_iso, mock_node_set_boot_device):
        self.config(debug=False)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            expected_params = {
                'ipa-agent-token': mock.ANY,
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_floppy_image', autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_has_vmedia_device', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_ramdisk_with_floppy(
            self, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock__has_vmedia_device, mock_prepare_deploy_iso,
            mock_prepare_floppy_image, mock_node_set_boot_device):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            d_info = {
                'config_via_floppy': True
            }

            mock__parse_driver_info.return_value = d_info

            mock__has_vmedia_device.return_value = True
            mock_prepare_floppy_image.return_value = 'floppy-image-url'
            mock_prepare_deploy_iso.return_value = 'cd-image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__has_vmedia_device.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_FLOPPY)

            eject_calls = [
                mock.call(task, sushy.VIRTUAL_MEDIA_FLOPPY),
                mock.call(task, sushy.VIRTUAL_MEDIA_CD)
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)

            insert_calls = [
                mock.call(task, 'floppy-image-url',
                          sushy.VIRTUAL_MEDIA_FLOPPY),
                mock.call(task, 'cd-image-url',
                          sushy.VIRTUAL_MEDIA_CD),
            ]

            mock__insert_vmedia.assert_has_calls(insert_calls)

            expected_params = {
                'boot_method': 'vmedia',
                'ipa-debug': '1',
                'ipa-agent-token': mock.ANY,
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', d_info)

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot, '_has_vmedia_device', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_floppy_image', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    def test_clean_up_ramdisk(
            self, mock__parse_driver_info, mock_cleanup_floppy_image,
            mock_cleanup_iso_image, mock__eject_vmedia,
            mock__has_vmedia_device):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {'config_via_floppy': True}
            mock__has_vmedia_device.return_value = True

            task.driver.boot.clean_up_ramdisk(task)

            mock_cleanup_iso_image.assert_called_once_with(task)

            mock_cleanup_floppy_image.assert_called_once_with(task)

            mock__has_vmedia_device.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_FLOPPY)

            eject_calls = [
                mock.call(task, sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, sushy.VIRTUAL_MEDIA_FLOPPY)
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       'clean_up_instance', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_instance_normal_boot(
            self, mock_boot_mode_utils, mock_deploy_utils, mock_manager_utils,
            mock__parse_deploy_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_boot_iso, mock_clean_up_instance):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid

            mock_deploy_utils.get_boot_option.return_value = 'net'

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }

            mock__parse_deploy_info.return_value = d_info

            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            expected_params = {
                'root_uuid': self.node.uuid
            }

            mock_prepare_boot_iso.assert_called_once_with(
                task, d_info, **expected_params)

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       'clean_up_instance', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_instance_ramdisk_boot(
            self, mock_boot_mode_utils, mock_deploy_utils, mock_manager_utils,
            mock__parse_deploy_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_boot_iso, mock_clean_up_instance):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid

            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            mock__parse_deploy_info.return_value = d_info

            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)

            mock_prepare_boot_iso.assert_called_once_with(task, d_info)

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       'clean_up_instance', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso(
            self, mock_boot_mode_utils, mock_deploy_utils, mock_manager_utils,
            mock__parse_deploy_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_boot_iso, mock_clean_up_instance):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid

            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }

            mock__parse_deploy_info.return_value = d_info
            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            mock_prepare_boot_iso.assert_called_once_with(task, d_info)

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       'clean_up_instance', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso_boot(
            self, mock_boot_mode_utils, mock_deploy_utils, mock_manager_utils,
            mock__parse_deploy_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_boot_iso, mock_clean_up_instance):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            i_info = task.node.instance_info
            i_info['boot_iso'] = "super-magic"
            task.node.instance_info = i_info
            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'
            mock__parse_deploy_info.return_value = {}

            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            mock_prepare_boot_iso.assert_called_once_with(task, {})

            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(boot_mode_utils, 'sync_boot_mode', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    def _test_prepare_instance_local_boot(
            self, mock_manager_utils,
            mock_cleanup_iso_image, mock__eject_vmedia, mock_sync_boot_mode):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid

            task.driver.boot.prepare_instance(task)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            mock_cleanup_iso_image.assert_called_once_with(task)
            mock__eject_vmedia.assert_called_once_with(
                task, sushy.VIRTUAL_MEDIA_CD)
            mock_sync_boot_mode.assert_called_once_with(task)

    def test_prepare_instance_local_whole_disk_image(self):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        self._test_prepare_instance_local_boot()

    def test_prepare_instance_local_boot_option(self):
        instance_info = self.node.instance_info
        instance_info['capabilities'] = '{"boot_option": "local"}'
        self.node.instance_info = instance_info
        self.node.save()
        self._test_prepare_instance_local_boot()

    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    def _test_clean_up_instance(self, mock_cleanup_iso_image,
                                mock__eject_vmedia):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.boot.clean_up_instance(task)

            mock_cleanup_iso_image.assert_called_once_with(task)
            eject_calls = [mock.call(task, sushy.VIRTUAL_MEDIA_CD)]
            if task.node.driver_info.get('config_via_floppy'):
                eject_calls.append(mock.call(task, sushy.VIRTUAL_MEDIA_FLOPPY))

            mock__eject_vmedia.assert_has_calls(eject_calls)

    def test_clean_up_instance_only_cdrom(self):
        self._test_clean_up_instance()

    def test_clean_up_instance_cdrom_and_floppy(self):
        driver_info = self.node.driver_info
        driver_info['config_via_floppy'] = True
        self.node.driver_info = driver_info
        self.node.save()
        self._test_clean_up_instance()

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__insert_vmedia_anew(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_vmedia_floppy = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd, mock_vmedia_floppy]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._insert_vmedia(
                task, 'img-url', sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_cd.insert_media.assert_called_once_with(
                'img-url', inserted=True, write_protected=True)

            self.assertFalse(mock_vmedia_floppy.insert_media.call_count)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__insert_vmedia_already_inserted(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                image='img-url',
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._insert_vmedia(
                task, 'img-url', sushy.VIRTUAL_MEDIA_CD)

            self.assertFalse(mock_vmedia_cd.insert_media.call_count)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    @mock.patch('time.sleep', lambda *args, **kwargs: None)
    def test__insert_vmedia_while_ejecting(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=False,
                image='img-url',
                media_types=[sushy.VIRTUAL_MEDIA_CD],
            )
            mock_manager = mock.MagicMock()

            def clear_and_raise(*args, **kwargs):
                mock_vmedia_cd.insert_media.side_effect = None
                raise sushy.exceptions.ServerSideError(
                    "POST", 'img-url', mock.MagicMock())
            mock_vmedia_cd.insert_media.side_effect = clear_and_raise
            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._insert_vmedia(
                task, 'img-url', sushy.VIRTUAL_MEDIA_CD)

            self.assertEqual(mock_vmedia_cd.insert_media.call_count, 2)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    @mock.patch('time.sleep', lambda *args, **kwargs: None)
    def test__insert_vmedia_bad_device(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_floppy = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])
            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_floppy]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            self.assertRaises(
                exception.InvalidParameterValue,
                redfish_boot._insert_vmedia,
                task, 'img-url', sushy.VIRTUAL_MEDIA_CD)
            self.assertEqual(mock_redfish_utils.get_system.call_count, 1)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__eject_vmedia_everything(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_vmedia_floppy = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd, mock_vmedia_floppy]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._eject_vmedia(task)

            mock_vmedia_cd.eject_media.assert_called_once_with()
            mock_vmedia_floppy.eject_media.assert_called_once_with()

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__eject_vmedia_specific(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_vmedia_floppy = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd, mock_vmedia_floppy]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_cd.eject_media.assert_called_once_with()
            self.assertFalse(mock_vmedia_floppy.eject_media.call_count)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__eject_vmedia_not_inserted(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_vmedia_floppy = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd, mock_vmedia_floppy]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._eject_vmedia(task)

            self.assertFalse(mock_vmedia_cd.eject_media.call_count)
            self.assertFalse(mock_vmedia_floppy.eject_media.call_count)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test__eject_vmedia_unknown(self, mock_redfish_utils):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_CD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot._eject_vmedia(task)

            self.assertFalse(mock_vmedia_cd.eject_media.call_count)
