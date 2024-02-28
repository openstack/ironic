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

import sushy

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_utils
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

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

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    def test_parse_driver_info_ramdisk(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info = {}
            task.node.automated_clean = False
            actual_driver_info = redfish_boot._parse_driver_info(task.node)
            self.assertEqual({'can_provide_config': False},
                             actual_driver_info)

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
            self.assertTrue(actual_driver_info['can_provide_config'])

    def test_parse_driver_info_iso(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_iso': 'http://boot.iso'})

            actual_driver_info = redfish_boot._parse_driver_info(task.node)

            self.assertEqual('http://boot.iso',
                             actual_driver_info['deploy_iso'])
            self.assertFalse(actual_driver_info['can_provide_config'])

    def test_parse_driver_info_iso_deprecated(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'redfish_deploy_iso': 'http://boot.iso'})

            actual_driver_info = redfish_boot._parse_driver_info(task.node)

            self.assertEqual('http://boot.iso',
                             actual_driver_info['deploy_iso'])
            self.assertFalse(actual_driver_info['can_provide_config'])

    def test_parse_driver_info_removable(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_iso': 'http://boot.iso',
                 'config_via_removable': True}
            )

            actual_driver_info = redfish_boot._parse_driver_info(task.node)
            self.assertTrue(actual_driver_info['config_via_removable'])
            self.assertTrue(actual_driver_info['can_provide_config'])

    @mock.patch.object(redfish_boot.LOG, 'warning', autospec=True)
    def test_parse_driver_info_removable_deprecated(self, mock_log):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader',
                 'config_via_floppy': True}
            )

            actual_driver_info = redfish_boot._parse_driver_info(task.node)
            self.assertTrue(actual_driver_info['config_via_removable'])
            self.assertTrue(mock_log.called)

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

    def _test_parse_driver_info_from_conf(self, mode='deploy', by_arch=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            if by_arch:
                ramdisk = 'glance://%s_ramdisk_uuid' % mode
                kernel = 'glance://%s_kernel_uuid' % mode

                config = {
                    '%s_ramdisk_by_arch' % mode: {'x86_64': ramdisk},
                    '%s_kernel_by_arch' % mode: {'x86_64': kernel}
                }
                expected = {
                    '%s_ramdisk' % mode: ramdisk,
                    '%s_kernel' % mode: kernel
                }
            else:
                expected = {
                    '%s_ramdisk' % mode: 'glance://%s_ramdisk_uuid' % mode,
                    '%s_kernel' % mode: 'glance://%s_kernel_uuid' % mode
                }
                config = expected

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_from_conf_deploy(self):
        self._test_parse_driver_info_from_conf()

    def test_parse_driver_info_from_conf_rescue(self):
        self._test_parse_driver_info_from_conf(mode='rescue')

    def test_parse_driver_info_from_conf_deploy_by_arch(self):
        self._test_parse_driver_info_from_conf(by_arch=True)

    def test_parse_driver_info_from_conf_rescue_by_arch(self):
        self._test_parse_driver_info_from_conf(mode='rescue', by_arch=True)

    def _test_parse_driver_info_mixed_source(self, mode='deploy',
                                             by_arch=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            if by_arch:
                kernel_config = {
                    '%s_kernel_by_arch' % mode: {
                        'x86': 'glance://%s_kernel_uuid' % mode
                    }
                }
            else:
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

    def test_parse_driver_info_mixed_source_deploy_by_arch(self):
        self._test_parse_driver_info_mixed_source(by_arch=True)

    def test_parse_driver_info_mixed_source_rescue_by_arch(self):
        self._test_parse_driver_info_mixed_source(mode='rescue', by_arch=True)

    def _test_parse_driver_info_choose_by_arch(self, mode='deploy'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING
            task.node.properties['cpu_arch'] = 'aarch64'
            wrong_ramdisk = 'glance://wrong_%s_ramdisk_uuid' % mode
            wrong_kernel = 'glance://wrong_%s_kernel_uuid' % mode
            ramdisk = 'glance://%s_ramdisk_uuid' % mode
            kernel = 'glance://%s_kernel_uuid' % mode

            config = {
                '%s_ramdisk_by_arch' % mode: {
                    'x86_64': wrong_ramdisk, 'aarch64': ramdisk},
                '%s_kernel_by_arch' % mode: {
                    'x86_64': wrong_kernel, 'aarch64': kernel}
            }
            expected = {
                '%s_ramdisk' % mode: ramdisk,
                '%s_kernel' % mode: kernel
            }

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_choose_by_arch_deploy(self):
        self._test_parse_driver_info_choose_by_arch()

    def test_parse_driver_info_choose_by_arch_rescue(self):
        self._test_parse_driver_info_choose_by_arch(mode='rescue')

    def _test_parse_driver_info_choose_by_hierarchy(self, mode='deploy',
                                                    ramdisk_missing=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            ramdisk = 'glance://def_%s_ramdisk_uuid' % mode
            kernel = 'glance://def_%s_kernel_uuid' % mode
            ramdisk_by_arch = 'glance://%s_ramdisk_by_arch_uuid' % mode
            kernel_by_arch = 'glance://%s_kernel_by_arch_uuid' % mode

            config = {
                '%s_kernel_by_arch' % mode: {
                    'x86_64': kernel_by_arch},
                '%s_ramdisk' % mode: ramdisk,
                '%s_kernel' % mode: kernel
            }
            if not ramdisk_missing:
                config['%s_ramdisk_by_arch' % mode] = {
                    'x86_64': ramdisk_by_arch}
                expected = {
                    '%s_ramdisk' % mode: ramdisk_by_arch,
                    '%s_kernel' % mode: kernel_by_arch
                }
            else:
                expected = {
                    '%s_ramdisk' % mode: ramdisk,
                    '%s_kernel' % mode: kernel
                }

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_choose_by_hierarchy_deploy(self):
        self._test_parse_driver_info_choose_by_hierarchy()

    def test_parse_driver_info_choose_by_hierarchy_rescue(self):
        self._test_parse_driver_info_choose_by_hierarchy(mode='rescue')

    def test_parse_driver_info_choose_by_hierarchy_missing_param_deploy(self):
        self._test_parse_driver_info_choose_by_hierarchy(ramdisk_missing=True)

    def test_parse_driver_info_choose_by_hierarchy_missing_param_rescue(self):
        self._test_parse_driver_info_choose_by_hierarchy(
            mode='rescue', ramdisk_missing=True)

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
    def test_validate_local(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info = {}

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )

            task.driver.boot.validate(task)

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_kernel_ramdisk(self, mock_validate_image_properties,
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

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                task, mock.ANY)

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_boot_iso(self, mock_validate_image_properties,
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

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                task, mock.ANY)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_correct_vendor(self, mock_validate_image_properties,
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

            task.node.properties['vendor'] = "Ironic Co."

            task.driver.boot.validate(task)

    def test__validate_vendor_incompatible_with_idrac(self):
        managers = [mock.Mock(firmware_version='5.10.30.00',
                              manager_type=sushy.MANAGER_TYPE_BMC)]
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

            self.assertRaisesRegex(
                exception.InvalidParameterValue, "with vendor Dell Inc.",
                task.driver.boot._validate_vendor, task, managers)

    def test__validate_vendor_compatible_with_idrac(self):
        managers = [mock.Mock(firmware_version='6.00.00.00',
                              manager_type=sushy.MANAGER_TYPE_BMC)]
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

            task.driver.boot._validate_vendor(task, managers)

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

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_validate_vendor', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_with_params(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_deploy_iso, mock_node_set_boot_device,
            mock_validate_vendor):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_validate_vendor.assert_called_once_with(
                task.driver.boot, task, managers
            )

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            token = task.node.driver_internal_info['agent_secret_token']
            self.assertTrue(token)

            expected_params = {
                'ipa-agent-token': token,
                'ipa-debug': '1',
                'boot_method': 'vmedia',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

            self.assertTrue(task.node.driver_internal_info[
                'agent_secret_token_pregenerated'])

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_no_debug(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_deploy_iso, mock_node_set_boot_device):
        self.config(debug=False)
        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            expected_params = {
                'ipa-agent-token': mock.ANY,
                'boot_method': 'vmedia',
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
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_with_floppy(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock__has_vmedia_device, mock_prepare_deploy_iso,
            mock_prepare_floppy_image, mock_node_set_boot_device):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            d_info = {
                'config_via_removable': True
            }

            mock__parse_driver_info.return_value = d_info

            mock__has_vmedia_device.return_value = sushy.VIRTUAL_MEDIA_FLOPPY
            mock_prepare_floppy_image.return_value = 'floppy-image-url'
            mock_prepare_deploy_iso.return_value = 'cd-image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__has_vmedia_device.assert_called_once_with(
                managers,
                [sushy.VIRTUAL_MEDIA_USBSTICK, sushy.VIRTUAL_MEDIA_FLOPPY])

            eject_calls = [
                mock.call(task, managers, dev)
                for dev in (sushy.VIRTUAL_MEDIA_FLOPPY,
                            sushy.VIRTUAL_MEDIA_CD)
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)

            insert_calls = [
                mock.call(task, managers, 'floppy-image-url',
                          sushy.VIRTUAL_MEDIA_FLOPPY),
                mock.call(task, managers, 'cd-image-url',
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
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_with_usb(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock__has_vmedia_device, mock_prepare_deploy_iso,
            mock_prepare_floppy_image, mock_node_set_boot_device):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            d_info = {
                'config_via_removable': True
            }

            mock__parse_driver_info.return_value = d_info

            mock__has_vmedia_device.return_value = sushy.VIRTUAL_MEDIA_USBSTICK
            mock_prepare_floppy_image.return_value = 'floppy-image-url'
            mock_prepare_deploy_iso.return_value = 'cd-image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__has_vmedia_device.assert_called_once_with(
                managers,
                [sushy.VIRTUAL_MEDIA_USBSTICK, sushy.VIRTUAL_MEDIA_FLOPPY])

            eject_calls = [
                mock.call(task, managers, dev)
                for dev in (sushy.VIRTUAL_MEDIA_USBSTICK,
                            sushy.VIRTUAL_MEDIA_CD)
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)

            insert_calls = [
                mock.call(task, managers, 'floppy-image-url',
                          sushy.VIRTUAL_MEDIA_USBSTICK),
                mock.call(task, managers, 'cd-image-url',
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

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_no_config(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {
                'can_provide_config': False}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            expected_params = {
                'ipa-debug': '1',
                'boot_method': 'vmedia',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

            self.assertNotIn('agent_secret_token',
                             task.node.driver_internal_info)
            self.assertNotIn('agent_secret_token_pregenerated',
                             task.node.driver_internal_info)

    @mock.patch.object(manager_utils, 'is_fast_track', lambda task: True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_has_vmedia_device', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_fast_track(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock__has_vmedia_device,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            mock__has_vmedia_device.return_value = sushy.VIRTUAL_MEDIA_CD

            task.driver.boot.prepare_ramdisk(task, {})

            mock__has_vmedia_device.assert_called_once_with(
                managers, sushy.VIRTUAL_MEDIA_CD, inserted=True)

            mock_node_power_action.assert_not_called()
            mock__eject_vmedia.assert_not_called()
            mock__insert_vmedia.assert_not_called()
            mock_prepare_deploy_iso.assert_not_called()
            mock_node_set_boot_device.assert_not_called()
            mock_boot_mode_utils.sync_boot_mode.assert_not_called()

    @mock.patch.object(manager_utils, 'is_fast_track', lambda task: True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_has_vmedia_device', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_fast_track_impossible(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info, mock__insert_vmedia, mock__eject_vmedia,
            mock__has_vmedia_device,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            mock__has_vmedia_device.return_value = False

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock__has_vmedia_device.assert_called_once_with(
                managers, sushy.VIRTUAL_MEDIA_CD, inserted=True)

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            mock__eject_vmedia.assert_called_once_with(
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            token = task.node.driver_internal_info['agent_secret_token']
            self.assertTrue(token)

            expected_params = {
                'ipa-agent-token': token,
                'ipa-debug': '1',
                'boot_method': 'vmedia',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

            self.assertTrue(task.node.driver_internal_info[
                'agent_secret_token_pregenerated'])

    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_floppy_image', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_clean_up_ramdisk(
            self, mock_system, mock__parse_driver_info,
            mock_cleanup_floppy_image, mock_cleanup_iso_image,
            mock__eject_vmedia):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_info['config_via_removable'] = True

            task.driver.boot.clean_up_ramdisk(task)

            mock_cleanup_iso_image.assert_called_once_with(task)

            mock_cleanup_floppy_image.assert_called_once_with(task)

            eject_calls = [
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK),
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_FLOPPY)
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_eject_all', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_normal_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_manager_utils, mock__parse_deploy_info, mock__insert_vmedia,
            mock__eject_vmedia, mock_prepare_boot_iso, mock_clean_up_instance):

        managers = mock_system.return_value.managers
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
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)
            csb = mock_boot_mode_utils.configure_secure_boot_if_needed
            csb.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_eject_all', autospec=True)
    @mock.patch.object(image_utils, 'prepare_configdrive_image', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock__insert_vmedia, mock__eject_vmedia, mock_prepare_boot_iso,
            mock_prepare_disk, mock_clean_up_instance):

        configdrive = 'Y29udGVudA=='
        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = configdrive

            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            mock__parse_deploy_info.return_value = d_info

            mock_prepare_boot_iso.return_value = 'image-url'
            mock_prepare_disk.return_value = 'cd-url'

            task.driver.boot.prepare_instance(task)

            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)

            mock_prepare_boot_iso.assert_called_once_with(task, d_info)
            mock_prepare_disk.assert_called_once_with(task, configdrive)

            mock__eject_vmedia.assert_has_calls([
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK),
            ])

            mock__insert_vmedia.assert_has_calls([
                mock.call(task, managers,
                          'image-url', sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers,
                          'cd-url', sushy.VIRTUAL_MEDIA_USBSTICK),
            ])

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_eject_all', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock__insert_vmedia, mock__eject_vmedia, mock_prepare_boot_iso,
            mock_clean_up_instance):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = None

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
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_eject_all', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock__insert_vmedia, mock__eject_vmedia, mock_prepare_boot_iso,
            mock_clean_up_instance):

        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            i_info = task.node.instance_info
            i_info['boot_iso'] = "super-magic"
            del i_info['configdrive']
            task.node.instance_info = i_info
            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'
            mock__parse_deploy_info.return_value = {}

            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            mock_prepare_boot_iso.assert_called_once_with(task, {})

            mock__eject_vmedia.assert_called_once_with(
                task, managers, sushy.VIRTUAL_MEDIA_CD)

            mock__insert_vmedia.assert_called_once_with(
                task, managers, 'image-url', sushy.VIRTUAL_MEDIA_CD)

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.manager_utils, 'build_configdrive',
                       autospec=True)
    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot,
                       '_eject_all', autospec=True)
    @mock.patch.object(image_utils, 'prepare_configdrive_image', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_insert_vmedia', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_render_configdrive(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock__insert_vmedia, mock__eject_vmedia, mock_prepare_boot_iso,
            mock_prepare_disk, mock_clean_up_instance, mock_build_configdrive):

        configdrive = 'Y29udGVudA=='
        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = {'meta_data': {}}

            mock_build_configdrive.return_value = configdrive

            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'

            d_info = {
                'deploy_kernel': 'kernel',
                'deploy_ramdisk': 'ramdisk',
                'bootloader': 'bootloader'
            }
            mock__parse_deploy_info.return_value = d_info

            mock_prepare_boot_iso.return_value = 'image-url'
            mock_prepare_disk.return_value = 'cd-url'

            task.driver.boot.prepare_instance(task)

            mock_clean_up_instance.assert_called_once_with(mock.ANY, task)

            mock_build_configdrive.assert_called_once_with(
                task.node, {'meta_data': {}})
            mock_prepare_boot_iso.assert_called_once_with(task, d_info)
            mock_prepare_disk.assert_called_once_with(task, configdrive)

            mock__eject_vmedia.assert_has_calls([
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK),
            ])

            mock__insert_vmedia.assert_has_calls([
                mock.call(task, managers,
                          'image-url', sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers,
                          'cd-url', sushy.VIRTUAL_MEDIA_USBSTICK),
            ])

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'sync_boot_mode', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def _test_prepare_instance_local_boot(
            self, mock_system, mock_manager_utils,
            mock_cleanup_iso_image, mock__eject_vmedia, mock_sync_boot_mode,
            mock_secure_boot):

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
                task, mock_system.return_value.managers,
                sushy.VIRTUAL_MEDIA_CD)
            mock_sync_boot_mode.assert_called_once_with(task)
            mock_secure_boot.assert_called_once_with(task)

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

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_floppy_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def _test_clean_up_instance(self, mock_system, mock_cleanup_iso_image,
                                mock_cleanup_floppy_image,
                                mock__eject_vmedia, mock_secure_boot):
        managers = mock_system.return_value.managers
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.boot.clean_up_instance(task)

            mock_cleanup_iso_image.assert_called_once_with(task)
            eject_calls = [mock.call(task, managers, sushy.VIRTUAL_MEDIA_CD)]
            if task.node.driver_info.get('config_via_removable'):
                eject_calls.extend([
                    mock.call(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK),
                    mock.call(task, managers, sushy.VIRTUAL_MEDIA_FLOPPY),
                ])
                mock_cleanup_floppy_image.assert_called_once_with(task)

            mock__eject_vmedia.assert_has_calls(eject_calls)
            mock_secure_boot.assert_called_once_with(task)

    def test_clean_up_instance_only_cdrom(self):
        self._test_clean_up_instance()

    def test_clean_up_instance_cdrom_and_floppy(self):
        driver_info = self.node.driver_info
        driver_info['config_via_removable'] = True
        self.node.driver_info = driver_info
        self.node.save()
        self._test_clean_up_instance()

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(redfish_boot, '_eject_vmedia', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_clean_up_instance_ramdisk(self, mock_system,
                                       mock_cleanup_iso_image,
                                       mock_cleanup_disk_image,
                                       mock__eject_vmedia,
                                       mock_get_boot_option,
                                       mock_secure_boot):
        managers = mock_system.return_value.managers

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_get_boot_option.return_value = 'ramdisk'

            task.driver.boot.clean_up_instance(task)

            mock_cleanup_iso_image.assert_called_once_with(task)
            mock_cleanup_disk_image.assert_called_once_with(
                task, prefix='configdrive')
            eject_calls = [
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_CD),
                mock.call(task, managers, sushy.VIRTUAL_MEDIA_USBSTICK),
            ]

            mock__eject_vmedia.assert_has_calls(eject_calls)
            mock_secure_boot.assert_called_once_with(task)

    def test__insert_vmedia_anew(self):

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

            redfish_boot._insert_vmedia(
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_cd.insert_media.assert_called_once_with(
                'img-url', inserted=True, write_protected=True)

            self.assertFalse(mock_vmedia_floppy.insert_media.call_count)

    def test__insert_vmedia_anew_dvd(self):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_dvd = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_dvd]

            redfish_boot._insert_vmedia(
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_dvd.insert_media.assert_called_once_with(
                'img-url', inserted=True, write_protected=True)

    @mock.patch('time.sleep', lambda *args, **kwargs: None)
    def test__insert_vmedia_anew_dvd_retry(self):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_dvd_1 = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])

            mock_vmedia_dvd_2 = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])

            mock_manager = mock.MagicMock()

            def clear_and_raise(*args, **kwargs):
                mock_vmedia_dvd_1.insert_media.side_effect = None
                raise sushy.exceptions.BadRequestError(
                    "POST", 'img-url', mock.MagicMock())
            mock_vmedia_dvd_1.insert_media.side_effect = clear_and_raise
            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_dvd_1, mock_vmedia_dvd_2]

            redfish_boot._insert_vmedia(
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

            self.assertEqual(mock_vmedia_dvd_2.insert_media.call_count, 1)

    def test__insert_vmedia_already_inserted(self):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                image='img-url',
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd]

            redfish_boot._insert_vmedia(
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

            self.assertFalse(mock_vmedia_cd.insert_media.call_count)

    @mock.patch('time.sleep', lambda *args, **kwargs: None)
    def test__insert_vmedia_while_ejecting(self):

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

            redfish_boot._insert_vmedia(
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

            self.assertEqual(mock_vmedia_cd.insert_media.call_count, 2)

    @mock.patch('time.sleep', lambda *args, **kwargs: None)
    def test__insert_vmedia_bad_device(self):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_floppy = mock.MagicMock(
                inserted=False,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])
            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_floppy]

            self.assertRaises(
                exception.InvalidParameterValue,
                redfish_boot._insert_vmedia,
                task, [mock_manager], 'img-url', sushy.VIRTUAL_MEDIA_CD)

    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test_eject_vmedia_everything(self, mock_redfish_utils,
                                     mock_cleanup_iso, mock_cleanup_disk):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_cd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_CD])
            mock_vmedia_floppy = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])
            mock_vmedia_dvd = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_cd, mock_vmedia_floppy, mock_vmedia_dvd]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot.eject_vmedia(task)

            mock_vmedia_cd.eject_media.assert_called_once_with()
            mock_vmedia_floppy.eject_media.assert_called_once_with()
            mock_vmedia_dvd.eject_media.assert_called_once_with()
            mock_cleanup_iso.assert_called_once_with(task)
            mock_cleanup_disk.assert_called_once_with(task,
                                                      prefix='configdrive')

    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test_eject_vmedia_specific(self, mock_redfish_utils,
                                   mock_cleanup_iso, mock_cleanup_disk):

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

            redfish_boot.eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_cd.eject_media.assert_called_once_with()
            self.assertFalse(mock_vmedia_floppy.eject_media.call_count)
            mock_cleanup_iso.assert_called_once_with(task)
            mock_cleanup_disk.assert_not_called()

    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    @mock.patch.object(redfish_boot.LOG, 'debug', autospec=True)
    @mock.patch.object(redfish_boot.LOG, 'info', autospec=True)
    def test_eject_vmedia_with_dvd_cisco_ucs(self, mock_log_info,
                                             mock_log_debug,
                                             mock_redfish_utils,
                                             mock_cleanup_iso,
                                             mock_cleanup_disk):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_vmedia_dvd_1 = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])
            mock_vmedia_dvd_2 = mock.MagicMock(
                inserted=True,
                media_types=[sushy.VIRTUAL_MEDIA_DVD])

            mock_manager = mock.MagicMock()

            mock_manager.virtual_media.get_members.return_value = [
                mock_vmedia_dvd_1, mock_vmedia_dvd_2]

            mock_redfish_utils.get_system.return_value.managers = [
                mock_manager]

            redfish_boot.eject_vmedia(task, sushy.VIRTUAL_MEDIA_CD)

            mock_vmedia_dvd_1.eject_media.assert_called_once_with()
            mock_vmedia_dvd_2.eject_media.assert_called_once_with()

            self.assertEqual(mock_log_info.call_count, 2)
            self.assertEqual(mock_log_debug.call_count, 3)
            mock_cleanup_iso.assert_called_once_with(task)
            mock_cleanup_disk.assert_not_called()

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test_eject_vmedia_not_inserted(self, mock_redfish_utils):

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

            redfish_boot.eject_vmedia(task)

            self.assertFalse(mock_vmedia_cd.eject_media.call_count)
            self.assertFalse(mock_vmedia_floppy.eject_media.call_count)

    @mock.patch.object(redfish_boot, 'redfish_utils', autospec=True)
    def test_eject_vmedia_unknown(self, mock_redfish_utils):

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

            redfish_boot.eject_vmedia(task)

            self.assertFalse(mock_vmedia_cd.eject_media.call_count)

    def test__has_vmedia_device(self):
        mock_vmedia_cd = mock.MagicMock(
            inserted=False,
            media_types=[sushy.VIRTUAL_MEDIA_CD])
        mock_vmedia_floppy = mock.MagicMock(
            inserted=False,
            media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

        mock_manager = mock.MagicMock()

        mock_manager.virtual_media.get_members.return_value = [
            mock_vmedia_cd, mock_vmedia_floppy]

        self.assertEqual(
            sushy.VIRTUAL_MEDIA_CD,
            redfish_boot._has_vmedia_device(
                [mock_manager], sushy.VIRTUAL_MEDIA_CD))

        self.assertFalse(
            redfish_boot._has_vmedia_device(
                [mock_manager], sushy.VIRTUAL_MEDIA_CD, inserted=True))

        self.assertFalse(
            redfish_boot._has_vmedia_device(
                [mock_manager], sushy.VIRTUAL_MEDIA_USBSTICK))

    def test__has_vmedia_device_inserted(self):
        mock_vmedia_cd = mock.MagicMock(
            inserted=False,
            media_types=[sushy.VIRTUAL_MEDIA_CD])
        mock_vmedia_floppy = mock.MagicMock(
            inserted=True,
            media_types=[sushy.VIRTUAL_MEDIA_FLOPPY])

        mock_manager = mock.MagicMock()

        mock_manager.virtual_media.get_members.return_value = [
            mock_vmedia_cd, mock_vmedia_floppy]

        self.assertEqual(
            sushy.VIRTUAL_MEDIA_FLOPPY,
            redfish_boot._has_vmedia_device(
                [mock_manager], sushy.VIRTUAL_MEDIA_FLOPPY, inserted=True))


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class RedfishHTTPBootTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishHTTPBootTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-https'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_with_params(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            mock__parse_driver_info.return_value = {}
            mock_prepare_deploy_iso.return_value = 'image-url'

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_called_once_with(
                task, states.POWER_OFF)

            token = task.node.driver_internal_info['agent_secret_token']
            self.assertTrue(token)

            expected_params = {
                'ipa-agent-token': token,
                'ipa-debug': '1',
                'boot_method': 'vmedia',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, False)
            self.assertEqual('image-url',
                             task.node.driver_internal_info.get(
                                 'redfish_uefi_http_url'))
            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)
            self.assertTrue(task.node.driver_internal_info[
                'agent_secret_token_pregenerated'])

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    def test_parse_driver_info_ramdisk(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info = {}
            task.node.automated_clean = False
            actual_driver_info = redfish_boot._parse_driver_info(task.node)
            self.assertEqual({'can_provide_config': False},
                             actual_driver_info)

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
            self.assertTrue(actual_driver_info['can_provide_config'])

    def test_parse_driver_info_iso(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info.update(
                {'deploy_iso': 'http://boot.iso'})

            actual_driver_info = redfish_boot._parse_driver_info(task.node)

            self.assertEqual('http://boot.iso',
                             actual_driver_info['deploy_iso'])
            self.assertFalse(actual_driver_info['can_provide_config'])

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

    def _test_parse_driver_info_from_conf(self, mode='deploy', by_arch=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            if by_arch:
                ramdisk = 'glance://%s_ramdisk_uuid' % mode
                kernel = 'glance://%s_kernel_uuid' % mode

                config = {
                    '%s_ramdisk_by_arch' % mode: {'x86_64': ramdisk},
                    '%s_kernel_by_arch' % mode: {'x86_64': kernel}
                }
                expected = {
                    '%s_ramdisk' % mode: ramdisk,
                    '%s_kernel' % mode: kernel
                }
            else:
                expected = {
                    '%s_ramdisk' % mode: 'glance://%s_ramdisk_uuid' % mode,
                    '%s_kernel' % mode: 'glance://%s_kernel_uuid' % mode
                }
                config = expected

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_from_conf_deploy(self):
        self._test_parse_driver_info_from_conf()

    def test_parse_driver_info_from_conf_rescue(self):
        self._test_parse_driver_info_from_conf(mode='rescue')

    def test_parse_driver_info_from_conf_deploy_by_arch(self):
        self._test_parse_driver_info_from_conf(by_arch=True)

    def test_parse_driver_info_from_conf_rescue_by_arch(self):
        self._test_parse_driver_info_from_conf(mode='rescue', by_arch=True)

    def _test_parse_driver_info_mixed_source(self, mode='deploy',
                                             by_arch=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            if by_arch:
                kernel_config = {
                    '%s_kernel_by_arch' % mode: {
                        'x86': 'glance://%s_kernel_uuid' % mode
                    }
                }
            else:
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

    def test_parse_driver_info_mixed_source_deploy_by_arch(self):
        self._test_parse_driver_info_mixed_source(by_arch=True)

    def test_parse_driver_info_mixed_source_rescue_by_arch(self):
        self._test_parse_driver_info_mixed_source(mode='rescue', by_arch=True)

    def _test_parse_driver_info_choose_by_arch(self, mode='deploy'):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING
            task.node.properties['cpu_arch'] = 'aarch64'
            wrong_ramdisk = 'glance://wrong_%s_ramdisk_uuid' % mode
            wrong_kernel = 'glance://wrong_%s_kernel_uuid' % mode
            ramdisk = 'glance://%s_ramdisk_uuid' % mode
            kernel = 'glance://%s_kernel_uuid' % mode

            config = {
                '%s_ramdisk_by_arch' % mode: {
                    'x86_64': wrong_ramdisk, 'aarch64': ramdisk},
                '%s_kernel_by_arch' % mode: {
                    'x86_64': wrong_kernel, 'aarch64': kernel}
            }
            expected = {
                '%s_ramdisk' % mode: ramdisk,
                '%s_kernel' % mode: kernel
            }

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_choose_by_arch_deploy(self):
        self._test_parse_driver_info_choose_by_arch()

    def test_parse_driver_info_choose_by_arch_rescue(self):
        self._test_parse_driver_info_choose_by_arch(mode='rescue')

    def _test_parse_driver_info_choose_by_hierarchy(self, mode='deploy',
                                                    ramdisk_missing=False):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            if mode == 'rescue':
                task.node.provision_state = states.RESCUING

            ramdisk = 'glance://def_%s_ramdisk_uuid' % mode
            kernel = 'glance://def_%s_kernel_uuid' % mode
            ramdisk_by_arch = 'glance://%s_ramdisk_by_arch_uuid' % mode
            kernel_by_arch = 'glance://%s_kernel_by_arch_uuid' % mode

            config = {
                '%s_kernel_by_arch' % mode: {
                    'x86_64': kernel_by_arch},
                '%s_ramdisk' % mode: ramdisk,
                '%s_kernel' % mode: kernel
            }
            if not ramdisk_missing:
                config['%s_ramdisk_by_arch' % mode] = {
                    'x86_64': ramdisk_by_arch}
                expected = {
                    '%s_ramdisk' % mode: ramdisk_by_arch,
                    '%s_kernel' % mode: kernel_by_arch
                }
            else:
                expected = {
                    '%s_ramdisk' % mode: ramdisk,
                    '%s_kernel' % mode: kernel
                }

            self.config(group='conductor', **config)

            image_info = redfish_boot._parse_driver_info(task.node)

            for key, value in expected.items():
                self.assertEqual(value, image_info[key])

    def test_parse_driver_info_choose_by_hierarchy_deploy(self):
        self._test_parse_driver_info_choose_by_hierarchy()

    def test_parse_driver_info_choose_by_hierarchy_rescue(self):
        self._test_parse_driver_info_choose_by_hierarchy(mode='rescue')

    def test_parse_driver_info_choose_by_hierarchy_missing_param_deploy(self):
        self._test_parse_driver_info_choose_by_hierarchy(ramdisk_missing=True)

    def test_parse_driver_info_choose_by_hierarchy_missing_param_rescue(self):
        self._test_parse_driver_info_choose_by_hierarchy(
            mode='rescue', ramdisk_missing=True)

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

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate_local(self, mock_parse_driver_info, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info = {}
            mock_get_system.return_value.boot.allowed_values = [
                "UefiHttp", "Hdd"]

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )
            task.driver.boot.validate(task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate_errors_with_lack_of_support(
            self, mock_parse_driver_info, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info = {}
            mock_get_system.return_value.boot.allowed_values = ["Hdd"]

            task.node.driver_info.update(
                {'deploy_kernel': 'kernel',
                 'deploy_ramdisk': 'ramdisk',
                 'bootloader': 'bootloader'}
            )
            msg = ("Node %s hardware does not support feature UefiHttp boot, "
                   "which is required based upon the requested configuration."
                   % task.node.uuid)
            self.assertRaisesRegex(
                exception.UnsupportedHardwareFeature,
                msg, task.driver.boot.validate, task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot, '_validate_hardware',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_kernel_ramdisk(self, mock_validate_image_properties,
                                     mock_parse_driver_info,
                                     mock_validate_hardware):
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

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                task, mock.ANY)
            mock_validate_hardware.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot, '_validate_hardware',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_boot_iso(self, mock_validate_image_properties,
                               mock_parse_driver_info,
                               mock_validate_hardware):
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

            task.driver.boot.validate(task)

            mock_validate_image_properties.assert_called_once_with(
                task, mock.ANY)
            mock_validate_hardware.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot, '_validate_hardware',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_correct_vendor(self, mock_validate_image_properties,
                                     mock_parse_driver_info,
                                     mock_validate_hardware):
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

            task.node.properties['vendor'] = "Ironic Co."

            task.driver.boot.validate(task)
            mock_validate_hardware.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot, '_validate_hardware',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       autospec=True)
    def test_validate_missing(self, mock_validate_image_properties,
                              mock_parse_driver_info, mock_validate_hardware):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)
            mock_validate_hardware.assert_called_once_with(mock.ANY, task)

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

    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_no_debug(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info,
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

            expected_params = {
                'ipa-agent-token': mock.ANY,
                'boot_method': 'vmedia',
            }

            mock_prepare_deploy_iso.assert_called_once_with(
                task, expected_params, 'deploy', {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, False)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'is_fast_track', lambda task: True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_power_action',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_ramdisk_fast_track(
            self, mock_system, mock_boot_mode_utils, mock_node_power_action,
            mock__parse_driver_info,
            mock_prepare_deploy_iso, mock_node_set_boot_device):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING

            task.driver.boot.prepare_ramdisk(task, {})

            mock_node_power_action.assert_not_called()
            mock_prepare_deploy_iso.assert_not_called()
            mock_node_set_boot_device.assert_not_called()
            mock_boot_mode_utils.sync_boot_mode.assert_not_called()

    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_floppy_image', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_driver_info', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_clean_up_ramdisk(
            self, mock_system, mock__parse_driver_info,
            mock_cleanup_floppy_image, mock_cleanup_iso_image):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_info['config_via_removable'] = True

            task.driver.boot.clean_up_ramdisk(task)

            mock_cleanup_iso_image.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot,
                       '_clean_up', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_normal_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_manager_utils, mock__parse_deploy_info,
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

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)
            csb = mock_boot_mode_utils.configure_secure_boot_if_needed
            csb.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot,
                       '_clean_up', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock_prepare_boot_iso, mock_clean_up_instance):

        configdrive = 'Y29udGVudA=='
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = configdrive

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

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(redfish_boot.RedfishHttpsBoot,
                       '_clean_up', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock_prepare_boot_iso,
            mock_clean_up_instance):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = None

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

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)

    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_iso_boot(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock_prepare_boot_iso,
            mock_image_cleanup, mock_disk_cleanup):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            i_info = task.node.instance_info
            i_info['boot_iso'] = "super-magic"
            del i_info['configdrive']
            task.node.instance_info = i_info
            mock_deploy_utils.get_boot_option.return_value = 'ramdisk'
            mock__parse_deploy_info.return_value = {}

            mock_prepare_boot_iso.return_value = 'image-url'

            task.driver.boot.prepare_instance(task)

            mock_prepare_boot_iso.assert_called_once_with(task, {})

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)
            mock_image_cleanup.assert_called_once_with(task)
            mock_disk_cleanup.assert_not_called()

    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso', autospec=True)
    @mock.patch.object(redfish_boot, '_parse_deploy_info', autospec=True)
    @mock.patch.object(redfish_boot.manager_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(redfish_boot, 'deploy_utils', autospec=True)
    @mock.patch.object(redfish_boot, 'boot_mode_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_prepare_instance_ramdisk_boot_render_configdrive(
            self, mock_system, mock_boot_mode_utils, mock_deploy_utils,
            mock_node_set_boot_device, mock__parse_deploy_info,
            mock_prepare_boot_iso,
            mock_image_cleanup, mock_disk_cleanup):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid
            task.node.instance_info['configdrive'] = {'meta_data': {}}

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

            mock_node_set_boot_device.assert_called_once_with(
                task, boot_devices.UEFIHTTP, persistent=True)

            mock_boot_mode_utils.sync_boot_mode.assert_called_once_with(task)
            mock_image_cleanup.assert_called_once_with(task)
            mock_disk_cleanup.assert_not_called()

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'sync_boot_mode', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_boot, 'manager_utils', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def _test_prepare_instance_local_boot(
            self, mock_system, mock_manager_utils,
            mock_cleanup_iso_image, mock_sync_boot_mode,
            mock_secure_boot):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.driver_internal_info[
                'root_uuid_or_disk_id'] = self.node.uuid

            task.driver.boot.prepare_instance(task)

            mock_manager_utils.node_set_boot_device.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            mock_cleanup_iso_image.assert_called_once_with(task)
            mock_sync_boot_mode.assert_called_once_with(task)
            mock_secure_boot.assert_called_once_with(task)

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

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def _test_clean_up_instance(self, mock_system, mock_cleanup_iso_image,
                                mock_secure_boot):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.boot.clean_up_instance(task)

            mock_cleanup_iso_image.assert_called_once_with(task)
            mock_secure_boot.assert_called_once_with(task)

    def test_clean_up_instance_only_cdrom(self):
        self._test_clean_up_instance()

    def test_clean_up_instance_cdrom_and_floppy(self):
        driver_info = self.node.driver_info
        driver_info['config_via_removable'] = True
        self.node.driver_info = driver_info
        self.node.save()
        self._test_clean_up_instance()

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_disk_image', autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_clean_up_instance_ramdisk(self, mock_system,
                                       mock_cleanup_iso_image,
                                       mock_cleanup_disk_image,
                                       mock_get_boot_option,
                                       mock_secure_boot):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_get_boot_option.return_value = 'ramdisk'

            task.driver.boot.clean_up_instance(task)

            mock_cleanup_iso_image.assert_called_once_with(task)

            mock_secure_boot.assert_called_once_with(task)
            mock_cleanup_disk_image.assert_not_called()
