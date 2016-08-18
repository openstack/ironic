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

import filecmp
import os
import shutil
import tempfile
import uuid

from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg
from oslo_serialization import jsonutils as json
from oslo_utils import fileutils

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import base_image_service
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import pxe
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


class PXEPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEPrivateMethodsTestCase, self).setUp()
        n = {
            'driver': 'fake_pxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.node = obj_utils.create_test_node(self.context, **n)

    def test__parse_driver_info_missing_deploy_kernel(self):
        del self.node.driver_info['deploy_kernel']
        self.assertRaises(exception.MissingParameterValue,
                          pxe._parse_driver_info, self.node)

    def test__parse_driver_info_missing_deploy_ramdisk(self):
        del self.node.driver_info['deploy_ramdisk']
        self.assertRaises(exception.MissingParameterValue,
                          pxe._parse_driver_info, self.node)

    def test__parse_driver_info(self):
        expected_info = {'deploy_ramdisk': 'glance://deploy_ramdisk_uuid',
                         'deploy_kernel': 'glance://deploy_kernel_uuid'}
        image_info = pxe._parse_driver_info(self.node)
        self.assertEqual(expected_info, image_info)

    def test__get_deploy_image_info(self):
        expected_info = {'deploy_ramdisk':
                         (DRV_INFO_DICT['deploy_ramdisk'],
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'deploy_ramdisk')),
                         'deploy_kernel':
                         (DRV_INFO_DICT['deploy_kernel'],
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'deploy_kernel'))}
        image_info = pxe._get_deploy_image_info(self.node)
        self.assertEqual(expected_info, image_info)

    def test__get_deploy_image_info_missing_deploy_kernel(self):
        del self.node.driver_info['deploy_kernel']
        self.assertRaises(exception.MissingParameterValue,
                          pxe._get_deploy_image_info, self.node)

    def test__get_deploy_image_info_deploy_ramdisk(self):
        del self.node.driver_info['deploy_ramdisk']
        self.assertRaises(exception.MissingParameterValue,
                          pxe._get_deploy_image_info, self.node)

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def _test__get_instance_image_info(self, show_mock):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                      u'ramdisk_id': u'instance_ramdisk_uuid'}}

        expected_info = {'ramdisk':
                         ('instance_ramdisk_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')),
                         'kernel':
                         ('instance_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel'))}
        show_mock.return_value = properties
        self.context.auth_token = 'fake'
        image_info = pxe._get_instance_image_info(self.node, self.context)
        show_mock.assert_called_once_with(mock.ANY, 'glance://image_uuid',
                                          method='get')
        self.assertEqual(expected_info, image_info)

        # test with saved info
        show_mock.reset_mock()
        image_info = pxe._get_instance_image_info(self.node, self.context)
        self.assertEqual(expected_info, image_info)
        self.assertFalse(show_mock.called)
        self.assertEqual('instance_kernel_uuid',
                         self.node.instance_info['kernel'])
        self.assertEqual('instance_ramdisk_uuid',
                         self.node.instance_info['ramdisk'])

    def test__get_instance_image_info(self):
        # Tests when 'is_whole_disk_image' exists in driver_internal_info
        self._test__get_instance_image_info()

    def test__get_instance_image_info_without_is_whole_disk_image(self):
        # Tests when 'is_whole_disk_image' doesn't exists in
        # driver_internal_info
        del self.node.driver_internal_info['is_whole_disk_image']
        self.node.save()
        self._test__get_instance_image_info()

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='local')
    def test__get_instance_image_info_localboot(self, boot_opt_mock):
        self.node.driver_internal_info['is_whole_disk_image'] = False
        self.node.save()
        image_info = pxe._get_instance_image_info(self.node, self.context)
        self.assertEqual({}, image_info)

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def test__get_instance_image_info_whole_disk_image(self, show_mock):
        properties = {'properties': None}
        show_mock.return_value = properties
        self.node.driver_internal_info['is_whole_disk_image'] = True
        image_info = pxe._get_instance_image_info(self.node, self.context)
        self.assertEqual({}, image_info)

    @mock.patch('ironic.common.image_service.GlanceImageService',
                autospec=True)
    @mock.patch.object(pxe_utils, '_build_pxe_config', autospec=True)
    def _test_build_pxe_config_options(self, build_pxe_mock, glance_mock,
                                       whle_dsk_img=False,
                                       ipxe_enabled=False,
                                       ipxe_timeout=0,
                                       ipxe_use_swift=False):
        self.config(pxe_append_params='test_param', group='pxe')
        # NOTE: right '/' should be removed from url string
        self.config(api_url='http://192.168.122.184:6385', group='conductor')
        self.config(ipxe_timeout=ipxe_timeout, group='pxe')

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = whle_dsk_img
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        tftp_server = CONF.pxe.tftp_server

        if ipxe_enabled:
            http_url = 'http://192.1.2.3:1234'
            self.config(ipxe_enabled=True, group='pxe')
            self.config(http_url=http_url, group='deploy')
            if ipxe_use_swift:
                self.config(ipxe_use_swift=True, group='pxe')
                glance = mock.Mock()
                glance_mock.return_value = glance
                glance.swift_temp_url.side_effect = [
                    deploy_kernel, deploy_ramdisk] = [
                    'swift_kernel', 'swift_ramdisk']
            else:
                deploy_kernel = os.path.join(http_url, self.node.uuid,
                                             'deploy_kernel')
                deploy_ramdisk = os.path.join(http_url, self.node.uuid,
                                              'deploy_ramdisk')
            kernel = os.path.join(http_url, self.node.uuid, 'kernel')
            ramdisk = os.path.join(http_url, self.node.uuid, 'ramdisk')
            root_dir = CONF.deploy.http_root
        else:
            deploy_kernel = os.path.join(CONF.pxe.tftp_root, self.node.uuid,
                                         'deploy_kernel')
            deploy_ramdisk = os.path.join(CONF.pxe.tftp_root, self.node.uuid,
                                          'deploy_ramdisk')
            kernel = os.path.join(CONF.pxe.tftp_root, self.node.uuid,
                                  'kernel')
            ramdisk = os.path.join(CONF.pxe.tftp_root, self.node.uuid,
                                   'ramdisk')
            root_dir = CONF.pxe.tftp_root

        if ipxe_use_swift:
            image_info = {
                'deploy_kernel': (str(uuid.uuid4()),
                                  os.path.join(root_dir,
                                               self.node.uuid,
                                               'deploy_kernel')),
                'deploy_ramdisk': (str(uuid.uuid4()),
                                   os.path.join(root_dir,
                                                self.node.uuid,
                                                'deploy_ramdisk'))
            }
        else:
            image_info = {
                'deploy_kernel': ('deploy_kernel',
                                  os.path.join(root_dir,
                                               self.node.uuid,
                                               'deploy_kernel')),
                'deploy_ramdisk': ('deploy_ramdisk',
                                   os.path.join(root_dir,
                                                self.node.uuid,
                                                'deploy_ramdisk'))
            }

        if (whle_dsk_img or
            deploy_utils.get_boot_option(self.node) == 'local'):
                ramdisk = 'no_ramdisk'
                kernel = 'no_kernel'
        else:
            image_info.update({
                'kernel': ('kernel_id',
                           os.path.join(root_dir,
                                        self.node.uuid,
                                        'kernel')),
                'ramdisk': ('ramdisk_id',
                            os.path.join(root_dir,
                                         self.node.uuid,
                                         'ramdisk'))
            })

        ipxe_timeout_in_ms = ipxe_timeout * 1000

        expected_options = {
            'ari_path': ramdisk,
            'deployment_ari_path': deploy_ramdisk,
            'pxe_append_params': 'test_param',
            'aki_path': kernel,
            'deployment_aki_path': deploy_kernel,
            'tftp_server': tftp_server,
            'ipxe_timeout': ipxe_timeout_in_ms,
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe._build_pxe_config_options(task, image_info)
        self.assertEqual(expected_options, options)

    def test__build_pxe_config_options(self):
        self._test_build_pxe_config_options(whle_dsk_img=True,
                                            ipxe_enabled=False)

    def test__build_pxe_config_options_local_boot(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'local'}})
        self.node.instance_info = i_info
        self.node.save()
        self._test_build_pxe_config_options(whle_dsk_img=False,
                                            ipxe_enabled=False)

    def test__build_pxe_config_options_ipxe(self):
        self._test_build_pxe_config_options(whle_dsk_img=True,
                                            ipxe_enabled=True)

    def test__build_pxe_config_options_ipxe_local_boot(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'local'}})
        self.node.instance_info = i_info
        self.node.save()
        self._test_build_pxe_config_options(whle_dsk_img=False,
                                            ipxe_enabled=True)

    def test__build_pxe_config_options_ipxe_swift_wdi(self):
        self._test_build_pxe_config_options(whle_dsk_img=True,
                                            ipxe_enabled=True,
                                            ipxe_use_swift=True)

    def test__build_pxe_config_options_ipxe_swift_partition(self):
        self._test_build_pxe_config_options(whle_dsk_img=False,
                                            ipxe_enabled=True,
                                            ipxe_use_swift=True)

    def test__build_pxe_config_options_without_is_whole_disk_image(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self.node.save()
        self._test_build_pxe_config_options(whle_dsk_img=False,
                                            ipxe_enabled=False)

    def test__build_pxe_config_options_ipxe_and_ipxe_timeout(self):
        self._test_build_pxe_config_options(whle_dsk_img=True,
                                            ipxe_enabled=True,
                                            ipxe_timeout=120)

    def test__build_pxe_config_options_no_kernel_no_ramdisk(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self.node.save()
        self.config(group='pxe', tftp_server='my-tftp-server')
        self.config(group='pxe', pxe_append_params='my-pxe-append-params')
        image_info = {
            'deploy_kernel': ('deploy_kernel',
                              'path-to-deploy_kernel'),
            'deploy_ramdisk': ('deploy_ramdisk',
                               'path-to-deploy_ramdisk')}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe._build_pxe_config_options(task, image_info)

        expected_options = {
            'deployment_aki_path': 'path-to-deploy_kernel',
            'deployment_ari_path': 'path-to-deploy_ramdisk',
            'pxe_append_params': 'my-pxe-append-params',
            'tftp_server': 'my-tftp-server',
            'aki_path': 'no_kernel',
            'ari_path': 'no_ramdisk',
            'ipxe_timeout': 0}
        self.assertEqual(expected_options, options)

    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test__cache_tftp_images_master_path(self, mock_fetch_image):
        temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=temp_dir, group='pxe')
        self.config(tftp_master_path=os.path.join(temp_dir,
                                                  'tftp_master_path'),
                    group='pxe')
        image_path = os.path.join(temp_dir, self.node.uuid,
                                  'deploy_kernel')
        image_info = {'deploy_kernel': ('deploy_kernel', image_path)}
        fileutils.ensure_tree(CONF.pxe.tftp_master_path)

        pxe._cache_ramdisk_kernel(None, self.node, image_info)

        mock_fetch_image.assert_called_once_with(None,
                                                 mock.ANY,
                                                 [('deploy_kernel',
                                                   image_path)],
                                                 True)

    @mock.patch.object(pxe, 'TFTPImageCache', lambda: None)
    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test__cache_ramdisk_kernel(self, mock_fetch_image, mock_ensure_tree):
        self.config(ipxe_enabled=False, group='pxe')
        fake_pxe_info = {'foo': 'bar'}
        expected_path = os.path.join(CONF.pxe.tftp_root, self.node.uuid)

        pxe._cache_ramdisk_kernel(self.context, self.node, fake_pxe_info)
        mock_ensure_tree.assert_called_with(expected_path)
        mock_fetch_image.assert_called_once_with(
            self.context, mock.ANY, list(fake_pxe_info.values()), True)

    @mock.patch.object(pxe, 'TFTPImageCache', lambda: None)
    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test__cache_ramdisk_kernel_ipxe(self, mock_fetch_image,
                                        mock_ensure_tree):
        self.config(ipxe_enabled=True, group='pxe')
        fake_pxe_info = {'foo': 'bar'}
        expected_path = os.path.join(CONF.deploy.http_root,
                                     self.node.uuid)

        pxe._cache_ramdisk_kernel(self.context, self.node, fake_pxe_info)
        mock_ensure_tree.assert_called_with(expected_path)
        mock_fetch_image.assert_called_once_with(self.context, mock.ANY,
                                                 list(fake_pxe_info.values()),
                                                 True)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_option_for_uefi_exc(self, mock_log):
        properties = {'capabilities': 'boot_mode:uefi'}
        instance_info = {"boot_option": "netboot"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        self.assertRaises(exception.InvalidParameterValue,
                          pxe.validate_boot_option_for_uefi,
                          self.node)
        self.assertTrue(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_option_for_uefi_noexc_one(self, mock_log):
        properties = {'capabilities': 'boot_mode:uefi'}
        instance_info = {"boot_option": "local"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        pxe.validate_boot_option_for_uefi(self.node)
        self.assertFalse(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_option_for_uefi_noexc_two(self, mock_log):
        properties = {'capabilities': 'boot_mode:bios'}
        instance_info = {"boot_option": "local"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        pxe.validate_boot_option_for_uefi(self.node)
        self.assertFalse(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_option_for_uefi_noexc_three(self, mock_log):
        properties = {'capabilities': 'boot_mode:uefi'}
        instance_info = {"boot_option": "local"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = False
        pxe.validate_boot_option_for_uefi(self.node)
        self.assertFalse(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_parameters_for_trusted_boot_one(self, mock_log):
        properties = {'capabilities': 'boot_mode:uefi'}
        instance_info = {"boot_option": "netboot"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = False
        self.assertRaises(exception.InvalidParameterValue,
                          pxe.validate_boot_parameters_for_trusted_boot,
                          self.node)
        self.assertTrue(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_parameters_for_trusted_boot_two(self, mock_log):
        properties = {'capabilities': 'boot_mode:bios'}
        instance_info = {"boot_option": "local"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = False
        self.assertRaises(exception.InvalidParameterValue,
                          pxe.validate_boot_parameters_for_trusted_boot,
                          self.node)
        self.assertTrue(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_parameters_for_trusted_boot_three(self, mock_log):
        properties = {'capabilities': 'boot_mode:bios'}
        instance_info = {"boot_option": "netboot"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        self.assertRaises(exception.InvalidParameterValue,
                          pxe.validate_boot_parameters_for_trusted_boot,
                          self.node)
        self.assertTrue(mock_log.called)

    @mock.patch.object(pxe.LOG, 'error', autospec=True)
    def test_validate_boot_parameters_for_trusted_boot_pass(self, mock_log):
        properties = {'capabilities': 'boot_mode:bios'}
        instance_info = {"boot_option": "netboot"}
        self.node.properties = properties
        self.node.instance_info['capabilities'] = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = False
        pxe.validate_boot_parameters_for_trusted_boot(self.node)
        self.assertFalse(mock_log.called)


@mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
@mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
@mock.patch.object(pxe, 'TFTPImageCache', autospec=True)
class CleanUpPxeEnvTestCase(db_base.DbTestCase):
    def setUp(self):
        super(CleanUpPxeEnvTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )

    def test__clean_up_pxe_env(self, mock_cache, mock_pxe_clean,
                               mock_unlink):
        image_info = {'label': ['', 'deploy_kernel']}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe._clean_up_pxe_env(task, image_info)
            mock_pxe_clean.assert_called_once_with(task)
            mock_unlink.assert_any_call('deploy_kernel')
        mock_cache.return_value.clean_up.assert_called_once_with()


class PXEBootTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEBootTestCase, self).setUp()
        self.context.auth_token = 'fake'
        self.temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=self.temp_dir, group='pxe')
        self.temp_dir = tempfile.mkdtemp()
        self.config(images_path=self.temp_dir, group='pxe')
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake_pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT)
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)
        self.config(group='conductor', api_url='http://127.0.0.1:1234/')

    def test_get_properties(self):
        expected = pxe.COMMON_PROPERTIES
        expected.update(agent_base_vendor.VENDOR_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def test_validate_good(self, mock_glance):
        mock_glance.return_value = {'properties': {'kernel_id': 'fake-kernel',
                                                   'ramdisk_id': 'fake-initr'}}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.boot.validate(task)

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def test_validate_good_whole_disk_image(self, mock_glance):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot.validate(task)

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

    def test_validate_fail_invalid_config_uefi_whole_disk_image(self):
        properties = {'capabilities': 'boot_mode:uefi,boot_option:netboot'}
        instance_info = {"boot_option": "netboot"}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties = properties
            task.node.instance_info['capabilities'] = instance_info
            task.node.driver_internal_info['is_whole_disk_image'] = True
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    def test_validate_fail_no_port(self):
        new_node = obj_utils.create_test_node(
            self.context,
            uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            driver='fake_pxe', instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT)
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

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def test_validate_fail_no_image_kernel_ramdisk_props(self, mock_glance):
        mock_glance.return_value = {'properties': {}}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.boot.validate,
                              task)

    @mock.patch.object(base_image_service.BaseImageService, '_show',
                       autospec=True)
    def test_validate_fail_glance_image_doesnt_exists(self, mock_glance):
        mock_glance.side_effect = exception.ImageNotFound('not found')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.boot.validate, task)

    @mock.patch.object(base_image_service.BaseImageService, '_show',
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

    @mock.patch.object(dhcp_factory, 'DHCPFactory')
    @mock.patch.object(pxe, '_get_instance_image_info', autospec=True)
    @mock.patch.object(pxe, '_get_deploy_image_info', autospec=True)
    @mock.patch.object(pxe, '_cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe, '_build_pxe_config_options', autospec=True)
    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    def _test_prepare_ramdisk(self, mock_pxe_config,
                              mock_build_pxe, mock_cache_r_k,
                              mock_deploy_img_info,
                              mock_instance_img_info,
                              dhcp_factory_mock, uefi=False,
                              cleaning=False,
                              ipxe_use_swift=False,
                              whole_disk_image=False):
        mock_build_pxe.return_value = {}
        mock_deploy_img_info.return_value = {'deploy_kernel': 'a'}
        if whole_disk_image:
            mock_instance_img_info.return_value = {}
        else:
            mock_instance_img_info.return_value = {'kernel': 'b'}
        mock_pxe_config.return_value = None
        mock_cache_r_k.return_value = None
        provider_mock = mock.MagicMock()
        dhcp_factory_mock.return_value = provider_mock
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = whole_disk_image
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            task.driver.boot.prepare_ramdisk(task, {'foo': 'bar'})
            mock_deploy_img_info.assert_called_once_with(task.node)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            if ipxe_use_swift:
                if whole_disk_image:
                    self.assertFalse(mock_cache_r_k.called)
                else:
                    mock_cache_r_k.assert_called_once_with(
                        self.context, task.node,
                        {'kernel': 'b'})
                mock_instance_img_info.assert_called_once_with(task.node,
                                                               self.context)
            elif cleaning is False:
                mock_cache_r_k.assert_called_once_with(
                    self.context, task.node,
                    {'deploy_kernel': 'a', 'kernel': 'b'})
                mock_instance_img_info.assert_called_once_with(task.node,
                                                               self.context)
            else:
                mock_cache_r_k.assert_called_once_with(
                    self.context, task.node,
                    {'deploy_kernel': 'a'})
            if uefi:
                mock_pxe_config.assert_called_once_with(
                    task, {'foo': 'bar'}, CONF.pxe.uefi_pxe_config_template)
            else:
                mock_pxe_config.assert_called_once_with(
                    task, {'foo': 'bar'}, CONF.pxe.pxe_config_template)

    def test_prepare_ramdisk(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self._test_prepare_ramdisk()

    def test_prepare_ramdisk_uefi(self):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        properties = self.node.properties
        properties['capabilities'] = 'boot_mode:uefi'
        self.node.properties = properties
        self.node.save()
        self._test_prepare_ramdisk(uefi=True)

    @mock.patch.object(os.path, 'isfile', autospec=True)
    @mock.patch.object(filecmp, 'cmp', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    def test_prepare_ramdisk_ipxe_with_copy_file_different(
            self, copyfile_mock, cmp_mock, isfile_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=True)
        self.config(group='deploy', http_url='http://myserver')
        isfile_mock.return_value = True
        cmp_mock.return_value = False
        self._test_prepare_ramdisk()
        copyfile_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)))

    @mock.patch.object(os.path, 'isfile', autospec=True)
    @mock.patch.object(filecmp, 'cmp', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    def test_prepare_ramdisk_ipxe_with_copy_no_file(
            self, copyfile_mock, cmp_mock, isfile_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=True)
        self.config(group='deploy', http_url='http://myserver')
        isfile_mock.return_value = False
        self._test_prepare_ramdisk()
        self.assertFalse(cmp_mock.called)
        copyfile_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)))

    @mock.patch.object(os.path, 'isfile', autospec=True)
    @mock.patch.object(filecmp, 'cmp', autospec=True)
    @mock.patch.object(shutil, 'copyfile', autospec=True)
    def test_prepare_ramdisk_ipxe_without_copy(
            self, copyfile_mock, cmp_mock, isfile_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=True)
        self.config(group='deploy', http_url='http://myserver')
        isfile_mock.return_value = True
        cmp_mock.return_value = True
        self._test_prepare_ramdisk()
        self.assertFalse(copyfile_mock.called)

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    def test_prepare_ramdisk_ipxe_swift(self, copyfile_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=True)
        self.config(group='pxe', ipxe_use_swift=True)
        self.config(group='deploy', http_url='http://myserver')
        self._test_prepare_ramdisk(ipxe_use_swift=True)
        copyfile_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)))

    @mock.patch.object(shutil, 'copyfile', autospec=True)
    def test_prepare_ramdisk_ipxe_swift_whole_disk_image(self, copyfile_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        self.config(group='pxe', ipxe_enabled=True)
        self.config(group='pxe', ipxe_use_swift=True)
        self.config(group='deploy', http_url='http://myserver')
        self._test_prepare_ramdisk(ipxe_use_swift=True, whole_disk_image=True)
        copyfile_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            os.path.join(
                CONF.deploy.http_root,
                os.path.basename(CONF.pxe.ipxe_boot_script)))

    def test_prepare_ramdisk_cleaning(self):
        self.node.provision_state = states.CLEANING
        self.node.save()
        self._test_prepare_ramdisk(cleaning=True)

    @mock.patch.object(pxe, '_clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe, '_get_deploy_image_info', autospec=True)
    def test_clean_up_ramdisk(self, get_deploy_image_info_mock,
                              clean_up_pxe_env_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            image_info = {'deploy_kernel': ['', '/path/to/deploy_kernel'],
                          'deploy_ramdisk': ['', '/path/to/deploy_ramdisk']}
            get_deploy_image_info_mock.return_value = image_info
            task.driver.boot.clean_up_ramdisk(task)
            clean_up_pxe_env_mock.assert_called_once_with(task, image_info)
            get_deploy_image_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    @mock.patch.object(pxe, '_cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe, '_get_instance_image_info', autospec=True)
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
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            pxe_config_path = pxe_utils.get_pxe_config_file_path(
                task.node.uuid)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['root_uuid_or_disk_id'] = (
                "30212642-09d3-467f-8e09-21685826ab50")
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task.node, task.context)
            cache_mock.assert_called_once_with(
                task.context, task.node, image_info)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            switch_pxe_config_mock.assert_called_once_with(
                pxe_config_path, "30212642-09d3-467f-8e09-21685826ab50",
                'bios', False, False)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.PXE)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory')
    @mock.patch.object(pxe, '_cache_ramdisk_kernel', autospec=True)
    @mock.patch.object(pxe, '_get_instance_image_info', autospec=True)
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
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            task.node.properties['capabilities'] = 'boot_mode:bios'
            task.node.driver_internal_info['is_whole_disk_image'] = False

            task.driver.boot.prepare_instance(task)

            get_image_info_mock.assert_called_once_with(
                task.node, task.context)
            cache_mock.assert_called_once_with(
                task.context, task.node, image_info)
            provider_mock.update_dhcp.assert_called_once_with(task, dhcp_opts)
            self.assertFalse(switch_pxe_config_mock.called)
            self.assertFalse(set_boot_device_mock.called)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
    def test_prepare_instance_localboot(self, clean_up_pxe_config_mock,
                                        set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.instance_info['capabilities'] = {'boot_option': 'local'}
            task.driver.boot.prepare_instance(task)
            clean_up_pxe_config_mock.assert_called_once_with(task)
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.DISK)

    @mock.patch.object(pxe, '_clean_up_pxe_env', autospec=True)
    @mock.patch.object(pxe, '_get_instance_image_info', autospec=True)
    def test_clean_up_instance(self, get_image_info_mock,
                               clean_up_pxe_env_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            image_info = {'kernel': ['', '/path/to/kernel'],
                          'ramdisk': ['', '/path/to/ramdisk']}
            get_image_info_mock.return_value = image_info
            task.driver.boot.clean_up_instance(task)
            clean_up_pxe_env_mock.assert_called_once_with(task, image_info)
            get_image_info_mock.assert_called_once_with(
                task.node, task.context)
