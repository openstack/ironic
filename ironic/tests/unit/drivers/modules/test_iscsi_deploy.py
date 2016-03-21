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

from ironic_lib import disk_utils
from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg
from oslo_utils import fileutils
from oslo_utils import uuidutils

from ironic.common import dhcp_factory
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import keystone
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

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
        info = deploy_utils.parse_instance_info(node)
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
                          deploy_utils.parse_instance_info,
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
                          deploy_utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_root_gb(self):
        info = dict(INST_INFO_DICT)
        info['root_gb'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          deploy_utils.parse_instance_info,
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
        data = deploy_utils.parse_instance_info(node)
        self.assertEqual(ephemeral_gb, data.get('ephemeral_gb'))
        self.assertEqual(ephemeral_fmt, data.get('ephemeral_format'))

    def test_parse_instance_info_unicode_swap_mb(self):
        swap_mb = u'10'
        swap_mb_int = 10
        info = dict(INST_INFO_DICT)
        info['swap_mb'] = swap_mb
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        data = deploy_utils.parse_instance_info(node)
        self.assertEqual(swap_mb_int, data.get('swap_mb'))

    def test_parse_instance_info_invalid_ephemeral_gb(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 'foobar'
        info['ephemeral_format'] = 'exttest'

        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          deploy_utils.parse_instance_info,
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
        instance_info = deploy_utils.parse_instance_info(node)
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
            data = deploy_utils.parse_instance_info(node)
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
            data = deploy_utils.parse_instance_info(node)
            self.assertFalse(data.get('preserve_ephemeral'))

    def test_parse_instance_info_invalid_preserve_ephemeral(self):
        info = dict(INST_INFO_DICT)
        info['preserve_ephemeral'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          deploy_utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_ephemeral_disk(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 9,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          deploy_utils.parse_instance_info,
                          node)

    def test__check_disk_layout_unchanged_fails(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 20,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          deploy_utils._check_disk_layout_unchanged,
                          node, info)

    def test__check_disk_layout_unchanged(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 10,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertIsNone(deploy_utils._check_disk_layout_unchanged(node,
                                                                    info))

    def test__save_disk_layout(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 10
        info['preserve_ephemeral'] = False
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        iscsi_deploy._save_disk_layout(node, info)
        node.refresh()
        for param in ('ephemeral_gb', 'swap_mb', 'root_gb'):
            self.assertEqual(
                info[param], node.driver_internal_info['instance'][param]
            )

    def test_parse_instance_info_configdrive(self):
        info = dict(INST_INFO_DICT)
        info['configdrive'] = 'http://1.2.3.4/cd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        instance_info = deploy_utils.parse_instance_info(node)
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
        deploy_utils.parse_instance_info(node)

    def test_parse_instance_info_nonglance_image_no_kernel(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          deploy_utils.parse_instance_info, node)

    def test_parse_instance_info_whole_disk_image(self):
        driver_internal_info = dict(DRV_INTERNAL_INFO_DICT)
        driver_internal_info['is_whole_disk_image'] = True
        node = obj_utils.create_test_node(
            self.context, instance_info=INST_INFO_DICT,
            driver_internal_info=driver_internal_info,
        )
        instance_info = deploy_utils.parse_instance_info(node)
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
                          deploy_utils.parse_instance_info, node)


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

    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    def test_check_image_size(self, get_image_mb_mock):
        get_image_mb_mock.return_value = 1000
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['root_gb'] = 1
            iscsi_deploy.check_image_size(task)
            get_image_mb_mock.assert_called_once_with(
                iscsi_deploy._get_image_file_path(task.node.uuid))

    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    def test_check_image_size_fails(self, get_image_mb_mock):
        get_image_mb_mock.return_value = 1025
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['root_gb'] = 1
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.check_image_size,
                              task)
            get_image_mb_mock.assert_called_once_with(
                iscsi_deploy._get_image_file_path(task.node.uuid))

    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
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

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(utils, 'rmtree_without_raise', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
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

        expected_iqn = 'iqn.2008-10.org.openstack:%s' % self.node.uuid
        expected_opts = {
            'iscsi_target_iqn': expected_iqn,
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

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    @mock.patch.object(utils, 'random_alnum', autospec=True)
    def test_build_deploy_ramdisk_options(self, mock_alnum, mock_get_url):
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url)

        # As we are getting the Ironic api url from the config file
        # assert keystone wasn't called
        self.assertFalse(mock_get_url.called)

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    @mock.patch.object(utils, 'random_alnum', autospec=True)
    def test_build_deploy_ramdisk_options_keystone(self, mock_alnum,
                                                   mock_get_url):
        fake_api_url = 'http://127.0.0.1:6385'
        mock_get_url.return_value = fake_api_url
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url)

        # As the Ironic api url is not specified in the config file
        # assert we are getting it from keystone
        mock_get_url.assert_called_once_with()

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    @mock.patch.object(utils, 'random_alnum', autospec=True)
    def test_build_deploy_ramdisk_options_root_device(self, mock_alnum,
                                                      mock_get_url):
        self.node.properties['root_device'] = {'wwn': 123456}
        expected = 'wwn=123456'
        fake_api_url = 'http://127.0.0.1:6385'
        self.config(api_url=fake_api_url, group='conductor')
        self._test_build_deploy_ramdisk_options(mock_alnum, fake_api_url,
                                                expected_root_device=expected)

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    @mock.patch.object(utils, 'random_alnum', autospec=True)
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

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail(self, deploy_mock, power_mock,
                                  mock_image_cache, mock_disk_layout):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'key': 'fake-56789'}
        deploy_mock.side_effect = iter([
            exception.InstanceDeployFailure("test deploy error")])
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
            self.assertFalse(mock_disk_layout.called)

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_ramdisk_fails(self, deploy_mock, power_mock,
                                           mock_image_cache, mock_disk_layout):
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
            self.assertFalse(mock_disk_layout.called)

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail_no_root_uuid_or_disk_id(
            self, deploy_mock, power_mock, mock_image_cache, mock_disk_layout):
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
            self.assertFalse(mock_disk_layout.called)

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail_empty_root_uuid(
            self, deploy_mock, power_mock, mock_image_cache, mock_disk_layout):
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
            self.assertFalse(mock_disk_layout.called)

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'LOG', autospec=True)
    @mock.patch.object(iscsi_deploy, 'get_deploy_info', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def test_continue_deploy(self, deploy_mock, power_mock, mock_image_cache,
                             mock_deploy_info, mock_log, mock_disk_layout):
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
            'preserve_ephemeral': True,
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
            mock_disk_layout.assert_called_once_with(task.node, mock.ANY)

    @mock.patch.object(iscsi_deploy, 'LOG', autospec=True)
    @mock.patch.object(iscsi_deploy, 'get_deploy_info', autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_disk_image', autospec=True)
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

    def _test_get_deploy_info(self, extra_instance_info=None):
        if extra_instance_info is None:
            extra_instance_info = {}

        instance_info = self.node.instance_info
        instance_info['deploy_key'] = 'key'
        instance_info.update(extra_instance_info)
        self.node.instance_info = instance_info
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn', 'key': 'key'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        return ret_val

    def test_get_deploy_info_boot_option_default(self):
        ret_val = self._test_get_deploy_info()
        self.assertEqual('netboot', ret_val['boot_option'])

    def test_get_deploy_info_netboot_specified(self):
        capabilities = {'capabilities': {'boot_option': 'netboot'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('netboot', ret_val['boot_option'])

    def test_get_deploy_info_localboot(self):
        capabilities = {'capabilities': {'boot_option': 'local'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('local', ret_val['boot_option'])

    def test_get_deploy_info_disk_label(self):
        capabilities = {'capabilities': {'disk_label': 'msdos'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('msdos', ret_val['disk_label'])

    def test_get_deploy_info_not_specified(self):
        ret_val = self._test_get_deploy_info()
        self.assertNotIn('disk_label', ret_val)

    @mock.patch.object(iscsi_deploy, 'continue_deploy', autospec=True)
    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options',
                       autospec=True)
    def test_do_agent_iscsi_deploy_okay(self, build_options_mock,
                                        continue_deploy_mock):
        build_options_mock.return_value = {'deployment_key': 'abcdef',
                                           'iscsi_target_iqn': 'iqn-qweqwe'}
        agent_client_mock = mock.MagicMock(spec_set=agent_client.AgentClient)
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

    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options',
                       autospec=True)
    def test_do_agent_iscsi_deploy_start_iscsi_failure(self,
                                                       build_options_mock):
        build_options_mock.return_value = {'deployment_key': 'abcdef',
                                           'iscsi_target_iqn': 'iqn-qweqwe'}
        agent_client_mock = mock.MagicMock(spec_set=agent_client.AgentClient)
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

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
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

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    def test_validate_good_api_url_from_config_file(self, mock_ks):
        # not present in the keystone catalog
        mock_ks.side_effect = exception.KeystoneFailure
        self.config(group='conductor', api_url='http://foo')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            iscsi_deploy.validate(task)
            self.assertFalse(mock_ks.called)

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    def test_validate_good_api_url_from_keystone(self, mock_ks):
        # present in the keystone catalog
        mock_ks.return_value = 'http://127.0.0.1:1234'
        # not present in the config file
        self.config(group='conductor', api_url=None)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            iscsi_deploy.validate(task)
            mock_ks.assert_called_once_with()

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    def test_validate_fail_no_api_url(self, mock_ks):
        # not present in the keystone catalog
        mock_ks.side_effect = exception.KeystoneFailure
        # not present in the config file
        self.config(group='conductor', api_url=None)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate, task)
            mock_ks.assert_called_once_with()

    def test_validate_invalid_root_device_hints(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate, task)


class ISCSIDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ISCSIDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.driver = driver_factory.get_driver("fake_pxe")
        self.driver.vendor = iscsi_deploy.VendorPassthru()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.node.driver_internal_info['agent_url'] = 'http://1.2.3.4:1234'
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = self.driver
        self.task.context = self.context
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual({}, task.driver.deploy.get_properties())

    @mock.patch.object(iscsi_deploy, 'validate', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate(self, pxe_validate_mock,
                      validate_capabilities_mock, validate_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.deploy.validate(task)

            pxe_validate_mock.assert_called_once_with(task.driver.boot, task)
            validate_capabilities_mock.assert_called_once_with(task.node)
            validate_mock.assert_called_once_with(task)

    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_node_active(self, prepare_instance_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.ACTIVE

            task.driver.deploy.prepare(task)

            prepare_instance_mock.assert_called_once_with(
                task.driver.boot, task)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options',
                       autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    def test_prepare_node_deploying(self, mock_prepare_ramdisk,
                                    mock_iscsi_options, mock_agent_options):
        mock_iscsi_options.return_value = {'a': 'b'}
        mock_agent_options.return_value = {'c': 'd'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYWAIT

            task.driver.deploy.prepare(task)

            mock_iscsi_options.assert_called_once_with(task.node)
            mock_agent_options.assert_called_once_with(task.node)
            mock_prepare_ramdisk.assert_called_once_with(
                task.driver.boot, task, {'a': 'b', 'c': 'd'})

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(iscsi_deploy, 'cache_instance_image', autospec=True)
    def test_deploy(self, mock_cache_instance_image,
                    mock_check_image_size, mock_node_power_action):
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            state = task.driver.deploy.deploy(task)
            self.assertEqual(state, states.DEPLOYWAIT)
            mock_cache_instance_image.assert_called_once_with(
                self.context, task.node)
            mock_check_image_size.assert_called_once_with(task)
            mock_node_power_action.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_tear_down(self, node_power_action_mock):
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            state = task.driver.deploy.tear_down(task)
            self.assertEqual(state, states.DELETED)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)

    @mock.patch('ironic.common.dhcp_factory.DHCPFactory._set_dhcp_provider')
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.clean_dhcp')
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(iscsi_deploy, 'destroy_images', autospec=True)
    def test_clean_up(self, destroy_images_mock, clean_up_ramdisk_mock,
                      clean_up_instance_mock, clean_dhcp_mock,
                      set_dhcp_provider_mock):
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            task.driver.deploy.clean_up(task)
            destroy_images_mock.assert_called_once_with(task.node.uuid)
            clean_up_ramdisk_mock.assert_called_once_with(
                task.driver.boot, task)
            clean_up_instance_mock.assert_called_once_with(
                task.driver.boot, task)
            set_dhcp_provider_mock.assert_called_once_with()
            clean_dhcp_mock.assert_called_once_with(task)

    @mock.patch.object(deploy_utils, 'prepare_inband_cleaning', autospec=True)
    def test_prepare_cleaning(self, prepare_inband_cleaning_mock):
        prepare_inband_cleaning_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(
                states.CLEANWAIT, task.driver.deploy.prepare_cleaning(task))
            prepare_inband_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch.object(deploy_utils, 'tear_down_inband_cleaning',
                       autospec=True)
    def test_tear_down_cleaning(self, tear_down_cleaning_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.tear_down_cleaning(task)
            tear_down_cleaning_mock.assert_called_once_with(
                task, manage_boot=True)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps(self, mock_get_clean_steps):
        # Test getting clean steps
        self.config(group='deploy', erase_devices_priority=10)
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        self.node.driver_internal_info = {'agent_url': 'foo'}
        self.node.save()
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = task.driver.deploy.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(
                task, interface='deploy',
                override_priorities={
                    'erase_devices': 10})
        self.assertEqual(mock_steps, steps)

    @mock.patch('ironic.drivers.modules.deploy_utils.agent_get_clean_steps',
                autospec=True)
    def test_get_clean_steps_no_agent_url(self, mock_get_clean_steps):
        # Test getting clean steps
        self.node.driver_internal_info = {}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = task.driver.deploy.get_clean_steps(task)

        self.assertEqual([], steps)
        self.assertFalse(mock_get_clean_steps.called)

    @mock.patch.object(deploy_utils, 'agent_execute_clean_step', autospec=True)
    def test_execute_clean_step(self, agent_execute_clean_step_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.execute_clean_step(
                task, {'some-step': 'step-info'})
            agent_execute_clean_step_mock.assert_called_once_with(
                task, {'some-step': 'step-info'})


class TestVendorPassthru(db_base.DbTestCase):

    def setUp(self):
        super(TestVendorPassthru, self).setUp()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.driver.vendor = iscsi_deploy.VendorPassthru()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.node.driver_internal_info['agent_url'] = 'http://1.2.3.4:1234'
        self.task = mock.MagicMock(spec=task_manager.TaskManager)
        self.task.shared = False
        self.task.node = self.node
        self.task.driver = self.driver
        self.task.context = self.context

    def test_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info['deploy_key'] = 'fake-56789'
            task.driver.vendor.validate(task, method='pass_deploy_info',
                                        address='123456', iqn='aaa-bbb',
                                        key='fake-56789')

    def test_validate_pass_deploy_info_during_cleaning(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.CLEANWAIT
            # Assert that it doesn't raise.
            self.assertIsNone(
                task.driver.vendor.validate(task, method='pass_deploy_info',
                                            address='123456', iqn='aaa-bbb',
                                            key='fake-56789'))

    def test_validate_fail(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.validate,
                              task, method='pass_deploy_info',
                              key='fake-56789')

    def test_validate_key_notmatch(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.vendor.validate,
                              task, method='pass_deploy_info',
                              address='123456', iqn='aaa-bbb',
                              key='fake-12345')

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'set_node_cleaning_steps', autospec=True)
    @mock.patch.object(iscsi_deploy, 'LOG', spec=['warning'])
    def test__initiate_cleaning(self, log_mock, set_node_cleaning_steps_mock,
                                notify_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.vendor._initiate_cleaning(task)

        log_mock.warning.assert_called_once_with(mock.ANY, mock.ANY)
        set_node_cleaning_steps_mock.assert_called_once_with(task)
        notify_mock.assert_called_once_with(self.driver.vendor, task)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(manager_utils, 'set_node_cleaning_steps', autospec=True)
    @mock.patch.object(iscsi_deploy, 'LOG', spec=['warning'])
    def test__initiate_cleaning_exception(
            self, log_mock, set_node_cleaning_steps_mock,
            cleaning_error_handler_mock, notify_mock):
        set_node_cleaning_steps_mock.side_effect = RuntimeError()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.vendor._initiate_cleaning(task)

        log_mock.warning.assert_called_once_with(mock.ANY, mock.ANY)
        set_node_cleaning_steps_mock.assert_called_once_with(task)
        cleaning_error_handler_mock.assert_called_once_with(task, mock.ANY)
        self.assertFalse(notify_mock.called)

    @mock.patch.object(fake.FakeBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'notify_ramdisk_to_proceed',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_partition_image', autospec=True)
    def _test_pass_deploy_info_deploy(self, is_localboot, mock_deploy,
                                      mock_image_cache,
                                      notify_mock,
                                      fakeboot_prepare_instance_mock):
        # set local boot
        i_info = self.node.instance_info
        if is_localboot:
            i_info['capabilities'] = '{"boot_option": "local"}'

        i_info['deploy_key'] = 'fake-56789'
        self.node.instance_info = i_info

        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        root_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        mock_deploy.return_value = {'root uuid': root_uuid}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.vendor.pass_deploy_info(
                task, address='123456', iqn='aaa-bbb', key='fake-56789')

        self.node.refresh()
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertIn('root_uuid_or_disk_id', self.node.driver_internal_info)
        self.assertIsNone(self.node.last_error)
        mock_image_cache.assert_called_once_with()
        mock_image_cache.return_value.clean_up.assert_called_once_with()
        notify_mock.assert_called_once_with('123456')
        fakeboot_prepare_instance_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(fake.FakeBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'notify_ramdisk_to_proceed',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'InstanceImageCache', autospec=True)
    @mock.patch.object(deploy_utils, 'deploy_disk_image', autospec=True)
    def _test_pass_deploy_info_whole_disk_image(self, is_localboot,
                                                mock_deploy,
                                                mock_image_cache,
                                                notify_mock,
                                                fakeboot_prep_inst_mock):
        i_info = self.node.instance_info
        # set local boot
        if is_localboot:
            i_info['capabilities'] = '{"boot_option": "local"}'

        i_info['deploy_key'] = 'fake-56789'
        self.node.instance_info = i_info

        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        disk_id = '0x12345678'
        mock_deploy.return_value = {'disk identifier': disk_id}

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.vendor.pass_deploy_info(task, address='123456',
                                                iqn='aaa-bbb',
                                                key='fake-56789')

        self.node.refresh()
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertIsNone(self.node.last_error)
        mock_image_cache.assert_called_once_with()
        mock_image_cache.return_value.clean_up.assert_called_once_with()
        notify_mock.assert_called_once_with('123456')
        fakeboot_prep_inst_mock.assert_called_once_with(mock.ANY, task)

    def test_pass_deploy_info_deploy(self):
        self._test_pass_deploy_info_deploy(False)
        self.assertEqual(states.ACTIVE, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)

    def test_pass_deploy_info_localboot(self):
        self._test_pass_deploy_info_deploy(True)
        self.assertEqual(states.DEPLOYWAIT, self.node.provision_state)
        self.assertEqual(states.ACTIVE, self.node.target_provision_state)

    def test_pass_deploy_info_whole_disk_image(self):
        self._test_pass_deploy_info_whole_disk_image(False)
        self.assertEqual(states.ACTIVE, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)

    def test_pass_deploy_info_whole_disk_image_localboot(self):
        self._test_pass_deploy_info_whole_disk_image(True)
        self.assertEqual(states.ACTIVE, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)

    def test_pass_deploy_info_invalid(self):
        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.AVAILABLE
        self.node.target_provision_state = states.NOSTATE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidState,
                              task.driver.vendor.pass_deploy_info,
                              task, address='123456', iqn='aaa-bbb',
                              key='fake-56789', error='test ramdisk error')

        self.node.refresh()
        self.assertEqual(states.AVAILABLE, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    @mock.patch.object(iscsi_deploy.VendorPassthru, 'pass_deploy_info')
    def test_pass_deploy_info_lock_elevated(self, mock_deploy_info):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.vendor.pass_deploy_info(
                task, address='123456', iqn='aaa-bbb', key='fake-56789')

            # lock elevated w/o exception
            self.assertEqual(1, mock_deploy_info.call_count,
                             "pass_deploy_info was not called once.")

    @mock.patch.object(iscsi_deploy.VendorPassthru,
                       '_initiate_cleaning', autospec=True)
    def test_pass_deploy_info_cleaning(self, initiate_cleaning_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.CLEANWAIT
            task.driver.vendor.pass_deploy_info(
                task, address='123456', iqn='aaa-bbb', key='fake-56789')
            initiate_cleaning_mock.assert_called_once_with(
                task.driver.vendor, task)
            # Asserting if we are still on CLEANWAIT state confirms that
            # we return from pass_deploy_info method after initiating
            # cleaning.
            self.assertEqual(states.CLEANWAIT, task.node.provision_state)

    def test_vendor_routes(self):
        expected = ['heartbeat', 'pass_deploy_info',
                    'pass_bootloader_install_info']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(sorted(expected), sorted(list(vendor_routes)))

    def test_driver_routes(self):
        expected = ['lookup']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_routes = task.driver.vendor.driver_routes
            self.assertIsInstance(driver_routes, dict)
            self.assertEqual(sorted(expected), sorted(list(driver_routes)))

    @mock.patch.object(iscsi_deploy, 'validate_bootloader_install_status',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'finish_deploy', autospec=True)
    def test_pass_bootloader_install_info(self, finish_deploy_mock,
                                          validate_input_mock):
        kwargs = {'method': 'pass_deploy_info', 'address': '123456'}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.pass_bootloader_install_info(task, **kwargs)
            finish_deploy_mock.assert_called_once_with(task, '123456')
            validate_input_mock.assert_called_once_with(task, kwargs)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_netboot(self, do_agent_iscsi_deploy_mock,
                                     reboot_and_finish_deploy_mock):

        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned
        self.driver.vendor.continue_deploy(self.task)
        do_agent_iscsi_deploy_mock.assert_called_once_with(
            self.task, self.driver.vendor._client)
        reboot_and_finish_deploy_mock.assert_called_once_with(
            mock.ANY, self.task)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'configure_local_boot', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_localboot(self, do_agent_iscsi_deploy_mock,
                                       configure_local_boot_mock,
                                       reboot_and_finish_deploy_mock):

        self.node.instance_info = {
            'capabilities': {'boot_option': 'local'}}
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned

        self.driver.vendor.continue_deploy(self.task)
        do_agent_iscsi_deploy_mock.assert_called_once_with(
            self.task, self.driver.vendor._client)
        configure_local_boot_mock.assert_called_once_with(
            self.task.driver.vendor, self.task, root_uuid='some-root-uuid',
            efi_system_part_uuid=None)
        reboot_and_finish_deploy_mock.assert_called_once_with(
            self.task.driver.vendor, self.task)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       'configure_local_boot', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_localboot_uefi(self, do_agent_iscsi_deploy_mock,
                                            configure_local_boot_mock,
                                            reboot_and_finish_deploy_mock):

        self.node.instance_info = {
            'capabilities': {'boot_option': 'local'}}
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid',
                              'efi system partition uuid': 'efi-part-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned

        self.driver.vendor.continue_deploy(self.task)
        do_agent_iscsi_deploy_mock.assert_called_once_with(
            self.task, self.driver.vendor._client)
        configure_local_boot_mock.assert_called_once_with(
            self.task.driver.vendor, self.task, root_uuid='some-root-uuid',
            efi_system_part_uuid='efi-part-uuid')
        reboot_and_finish_deploy_mock.assert_called_once_with(
            self.task.driver.vendor, self.task)


# Cleanup of iscsi_deploy with pxe boot interface
class CleanUpFullFlowTestCase(db_base.DbTestCase):
    def setUp(self):
        super(CleanUpFullFlowTestCase, self).setUp()
        self.config(image_cache_size=0, group='pxe')

        # Configure node
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.port = obj_utils.create_test_port(self.context,
                                               node_id=self.node.id)

        # Configure temporary directories
        pxe_temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=pxe_temp_dir, group='pxe')
        tftp_master_dir = os.path.join(CONF.pxe.tftp_root,
                                       'tftp_master')
        self.config(tftp_master_path=tftp_master_dir, group='pxe')
        os.makedirs(tftp_master_dir)

        instance_temp_dir = tempfile.mkdtemp()
        self.config(images_path=instance_temp_dir,
                    group='pxe')
        instance_master_dir = os.path.join(CONF.pxe.images_path,
                                           'instance_master')
        self.config(instance_master_path=instance_master_dir,
                    group='pxe')
        os.makedirs(instance_master_dir)
        self.pxe_config_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
        os.makedirs(self.pxe_config_dir)

        # Populate some file names
        self.master_kernel_path = os.path.join(CONF.pxe.tftp_master_path,
                                               'kernel')
        self.master_instance_path = os.path.join(CONF.pxe.instance_master_path,
                                                 'image_uuid')
        self.node_tftp_dir = os.path.join(CONF.pxe.tftp_root,
                                          self.node.uuid)
        os.makedirs(self.node_tftp_dir)
        self.kernel_path = os.path.join(self.node_tftp_dir,
                                        'kernel')
        self.node_image_dir = iscsi_deploy._get_image_dir_path(self.node.uuid)
        os.makedirs(self.node_image_dir)
        self.image_path = iscsi_deploy._get_image_file_path(self.node.uuid)
        self.config_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        self.mac_path = pxe_utils._get_pxe_mac_path(self.port.address)

        # Create files
        self.files = [self.config_path, self.master_kernel_path,
                      self.master_instance_path]
        for fname in self.files:
            # NOTE(dtantsur): files with 0 size won't be cleaned up
            with open(fname, 'w') as fp:
                fp.write('test')

        os.link(self.config_path, self.mac_path)
        os.link(self.master_kernel_path, self.kernel_path)
        os.link(self.master_instance_path, self.image_path)
        dhcp_factory.DHCPFactory._dhcp_provider = None

    @mock.patch('ironic.common.dhcp_factory.DHCPFactory._set_dhcp_provider')
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.clean_dhcp')
    @mock.patch.object(pxe, '_get_instance_image_info', autospec=True)
    @mock.patch.object(pxe, '_get_deploy_image_info', autospec=True)
    def test_clean_up_with_master(self, mock_get_deploy_image_info,
                                  mock_get_instance_image_info,
                                  clean_dhcp_mock, set_dhcp_provider_mock):
        image_info = {'kernel': ('kernel_uuid',
                                 self.kernel_path)}
        mock_get_instance_image_info.return_value = image_info
        mock_get_deploy_image_info.return_value = {}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.deploy.clean_up(task)
            mock_get_instance_image_info.assert_called_with(task.node,
                                                            task.context)
            mock_get_deploy_image_info.assert_called_with(task.node)
            set_dhcp_provider_mock.assert_called_once_with()
            clean_dhcp_mock.assert_called_once_with(task)
        for path in ([self.kernel_path, self.image_path, self.config_path]
                     + self.files):
            self.assertFalse(os.path.exists(path),
                             '%s is not expected to exist' % path)
