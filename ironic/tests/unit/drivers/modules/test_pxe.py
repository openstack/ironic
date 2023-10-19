# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Test class for PXE driver."""

import os
import tempfile
from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import image_service
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe
from ironic.drivers.modules import pxe_base
from ironic.drivers.modules.storage import noop as noop_storage
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


# NOTE(TheJulia): Mark pxe interface loading as None in order
# to prent false counts for individual method tests.
@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
@mock.patch.object(pxe.PXEBoot, '__init__', lambda self: None)
class PXEBootTestCase(db_base.DbTestCase):

    driver = 'fake-hardware'
    boot_interface = 'pxe'
    driver_info = DRV_INFO_DICT
    driver_internal_info = DRV_INTERNAL_INFO_DICT

    def setUp(self):
        super(PXEBootTestCase, self).setUp()
        self.context.auth_token = 'fake'
        self.config_temp_dir('tftp_root', group='pxe')
        self.config_temp_dir('images_path', group='pxe')
        self.config_temp_dir('http_root', group='deploy')
        self.config(default_ks_template='/etc/ironic/ks.cfg.template',
                    group='anaconda')
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        instance_info['image_url'] = 'http://fakeserver/os.tar.gz'

        self.config(enabled_boot_interfaces=[self.boot_interface,
                                             'ipxe', 'fake'])
        self.config(enabled_deploy_interfaces=['fake', 'direct', 'anaconda'])
        self.node = obj_utils.create_test_node(
            self.context,
            driver=self.driver,
            boot_interface=self.boot_interface,
            # Avoid fake properties in get_properties() output
            vendor_interface='no-vendor',
            instance_info=instance_info,
            driver_info=self.driver_info,
            driver_internal_info=self.driver_internal_info)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)
        self.config(my_ipv6='2001:db8::1')

    def test_get_properties(self):
        expected = pxe_base.COMMON_PROPERTIES
        expected.update(agent_base.VENDOR_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_good(self, mock_glance):
        mock_glance.return_value = {'properties': {'kernel_id': 'fake-kernel',
                                                   'ramdisk_id': 'fake-initr'}}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot.validate(task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_good_whole_disk_image(self, mock_glance):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot.validate(task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    def test_validate_skip_check_write_image_false(self, mock_write,
                                                   mock_glance):
        mock_write.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot.validate(task)
        self.assertFalse(mock_glance.called)

    def test_validate_fail_missing_deploy_kernel(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            del task.node.driver_info['deploy_kernel']
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_fail_missing_deploy_ramdisk(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            del task.node.driver_info['deploy_ramdisk']
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_no_image_source_for_local_boot(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            del task.node['instance_info']['image_source']
            task.driver.boot.validate(task)

    def test_validate_fail_missing_image_source(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node['instance_info']['capabilities'] = {
                'boot_option': 'netboot'}
            del task.node['instance_info']['image_source']
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_fail_no_port(self):
        new_node = obj_utils.create_test_node(
            self.context,
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            driver=self.driver, boot_interface=self.boot_interface,
            instance_info=INST_INFO_DICT, driver_info=DRV_INFO_DICT)
        with task_manager.acquire(self.context, new_node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_fail_trusted_boot_with_secure_boot(self):
        instance_info = {"boot_option": "netboot",
                         "secure_boot": "true",
                         "trusted_boot": "true"}
        properties = {'capabilities': 'trusted_boot:true'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info['capabilities'] = instance_info
            task.node.properties = properties
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_fail_invalid_trusted_boot_value(self):
        properties = {'capabilities': 'trusted_boot:value'}
        instance_info = {"trusted_boot": "value"}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties = properties
            task.node.instance_info['capabilities'] = instance_info
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_fail_no_image_kernel_ramdisk_props(self, mock_glance):
        instance_info = {"boot_option": "netboot"}
        mock_glance.return_value = {'properties': {}}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info['capabilities'] = instance_info
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate,
                              task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_fail_glance_image_doesnt_exists(self, mock_glance):
        mock_glance.side_effect = exception.ImageNotFound('not found')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info['capabilities'] = {
                'boot_option': 'netboot'}
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_fail_glance_conn_problem(self, mock_glance):
        exceptions = (exception.GlanceConnectionFailed('connection fail'),
                      exception.ImageNotAuthorized('not authorized'),
                      exception.Invalid('invalid'))
        mock_glance.side_effect = exceptions
        for exc in exceptions:
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                task.node.instance_info['capabilities'] = {
                    'boot_option': 'netboot'}
                self.assertRaises(exception.InvalidParameterValue,
                                  task.driver.boot.validate, task)

    def test_validate_inspection(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.boot.validate_inspection(task)

    def test_validate_inspection_no_inspection_ramdisk(self):
        driver_info = self.node.driver_info
        del driver_info['deploy_ramdisk']
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.boot.validate_inspection, task)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_validate_kickstart_missing_stage2_id(self, mock_glance):
        mock_glance.return_value = {'properties': {'kernel_id': 'fake-kernel',
                                                   'ramdisk_id': 'fake-initr'}}
        self.node.deploy_interface = 'anaconda'
        self.node.save()
        self.config(http_url='http://fake_url', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'stage2_id',
                                   task.driver.boot.validate, task)

    def test_validate_kickstart_fail_http_url_not_set(self):
        node = self.node
        node.deploy_interface = 'anaconda'
        node.save()
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(manager_utils, 'node_get_boot_mode', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    @mock.patch.object(pxe_utils, 'get_image_info', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'build_pxe_config_options', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    def _test_prepare_ramdisk(self, mock_pxe_config,
                              mock_build_pxe, mock_cache_r_k,
                              mock_deploy_img_info,
                              mock_instance_img_info,
                              dhcp_factory_mock,
                              set_boot_device_mock,
                              get_boot_mode_mock,
                              uefi=False,
                              cleaning=False,
                              ipxe_use_swift=False,
                              whole_disk_image=False,
                              mode='deploy',
                              node_boot_mode=None,
                              persistent=False):
        mock_build_pxe.return_value = {}
        kernel_label = '%s_kernel' % mode
        ramdisk_label = '%s_ramdisk' % mode
        mock_deploy_img_info.return_value = {kernel_label: 'a',
                                             ramdisk_label: 'r'}
        if whole_disk_image:
            mock_instance_img_info.return_value = {}
        else:
            mock_instance_img_info.return_value = {'kernel': 'b'}
        mock_pxe_config.return_value = None
        mock_cache_r_k.return_value = None
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        get_boot_mode_mock.return_value = node_boot_mode
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = whole_disk_image
        self.node.driver_internal_info = driver_internal_info
        if mode == 'rescue':
            mock_deploy_img_info.return_value = {
                'rescue_kernel': 'a',
                'rescue_ramdisk': 'r'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            task.driver.boot.prepare_ramdisk(task, {'foo': 'bar'})
            mock_deploy_img_info.assert_called_once_with(task.node,
                                                         mode=mode,
                                                         ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            get_boot_mode_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=persistent)
            if ipxe_use_swift:
                if whole_disk_image:
                    self.assertFalse(mock_cache_r_k.called)
                else:
                    mock_cache_r_k.assert_called_once_with(
                        task,
                        {'kernel': 'b'},
                        ipxe_enabled=False)
                mock_instance_img_info.assert_called_once_with(
                    task, ipxe_enabled=False)
            elif not cleaning and mode == 'deploy':
                mock_cache_r_k.assert_called_once_with(
                    task,
                    {'deploy_kernel': 'a', 'deploy_ramdisk': 'r',
                     'kernel': 'b'},
                    ipxe_enabled=False)
                mock_instance_img_info.assert_called_once_with(
                    task, ipxe_enabled=False)
            elif mode == 'deploy':
                mock_cache_r_k.assert_called_once_with(
                    task,
                    {'deploy_kernel': 'a', 'deploy_ramdisk': 'r'},
                    ipxe_enabled=False)
            elif mode == 'rescue':
                mock_cache_r_k.assert_called_once_with(
                    task,
                    {'rescue_kernel': 'a', 'rescue_ramdisk': 'r'},
                    ipxe_enabled=False)
            if uefi:
                mock_pxe_config.assert_called_once_with(
                    task, {}, CONF.pxe.uefi_pxe_config_template,
                    ipxe_enabled=False)
            else:
                mock_pxe_config.assert_called_once_with(
                    task, {}, CONF.pxe.pxe_config_template,
                    ipxe_enabled=False)

    def test_prepare_ramdisk(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk()

    def test_prepare_ramdisk_rescue(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_prepare_ramdisk(mode='rescue')

    def test_prepare_ramdisk_uefi(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        self._test_prepare_ramdisk(uefi=True)

    def test_prepare_ramdisk_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(cleaning=True)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_set_boot_mode_on_bm(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        self._test_prepare_ramdisk(uefi=True)
        set_boot_mode_mock.assert_called_once_with(mock.ANY, boot_modes.UEFI)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_set_boot_mode_on_ironic(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk(node_boot_mode=boot_modes.LEGACY_BIOS)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            self.assertIn('deploy_boot_mode', driver_internal_info)
            self.assertEqual(boot_modes.LEGACY_BIOS,
                             driver_internal_info['deploy_boot_mode'])
            self.assertEqual(set_boot_mode_mock.call_count, 0)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_set_default_boot_mode_on_ironic_bios(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()

        self.config(default_boot_mode=boot_modes.LEGACY_BIOS, group='deploy')

        self._test_prepare_ramdisk()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            self.assertIn('deploy_boot_mode', driver_internal_info)
            self.assertEqual(boot_modes.LEGACY_BIOS,
                             driver_internal_info['deploy_boot_mode'])
            self.assertEqual(set_boot_mode_mock.call_count, 1)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_set_default_boot_mode_on_ironic_uefi(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()

        self.config(default_boot_mode=boot_modes.UEFI, group='deploy')

        self._test_prepare_ramdisk(uefi=True)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            self.assertIn('deploy_boot_mode', driver_internal_info)
            self.assertEqual(boot_modes.UEFI,
                             driver_internal_info['deploy_boot_mode'])
            self.assertEqual(set_boot_mode_mock.call_count, 1)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_conflicting_boot_modes(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        self._test_prepare_ramdisk(uefi=True,
                                   node_boot_mode=boot_modes.LEGACY_BIOS)
        set_boot_mode_mock.assert_called_once_with(mock.ANY, boot_modes.UEFI)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_conflicting_boot_modes_set_unsupported(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        set_boot_mode_mock.side_effect = exception.UnsupportedDriverExtension(
            extension='management', driver='test-driver'
        )
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self._test_prepare_ramdisk,
                          uefi=True, node_boot_mode=boot_modes.LEGACY_BIOS)

    @mock.patch.object(manager_utils, 'node_set_boot_mode', autospec=True)
    def test_prepare_ramdisk_set_boot_mode_not_called(
            self, set_boot_mode_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        self._test_prepare_ramdisk(uefi=True, node_boot_mode=boot_modes.UEFI)
        self.assertEqual(set_boot_mode_mock.call_count, 0)

    @mock.patch.object(pxe_utils, 'clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe_utils, 'get_image_info', autospec=True)
    def _test_clean_up_ramdisk(self, get_image_info_mock,
                               clean_up_pxe_env_mock, mode='deploy'):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            kernel_label = '%s_kernel' % mode
            ramdisk_label = '%s_ramdisk' % mode
            image_info = {kernel_label: ['', '/path/to/' + kernel_label],
                          ramdisk_label: ['', '/path/to/' + ramdisk_label]}
            get_image_info_mock.return_value = image_info
            task.driver.boot.clean_up_ramdisk(task)
            clean_up_pxe_env_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            get_image_info_mock.assert_called_once_with(
                task.node, mode=mode, ipxe_enabled=False)

    def test_clean_up_ramdisk(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_clean_up_ramdisk()

    def test_clean_up_ramdisk_rescue(self):
        self.node.provision_state = states.RESCUING
        self.node.save()
        self._test_clean_up_ramdisk(mode='rescue')

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_netboot(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, switch_pxe_config_mock,
            set_boot_device_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        get_image_info_mock.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=4)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['root_uuid_or_disk_id'] = (
                "30212642-09d3-467f-8e09-21685826ab50")
            task.node.driver_internal_info['is_whole_disk_image'] = False
            task.node.instance_info = {
                'capabilities': {'boot_option': 'netboot'}}
            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, "30212642-09d3-467f-8e09-21685826ab50",
                'bios', False, False, False, False, ipxe_enabled=False,
                anaconda_boot=False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch('os.path.isfile', return_value=False, autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_netboot_active(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, switch_pxe_config_mock,
            set_boot_device_mock, create_pxe_config_mock, isfile_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        instance_info = {"boot_option": "netboot"}
        get_image_info_mock.return_value = image_info
        self.node.provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['root_uuid_or_disk_id'] = (
                "30212642-09d3-467f-8e09-21685826ab50")
            task.node.driver_internal_info['is_whole_disk_image'] = False
            task.node.instance_info['capabilities'] = instance_info
            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            create_pxe_config_mock.assert_called_once_with(
                task, mock.ANY, CONF.pxe.pxe_config_template,
                ipxe_enabled=False)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, "30212642-09d3-467f-8e09-21685826ab50",
                'bios', False, False, False, False, ipxe_enabled=False,
                anaconda_boot=False)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_netboot_missing_root_uuid(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, switch_pxe_config_mock,
            set_boot_device_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk')}
        instance_info = {"boot_option": "netboot"}
        get_image_info_mock.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.instance_info['capabilities'] = instance_info
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            self.assertFalse(switch_pxe_config_mock.called)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(pxe_base.LOG, 'warning', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_whole_disk_image_missing_root_uuid(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, set_boot_device_mock,
            clean_up_pxe_mock, log_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        get_image_info_mock.return_value = {}
        instance_info = {"boot_option": "netboot"}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.instance_info['capabilities'] = instance_info
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot.prepare_instance(task)
            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, {}, ipxe_enabled=False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            self.assertTrue(log_mock.called)
            clean_up_pxe_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(boot_mode_utils, 'configure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    def test_prepare_instance_localboot(self, clean_up_pxe_config_mock,
                                        set_boot_device_mock,
                                        secure_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = {'boot_option': 'local'}
            task.node.instance_info = instance_info
            task.node.save()
            task.driver.boot.prepare_instance(task)
            clean_up_pxe_config_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK,
                                                         persistent=True)
            secure_boot_mock.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    def test_prepare_instance_localboot_active(self, clean_up_pxe_config_mock,
                                               set_boot_device_mock):
        self.node.provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = {'boot_option': 'local'}
            task.node.instance_info = instance_info
            task.node.save()
            task.driver.boot.prepare_instance(task)
            clean_up_pxe_config_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def _test_prepare_instance_ramdisk(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, create_pxe_config_mock,
            switch_pxe_config_mock,
            set_boot_device_mock, config_file_exits=False):
        image_info = {'kernel': ['', '/path/to/kernel'],
                      'ramdisk': ['', '/path/to/ramdisk']}
        get_image_info_mock.return_value = image_info
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        self.node.provision_state = states.DEPLOYING
        get_image_info_mock.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = {'boot_option': 'ramdisk'}
            task.node.instance_info = instance_info
            task.node.save()
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, False)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            if config_file_exits:
                self.assertFalse(create_pxe_config_mock.called)
            else:
                create_pxe_config_mock.assert_called_once_with(
                    task, mock.ANY, CONF.pxe.pxe_config_template,
                    ipxe_enabled=False)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, None,
                'bios', False, ipxe_enabled=False, iscsi_boot=False,
                ramdisk_boot=True, anaconda_boot=False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch.object(os.path, 'isfile', lambda path: True)
    def test_prepare_instance_ramdisk_pxe_conf_missing(self):
        self._test_prepare_instance_ramdisk(config_file_exits=True)

    @mock.patch.object(os.path, 'isfile', lambda path: False)
    def test_prepare_instance_ramdisk_pxe_conf_exists(self):
        self._test_prepare_instance_ramdisk(config_file_exits=False)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='kickstart', autospec=True)
    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url',
                return_value='http://fakeserver/api', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.execute', autospec=True)
    def test_prepare_instance_kickstart(
            self, exec_mock, write_file_mock, render_mock, api_url_mock,
            boot_opt_mock, get_image_info_mock, cache_mock, dhcp_factory_mock,
            create_pxe_config_mock, switch_pxe_config_mock,
            set_boot_device_mock):
        image_info = {'kernel': ['ins_kernel_id', '/path/to/kernel'],
                      'ramdisk': ['ins_ramdisk_id', '/path/to/ramdisk'],
                      'stage2': ['ins_stage2_id', '/path/to/stage2'],
                      'ks_cfg': ['', '/path/to/ks.cfg'],
                      'ks_template': ['template_id', '/path/to/ks_template']}
        get_image_info_mock.return_value = image_info
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        self.node.provision_state = states.DEPLOYING
        self.config(http_url='http://fake_url', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False)
            dhcp_opts += pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=False, ip_version=6)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            cache_mock.assert_called_once_with(
                task, image_info, False)
            if os.path.isfile('/usr/bin/ksvalidator'):
                exec_mock.assert_called_once_with(
                    'ksvalidator', mock.ANY, check_on_exit=[0], attempts=1
                )
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            render_mock.assert_called()
            write_file_mock.assert_called_with(
                '/path/to/ks.cfg', render_mock.return_value
            )
            create_pxe_config_mock.assert_called_once_with(
                task, mock.ANY, CONF.pxe.pxe_config_template,
                ipxe_enabled=False)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, None,
                'bios', False, ipxe_enabled=False, iscsi_boot=False,
                ramdisk_boot=False, anaconda_boot=True)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch.object(boot_mode_utils, 'deconfigure_secure_boot_if_needed',
                       autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_clean_up_instance(self, get_image_info_mock,
                               clean_up_pxe_env_mock,
                               secure_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            image_info = {'kernel': ['', '/path/to/kernel'],
                          'ramdisk': ['', '/path/to/ramdisk']}
            get_image_info_mock.return_value = image_info
            task.driver.boot.clean_up_instance(task)
            clean_up_pxe_env_mock.assert_called_once_with(task, image_info,
                                                          ipxe_enabled=False)
            get_image_info_mock.assert_called_once_with(task,
                                                        ipxe_enabled=False)
            secure_boot_mock.assert_called_once_with(task)


class PXEAnacondaDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEAnacondaDeployTestCase, self).setUp()
        self.temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=self.temp_dir, group='pxe')
        self.config_temp_dir('http_root', group='deploy')
        self.config(http_url='http://fakeurl', group='deploy')
        self.temp_dir = tempfile.mkdtemp()
        self.config(images_path=self.temp_dir, group='pxe')
        self.config(enabled_deploy_interfaces=['anaconda'])
        self.config(enabled_boot_interfaces=['pxe'])
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'network':
                impl = 'noop'
            if iface == 'deploy':
                impl = 'anaconda'
            if iface == 'boot':
                impl = 'pxe'
            config_kwarg = {'enabled_%s_interfaces' % iface: [impl],
                            'default_%s_interface' % iface: impl}
            self.config(**config_kwarg)
        self.config(enabled_hardware_types=['fake-hardware'])
        instance_info = INST_INFO_DICT
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake-hardware',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)
        self.deploy = pxe.PXEAnacondaDeploy()

    @mock.patch.object(pxe_utils, 'prepare_instance_kickstart_config',
                       autospec=True)
    @mock.patch.object(pxe_utils, 'validate_kickstart_file', autospec=True)
    @mock.patch.object(pxe_utils, 'validate_kickstart_template', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_deploy(self, mock_image_info, mock_cache,
                    mock_dhcp_factory, mock_switch_config, mock_ks_tmpl,
                    mock_ks_file, mock_prepare_ks_config):
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk'),
                      'stage2': ('', '/path/to/stage2'),
                      'ks_template': ('', '/path/to/ks_template'),
                      'ks_cfg': ('', '/path/to/ks_cfg')}
        mock_image_info.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.DEPLOYWAIT, task.driver.deploy.deploy(task)
            )
            mock_image_info.assert_called_once_with(task, ipxe_enabled=False)
            mock_cache.assert_called_once_with(
                task, image_info, ipxe_enabled=False)
            mock_ks_tmpl.assert_called_once_with(image_info['ks_template'][1])
            mock_ks_file.assert_called_once_with(mock_ks_tmpl.return_value)
            mock_prepare_ks_config.assert_called_once_with(task, image_info,
                                                           anaconda_boot=True)

    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare(self, mock_prepare_instance, mock_build_instance):

        node = self.node
        node.provision_state = states.DEPLOYING
        node.instance_info = {}
        node.save()
        updated_instance_info = {'image_url': 'foo'}
        mock_build_instance.return_value = updated_instance_info
        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.deploy.prepare(task)
            self.assertFalse(mock_prepare_instance.called)
            mock_build_instance.assert_called_once_with(task)
            node.refresh()
            self.assertEqual(updated_instance_info, node.instance_info)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_active(self, mock_prepare_instance):
        node = self.node
        node.provision_state = states.ACTIVE
        node.save()
        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.deploy.prepare(task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(pxe_utils, 'clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    def test_reboot_to_instance(self, mock_set_boot_dev, mock_image_info,
                                mock_cleanup_pxe_env):
        image_info = {'kernel': ('', '/path/to/kernel'),
                      'ramdisk': ('', '/path/to/ramdisk'),
                      'stage2': ('', '/path/to/stage2'),
                      'ks_template': ('', '/path/to/ks_template'),
                      'ks_cfg': ('', '/path/to/ks_cfg')}
        mock_image_info.return_value = image_info
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.reboot_to_instance(task)
            mock_set_boot_dev.assert_called_once_with(task, boot_devices.DISK)
            mock_cleanup_pxe_env.assert_called_once_with(task, image_info,
                                                         ipxe_enabled=False)

    @mock.patch.object(objects.node.Node, 'touch_provisioning', autospec=True)
    def test_heartbeat_deploy_start(self, mock_touch):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, 'url', '3.2.0', None, 'start', 'msg')
            self.assertFalse(task.shared)
            self.assertEqual(
                'url', task.node.driver_internal_info['agent_url'])
            self.assertEqual(
                '3.2.0',
                task.node.driver_internal_info['agent_version'])
            self.assertEqual(
                'start',
                task.node.driver_internal_info['agent_status'])
            mock_touch.assert_called()

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    def test_heartbeat_deploy_error(self, mock_set_failed_state):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, 'url', '3.2.0', None, 'error',
                                  'errmsg')
            self.assertFalse(task.shared)
            self.assertEqual(
                'url', task.node.driver_internal_info['agent_url'])
            self.assertEqual(
                '3.2.0',
                task.node.driver_internal_info['agent_version'])
            self.assertEqual(
                'error',
                task.node.driver_internal_info['agent_status'])
            mock_set_failed_state.assert_called_once_with(task, 'errmsg',
                                                          collect_logs=False)

    @mock.patch.object(pxe.PXEAnacondaDeploy, 'reboot_to_instance',
                       autospec=True)
    def test_heartbeat_deploy_end(self, mock_reboot_to_instance):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, None, None, None, 'end', 'sucess')
            self.assertFalse(task.shared)
            self.assertIsNone(
                task.node.driver_internal_info['agent_url'])
            self.assertIsNone(
                task.node.driver_internal_info['agent_version'])
            self.assertEqual(
                'end',
                task.node.driver_internal_info['agent_status'])
            self.assertTrue(mock_reboot_to_instance.called)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning(self, prepare_inband_cleaning_mock):
        prepare_inband_cleaning_mock.return_value = states.CLEANWAIT
        self.node.provision_state = states.CLEANING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.CLEANWAIT, self.deploy.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)


class PXEValidateRescueTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEValidateRescueTestCase, self).setUp()
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'network':
                impl = 'flat'
            if iface == 'rescue':
                impl = 'agent'
            if iface == 'boot':
                impl = 'pxe'
            config_kwarg = {'enabled_%s_interfaces' % iface: [impl],
                            'default_%s_interface' % iface: impl}
            self.config(**config_kwarg)
        self.config(enabled_hardware_types=['fake-hardware'])
        driver_info = DRV_INFO_DICT
        driver_info.update({'rescue_ramdisk': 'my_ramdisk',
                            'rescue_kernel': 'my_kernel'})
        instance_info = INST_INFO_DICT
        instance_info.update({'rescue_password': 'password'})
        n = {
            'driver': 'fake-hardware',
            'instance_info': instance_info,
            'driver_info': driver_info,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.node = obj_utils.create_test_node(self.context, **n)

    def test_validate_rescue(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.boot.validate_rescue(task)

    def test_validate_rescue_no_rescue_ramdisk(self):
        driver_info = self.node.driver_info
        del driver_info['rescue_ramdisk']
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'Missing.*rescue_ramdisk',
                                   task.driver.boot.validate_rescue, task)

    def test_validate_rescue_fails_no_rescue_kernel(self):
        driver_info = self.node.driver_info
        del driver_info['rescue_kernel']
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   'Missing.*rescue_kernel',
                                   task.driver.boot.validate_rescue, task)


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
@mock.patch.object(pxe.PXEBoot, '__init__', lambda self: None)
@mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
@mock.patch.object(manager_utils, 'node_power_action', autospec=True)
class PXEBootRetryTestCase(db_base.DbTestCase):

    boot_interface = 'pxe'

    def setUp(self):
        super(PXEBootRetryTestCase, self).setUp()
        self.config(enabled_boot_interfaces=['pxe', 'ipxe', 'fake'])
        self.config(boot_retry_timeout=300, group='pxe')
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake-hardware',
            boot_interface=self.boot_interface,
            provision_state=states.DEPLOYWAIT)

    @mock.patch.object(pxe.PXEBoot, '_check_boot_status', autospec=True)
    def test_check_boot_timeouts(self, mock_check_status, mock_power,
                                 mock_boot_dev):
        def _side_effect(iface, task):
            self.assertEqual(self.node.uuid, task.node.uuid)

        mock_check_status.side_effect = _side_effect
        manager = mock.Mock(spec=['iter_nodes'])
        manager.iter_nodes.return_value = [
            (uuidutils.generate_uuid(), 'fake-hardware', ''),
            (self.node.uuid, self.node.driver, self.node.conductor_group)
        ]
        iface = pxe.PXEBoot()
        iface._check_boot_timeouts(manager, self.context)
        mock_check_status.assert_called_once_with(iface, mock.ANY)

    def test_check_boot_status_another_boot_interface(self, mock_power,
                                                      mock_boot_dev):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot = fake.FakeBoot()
            pxe.PXEBoot()._check_boot_status(task)
            self.assertTrue(task.shared)
        self.assertFalse(mock_power.called)
        self.assertFalse(mock_boot_dev.called)

    def test_check_boot_status_recent_power_change(self, mock_power,
                                                   mock_boot_dev):
        for field in ('agent_last_heartbeat', 'last_power_state_change'):
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                task.node.driver_internal_info = {
                    field: str(timeutils.utcnow().isoformat())
                }
                task.driver.boot._check_boot_status(task)
                self.assertTrue(task.shared)
            self.assertFalse(mock_power.called)
            self.assertFalse(mock_boot_dev.called)

    def test_check_boot_status_maintenance(self, mock_power, mock_boot_dev):
        self.node.maintenance = True
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot._check_boot_status(task)
            self.assertFalse(task.shared)
        self.assertFalse(mock_power.called)
        self.assertFalse(mock_boot_dev.called)

    def test_check_boot_status_wrong_state(self, mock_power, mock_boot_dev):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot._check_boot_status(task)
            self.assertFalse(task.shared)
        self.assertFalse(mock_power.called)
        self.assertFalse(mock_boot_dev.called)

    def test_check_boot_status_retry(self, mock_power, mock_boot_dev):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot._check_boot_status(task)
            self.assertFalse(task.shared)
            mock_power.assert_has_calls([
                mock.call(task, states.POWER_OFF),
                mock.call(task, states.POWER_ON)
            ])
            mock_boot_dev.assert_called_once_with(task, 'pxe',
                                                  persistent=False)

    def test_check_boot_status_not_retry_with_token(self, mock_power,
                                                    mock_boot_dev):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info = {
                'agent_secret_token': 'xyz'
            }
            task.driver.boot._check_boot_status(task)
            self.assertTrue(task.shared)
            mock_power.assert_not_called()
            mock_boot_dev.assert_not_called()


class iPXEBootRetryTestCase(PXEBootRetryTestCase):

    boot_interface = 'ipxe'
