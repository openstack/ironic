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

"""Test class for iSCSI deploy mechanism."""

import os
import tempfile

import mock
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import image_service
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.openstack.common import fileutils
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


class IscsiDeployValidateParametersTestCase(db_base.DbTestCase):

    def test_parse_instance_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(
                   self.context, driver='fake_pxe',
                   instance_info=INST_INFO_DICT,
                   driver_internal_info=DRV_INTERNAL_INFO_DICT
               )
        info = iscsi_deploy.parse_instance_info(node)
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('root_gb'))
        self.assertEqual(0, info.get('ephemeral_gb'))
        self.assertIsNone(info.get('configdrive'))

    def test_parse_instance_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['image_source']
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.MissingParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['root_gb']

        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.MissingParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_invalid_root_gb(self):
        info = dict(INST_INFO_DICT)
        info['root_gb'] = 'foobar'
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.InvalidParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_valid_ephemeral_gb(self):
        ephemeral_gb = 10
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = ephemeral_fmt
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        data = iscsi_deploy.parse_instance_info(node)
        self.assertEqual(ephemeral_gb, data.get('ephemeral_gb'))
        self.assertEqual(ephemeral_fmt, data.get('ephemeral_format'))

    def test_parse_instance_info_invalid_ephemeral_gb(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 'foobar'
        info['ephemeral_format'] = 'exttest'

        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.InvalidParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_valid_ephemeral_missing_format(self):
        ephemeral_gb = 10
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = None
        self.config(default_ephemeral_format=ephemeral_fmt, group='pxe')
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        instance_info = iscsi_deploy.parse_instance_info(node)
        self.assertEqual(ephemeral_fmt, instance_info['ephemeral_format'])

    def test_parse_instance_info_valid_preserve_ephemeral_true(self):
        info = dict(INST_INFO_DICT)
        for opt in ['true', 'TRUE', 'True', 't',
                    'on', 'yes', 'y', '1']:
            info['preserve_ephemeral'] = opt

            node = obj_utils.create_test_node(
                      self.context, uuid=uuidutils.generate_uuid(),
                      instance_info=info,
                      driver_internal_info=DRV_INTERNAL_INFO_DICT,
                   )
            data = iscsi_deploy.parse_instance_info(node)
            self.assertTrue(data.get('preserve_ephemeral'))

    def test_parse_instance_info_valid_preserve_ephemeral_false(self):
        info = dict(INST_INFO_DICT)
        for opt in ['false', 'FALSE', 'False', 'f',
                    'off', 'no', 'n', '0']:
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(
                      self.context, uuid=uuidutils.generate_uuid(),
                      instance_info=info,
                      driver_internal_info=DRV_INTERNAL_INFO_DICT,
                   )
            data = iscsi_deploy.parse_instance_info(node)
            self.assertFalse(data.get('preserve_ephemeral'))

    def test_parse_instance_info_invalid_preserve_ephemeral(self):
        info = dict(INST_INFO_DICT)
        info['preserve_ephemeral'] = 'foobar'
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.InvalidParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_configdrive(self):
        info = dict(INST_INFO_DICT)
        info['configdrive'] = 'http://1.2.3.4/cd'
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        instance_info = iscsi_deploy.parse_instance_info(node)
        self.assertEqual('http://1.2.3.4/cd', instance_info['configdrive'])

    def test_parse_instance_info_nonglance_image(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['kernel'] = 'file:///image.vmlinuz'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        iscsi_deploy.parse_instance_info(node)

    def test_parse_instance_info_nonglance_image_no_kernel(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
                  self.context, instance_info=info,
                  driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        self.assertRaises(exception.MissingParameterValue,
                          iscsi_deploy.parse_instance_info, node)

    @mock.patch.object(image_service, 'get_image_service')
    def test_validate_image_properties_glance_image(self, image_service_mock):
        node = obj_utils.create_test_node(
                   self.context, driver='fake_pxe',
                   instance_info=INST_INFO_DICT,
                   driver_info=DRV_INFO_DICT,
                   driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        d_info = pxe._parse_deploy_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111', 'ramdisk_id': '2222'},
        }

        iscsi_deploy.validate_image_properties(self.context, d_info,
                                               ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service')
    def test_validate_image_properties_glance_image_missing_prop(self,
            image_service_mock):
        node = obj_utils.create_test_node(
                   self.context, driver='fake_pxe',
                   instance_info=INST_INFO_DICT,
                   driver_info=DRV_INFO_DICT,
                   driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        d_info = pxe._parse_deploy_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111'},
        }

        self.assertRaises(exception.MissingParameterValue,
            iscsi_deploy.validate_image_properties, self.context, d_info,
            ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service')
    def test_validate_image_properties_glance_image_not_authorized(self,
            image_service_mock):
        d_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotAuthorized(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          iscsi_deploy.validate_image_properties, self.context,
                          d_info, [])

    @mock.patch.object(image_service, 'get_image_service')
    def test_validate_image_properties_glance_image_not_found(self,
            image_service_mock):
        d_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotFound(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          iscsi_deploy.validate_image_properties, self.context,
                          d_info, [])

    def test_validate_image_properties_invalid_image_href(self):
        d_info = {'image_source': 'emule://uuid'}
        self.assertRaises(exception.InvalidParameterValue,
                          iscsi_deploy.validate_image_properties, self.context,
                          d_info, [])

    @mock.patch.object(image_service.HttpImageService, 'show')
    def test_validate_image_properties_nonglance_image(self,
            image_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        image_service_show_mock.return_value = {'size': 1, 'properties': {}}
        node = obj_utils.create_test_node(
                   self.context, driver='fake_pxe',
                   instance_info=instance_info,
                   driver_info=DRV_INFO_DICT,
                   driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        d_info = pxe._parse_deploy_info(node)
        iscsi_deploy.validate_image_properties(self.context, d_info,
                                               ['kernel', 'ramdisk'])
        image_service_show_mock.assert_called_once_with(
            instance_info['image_source'])

    @mock.patch.object(image_service.HttpImageService, 'show')
    def test_validate_image_properties_nonglance_image_validation_fail(self,
            img_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        img_service_show_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://ubuntu', reason='HTTPError')
        node = obj_utils.create_test_node(
                   self.context, driver='fake_pxe',
                   instance_info=instance_info,
                   driver_info=DRV_INFO_DICT,
                   driver_internal_info=DRV_INTERNAL_INFO_DICT,
               )
        d_info = pxe._parse_deploy_info(node)
        self.assertRaises(exception.InvalidParameterValue,
                          iscsi_deploy.validate_image_properties, self.context,
                          d_info, ['kernel', 'ramdisk'])

    def test_parse_instance_info_whole_disk_image(self):
        driver_internal_info = dict(DRV_INTERNAL_INFO_DICT)
        driver_internal_info['is_whole_disk_image'] = True
        node = obj_utils.create_test_node(
                  self.context, instance_info=INST_INFO_DICT,
                  driver_internal_info=driver_internal_info,
               )
        instance_info = iscsi_deploy.parse_instance_info(node)
        self.assertIsNotNone(instance_info.get('image_source'))
        self.assertIsNotNone(instance_info.get('root_gb'))
        self.assertEqual(0, instance_info.get('swap_mb'))
        self.assertEqual(0, instance_info.get('ephemeral_gb'))
        self.assertIsNone(instance_info.get('configdrive'))

    def test_parse_instance_info_whole_disk_image_missing_root(self):
        info = dict(INST_INFO_DICT)
        del info['root_gb']
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          iscsi_deploy.parse_instance_info, node)


class IscsiDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployPrivateMethodsTestCase, self).setUp()
        n = {
              'driver': 'fake_pxe',
              'instance_info': INST_INFO_DICT,
              'driver_info': DRV_INFO_DICT,
              'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.node = obj_utils.create_test_node(self.context, **n)

    def test__get_image_dir_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path,
                                      self.node.uuid),
                         iscsi_deploy._get_image_dir_path(self.node.uuid))

    def test__get_image_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path,
                                      self.node.uuid,
                                      'disk'),
                         iscsi_deploy._get_image_file_path(self.node.uuid))


class IscsiDeployMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployMethodsTestCase, self).setUp()
        instance_info = dict(INST_INFO_DICT)
        instance_info['deploy_key'] = 'fake-56789'
        n = {
              'driver': 'fake_pxe',
              'instance_info': instance_info,
              'driver_info': DRV_INFO_DICT,
              'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.node = obj_utils.create_test_node(self.context, **n)

    @mock.patch.object(deploy_utils, 'fetch_images')
    def test_cache_instance_images_master_path(self, mock_fetch_image):
        temp_dir = tempfile.mkdtemp()
        self.config(images_path=temp_dir, group='pxe')
        self.config(instance_master_path=os.path.join(temp_dir,
                                                      'instance_master_path'),
                    group='pxe')
        fileutils.ensure_tree(CONF.pxe.instance_master_path)

        (uuid, image_path) = iscsi_deploy.cache_instance_image(None, self.node)
        mock_fetch_image.assert_called_once_with(None,
                                                 mock.ANY,
                                                 [(uuid, image_path)], True)
        self.assertEqual('glance://image_uuid', uuid)
        self.assertEqual(os.path.join(temp_dir,
                                      self.node.uuid,
                                      'disk'),
                         image_path)

    @mock.patch.object(utils, 'unlink_without_raise')
    @mock.patch.object(utils, 'rmtree_without_raise')
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    def test_destroy_images(self, mock_cache, mock_rmtree, mock_unlink):
        self.config(images_path='/path', group='pxe')

        iscsi_deploy.destroy_images('uuid')

        mock_cache.return_value.clean_up.assert_called_once_with()
        mock_unlink.assert_called_once_with('/path/uuid/disk')
        mock_rmtree.assert_called_once_with('/path/uuid')

    def _test_build_deploy_ramdisk_options(self, mock_alnum, api_url,
                                           expected_root_device=None,
                                           expected_boot_option='netboot',
                                           expected_boot_mode='bios'):
        fake_key = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
        fake_disk = 'fake-disk'

        self.config(disk_devices=fake_disk, group='pxe')

        mock_alnum.return_value = fake_key

        expected_opts = {
                         'iscsi_target_iqn': 'iqn-%s' % self.node.uuid,
                         'deployment_id': self.node.uuid,
                         'deployment_key': fake_key,
                         'disk': fake_disk,
                         'ironic_api_url': api_url,
                         'boot_option': expected_boot_option,
                         'boot_mode': expected_boot_mode,
                         'coreos.configdrive': 0,
                        }

        if expected_root_device:
            expected_opts['root_device'] = expected_root_device

        opts = iscsi_deploy.build_deploy_ramdisk_options(self.node)

        self.assertEqual(expected_opts, opts)
        mock_alnum.assert_called_once_with(32)
        # assert deploy_key was injected in the node
        self.assertIn('deploy_key', self.node.instance_info)

    @mock.patch.object(keystone, 'get_service_url')
    @mock.patch.object(utils, 'random_alnum')
    def test_build_deploy_ramdisk_options(self, mock_alnum, mock_get_url):
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url)

        # As we are getting the Ironic api url from the config file
        # assert keystone wasn't called
        self.assertFalse(mock_get_url.called)

    @mock.patch.object(keystone, 'get_service_url')
    @mock.patch.object(utils, 'random_alnum')
    def test_build_deploy_ramdisk_options_keystone(self, mock_alnum,
                                                   mock_get_url):
        fake_api_url = 'http://127.0.0.1:6385'
        mock_get_url.return_value = fake_api_url
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url)

        # As the Ironic api url is not specified in the config file
        # assert we are getting it from keystone
        mock_get_url.assert_called_once_with()

    @mock.patch.object(keystone, 'get_service_url')
    @mock.patch.object(utils, 'random_alnum')
    def test_build_deploy_ramdisk_options_root_device(self, mock_alnum,
                                                      mock_get_url):
        self.node.properties['root_device'] = {'wwn': 123456}
        expected = 'wwn=123456'
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url,
                                                expected_root_device=expected)

    @mock.patch.object(keystone, 'get_service_url')
    @mock.patch.object(utils, 'random_alnum')
    def test_build_deploy_ramdisk_options_boot_option(self, mock_alnum,
                                                      mock_get_url):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        expected = 'local'
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url,
                                                expected_boot_option=expected)

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    @mock.patch.object(utils, 'random_alnum', autospec=True)
    def test_build_deploy_ramdisk_options_whole_disk_image(self, mock_alnum,
                                                           mock_get_url):
        """Tests a hack to boot_option for whole disk images.

        This hack is in place to fix bug #1441556.
        """
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        dii = self.node.driver_internal_info
        dii['is_whole_disk_image'] = True
        self.node.driver_internal_info = dii
        self.node.save()
        expected = 'netboot'
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url,
                                                expected_boot_option=expected)

    def test_get_boot_option(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        result = iscsi_deploy.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_default_value(self):
        self.node.instance_info = {}
        result = iscsi_deploy.get_boot_option(self.node)
        self.assertEqual("netboot", result)

    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_partition_image')
    def test_continue_deploy_fail(self, deploy_mock, power_mock,
                                  mock_image_cache):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        deploy_mock.side_effect = exception.InstanceDeployFailure(
                                  "test deploy error")
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            params = iscsi_deploy.get_deploy_info(task.node, **kwargs)
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.continue_deploy,
                              task, **kwargs)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertIsNotNone(task.node.last_error)
            deploy_mock.assert_called_once_with(**params)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()

    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_partition_image')
    def test_continue_deploy_ramdisk_fails(self, deploy_mock, power_mock,
                                           mock_image_cache):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789',
                  'error': 'test ramdisk error'}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.continue_deploy,
                              task, **kwargs)
            self.assertIsNotNone(task.node.last_error)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()
            self.assertFalse(deploy_mock.called)

    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_partition_image')
    def test_continue_deploy_fail_no_root_uuid_or_disk_id(
            self, deploy_mock, power_mock, mock_image_cache):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        deploy_mock.return_value = {}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            params = iscsi_deploy.get_deploy_info(task.node, **kwargs)
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.continue_deploy,
                              task, **kwargs)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertIsNotNone(task.node.last_error)
            deploy_mock.assert_called_once_with(**params)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()

    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_partition_image')
    def test_continue_deploy_fail_empty_root_uuid(
            self, deploy_mock, power_mock, mock_image_cache):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        deploy_mock.return_value = {'root uuid': ''}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            params = iscsi_deploy.get_deploy_info(task.node, **kwargs)
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.continue_deploy,
                              task, **kwargs)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertIsNotNone(task.node.last_error)
            deploy_mock.assert_called_once_with(**params)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()

    @mock.patch.object(iscsi_deploy, 'LOG')
    @mock.patch.object(iscsi_deploy, 'get_deploy_info')
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_partition_image')
    def test_continue_deploy(self, deploy_mock, power_mock, mock_image_cache,
                             mock_deploy_info, mock_log):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        mock_deploy_info.return_value = {
            'address': '123456',
            'boot_option': 'netboot',
            'configdrive': "I've got the power",
            'ephemeral_format': None,
            'ephemeral_mb': 0,
            'image_path': (u'/var/lib/ironic/images/1be26c0b-03f2-4d2e-ae87-'
                           u'c02d7f33c123/disk'),
            'iqn': 'aaa-bbb',
            'lun': '1',
            'node_uuid': u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'port': '3260',
            'preserve_ephemeral': False,
            'root_mb': 102400,
            'swap_mb': 0,
        }
        log_params = mock_deploy_info.return_value.copy()
        # Make sure we don't log the full content of the configdrive
        log_params['configdrive'] = '***'
        expected_dict = {
            'node': self.node.uuid,
            'params': log_params,
        }
        uuid_dict_returned = {'root uuid': '12345678-87654321'}
        deploy_mock.return_value = uuid_dict_returned

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_log.isEnabledFor.return_value = True
            retval = iscsi_deploy.continue_deploy(task, **kwargs)
            mock_log.debug.assert_called_once_with(
                mock.ANY, expected_dict)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertIsNone(task.node.last_error)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()
            self.assertEqual(uuid_dict_returned, retval)

    @mock.patch.object(iscsi_deploy, 'LOG')
    @mock.patch.object(iscsi_deploy, 'get_deploy_info')
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache')
    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'deploy_disk_image')
    def test_continue_deploy_whole_disk_image(
            self, deploy_mock, power_mock, mock_image_cache, mock_deploy_info,
            mock_log):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        mock_deploy_info.return_value = {
            'address': '123456',
            'image_path': (u'/var/lib/ironic/images/1be26c0b-03f2-4d2e-ae87-'
                           u'c02d7f33c123/disk'),
            'iqn': 'aaa-bbb',
            'lun': '1',
            'node_uuid': u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'port': '3260',
            'root_mb': 102400,
        }
        log_params = mock_deploy_info.return_value.copy()
        expected_dict = {
            'node': self.node.uuid,
            'params': log_params,
        }
        uuid_dict_returned = {'disk identifier': '87654321'}
        deploy_mock.return_value = uuid_dict_returned
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            mock_log.isEnabledFor.return_value = True
            retval = iscsi_deploy.continue_deploy(task, **kwargs)
            mock_log.debug.assert_called_once_with(
                mock.ANY, expected_dict)
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertIsNone(task.node.last_error)
            mock_image_cache.assert_called_once_with()
            mock_image_cache.return_value.clean_up.assert_called_once_with()
            self.assertEqual(uuid_dict_returned, retval)

    def test_get_deploy_info_boot_option_default(self):
        instance_info = self.node.instance_info
        instance_info['deploy_key'] = 'key'
        self.node.instance_info = instance_info
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn', 'key': 'key'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        self.assertEqual('netboot', ret_val['boot_option'])

    def test_get_deploy_info_netboot_specified(self):
        instance_info = self.node.instance_info
        instance_info['deploy_key'] = 'key'
        instance_info['capabilities'] = {'boot_option': 'netboot'}
        self.node.instance_info = instance_info
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn', 'key': 'key'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        self.assertEqual('netboot', ret_val['boot_option'])

    def test_get_deploy_info_localboot(self):
        instance_info = self.node.instance_info
        instance_info['deploy_key'] = 'key'
        instance_info['capabilities'] = {'boot_option': 'local'}
        self.node.instance_info = instance_info
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn', 'key': 'key'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        self.assertEqual('local', ret_val['boot_option'])

    @mock.patch.object(iscsi_deploy, 'continue_deploy')
    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options')
    def test_do_agent_iscsi_deploy_okay(self, build_options_mock,
                                        continue_deploy_mock):
        build_options_mock.return_value = {'deployment_key': 'abcdef',
                                           'iscsi_target_iqn': 'iqn-qweqwe'}
        agent_client_mock = mock.MagicMock()
        agent_client_mock.start_iscsi_target.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        driver_internal_info = {'agent_url': 'http://1.2.3.4:1234'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        continue_deploy_mock.return_value = uuid_dict_returned

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret_val = iscsi_deploy.do_agent_iscsi_deploy(
                task, agent_client_mock)
            build_options_mock.assert_called_once_with(task.node)
            agent_client_mock.start_iscsi_target.assert_called_once_with(
                task.node, 'iqn-qweqwe')
            continue_deploy_mock.assert_called_once_with(
                task, error=None, iqn='iqn-qweqwe', key='abcdef',
                address='1.2.3.4')
            self.assertEqual(
                'some-root-uuid',
                task.node.driver_internal_info['root_uuid_or_disk_id'])
            self.assertEqual(ret_val, uuid_dict_returned)

    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options')
    def test_do_agent_iscsi_deploy_start_iscsi_failure(self,
                                                       build_options_mock):
        build_options_mock.return_value = {'deployment_key': 'abcdef',
                                           'iscsi_target_iqn': 'iqn-qweqwe'}
        agent_client_mock = mock.MagicMock()
        agent_client_mock.start_iscsi_target.return_value = {
            'command_status': 'FAILED', 'command_error': 'booom'}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.do_agent_iscsi_deploy,
                              task, agent_client_mock)
            build_options_mock.assert_called_once_with(task.node)
            agent_client_mock.start_iscsi_target.assert_called_once_with(
                task.node, 'iqn-qweqwe')
            self.node.refresh()
            self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
            self.assertEqual(states.ACTIVE, self.node.target_provision_state)
            self.assertIsNotNone(self.node.last_error)

    def test_validate_pass_bootloader_info_input(self):
        params = {'key': 'some-random-key', 'address': '1.2.3.4',
                  'error': '', 'status': 'SUCCEEDED'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['deploy_key'] = 'some-random-key'
            # Assert that the method doesn't raise
            iscsi_deploy.validate_pass_bootloader_info_input(task, params)

    def test_validate_pass_bootloader_info_missing_status(self):
        params = {'key': 'some-random-key', 'address': '1.2.3.4'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              iscsi_deploy.validate_pass_bootloader_info_input,
                              task, params)

    def test_validate_pass_bootloader_info_missing_key(self):
        params = {'status': 'SUCCEEDED', 'address': '1.2.3.4'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              iscsi_deploy.validate_pass_bootloader_info_input,
                              task, params)

    def test_validate_pass_bootloader_info_missing_address(self):
        params = {'status': 'SUCCEEDED', 'key': 'some-random-key'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.MissingParameterValue,
                              iscsi_deploy.validate_pass_bootloader_info_input,
                              task, params)

    def test_validate_pass_bootloader_info_input_invalid_key(self):
        params = {'key': 'some-other-key', 'address': '1.2.3.4',
                  'status': 'SUCCEEDED'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['deploy_key'] = 'some-random-key'
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate_pass_bootloader_info_input,
                              task, params)

    def test_validate_bootloader_install_status(self):
        kwargs = {'key': 'abcdef', 'status': 'SUCCEEDED', 'error': ''}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['deploy_key'] = 'abcdef'
            # Nothing much to assert except that it shouldn't raise.
            iscsi_deploy.validate_bootloader_install_status(task, kwargs)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    def test_validate_bootloader_install_status_install_failed(
            self, set_fail_state_mock):
        kwargs = {'key': 'abcdef', 'status': 'FAILED', 'error': 'some-error'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.target_provision_state = states.ACTIVE
            task.node.instance_info['deploy_key'] = 'abcdef'
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.validate_bootloader_install_status,
                              task, kwargs)
            set_fail_state_mock.assert_called_once_with(task, mock.ANY)

    @mock.patch.object(deploy_utils, 'notify_ramdisk_to_proceed',
                       autospec=True)
    def test_finish_deploy(self, notify_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            iscsi_deploy.finish_deploy(task, '1.2.3.4')
            notify_mock.assert_called_once_with('1.2.3.4')
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(deploy_utils, 'notify_ramdisk_to_proceed',
                       autospec=True)
    def test_finish_deploy_notify_fails(self, notify_mock,
                                        set_fail_state_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            notify_mock.side_effect = RuntimeError()
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.finish_deploy, task, '1.2.3.4')
            set_fail_state_mock.assert_called_once_with(task, mock.ANY)

    @mock.patch.object(manager_utils, 'node_power_action')
    @mock.patch.object(deploy_utils, 'notify_ramdisk_to_proceed',
                       autospec=True)
    def test_finish_deploy_ssh_with_local_boot(self, notify_mock,
                                               node_power_mock):
        instance_info = dict(INST_INFO_DICT)
        instance_info['capabilities'] = {'boot_option': 'local'}
        n = {
              'uuid': uuidutils.generate_uuid(),
              'driver': 'fake_ssh',
              'instance_info': instance_info,
              'provision_state': states.DEPLOYING,
              'target_provision_state': states.ACTIVE,
        }
        mgr_utils.mock_the_extension_manager(driver="fake_ssh")
        node = obj_utils.create_test_node(self.context, **n)

        with task_manager.acquire(self.context, node.uuid,
                                  shared=False) as task:
            iscsi_deploy.finish_deploy(task, '1.2.3.4')
            notify_mock.assert_called_once_with('1.2.3.4')
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
            node_power_mock.assert_called_once_with(task, states.REBOOT)
