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

from ironic.common import exception
from ironic.common import keystone
from ironic.common import utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import iscsi_deploy
from ironic.openstack.common import fileutils
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()


class IscsiDeployValidateParametersTestCase(db_base.DbTestCase):

    def test_parse_instance_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_pxe',
                                          instance_info=INST_INFO_DICT)
        info = iscsi_deploy.parse_instance_info(node)
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('root_gb'))
        self.assertEqual(0, info.get('ephemeral_gb'))
        self.assertIsNone(info.get('configdrive'))

    def test_parse_instance_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['image_source']
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.MissingParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['root_gb']
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.MissingParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_invalid_root_gb(self):
        info = dict(INST_INFO_DICT)
        info['root_gb'] = 'foobar'
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_valid_ephemeral_gb(self):
        ephemeral_gb = 10
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = ephemeral_fmt
        node = obj_utils.create_test_node(self.context, instance_info=info)
        data = iscsi_deploy.parse_instance_info(node)
        self.assertEqual(ephemeral_gb, data.get('ephemeral_gb'))
        self.assertEqual(ephemeral_fmt, data.get('ephemeral_format'))

    def test_parse_instance_info_invalid_ephemeral_gb(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 'foobar'
        info['ephemeral_format'] = 'exttest'
        node = obj_utils.create_test_node(self.context, instance_info=info)
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
        node = obj_utils.create_test_node(self.context, instance_info=info)
        instance_info = iscsi_deploy.parse_instance_info(node)
        self.assertEqual(ephemeral_fmt, instance_info['ephemeral_format'])

    def test_parse_instance_info_valid_preserve_ephemeral_true(self):
        info = dict(INST_INFO_DICT)
        for opt in ['true', 'TRUE', 'True', 't',
                    'on', 'yes', 'y', '1']:
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(self.context,
                                              uuid=utils.generate_uuid(),
                                              instance_info=info)
            data = iscsi_deploy.parse_instance_info(node)
            self.assertTrue(data.get('preserve_ephemeral'))

    def test_parse_instance_info_valid_preserve_ephemeral_false(self):
        info = dict(INST_INFO_DICT)
        for opt in ['false', 'FALSE', 'False', 'f',
                    'off', 'no', 'n', '0']:
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(self.context,
                                              uuid=utils.generate_uuid(),
                                              instance_info=info)
            data = iscsi_deploy.parse_instance_info(node)
            self.assertFalse(data.get('preserve_ephemeral'))

    def test_parse_instance_info_invalid_preserve_ephemeral(self):
        info = dict(INST_INFO_DICT)
        info['preserve_ephemeral'] = 'foobar'
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                iscsi_deploy.parse_instance_info,
                node)

    def test_parse_instance_info_configdrive(self):
        info = dict(INST_INFO_DICT)
        info['configdrive'] = 'http://1.2.3.4/cd'
        node = obj_utils.create_test_node(self.context, instance_info=info)
        instance_info = iscsi_deploy.parse_instance_info(node)
        self.assertEqual('http://1.2.3.4/cd', instance_info['configdrive'])


class IscsiDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployPrivateMethodsTestCase, self).setUp()
        n = {
              'driver': 'fake_pxe',
              'instance_info': INST_INFO_DICT,
              'driver_info': DRV_INFO_DICT,
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
        n = {
              'driver': 'fake_pxe',
              'instance_info': INST_INFO_DICT,
              'driver_info': DRV_INFO_DICT,
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
                                           expected_root_device=None):
        fake_key = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
        fake_disk = 'fake-disk'

        self.config(disk_devices=fake_disk, group='pxe')

        mock_alnum.return_value = fake_key

        expected_opts = {'iscsi_target_iqn': 'iqn-%s' % self.node.uuid,
                         'deployment_id': self.node.uuid,
                         'deployment_key': fake_key,
                         'disk': fake_disk,
                         'ironic_api_url': api_url}

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

    def test_parse_root_device_hints(self):
        self.node.properties['root_device'] = {'wwn': 123456}
        expected = 'wwn=123456'
        result = iscsi_deploy.parse_root_device_hints(self.node)
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_string_space(self):
        self.node.properties['root_device'] = {'model': 'fake model'}
        expected = 'model=fake%20model'
        result = iscsi_deploy.parse_root_device_hints(self.node)
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_no_hints(self):
        self.node.properties = {}
        result = iscsi_deploy.parse_root_device_hints(self.node)
        self.assertIsNone(result)
