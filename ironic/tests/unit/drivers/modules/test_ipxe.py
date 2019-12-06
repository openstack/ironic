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

"""Test class for iPXE driver."""

import os

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils as json
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import image_service
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import ipxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


# NOTE(TheJulia): This code is essentially a bulk copy of the
# test_pxe file with some contextual modifications to enforce
# use of ipxe while also explicitly having it globally disabled
# in the conductor.
@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class iPXEBootTestCase(db_base.DbTestCase):

    driver = 'fake-hardware'
    boot_interface = 'ipxe'
    driver_info = DRV_INFO_DICT
    driver_internal_info = DRV_INTERNAL_INFO_DICT

    def setUp(self):
        super(iPXEBootTestCase, self).setUp()
        self.context.auth_token = 'fake'
        self.config_temp_dir('tftp_root', group='pxe')
        self.config_temp_dir('images_path', group='pxe')
        self.config_temp_dir('http_root', group='deploy')
        self.config(group='deploy', http_url='http://myserver')
        instance_info = INST_INFO_DICT

        self.config(enabled_boot_interfaces=[self.boot_interface,
                                             'ipxe', 'fake'])
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
        self.config(group='conductor', api_url='http://127.0.0.1:1234/')

    def test_get_properties(self):
        expected = ipxe.COMMON_PROPERTIES
        expected.update(agent_base_vendor.VENDOR_PROPERTIES)
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

    def test_validate_fail_missing_image_source(self):
        info = dict(INST_INFO_DICT)
        del info['image_source']
        self.node.instance_info = json.dumps(info)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node['instance_info'] = json.dumps(info)
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

    @mock.patch.object(image_service.GlanceImageService, 'show',
                       autospec=True)
    def test_validate_fail_no_image_kernel_ramdisk_props(self, mock_glance):
        mock_glance.return_value = {'properties': {}}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate,
                              task)

    @mock.patch.object(image_service.GlanceImageService, 'show',
                       autospec=True)
    def test_validate_fail_glance_image_doesnt_exists(self, mock_glance):
        mock_glance.side_effect = exception.ImageNotFound('not found')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(image_service.GlanceImageService, 'show',
                       autospec=True)
    def test_validate_fail_glance_conn_problem(self, mock_glance):
        exceptions = (exception.GlanceConnectionFailed('connection fail'),
                      exception.ImageNotAuthorized('not authorized'),
                      exception.Invalid('invalid'))
        mock_glance.side_effect = exceptions
        for exc in exceptions:
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
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

    # TODO(TheJulia): Many of the interfaces mocked below are private PXE
    # interface methods. As time progresses, these will need to be migrated
    # and refactored as we begin to separate PXE and iPXE interfaces.
    @mock.patch.object(manager_utils, 'node_get_boot_mode', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory')
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
                task, ipxe_enabled=True)
            task.driver.boot.prepare_ramdisk(task, {'foo': 'bar'})
            mock_deploy_img_info.assert_called_once_with(task.node, mode=mode,
                                                         ipxe_enabled=True)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            if self.node.provision_state == states.DEPLOYING:
                get_boot_mode_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=persistent)
            if ipxe_use_swift:
                if whole_disk_image:
                    self.assertFalse(mock_cache_r_k.called)
                else:
                    mock_cache_r_k.assert_called_once_with(
                        task, {'kernel': 'b'},
                        ipxe_enabled=True)
                mock_instance_img_info.assert_called_once_with(
                    task, ipxe_enabled=True)
            elif not cleaning and mode == 'deploy':
                mock_cache_r_k.assert_called_once_with(
                    task,
                    {'deploy_kernel': 'a', 'deploy_ramdisk': 'r',
                     'kernel': 'b'},
                    ipxe_enabled=True)
                mock_instance_img_info.assert_called_once_with(
                    task, ipxe_enabled=True)
            elif mode == 'deploy':
                    mock_cache_r_k.assert_called_once_with(
                        task, {'deploy_kernel': 'a', 'deploy_ramdisk': 'r'},
                        ipxe_enabled=True)
            elif mode == 'rescue':
                    mock_cache_r_k.assert_called_once_with(
                        task, {'rescue_kernel': 'a', 'rescue_ramdisk': 'r'},
                        ipxe_enabled=True)
            if uefi:
                mock_pxe_config.assert_called_once_with(
                    task, {}, CONF.pxe.uefi_pxe_config_template,
                    ipxe_enabled=True)
            else:
                mock_pxe_config.assert_called_once_with(
                    task, {}, CONF.pxe.pxe_config_template,
                    ipxe_enabled=True)

    def test_prepare_ramdisk(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk()

    def test_prepare_ramdisk_force_persistent_boot_device_true(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = 'True'
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=True)

    def test_prepare_ramdisk_force_persistent_boot_device_bool_true(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = True
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=True)

    def test_prepare_ramdisk_force_persistent_boot_device_sloppy_true(self):
        for value in ['true', 't', '1', 'on', 'y', 'YES']:
            self.node.provision_state = states.DEPLOYING
            driver_info = self.node.driver_info
            driver_info['force_persistent_boot_device'] = value
            self.node.driver_info = driver_info
            self.node.save()
            self._test_prepare_ramdisk(persistent=True)

    def test_prepare_ramdisk_force_persistent_boot_device_false(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = 'False'
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk()

    def test_prepare_ramdisk_force_persistent_boot_device_bool_false(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = False
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=False)

    def test_prepare_ramdisk_force_persistent_boot_device_sloppy_false(self):
        for value in ['false', 'f', '0', 'off', 'n', 'NO', 'yxz']:
            self.node.provision_state = states.DEPLOYING
            driver_info = self.node.driver_info
            driver_info['force_persistent_boot_device'] = value
            self.node.driver_info = driver_info
            self.node.save()
            self._test_prepare_ramdisk()

    def test_prepare_ramdisk_force_persistent_boot_device_default(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = 'Default'
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=False)

    def test_prepare_ramdisk_force_persistent_boot_device_always(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = 'Always'
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=True)

    def test_prepare_ramdisk_force_persistent_boot_device_never(self):
        self.node.provision_state = states.DEPLOYING
        driver_info = self.node.driver_info
        driver_info['force_persistent_boot_device'] = 'Never'
        self.node.driver_info = driver_info
        self.node.save()
        self._test_prepare_ramdisk(persistent=False)

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

    @mock.patch.object(os.path, 'isfile', lambda path: True)
    @mock.patch.object(common_utils, 'file_has_content', lambda *args: False)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_prepare_ramdisk_ipxe_with_copy_file_different(
            self, render_mock, write_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=False)
        render_mock.return_value = 'foo'
        self._test_prepare_ramdisk()
        write_mock.assert_called_once_with(
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

    @mock.patch.object(os.path, 'isfile', lambda path: False)
    @mock.patch('ironic.common.utils.file_has_content', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_prepare_ramdisk_ipxe_with_copy_no_file(
            self, render_mock, write_mock, file_has_content_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=False)
        render_mock.return_value = 'foo'
        self._test_prepare_ramdisk()
        self.assertFalse(file_has_content_mock.called)
        write_mock.assert_called_once_with(
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

    @mock.patch.object(os.path, 'isfile', lambda path: True)
    @mock.patch.object(common_utils, 'file_has_content', lambda *args: True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_prepare_ramdisk_ipxe_without_copy(
            self, render_mock, write_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=False)
        self._test_prepare_ramdisk()
        self.assertFalse(write_mock.called)

    @mock.patch.object(common_utils, 'render_template', lambda *args: 'foo')
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    def test_prepare_ramdisk_ipxe_swift(self, write_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=False)
        self.config(group='pxe', ipxe_use_swift=True)
        self._test_prepare_ramdisk(ipxe_use_swift=True)
        write_mock.assert_called_once_with(
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')

    @mock.patch.object(common_utils, 'render_template', lambda *args: 'foo')
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    def test_prepare_ramdisk_ipxe_swift_whole_disk_image(
            self, write_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=False)
        self.config(group='pxe', ipxe_use_swift=True)
        self._test_prepare_ramdisk(ipxe_use_swift=True, whole_disk_image=True)
        write_mock.assert_called_once_with(
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')

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
                task, image_info, ipxe_enabled=True)
            get_image_info_mock.assert_called_once_with(
                task.node, mode=mode, ipxe_enabled=True)

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
                task, ipxe_enabled=True)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid, ipxe_enabled=True)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['root_uuid_or_disk_id'] = (
                "30212642-09d3-467f-8e09-21685826ab50")
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=True)
            cache_mock.assert_called_once_with(task, image_info,
                                               ipxe_enabled=True)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, "30212642-09d3-467f-8e09-21685826ab50",
                'bios', False, False, False, False, ipxe_enabled=True)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch('os.path.isfile', return_value=False)
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
        get_image_info_mock.return_value = image_info
        self.node.provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=True)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid, ipxe_enabled=True)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['root_uuid_or_disk_id'] = (
                "30212642-09d3-467f-8e09-21685826ab50")
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=True)
            cache_mock.assert_called_once_with(task, image_info,
                                               ipxe_enabled=True)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            create_pxe_config_mock.assert_called_once_with(
                task, mock.ANY, CONF.pxe.pxe_config_template,
                ipxe_enabled=True)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, "30212642-09d3-467f-8e09-21685826ab50",
                'bios', False, False, False, False, ipxe_enabled=True)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory')
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
        get_image_info_mock.return_value = image_info
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=True)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=True)
            cache_mock.assert_called_once_with(task, image_info,
                                               ipxe_enabled=True)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            self.assertFalse(switch_pxe_config_mock.called)
            self.assertFalse(set_boot_device_mock.called)

    # NOTE(TheJulia): The log mock below is attached to the iPXE interface
    # which directly logs the warning that is being checked for.
    @mock.patch.object(ipxe.LOG, 'warning', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory')
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_whole_disk_image_missing_root_uuid(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, set_boot_device_mock,
            clean_up_pxe_mock, log_mock):
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        get_image_info_mock.return_value = {}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(
                task, ipxe_enabled=True)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot.prepare_instance(task)
            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=True)
            cache_mock.assert_called_once_with(task, {}, ipxe_enabled=True)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            self.assertTrue(log_mock.called)
            clean_up_pxe_mock.assert_called_once_with(task, ipxe_enabled=True)
            set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch('os.path.isfile', lambda filename: False)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(deploy_utils, 'is_iscsi_boot', lambda task: True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       lambda task: False)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe_utils, 'cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_prepare_instance_netboot_iscsi(
            self, get_image_info_mock, cache_mock,
            dhcp_factory_mock, switch_pxe_config_mock,
            set_boot_device_mock, create_pxe_config_mock):
        http_url = 'http://192.1.2.3:1234'
        self.config(ipxe_enabled=False, group='pxe')
        self.config(http_url=http_url, group='deploy')
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        vol_id = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'target_lun': 0,
                        'target_portal': 'fake_host:3260',
                        'target_iqn': 'fake_iqn',
                        'auth_username': 'fake_username',
                        'auth_password': 'fake_password'})
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_internal_info = {
                'boot_from_volume': vol_id}
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task,
                                                            ipxe_enabled=True)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid, ipxe_enabled=True)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.driver.boot.prepare_instance(task)
            self.assertFalse(get_image_info_mock.called)
            self.assertFalse(cache_mock.called)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            create_pxe_config_mock.assert_called_once_with(
                task, mock.ANY, CONF.pxe.pxe_config_template,
                ipxe_enabled=True)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, None, boot_modes.LEGACY_BIOS, False,
                ipxe_enabled=True, iscsi_boot=True, ramdisk_boot=False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE,
                                                         persistent=True)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    def test_prepare_instance_localboot(self, clean_up_pxe_config_mock,
                                        set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            instance_info = task.node.instance_info
            instance_info['capabilities'] = {'boot_option': 'local'}
            task.node.instance_info = instance_info
            task.node.save()
            task.driver.boot.prepare_instance(task)
            clean_up_pxe_config_mock.assert_called_once_with(
                task, ipxe_enabled=True)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK,
                                                         persistent=True)

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
                task, ipxe_enabled=True)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(pxe_utils, 'clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    def test_clean_up_instance(self, get_image_info_mock,
                               clean_up_pxe_env_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            image_info = {'kernel': ['', '/path/to/kernel'],
                          'ramdisk': ['', '/path/to/ramdisk']}
            get_image_info_mock.return_value = image_info
            task.driver.boot.clean_up_instance(task)
            clean_up_pxe_env_mock.assert_called_once_with(
                task, image_info, ipxe_enabled=True)
            get_image_info_mock.assert_called_once_with(
                task, ipxe_enabled=True)


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class iPXEValidateRescueTestCase(db_base.DbTestCase):

    def setUp(self):
        super(iPXEValidateRescueTestCase, self).setUp()
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'network':
                impl = 'flat'
            if iface == 'rescue':
                impl = 'agent'
            if iface == 'boot':
                impl = 'ipxe'
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
