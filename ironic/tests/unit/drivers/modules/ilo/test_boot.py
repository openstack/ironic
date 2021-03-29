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

"""Test class for boot methods used by iLO modules."""

from unittest import mock
from urllib import parse as urlparse

from oslo_config import cfg

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common import image_service
from ironic.common import images
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import management as ilo_management
from ironic.drivers.modules import image_utils
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.ilo import test_common
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF
INFO_DICT = db_utils.get_test_ilo_info()


class IloBootCommonMethodsTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    def test_parse_driver_info_deploy_iso(self):
        self.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
        self.node.driver_info['ilo_kernel_append_params'] = 'kernel-param'
        expected_driver_info = {'ilo_bootloader': None,
                                'ilo_kernel_append_params': 'kernel-param',
                                'ilo_deploy_iso': 'deploy-iso'}

        actual_driver_info = ilo_boot.parse_driver_info(self.node)
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_rescue_iso(self):
        self.node.driver_info['ilo_rescue_iso'] = 'rescue-iso'
        expected_driver_info = {'ilo_bootloader': None,
                                'ilo_kernel_append_params': None,
                                'ilo_rescue_iso': 'rescue-iso'}

        actual_driver_info = ilo_boot.parse_driver_info(self.node, 'rescue')
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_deploy(self):
        self.node.driver_info['ilo_deploy_kernel'] = 'kernel'
        self.node.driver_info['ilo_deploy_ramdisk'] = 'ramdisk'
        self.node.driver_info['ilo_bootloader'] = 'bootloader'
        self.node.driver_info['ilo_kernel_append_params'] = 'kernel-param'
        expected_driver_info = {'ilo_deploy_kernel': 'kernel',
                                'ilo_deploy_ramdisk': 'ramdisk',
                                'ilo_bootloader': 'bootloader',
                                'ilo_kernel_append_params': 'kernel-param'}

        actual_driver_info = ilo_boot.parse_driver_info(self.node)
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_rescue(self):
        self.node.driver_info['ilo_rescue_kernel'] = 'kernel'
        self.node.driver_info['ilo_rescue_ramdisk'] = 'ramdisk'
        self.node.driver_info['ilo_bootloader'] = 'bootloader'
        expected_driver_info = {'ilo_rescue_kernel': 'kernel',
                                'ilo_rescue_ramdisk': 'ramdisk',
                                'ilo_bootloader': 'bootloader',
                                'ilo_kernel_append_params': None}

        actual_driver_info = ilo_boot.parse_driver_info(self.node, 'rescue')
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_deploy_config(self):
        CONF.conductor.deploy_kernel = 'kernel'
        CONF.conductor.deploy_ramdisk = 'ramdisk'
        CONF.conductor.bootloader = 'bootloader'
        expected_driver_info = {'ilo_deploy_kernel': 'kernel',
                                'ilo_deploy_ramdisk': 'ramdisk',
                                'ilo_bootloader': 'bootloader',
                                'ilo_kernel_append_params': None}

        actual_driver_info = ilo_boot.parse_driver_info(self.node)
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_rescue_config(self):
        CONF.conductor.rescue_kernel = 'kernel'
        CONF.conductor.rescue_ramdisk = 'ramdisk'
        CONF.conductor.bootloader = 'bootloader'

        expected_driver_info = {'ilo_rescue_kernel': 'kernel',
                                'ilo_rescue_ramdisk': 'ramdisk',
                                'ilo_bootloader': 'bootloader',
                                'ilo_kernel_append_params': None}

        actual_driver_info = ilo_boot.parse_driver_info(self.node, 'rescue')
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_bootloader_none(self):
        CONF.conductor.deploy_kernel = 'kernel'
        CONF.conductor.deploy_ramdisk = 'ramdisk'

        expected_driver_info = {'ilo_deploy_kernel': 'kernel',
                                'ilo_deploy_ramdisk': 'ramdisk',
                                'ilo_bootloader': None,
                                'ilo_kernel_append_params': None}

        actual_driver_info = ilo_boot.parse_driver_info(self.node)
        self.assertEqual(expected_driver_info, actual_driver_info)

    def test_parse_driver_info_exc(self):
        self.assertRaises(exception.MissingParameterValue,
                          ilo_boot.parse_driver_info, self.node)


class IloBootPrivateMethodsTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    def test__get_boot_iso_http_url(self, service_mock):
        url = 'http://abc.org/image/qcow2'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = url
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            service_mock.assert_called_once_with(mock.ANY, url)
            self.assertEqual(url, boot_iso_actual)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    def test__get_boot_iso_unsupported_url(self, validate_href_mock):
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='file://img.qcow2', reason='fail')
        url = 'file://img.qcow2'
        i_info = self.node.instance_info
        i_info['ilo_boot_iso'] = url
        self.node.instance_info = i_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.ImageRefValidationFailed,
                              ilo_boot._get_boot_iso, task, 'root-uuid')

    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_glance_image(self, deploy_info_mock,
                                        image_props_mock):
        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': u'glance://uui\u0111'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid', ['boot_iso'])
            boot_iso_expected = u'glance://uui\u0111'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(image_utils, 'prepare_boot_iso', spec_set=True,
                       autospec=True)
    @mock.patch.object(images, 'get_image_properties', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def test__get_boot_iso_create(self, deploy_info_mock, image_props_mock,
                                  prepare_iso_mock):

        deploy_info_mock.return_value = {'image_source': 'image-uuid',
                                         'ilo_deploy_iso': 'deploy_iso_uuid'}
        image_props_mock.return_value = {'boot_iso': None}

        prepare_iso_mock.return_value = 'swift:boot-iso'
        d_info = {'image_source': 'image-uuid',
                  'ilo_deploy_iso': 'deploy_iso_uuid'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            boot_iso_actual = ilo_boot._get_boot_iso(task, 'root-uuid')
            deploy_info_mock.assert_called_once_with(task.node)
            image_props_mock.assert_called_once_with(
                task.context, 'image-uuid', ['boot_iso'])
            prepare_iso_mock.assert_called_once_with(
                task, d_info, 'root-uuid')
            boot_iso_expected = 'swift:boot-iso'
            self.assertEqual(boot_iso_expected, boot_iso_actual)

    @mock.patch.object(ilo_boot, 'parse_driver_info', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       spec_set=True, autospec=True)
    def test__parse_deploy_info(self, instance_info_mock, driver_info_mock):
        instance_info_mock.return_value = {'a': 'b'}
        driver_info_mock.return_value = {'c': 'd'}
        expected_info = {'a': 'b', 'c': 'd'}
        actual_info = ilo_boot._parse_deploy_info(self.node)
        self.assertEqual(expected_info, actual_info)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_driver_info(self, mock_driver_info,
                                   mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_boot._validate_driver_info(task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_parse_deploy_info', spec_set=True,
                       autospec=True)
    def _test__validate_instance_image_info(self,
                                            deploy_info_mock,
                                            validate_prop_mock,
                                            props_expected):
        d_info = {'image_source': 'uuid'}
        deploy_info_mock.return_value = d_info
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ilo_boot._validate_instance_image_info(task)
            deploy_info_mock.assert_called_once_with(task.node)
            validate_prop_mock.assert_called_once_with(
                task.context, d_info, props_expected)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_glance_partition_image(self,
                                              is_glance_image_mock):
        is_glance_image_mock.return_value = True
        self._test__validate_instance_image_info(props_expected=['kernel_id',
                                                                 'ramdisk_id'])

    def test__validate_whole_disk_image(self):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        self._test__validate_instance_image_info(props_expected=[])

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_non_glance_partition_image(self, is_glance_image_mock):
        is_glance_image_mock.return_value = False
        self._test__validate_instance_image_info(props_expected=['kernel',
                                                                 'ramdisk'])

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_false(self,
                                        func_get_secure_boot_mode,
                                        func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            self.assertFalse(func_set_secure_boot_mode.called)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_true(self,
                                       func_get_secure_boot_mode,
                                       func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            func_set_secure_boot_mode.assert_called_once_with(task, False)
        self.assertTrue(returned_state)

    @mock.patch.object(ilo_boot, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_exception(self,
                                            func_get_secure_boot_mode,
                                            exception_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            exception_mock.IloOperationNotSupported = Exception
            func_get_secure_boot_mode.side_effect = Exception
            returned_state = ilo_boot._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy(self,
                                     func_node_power_action,
                                     func_disable_secure_boot,
                                     func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_sec_boot_on(self,
                                                 func_node_power_action,
                                                 func_disable_secure_boot,
                                                 func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            ret_boot_mode = task.node.driver_internal_info['deploy_boot_mode']
            self.assertEqual('uefi', ret_boot_mode)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_inst_info(self,
                                               func_node_power_action,
                                               func_disable_secure_boot,
                                               func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            task.node.instance_info = instance_info
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode',
                             task.node.driver_internal_info)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_node_for_deploy_sec_boot_on_inst_info(
            self, func_node_power_action, func_disable_secure_boot,
            func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            task.node.instance_info = instance_info
            ilo_boot.prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode',
                             task.node.driver_internal_info)


class IloVirtualMediaBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-virtual-media'

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate(self, mock_val_instance_image_info,
                      mock_val_driver_info, storage_mock):
        instance_info = self.node.instance_info
        instance_info['ilo_boot_iso'] = 'deploy-iso'
        instance_info['image_source'] = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            storage_mock.return_value = True
            task.driver.boot.validate(task)
            mock_val_instance_image_info.assert_called_once_with(task)
            mock_val_driver_info.assert_called_once_with(task)

    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_glance(self, is_glance_image_mock,
                                                 validate_href_mock,
                                                 val_driver_info_mock):
        instance_info = self.node.instance_info
        boot_iso = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = True
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            self.assertFalse(validate_href_mock.called)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver(self, is_glance_image_mock,
                                                    validate_href_mock,
                                                    val_driver_info_mock):
        instance_info = self.node.instance_info
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = False
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_boot.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver_exc(self,
                                                        is_glance_image_mock,
                                                        validate_href_mock,
                                                        val_driver_info_mock,
                                                        log_mock):
        instance_info = self.node.instance_info
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://myserver/boot.iso', reason='fail')
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            is_glance_image_mock.return_value = False
            self.assertRaisesRegex(exception.ImageRefValidationFailed,
                                   "Validation of image href "
                                   "http://myserver/boot.iso failed",
                                   task.driver.boot.validate, task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)
            self.assertIn("Virtual media deploy with 'ramdisk' boot_option "
                          "accepts only Glance images or HTTP(S) URLs as "
                          "instance_info['ilo_boot_iso'].",
                          log_mock.call_args[0][0])

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate_boot_from_volume(self, mock_val_instance_image_info,
                                       mock_val_driver_info, storage_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            storage_mock.return_value = False
            task.driver.boot.validate(task)
            mock_val_driver_info.assert_called_once_with(task)
            self.assertFalse(mock_val_instance_image_info.called)

    @mock.patch.object(ilo_boot, '_validate_driver_info', autospec=True)
    def test_validate_inspection(self, mock_val_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info['ilo_deploy_iso'] = 'deploy-iso'
            task.driver.boot.validate_inspection(task)
            mock_val_driver_info.assert_called_once_with(task)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_inspection_missing(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.boot.validate_inspection, task)

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_single_nic_with_vif_port_id',
                       spec_set=True, autospec=True)
    def _test_prepare_ramdisk(self, get_nic_mock, setup_vmedia_mock,
                              eject_mock,
                              prepare_node_for_deploy_mock,
                              ilo_boot_iso, image_source,
                              ramdisk_params={'a': 'b'},
                              mode='deploy'):
        instance_info = self.node.instance_info
        instance_info['ilo_boot_iso'] = ilo_boot_iso
        instance_info['image_source'] = image_source
        self.node.instance_info = instance_info
        self.node.save()
        iso = 'provisioning-iso'

        get_nic_mock.return_value = '12:34:56:78:90:ab'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            driver_info = task.node.driver_info
            driver_info['ilo_%s_iso' % mode] = iso
            task.node.driver_info = driver_info

            task.driver.boot.prepare_ramdisk(task, ramdisk_params)

            prepare_node_for_deploy_mock.assert_called_once_with(task)
            eject_mock.assert_called_once_with(task)
            expected_ramdisk_opts = {'a': 'b', 'BOOTIF': '12:34:56:78:90:ab',
                                     'ipa-agent-token': mock.ANY,
                                     'boot_method': 'vmedia'}
            get_nic_mock.assert_called_once_with(task)
            setup_vmedia_mock.assert_called_once_with(task, iso,
                                                      expected_ramdisk_opts)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_prepare_ramdisk_in_takeover(self, mock_is_image):
        """Ensure deploy ops are blocked when not deploying and not cleaning"""

        for state in states.STABLE_STATES:
            mock_is_image.reset_mock()
            self.node.provision_state = state
            self.node.save()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                self.assertIsNone(
                    task.driver.boot.prepare_ramdisk(task, None))
                self.assertFalse(mock_is_image.called)

    def test_prepare_ramdisk_rescue_glance_image(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af',
            mode='rescue')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_rescue_not_a_glance_image(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage',
            mode='rescue')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'eject_vmedia_devices',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_single_nic_with_vif_port_id',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'rescue_or_deploy_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, 'parse_driver_info', spec_set=True,
                       autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso',
                       spec_set=True, autospec=True)
    def test_prepare_ramdisk_not_iso(
            self, prepare_deploy_iso_mock, driver_info_mock,
            mode_mock, get_nic_mock, setup_vmedia_mock,
            eject_mock, prepare_node_for_deploy_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        mode = 'deploy'
        ramdisk_params = {'a': 'b'}
        d_info = {
            'ilo_deploy_kernel': 'kernel',
            'ilo_deploy_ramdisk': 'ramdisk',
            'ilo_bootloader': 'bootloader'
        }
        driver_info_mock.return_value = d_info
        prepare_deploy_iso_mock.return_value = 'recreated-iso'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mode_mock.return_value = 'deploy'
            get_nic_mock.return_value = '12:34:56:78:90:ab'
            task.driver.boot.prepare_ramdisk(task, ramdisk_params)
            prepare_node_for_deploy_mock.assert_called_once_with(task)
            eject_mock.assert_called_once_with(task)
            driver_info_mock.assert_called_once_with(task.node, mode)
            prepare_deploy_iso_mock.assert_called_once_with(
                task, ramdisk_params, mode, d_info)
            setup_vmedia_mock.assert_called_once_with(task, 'recreated-iso')

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso', spec_set=True,
                       autospec=True)
    def test__configure_vmedia_boot_with_boot_iso(
            self, get_boot_iso_mock, setup_vmedia_mock, set_boot_device_mock):
        root_uuid = {'root uuid': 'root_uuid'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_boot_iso_mock.return_value = 'boot.iso'

            task.driver.boot._configure_vmedia_boot(
                task, root_uuid)

            get_boot_iso_mock.assert_called_once_with(
                task, root_uuid)
            setup_vmedia_mock.assert_called_once_with(
                task, 'boot.iso')
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)
            self.assertEqual('boot.iso',
                             task.node.instance_info['ilo_boot_iso'])

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso', spec_set=True,
                       autospec=True)
    def test__configure_vmedia_boot_without_boot_iso(
            self, get_boot_iso_mock, setup_vmedia_mock, set_boot_device_mock):
        root_uuid = {'root uuid': 'root_uuid'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_boot_iso_mock.return_value = None

            task.driver.boot._configure_vmedia_boot(
                task, root_uuid)

            get_boot_iso_mock.assert_called_once_with(
                task, root_uuid)
            self.assertFalse(setup_vmedia_mock.called)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    def _test_clean_up_instance(self, cleanup_iso_mock,
                                cleanup_vmedia_mock, node_power_mock,
                                update_secure_boot_mode_mock,
                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            cleanup_iso_mock.assert_called_once_with(task)
            cleanup_vmedia_mock.assert_called_once_with(task)
            driver_internal_info = task.node.driver_internal_info
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task)

    def test_clean_up_instance_deleting(self):
        self.node.provisioning_state = states.DELETING
        self._test_clean_up_instance()

    def test_clean_up_instance_rescuing(self):
        self.node.provisioning_state = states.RESCUING
        self._test_clean_up_instance()

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(
            self, node_power_mock, update_secure_boot_mode_mock,
            clear_iscsi_boot_target_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, node_power_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_iso_mock, cleanup_vmedia_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            cleanup_iso_mock.assert_called_once_with(task)
            cleanup_vmedia_mock.assert_called_once_with(task)
            node_power_mock.assert_called_once_with(task,
                                                    states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task)

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'rescue_or_deploy_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    def test_clean_up_ramdisk(self, cleanup_iso_mock, mode_mock,
                              cleanup_vmedia_mock):
        mode_mock.return_value = 'deploy'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_ramdisk(task)
            cleanup_vmedia_mock.assert_called_once_with(task)
            mode_mock.assert_called_once_with(task.node)
            cleanup_iso_mock.assert_called_once_with(task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def _test_prepare_instance_whole_disk_image(
            self, cleanup_vmedia_boot_mock, set_boot_device_mock,
            update_boot_mode_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        is_iscsi_boot_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)

            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK,
                                                         persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    def test_prepare_instance_whole_disk_image_local(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        self.node.save()
        self._test_prepare_instance_whole_disk_image()

    def test_prepare_instance_whole_disk_image(self):
        self._test_prepare_instance_whole_disk_image()

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot.IloVirtualMediaBoot,
                       '_configure_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def test_prepare_instance_partition_image(
            self, cleanup_vmedia_boot_mock, configure_vmedia_mock,
            update_boot_mode_mock, update_secure_boot_mode_mock,
            is_iscsi_boot_mock):
        self.node.driver_internal_info = {'root_uuid_or_disk_id': (
            "12312642-09d3-467f-8e09-12385826a123")}
        self.node.instance_info = {
            'capabilities': {'boot_option': 'netboot'}}
        self.node.save()
        is_iscsi_boot_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            configure_vmedia_mock.assert_called_once_with(
                mock.ANY, task, "12312642-09d3-467f-8e09-12385826a123")
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_from_volume_bios(
            self, get_boot_mode_mock,
            is_iscsi_boot_mock, cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'bios'
            self.assertRaisesRegex(exception.InstanceDeployFailure,
                                   "Virtual media can not boot volume "
                                   "in BIOS boot mode.",
                                   task.driver.boot.prepare_instance, task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(ilo_common, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, '_get_boot_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_ramdisk(self, update_secure_boot_mode_mock,
                                           update_boot_mode_mock,
                                           set_boot_device_mock,
                                           get_boot_iso_mock,
                                           setup_vmedia_mock,
                                           is_iscsi_boot_mock,
                                           cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
            task.node.instance_info = instance_info
            task.node.save()
            is_iscsi_boot_mock.return_value = False
            url = 'http://myserver/boot.iso'
            get_boot_iso_mock.return_value = url
            task.driver.boot.prepare_instance(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            get_boot_iso_mock.assert_called_once_with(task, None)
            setup_vmedia_mock.assert_called_once_with(task, url)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.CDROM, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)

    def test_validate_rescue(self):
        driver_info = self.node.driver_info
        driver_info['ilo_rescue_iso'] = 'rescue.iso'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.boot.validate_rescue(task)

    def test_validate_rescue_no_rescue_ramdisk(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'Some parameters were missing*',
                                   task.driver.boot.validate_rescue, task)


class IloPXEBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-pxe'

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    def _test_prepare_ramdisk_needs_node_prep(self, pxe_prepare_ramdisk_mock,
                                              prepare_node_mock, prov_state):
        self.node.provision_state = prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(
                task.driver.boot.prepare_ramdisk(task, None))

            prepare_node_mock.assert_called_once_with(task)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                mock.ANY, task, None)

    def test_prepare_ramdisk_in_deploying(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.DEPLOYING)

    def test_prepare_ramdisk_in_rescuing(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.RESCUING)

    def test_prepare_ramdisk_in_cleaning(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.CLEANING)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance(self, pxe_cleanup_mock, node_power_mock,
                               is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, pxe_cleanup_mock, node_power_mock, is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(self, node_power_mock,
                                                update_secure_boot_mode_mock,
                                                clear_iscsi_boot_target_mock,
                                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance(self, pxe_prepare_instance_mock,
                              update_boot_mode_mock,
                              get_boot_mode_mock,
                              is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            update_boot_mode_mock.assert_called_once_with(task)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance_bios(self, pxe_prepare_instance_mock,
                                   update_boot_mode_mock,
                                   get_boot_mode_mock,
                                   is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'bios'
            task.driver.boot.prepare_instance(task)
            update_boot_mode_mock.assert_called_once_with(task)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class IloiPXEBootTestCase(test_common.BaseIloTest):

    boot_interface = 'ilo-ipxe'

    def setUp(self):
        super(IloiPXEBootTestCase, self).setUp()
        self.config(enabled_boot_interfaces=['ilo-ipxe'])

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    def _test_prepare_ramdisk_needs_node_prep(self, pxe_prepare_ramdisk_mock,
                                              prepare_node_mock, prov_state):
        self.node.provision_state = prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertIsNone(
                task.driver.boot.prepare_ramdisk(task, None))

            prepare_node_mock.assert_called_once_with(task)
            pxe_prepare_ramdisk_mock.assert_called_once_with(
                mock.ANY, task, None)

    def test_prepare_ramdisk_in_deploying(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.DEPLOYING)

    def test_prepare_ramdisk_in_rescuing(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.RESCUING)

    def test_prepare_ramdisk_in_cleaning(self):
        self._test_prepare_ramdisk_needs_node_prep(prov_state=states.CLEANING)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance(self, pxe_cleanup_mock, node_power_mock,
                               is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'clean_up_instance', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume_bios(
            self, pxe_cleanup_mock, node_power_mock, is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            pxe_cleanup_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'clear_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_clean_up_instance_boot_from_volume(self, node_power_mock,
                                                update_secure_boot_mode_mock,
                                                clear_iscsi_boot_target_mock,
                                                is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['ilo_uefi_iscsi_boot'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            is_iscsi_boot_mock.return_value = True
            task.driver.boot.clean_up_instance(task)
            clear_iscsi_boot_target_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            node_power_mock.assert_called_once_with(task, states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance(self, pxe_prepare_instance_mock,
                              update_boot_mode_mock,
                              get_boot_mode_mock,
                              is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            update_boot_mode_mock.assert_called_once_with(task)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ipxe.iPXEBoot, 'prepare_instance', spec_set=True,
                       autospec=True)
    def test_prepare_instance_bios(self, pxe_prepare_instance_mock,
                                   update_boot_mode_mock,
                                   get_boot_mode_mock,
                                   is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = False
            get_boot_mode_mock.return_value = 'bios'
            task.driver.boot.prepare_instance(task)
            update_boot_mode_mock.assert_called_once_with(task)
            pxe_prepare_instance_mock.assert_called_once_with(mock.ANY, task)
            self.assertIsNone(task.node.driver_internal_info.get(
                              'ilo_uefi_iscsi_boot'))

    @mock.patch.object(deploy_utils, 'is_iscsi_boot',
                       spec_set=True, autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_management.IloManagement, 'set_iscsi_boot_target',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    def test_prepare_instance_boot_from_volume(
            self, update_secure_boot_mode_mock,
            update_boot_mode_mock, set_boot_device_mock,
            set_iscsi_boot_target_mock, get_boot_mode_mock,
            is_iscsi_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_iscsi_boot_mock.return_value = True
            get_boot_mode_mock.return_value = 'uefi'
            task.driver.boot.prepare_instance(task)
            set_iscsi_boot_target_mock.assert_called_once_with(mock.ANY, task)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.ISCSIBOOT, persistent=True)
            update_boot_mode_mock.assert_called_once_with(task)
            update_secure_boot_mode_mock.assert_called_once_with(task)
            self.assertTrue(task.node.driver_internal_info.get(
                            'ilo_uefi_iscsi_boot'))


class IloUefiHttpsBootTestCase(db_base.DbTestCase):
    def setUp(self):
        super(IloUefiHttpsBootTestCase, self).setUp()
        self.driver = mock.Mock(boot=ilo_boot.IloUefiHttpsBoot())
        n = {
            'driver': 'ilo5',
            'driver_info': INFO_DICT
        }
        self.config(enabled_hardware_types=['ilo5'],
                    enabled_boot_interfaces=['ilo-uefi-https'],
                    enabled_console_interfaces=['ilo'],
                    enabled_deploy_interfaces=['iscsi'],
                    enabled_inspect_interfaces=['ilo'],
                    enabled_management_interfaces=['ilo5'],
                    enabled_power_interfaces=['ilo'],
                    enabled_raid_interfaces=['ilo5'])
        self.node = obj_utils.create_test_node(self.context, **n)

    @mock.patch.object(urlparse, 'urlparse', spec_set=True,
                       autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_hrefs_https_image(self, is_glance_mock, urlparse_mock):
        is_glance_mock.return_value = False
        urlparse_mock.return_value.scheme = 'https'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            data = {
                'ilo_deploy_kernel': 'https://a.b.c.d/kernel',
                'ilo_deploy_ramdisk': 'https://a.b.c.d/ramdisk',
                'ilo_bootloader': 'https://a.b.c.d/bootloader'
            }
            task.driver.boot._validate_hrefs(data)

        glance_calls = [
            mock.call('https://a.b.c.d/kernel'),
            mock.call('https://a.b.c.d/ramdisk'),
            mock.call('https://a.b.c.d/bootloader')
        ]

        is_glance_mock.assert_has_calls(glance_calls)
        urlparse_mock.assert_has_calls(glance_calls)

    @mock.patch.object(urlparse, 'urlparse', spec_set=True,
                       autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_hrefs_http_image(self, is_glance_mock, urlparse_mock):
        is_glance_mock.return_value = False
        scheme_mock = mock.PropertyMock(
            side_effect=['http', 'https', 'http'])
        type(urlparse_mock.return_value).scheme = scheme_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            data = {
                'ilo_deploy_kernel': 'http://a.b.c.d/kernel',
                'ilo_deploy_ramdisk': 'https://a.b.c.d/ramdisk',
                'ilo_bootloader': 'http://a.b.c.d/bootloader'
            }

            glance_calls = [
                mock.call('http://a.b.c.d/kernel'),
                mock.call('https://a.b.c.d/ramdisk'),
                mock.call('http://a.b.c.d/bootloader')
            ]
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Secure URLs exposed over HTTPS are .*"
                                   "['ilo_deploy_kernel', 'ilo_bootloader']",
                                   task.driver.boot._validate_hrefs, data)
            is_glance_mock.assert_has_calls(glance_calls)
            urlparse_mock.assert_has_calls(glance_calls)

    @mock.patch.object(urlparse, 'urlparse', spec_set=True,
                       autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_hrefs_glance_image(self, is_glance_mock, urlparse_mock):
        is_glance_mock.return_value = True

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            data = {
                'ilo_deploy_kernel': 'https://a.b.c.d/kernel',
                'ilo_deploy_ramdisk': 'https://a.b.c.d/ramdisk',
                'ilo_bootloader': 'https://a.b.c.d/bootloader'
            }

            task.driver.boot._validate_hrefs(data)

        glance_calls = [
            mock.call('https://a.b.c.d/kernel'),
            mock.call('https://a.b.c.d/ramdisk'),
            mock.call('https://a.b.c.d/bootloader')
        ]

        is_glance_mock.assert_has_calls(glance_calls)
        urlparse_mock.assert_not_called()

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_driver_info',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       autospec=True)
    def test__parse_deploy_info(self, get_img_inst_mock,
                                parse_driver_mock):
        parse_driver_mock.return_value = {
            'ilo_deploy_kernel': 'deploy-kernel',
            'ilo_deploy_ramdisk': 'deploy-ramdisk',
            'ilo_bootloader': 'bootloader'
        }
        get_img_inst_mock.return_value = {
            'ilo_boot_iso': 'boot-iso',
            'image_source': '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        }
        instance_info = self.node.instance_info
        driver_info = self.node.driver_info

        instance_info['ilo_boot_iso'] = 'boot-iso'
        instance_info['image_source'] = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        self.node.instance_info = instance_info

        driver_info['ilo_deploy_kernel'] = 'deploy-kernel'
        driver_info['ilo_deploy_ramdisk'] = 'deploy-ramdisk'
        driver_info['ilo_bootloader'] = 'bootloader'
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            expected_info = {
                'ilo_deploy_kernel': 'deploy-kernel',
                'ilo_deploy_ramdisk': 'deploy-ramdisk',
                'ilo_bootloader': 'bootloader',
                'ilo_boot_iso': 'boot-iso',
                'image_source': '6b2f0c0c-79e8-4db6-842e-43c9764204af'
            }

            actual_info = task.driver.boot._parse_deploy_info(task.node)
            get_img_inst_mock.assert_called_once_with(task.node)
            parse_driver_mock.assert_called_once_with(mock.ANY, task.node)
        self.assertEqual(expected_info, actual_info)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'check_for_missing_params',
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', autospec=True)
    def test__parse_driver_info_default_mode(
            self, parse_driver_mock, check_missing_mock, validate_href_mock):
        parse_driver_mock.return_value = {
            'ilo_username': 'admin',
            'ilo_password': 'admin'
        }
        driver_info = self.node.driver_info
        driver_info['ilo_deploy_kernel'] = 'deploy-kernel'
        driver_info['ilo_rescue_kernel'] = 'rescue-kernel'
        driver_info['ilo_deploy_ramdisk'] = 'deploy-ramdisk'
        driver_info['ilo_rescue_ramdisk'] = 'rescue-ramdisk'
        driver_info['ilo_bootloader'] = 'bootloader'
        driver_info['ilo_add_certificates'] = True
        driver_info['dummy_key'] = 'dummy-value'
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_info = {
                'ilo_deploy_kernel': 'deploy-kernel',
                'ilo_deploy_ramdisk': 'deploy-ramdisk',
                'ilo_bootloader': 'bootloader',
                'ilo_kernel_append_params': 'nofb nomodeset vga=normal'
            }

            deploy_info.update({'ilo_username': 'admin',
                                'ilo_password': 'admin'})

            expected_info = task.driver.boot._parse_driver_info(task.node)
            validate_href_mock.assert_called_once_with(mock.ANY, deploy_info)
            check_missing_mock.assert_called_once_with(deploy_info, mock.ANY)
            parse_driver_mock.assert_called_once_with(task.node)
            self.assertEqual(deploy_info, expected_info)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'check_for_missing_params',
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', autospec=True)
    def test__parse_driver_info_rescue_mode(
            self, parse_driver_mock, check_missing_mock, validate_href_mock):
        parse_driver_mock.return_value = {
            'ilo_username': 'admin',
            'ilo_password': 'admin'
        }
        mode = 'rescue'
        driver_info = self.node.driver_info
        driver_info['ilo_deploy_kernel'] = 'deploy-kernel'
        driver_info['ilo_rescue_kernel'] = 'rescue-kernel'
        driver_info['ilo_deploy_ramdisk'] = 'deploy-ramdisk'
        driver_info['ilo_rescue_ramdisk'] = 'rescue-ramdisk'
        driver_info['ilo_bootloader'] = 'bootloader'
        driver_info['ilo_add_certificates'] = 'false'
        driver_info['ilo_kernel_append_params'] = 'kernel-param'
        driver_info['dummy_key'] = 'dummy-value'
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_info = {
                'ilo_rescue_kernel': 'rescue-kernel',
                'ilo_rescue_ramdisk': 'rescue-ramdisk',
                'ilo_bootloader': 'bootloader',
                'ilo_kernel_append_params': 'kernel-param'
            }

            deploy_info.update({'ilo_username': 'admin',
                                'ilo_password': 'admin'})

            expected_info = task.driver.boot._parse_driver_info(
                task.node, mode)
            check_missing_mock.assert_called_once_with(deploy_info, mock.ANY)
            validate_href_mock.assert_called_once_with(mock.ANY, deploy_info)
            parse_driver_mock.assert_called_once_with(task.node)
            self.assertEqual(deploy_info, expected_info)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'check_for_missing_params',
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', autospec=True)
    def test__parse_driver_info_invalid_params(
            self, parse_driver_mock, check_missing_mock, validate_href_mock):
        parse_driver_mock.return_value = {
            'ilo_username': 'admin',
            'ilo_password': 'admin'
        }
        driver_info = self.node.driver_info
        driver_info['ilo_deploy_kernel'] = 'deploy-kernel'
        driver_info['ilo_rescue_kernel'] = 'rescue-kernel'
        driver_info['ilo_deploy_ramdisk'] = 'deploy-ramdisk'
        driver_info['ilo_rescue_ramdisk'] = 'rescue-ramdisk'
        driver_info['ilo_bootloader'] = 'bootloader'
        driver_info['dummy_key'] = 'dummy-value'
        driver_info['ilo_add_certificates'] = 'xyz'
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_info = {
                'ilo_deploy_kernel': 'deploy-kernel',
                'ilo_deploy_ramdisk': 'deploy-ramdisk',
                'ilo_bootloader': 'bootloader'
            }

            deploy_info.update({'ilo_username': 'admin',
                                'ilo_password': 'admin'})
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Invalid value type set in driver_info.*",
                                   task.driver.boot._parse_driver_info,
                                   task.node)
            validate_href_mock.assert_not_called()
            check_missing_mock.assert_not_called()
            parse_driver_mock.assert_not_called()

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_instance_image_info_not_iwdi(
            self, glance_mock, get_image_inst_mock, validate_image_mock,
            validate_href_mock):
        instance_info = {
            'ilo_boot_iso': 'boot-iso',
            'image_source': '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        }
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info.pop('is_whole_disk_image', None)
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = instance_info
        self.node.save()
        get_image_inst_mock.return_value = instance_info
        glance_mock.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.driver.boot._validate_instance_image_info(task)
            get_image_inst_mock.assert_called_once_with(task.node)
            glance_mock.assert_called_once_with(
                '6b2f0c0c-79e8-4db6-842e-43c9764204af')
            validate_image_mock.assert_called_once_with(task.context,
                                                        instance_info,
                                                        ['kernel_id',
                                                         'ramdisk_id'])
            validate_href_mock.assert_called_once_with(mock.ANY, instance_info)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_instance_image_info_neither_iwdi_nor_glance(
            self, glance_mock, get_image_inst_mock, validate_image_mock,
            validate_href_mock):

        instance_info = {
            'ilo_boot_iso': 'boot-iso',
            'image_source': '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        }
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info.pop('is_whole_disk_image', None)
        self.node.driver_internal_info = driver_internal_info
        self.node.instance_info = instance_info
        self.node.save()
        get_image_inst_mock.return_value = instance_info
        glance_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.driver.boot._validate_instance_image_info(task)
            get_image_inst_mock.assert_called_once_with(task.node)
            glance_mock.assert_called_once_with(
                '6b2f0c0c-79e8-4db6-842e-43c9764204af')
            validate_image_mock.assert_called_once_with(task.context,
                                                        instance_info,
                                                        ['kernel',
                                                         'ramdisk'])
            validate_href_mock.assert_called_once_with(mock.ANY, instance_info)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_hrefs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'validate_image_properties',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'get_image_instance_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test__validate_instance_image_info_iwdi(
            self, glance_mock, get_image_inst_mock, validate_image_mock,
            validate_href_mock):
        instance_info = {
            'ilo_boot_iso': 'boot-iso',
            'image_source': '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        }
        driver_internal_info = self.node.driver_internal_info or {}
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        get_image_inst_mock.return_value = instance_info
        glance_mock.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.driver.boot._validate_instance_image_info(task)
            get_image_inst_mock.assert_called_once_with(task.node)
            glance_mock.assert_not_called()
            validate_image_mock.assert_called_once_with(task.context,
                                                        instance_info, [])
            validate_href_mock.assert_called_once_with(mock.ANY, instance_info)

    @mock.patch.object(ilo_common, 'get_current_boot_mode',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot,
                       '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate(self, mock_val_instance_image_info,
                      mock_val_driver_info, storage_mock, get_boot_mock):
        get_boot_mock.return_value = 'UEFI'
        instance_info = self.node.instance_info

        instance_info['ilo_boot_iso'] = 'boot-iso'
        instance_info['image_source'] = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            task.node.driver_info['ilo_deploy_kernel'] = 'deploy-kernel'
            task.node.driver_info['ilo_deploy_ramdisk'] = 'deploy-ramdisk'
            task.node.driver_info['ilo_bootloader'] = 'bootloader'
            storage_mock.return_value = True
            task.driver.boot.validate(task)
            mock_val_instance_image_info.assert_called_once_with(
                mock.ANY, task)
            mock_val_driver_info.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ilo_common, 'get_current_boot_mode',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot,
                       '_validate_instance_image_info',
                       spec_set=True, autospec=True)
    def test_validate_bios(self, mock_val_instance_image_info,
                           mock_val_driver_info, storage_mock, get_boot_mock):
        get_boot_mock.return_value = 'LEGACY'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Validation for 'ilo-uefi-https' boot "
                                   "interface failed.*",
                                   task.driver.boot.validate, task)
            mock_val_instance_image_info.assert_not_called()
            mock_val_driver_info.assert_not_called()

    @mock.patch.object(ilo_common, 'get_current_boot_mode',
                       autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_glance(self, is_glance_image_mock,
                                                 validate_href_mock,
                                                 val_driver_info_mock,
                                                 get_boot_mock):
        get_boot_mock.return_value = 'UEFI'
        instance_info = self.node.instance_info
        boot_iso = '6b2f0c0c-79e8-4db6-842e-43c9764204af'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = True
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            self.assertFalse(validate_href_mock.called)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_common, 'get_current_boot_mode',
                       autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver(self, is_glance_image_mock,
                                                    validate_href_mock,
                                                    val_driver_info_mock,
                                                    get_boot_mock):
        get_boot_mock.return_value = 'UEFI'
        instance_info = self.node.instance_info
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            is_glance_image_mock.return_value = False
            task.driver.boot.validate(task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)

    @mock.patch.object(ilo_common, 'get_current_boot_mode',
                       autospec=True)
    @mock.patch.object(ilo_boot.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    def test_validate_ramdisk_boot_option_webserver_exc(
            self, is_glance_image_mock, validate_href_mock,
            val_driver_info_mock, log_mock, get_boot_mock):

        get_boot_mock.return_value = 'UEFI'
        instance_info = self.node.instance_info
        validate_href_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://myserver/boot.iso', reason='fail')
        boot_iso = 'http://myserver/boot.iso'
        instance_info['ilo_boot_iso'] = boot_iso
        instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
        self.node.instance_info = instance_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            is_glance_image_mock.return_value = False
            self.assertRaisesRegex(exception.ImageRefValidationFailed,
                                   "Validation of image href "
                                   "http://myserver/boot.iso failed",
                                   task.driver.boot.validate, task)
            is_glance_image_mock.assert_called_once_with(boot_iso)
            validate_href_mock.assert_called_once_with(mock.ANY, boot_iso)
            self.assertFalse(val_driver_info_mock.called)
            self.assertIn("UEFI-HTTPS boot with 'ramdisk' boot_option "
                          "accepts only Glance images or HTTPS URLs as "
                          "instance_info['ilo_boot_iso'].",
                          log_mock.call_args[0][0])

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_validate_driver_info',
                       autospec=True)
    def test_validate_inspection(self, mock_val_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot.validate_inspection(task)
            mock_val_driver_info.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_driver_info',
                       spec_set=True, autospec=True)
    def test_validate_inspection_missing(self, mock_parse_driver_info):
        mock_parse_driver_info.side_effect = exception.MissingParameterValue(
            "Error validating iLO UEFIHTTPS for deploy.")
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.boot.validate_inspection, task)

    @mock.patch.object(ilo_common, 'add_certificates',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'setup_uefi_https',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_driver_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'get_single_nic_with_vif_port_id',
                       spec_set=True, autospec=True)
    def _test_prepare_ramdisk(self, get_nic_mock,
                              parse_driver_mock,
                              prepare_node_for_deploy_mock,
                              prepare_deploy_iso_mock,
                              setup_uefi_https_mock,
                              add_mock,
                              ilo_boot_iso, image_source,
                              ramdisk_params={'a': 'b'},
                              mode='deploy', state=states.DEPLOYING):
        self.node.provision_state = state
        self.node.save()
        instance_info = self.node.instance_info
        instance_info['ilo_boot_iso'] = ilo_boot_iso
        instance_info['image_source'] = image_source
        self.node.instance_info = instance_info
        self.node.save()
        iso = 'provisioning-iso'

        d_info = {
            'ilo_' + mode + '_kernel': mode + '-kernel',
            'ilo_' + mode + '_ramdisk': mode + '-ramdisk',
            'ilo_' + 'bootloader': 'bootloader'
        }
        parse_driver_mock.return_value = d_info
        prepare_deploy_iso_mock.return_value = 'recreated-iso'

        get_nic_mock.return_value = '12:34:56:78:90:ab'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            driver_info = task.node.driver_info
            driver_info['ilo_%s_iso' % mode] = iso
            task.node.driver_info = driver_info

            task.driver.boot.prepare_ramdisk(task, ramdisk_params)

            prepare_node_for_deploy_mock.assert_called_once_with(task)

            get_nic_mock.assert_called_once_with(task)
            parse_driver_mock.assert_called_once_with(
                mock.ANY, task.node, mode)
            prepare_deploy_iso_mock.assert_called_once_with(
                task, ramdisk_params, mode, d_info)
            setup_uefi_https_mock.assert_called_once_with(task,
                                                          'recreated-iso')
            add_mock.assert_called_once_with(task)

    def test_prepare_ramdisk_rescue_glance_image(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af',
            mode='rescue', state=states.RESCUING)
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_rescue_not_a_glance_image(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage',
            mode='rescue', state=states.RESCUING)
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af')
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage')
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    def test_prepare_ramdisk_glance_image_cleaning(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='swift:abcdef',
            image_source='6b2f0c0c-79e8-4db6-842e-43c9764204af',
            mode='deploy', state=states.CLEANING)
        self.node.refresh()
        self.assertNotIn('ilo_boot_iso', self.node.instance_info)

    def test_prepare_ramdisk_not_a_glance_image_cleaning(self):
        self._test_prepare_ramdisk(
            ilo_boot_iso='http://mybootiso',
            image_source='http://myimage',
            mode='deploy', state=states.CLEANING)
        self.node.refresh()
        self.assertEqual('http://mybootiso',
                         self.node.instance_info['ilo_boot_iso'])

    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    def test_clean_up_ramdisk(self, cleanup_iso_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_ramdisk(task)
            cleanup_iso_mock.assert_called_once_with(task)

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_uefi_https',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'prepare_deploy_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_deploy_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    def _test_prepare_instance_local_or_whole_disk_image(
            self, set_boot_device_mock,
            parse_deploy_mock, prepare_iso_mock, setup_uefi_https_mock,
            cleanup_iso_mock, update_secureboot_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)

            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK,
                                                         persistent=True)
            update_secureboot_mock.assert_called_once_with(task)
            cleanup_iso_mock.assert_called_once_with(task)
            prepare_iso_mock.assert_not_called()
            setup_uefi_https_mock.assert_not_called()

    def test_prepare_instance_image_local(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        self.node.save()
        self._test_prepare_instance_local_or_whole_disk_image()

    def test_prepare_instance_whole_disk_image(self):
        self.node.driver_internal_info = {'is_whole_disk_image': True}
        self.node.save()
        self._test_prepare_instance_local_or_whole_disk_image()

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_uefi_https',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_deploy_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    def test_prepare_instance_partition_image(
            self, set_boot_device_mock,
            parse_deploy_mock, prepare_iso_mock, setup_uefi_https_mock,
            cleanup_iso_mock, update_secureboot_mock):

        self.node.instance_info = {
            'capabilities': '{"boot_option": "netboot"}'
        }
        self.node.driver_internal_info = {
            'root_uuid_or_disk_id': (
                "12312642-09d3-467f-8e09-12385826a123")
        }
        self.node.driver_internal_info.update({'is_whole_disk_image': False})
        self.node.save()
        d_info = {'a': 'x', 'b': 'y'}
        parse_deploy_mock.return_value = d_info
        prepare_iso_mock.return_value = "recreated-iso"
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.prepare_instance(task)

            cleanup_iso_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_not_called()
            parse_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            prepare_iso_mock.assert_called_once_with(
                task, d_info, root_uuid='12312642-09d3-467f-8e09-12385826a123')
            update_secureboot_mock.assert_called_once_with(task)
            setup_uefi_https_mock.assert_called_once_with(
                task, "recreated-iso", True)
            self.assertEqual(task.node.instance_info['ilo_boot_iso'],
                             "recreated-iso")

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_uefi_https',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'prepare_boot_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot.IloUefiHttpsBoot, '_parse_deploy_info',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    def test_prepare_instance_boot_ramdisk(
            self, set_boot_device_mock,
            parse_deploy_mock, prepare_iso_mock, setup_uefi_https_mock,
            cleanup_iso_mock, update_secureboot_mock):

        self.node.driver_internal_info.update({'is_whole_disk_image': False})
        self.node.save()
        d_info = {'a': 'x', 'b': 'y'}
        parse_deploy_mock.return_value = d_info
        prepare_iso_mock.return_value = "recreated-iso"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = '{"boot_option": "ramdisk"}'
            task.node.instance_info = instance_info
            task.node.save()
            task.driver.boot.prepare_instance(task)

            cleanup_iso_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_not_called()
            parse_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            prepare_iso_mock.assert_called_once_with(
                task, d_info)
            update_secureboot_mock.assert_called_once_with(task)
            setup_uefi_https_mock.assert_called_once_with(
                task, "recreated-iso", True)
            self.assertTrue('ilo_boot_iso' not in task.node.instance_info)

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       spec_set=True, autospec=True)
    @mock.patch.object(image_utils, 'cleanup_iso_image', spec_set=True,
                       autospec=True)
    def test_clean_up_instance(self, cleanup_iso_mock, disable_secure_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.boot.clean_up_instance(task)
            cleanup_iso_mock.assert_called_once_with(task)
            disable_secure_mock.assert_called_once_with(task)

    def test_validate_rescue(self):
        driver_info = self.node.driver_info
        driver_info['ilo_rescue_kernel'] = 'rescue-kernel'
        driver_info['ilo_rescue_ramdisk'] = 'rescue-ramdisk'
        driver_info['ilo_bootloader'] = 'bootloader'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.boot.validate_rescue(task)

    def test_validate_rescue_no_rescue_ramdisk(self):
        driver_info = self.node.driver_info
        driver_info['ilo_rescue_kernel'] = 'rescue-kernel'
        driver_info['ilo_rescue_ramdisk'] = 'rescue-ramdisk'
        driver_info.pop('ilo_bootloader', None)
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   "Error validating rescue for iLO UEFI "
                                   "HTTPS boot.* ['ilo_bootloader']",
                                   task.driver.boot.validate_rescue, task)
