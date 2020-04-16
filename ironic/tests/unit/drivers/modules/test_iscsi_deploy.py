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
import time
import types

from ironic_lib import disk_utils
from ironic_lib import utils as ironic_utils
import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import fileutils
import testtools

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules.network import flat as flat_network
from ironic.drivers.modules import pxe
from ironic.drivers.modules.storage import noop as noop_storage
from ironic.drivers import utils as driver_utils
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


class IscsiDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployPrivateMethodsTestCase, self).setUp()
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'iscsi',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.node = obj_utils.create_test_node(self.context, **n)

    def test__save_disk_layout(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 10
        info['preserve_ephemeral'] = False
        self.node.instance_info = info

        iscsi_deploy._save_disk_layout(self.node, info)
        self.node.refresh()
        for param in ('ephemeral_gb', 'swap_mb', 'root_gb'):
            self.assertEqual(
                info[param], self.node.driver_internal_info['instance'][param]
            )

    def test__get_image_dir_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path,
                                      self.node.uuid),
                         deploy_utils._get_image_dir_path(self.node.uuid))

    def test__get_image_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path,
                                      self.node.uuid,
                                      'disk'),
                         deploy_utils._get_image_file_path(self.node.uuid))


class IscsiDeployMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployMethodsTestCase, self).setUp()
        instance_info = dict(INST_INFO_DICT)
        instance_info['deploy_key'] = 'fake-56789'
        n = {
            'boot_interface': 'pxe',
            'deploy_interface': 'iscsi',
            'instance_info': instance_info,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.node = obj_utils.create_test_node(self.context, **n)

    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    def test_check_image_size(self, get_image_mb_mock):
        get_image_mb_mock.return_value = 1000
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['root_gb'] = 1
            iscsi_deploy.check_image_size(task)
            get_image_mb_mock.assert_called_once_with(
                deploy_utils._get_image_file_path(task.node.uuid))

    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    def test_check_image_size_whole_disk_image(self, get_image_mb_mock):
        get_image_mb_mock.return_value = 1025
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['root_gb'] = 1
            task.node.driver_internal_info['is_whole_disk_image'] = True
            # No error for whole disk images
            iscsi_deploy.check_image_size(task)
            self.assertFalse(get_image_mb_mock.called)

    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    def test_check_image_size_whole_disk_image_no_root(self,
                                                       get_image_mb_mock):
        get_image_mb_mock.return_value = 1025
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            del task.node.instance_info['root_gb']
            task.node.driver_internal_info['is_whole_disk_image'] = True
            # No error for whole disk images
            iscsi_deploy.check_image_size(task)
            self.assertFalse(get_image_mb_mock.called)

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
                deploy_utils._get_image_file_path(task.node.uuid))

    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test_cache_instance_images_master_path(self, mock_fetch_image):
        temp_dir = tempfile.mkdtemp()
        self.config(images_path=temp_dir, group='pxe')
        self.config(instance_master_path=os.path.join(temp_dir,
                                                      'instance_master_path'),
                    group='pxe')
        fileutils.ensure_tree(CONF.pxe.instance_master_path)

        (uuid, image_path) = deploy_utils.cache_instance_image(None, self.node)
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
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    def test_destroy_images(self, mock_cache, mock_rmtree, mock_unlink):
        self.config(images_path='/path', group='pxe')

        deploy_utils.destroy_images('uuid')

        mock_cache.return_value.clean_up.assert_called_once_with()
        mock_unlink.assert_called_once_with('/path/uuid/disk')
        mock_rmtree.assert_called_once_with('/path/uuid')

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail(
            self, deploy_mock, power_mock, mock_image_cache, mock_disk_layout,
            mock_collect_logs):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb', 'conv_flags': None}
        deploy_mock.side_effect = exception.InstanceDeployFailure(
            "test deploy error")
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            params = iscsi_deploy.get_deploy_info(task.node, **kwargs)
            # Ironic exceptions are preserved as they are
            self.assertRaisesRegex(exception.InstanceDeployFailure,
                                   '^test deploy error$',
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
            mock_collect_logs.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_unexpected_fail(
            self, deploy_mock, power_mock, mock_image_cache, mock_disk_layout,
            mock_collect_logs):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb'}
        deploy_mock.side_effect = KeyError('boom')
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            params = iscsi_deploy.get_deploy_info(task.node, **kwargs)
            self.assertRaisesRegex(exception.InstanceDeployFailure,
                                   "Deploy failed.*Error: 'boom'",
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
            mock_collect_logs.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail_no_root_uuid_or_disk_id(
            self, deploy_mock, power_mock, mock_image_cache, mock_disk_layout,
            mock_collect_logs):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb'}
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
            mock_collect_logs.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_partition_image', autospec=True)
    def test_continue_deploy_fail_empty_root_uuid(
            self, deploy_mock, power_mock, mock_image_cache,
            mock_disk_layout, mock_collect_logs):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb'}
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
            mock_collect_logs.assert_called_once_with(task.node)

    @mock.patch.object(iscsi_deploy, '_save_disk_layout', autospec=True)
    @mock.patch.object(iscsi_deploy, 'LOG', autospec=True)
    @mock.patch.object(iscsi_deploy, 'get_deploy_info', autospec=True)
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_partition_image', autospec=True)
    def test_continue_deploy(self, deploy_mock, power_mock, mock_image_cache,
                             mock_deploy_info, mock_log, mock_disk_layout):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb'}
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
    @mock.patch.object(deploy_utils, 'InstanceImageCache', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'deploy_disk_image', autospec=True)
    def test_continue_deploy_whole_disk_image(
            self, deploy_mock, power_mock, mock_image_cache, mock_deploy_info,
            mock_log):
        kwargs = {'address': '123456', 'iqn': 'aaa-bbb'}
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
        instance_info.update(extra_instance_info)
        self.node.instance_info = instance_info
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        return ret_val

    def test_get_deploy_info_boot_option_default(self):
        ret_val = self._test_get_deploy_info()
        self.assertEqual('local', ret_val['boot_option'])

    def test_get_deploy_info_netboot_specified(self):
        capabilities = {'capabilities': {'boot_option': 'netboot'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('netboot', ret_val['boot_option'])

    def test_get_deploy_info_localboot(self):
        capabilities = {'capabilities': {'boot_option': 'local'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('local', ret_val['boot_option'])

    def test_get_deploy_info_cpu_arch(self):
        ret_val = self._test_get_deploy_info()
        self.assertEqual('x86_64', ret_val['cpu_arch'])

    def test_get_deploy_info_cpu_arch_none(self):
        self.node.properties['cpu_arch'] = None
        ret_val = self._test_get_deploy_info()
        self.assertNotIn('cpu_arch', ret_val)

    def test_get_deploy_info_disk_label(self):
        capabilities = {'capabilities': {'disk_label': 'msdos'}}
        ret_val = self._test_get_deploy_info(extra_instance_info=capabilities)
        self.assertEqual('msdos', ret_val['disk_label'])

    def test_get_deploy_info_not_specified(self):
        ret_val = self._test_get_deploy_info()
        self.assertNotIn('disk_label', ret_val)

    def test_get_deploy_info_portal_port(self):
        self.config(portal_port=3266, group='iscsi')
        ret_val = self._test_get_deploy_info()
        self.assertEqual(3266, ret_val['port'])

    def test_get_deploy_info_whole_disk_image(self):
        instance_info = self.node.instance_info
        instance_info['configdrive'] = 'My configdrive'
        self.node.instance_info = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        self.assertEqual('My configdrive', ret_val['configdrive'])

    def test_get_deploy_info_whole_disk_image_no_root(self):
        instance_info = self.node.instance_info
        instance_info['configdrive'] = 'My configdrive'
        del instance_info['root_gb']
        self.node.instance_info = instance_info
        self.node.driver_internal_info['is_whole_disk_image'] = True
        kwargs = {'address': '1.1.1.1', 'iqn': 'target-iqn'}
        ret_val = iscsi_deploy.get_deploy_info(self.node, **kwargs)
        self.assertEqual('1.1.1.1', ret_val['address'])
        self.assertEqual('target-iqn', ret_val['iqn'])
        self.assertEqual('My configdrive', ret_val['configdrive'])

    @mock.patch.object(iscsi_deploy, 'continue_deploy', autospec=True)
    def test_do_agent_iscsi_deploy_okay(self, continue_deploy_mock):
        agent_client_mock = mock.MagicMock(spec_set=agent_client.AgentClient)
        agent_client_mock.start_iscsi_target.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        driver_internal_info = {'agent_url': 'http://1.2.3.4:1234'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        continue_deploy_mock.return_value = uuid_dict_returned
        expected_iqn = 'iqn.2008-10.org.openstack:%s' % self.node.uuid

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret_val = iscsi_deploy.do_agent_iscsi_deploy(
                task, agent_client_mock)
            agent_client_mock.start_iscsi_target.assert_called_once_with(
                task.node, expected_iqn, 3260, wipe_disk_metadata=True)
            continue_deploy_mock.assert_called_once_with(
                task, iqn=expected_iqn, address='1.2.3.4', conv_flags=None)
            self.assertEqual(
                'some-root-uuid',
                task.node.driver_internal_info['root_uuid_or_disk_id'])
            self.assertEqual(ret_val, uuid_dict_returned)

    @mock.patch.object(iscsi_deploy, 'continue_deploy', autospec=True)
    def test_do_agent_iscsi_deploy_preserve_ephemeral(self,
                                                      continue_deploy_mock):
        """Ensure the disk is not wiped if preserve_ephemeral is True."""
        agent_client_mock = mock.MagicMock(spec_set=agent_client.AgentClient)
        agent_client_mock.start_iscsi_target.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        driver_internal_info = {
            'agent_url': 'http://1.2.3.4:1234'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        continue_deploy_mock.return_value = uuid_dict_returned
        expected_iqn = 'iqn.2008-10.org.openstack:%s' % self.node.uuid

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.instance_info['preserve_ephemeral'] = True
            iscsi_deploy.do_agent_iscsi_deploy(
                task, agent_client_mock)
            agent_client_mock.start_iscsi_target.assert_called_once_with(
                task.node, expected_iqn, 3260, wipe_disk_metadata=False)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_do_agent_iscsi_deploy_start_iscsi_failure(
            self, mock_collect_logs):
        agent_client_mock = mock.MagicMock(spec_set=agent_client.AgentClient)
        agent_client_mock.start_iscsi_target.return_value = {
            'command_status': 'FAILED', 'command_error': 'booom'}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        expected_iqn = 'iqn.2008-10.org.openstack:%s' % self.node.uuid

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              iscsi_deploy.do_agent_iscsi_deploy,
                              task, agent_client_mock)
            agent_client_mock.start_iscsi_target.assert_called_once_with(
                task.node, expected_iqn, 3260, wipe_disk_metadata=True)
            self.node.refresh()
            self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
            self.assertEqual(states.ACTIVE, self.node.target_provision_state)
            self.assertIsNotNone(self.node.last_error)
            mock_collect_logs.assert_called_once_with(task.node)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url')
    def test_validate_good_api_url(self, mock_get_url):
        mock_get_url.return_value = 'http://127.0.0.1:1234'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            iscsi_deploy.validate(task)
        mock_get_url.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url')
    def test_validate_fail_no_api_url(self, mock_get_url):
        mock_get_url.side_effect = exception.InvalidParameterValue('Ham!')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate, task)
        mock_get_url.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url')
    def test_validate_invalid_root_device_hints(self, mock_get_url):
        mock_get_url.return_value = 'http://spam.ham/baremetal'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate, task)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_ironic_api_url')
    def test_validate_invalid_root_device_hints_iinfo(self, mock_get_url):
        mock_get_url.return_value = 'http://spam.ham/baremetal'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties['root_device'] = {'size': 42}
            task.node.instance_info['root_device'] = {'size': 'not-int'}
            self.assertRaises(exception.InvalidParameterValue,
                              iscsi_deploy.validate, task)


class ISCSIDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ISCSIDeployTestCase, self).setUp()
        # NOTE(TheJulia): We explicitly set the noop storage interface as the
        # default below for deployment tests in order to raise any change
        # in the default which could be a breaking behavior change
        # as the storage interface is explicitly an "opt-in" interface.
        self.node = obj_utils.create_test_node(
            self.context, boot_interface='pxe', deploy_interface='iscsi',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
            storage_interface='noop',
        )
        self.node.driver_internal_info['agent_url'] = 'http://1.2.3.4:1234'
        dhcp_factory.DHCPFactory._dhcp_provider = None

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            props = task.driver.deploy.get_properties()
            self.assertEqual(['deploy_forces_oob_reboot'], list(props))

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

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'validate', autospec=True)
    @mock.patch.object(deploy_utils, 'validate_capabilities', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'validate', autospec=True)
    def test_validate_storage_should_write_image_false(
            self, pxe_validate_mock,
            validate_capabilities_mock, validate_mock,
            should_write_image_mock):
        should_write_image_mock.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            task.driver.deploy.validate(task)

            pxe_validate_mock.assert_called_once_with(task.driver.boot, task)
            validate_capabilities_mock.assert_called_once_with(task.node)
            self.assertFalse(validate_mock.called)
            should_write_image_mock.assert_called_once_with(
                task.driver.storage, task)

    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_node_active(self, prepare_instance_mock,
                                 add_provisioning_net_mock,
                                 storage_driver_info_mock,
                                 storage_attach_volumes_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.ACTIVE

            task.driver.deploy.prepare(task)

            prepare_instance_mock.assert_called_once_with(
                task.driver.boot, task)
            self.assertEqual(0, add_provisioning_net_mock.call_count)
            storage_driver_info_mock.assert_called_once_with(task)
        self.assertFalse(storage_attach_volumes_mock.called)

    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    def test_prepare_node_adopting(self, prepare_instance_mock,
                                   add_provisioning_net_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.ADOPTING

            task.driver.deploy.prepare(task)

            prepare_instance_mock.assert_called_once_with(
                task.driver.boot, task)
            self.assertEqual(0, add_provisioning_net_mock.call_count)

    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    def test_prepare_node_deploying(
            self, unconfigure_tenant_net_mock, add_provisioning_net_mock,
            mock_prepare_ramdisk, mock_agent_options,
            storage_driver_info_mock, storage_attach_volumes_mock):
        mock_agent_options.return_value = {'c': 'd'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING

            task.driver.deploy.prepare(task)

            mock_agent_options.assert_called_once_with(task.node)
            mock_prepare_ramdisk.assert_called_once_with(
                task.driver.boot, task, {'c': 'd'})
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_driver_info_mock.assert_called_once_with(task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    def test_prepare_node_deploying_storage_should_write_false(
            self, unconfigure_tenant_net_mock, add_provisioning_net_mock,
            mock_prepare_ramdisk, mock_agent_options,
            storage_driver_info_mock, storage_attach_volumes_mock,
            storage_should_write_mock):
        storage_should_write_mock.return_value = False
        mock_agent_options.return_value = {'c': 'd'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING

            task.driver.deploy.prepare(task)

            self.assertFalse(mock_agent_options.called)
            self.assertFalse(mock_prepare_ramdisk.called)
            self.assertFalse(add_provisioning_net_mock.called)
            self.assertFalse(unconfigure_tenant_net_mock.called)
            storage_driver_info_mock.assert_called_once_with(task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            self.assertEqual(2, storage_should_write_mock.call_count)

    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info')
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk')
    @mock.patch.object(deploy_utils, 'build_agent_options')
    @mock.patch.object(deploy_utils, 'build_instance_info_for_deploy')
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'validate',
                       spec_set=True, autospec=True)
    def test_prepare_fast_track(
            self, validate_net_mock,
            unconfigure_tenant_net_mock, add_provisioning_net_mock,
            build_instance_info_mock, build_options_mock,
            pxe_prepare_ramdisk_mock, storage_driver_info_mock,
            storage_attach_volumes_mock, is_fast_track_mock):
        # TODO(TheJulia): We should revisit this test. Smartnic
        # support didn't wire in tightly on testing for power in
        # these tests, and largely fast_track impacts power operations.
        node = self.node
        node.network_interface = 'flat'
        node.save()
        is_fast_track_mock.return_value = True
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYING
            build_options_mock.return_value = {'a': 'b'}
            task.driver.deploy.prepare(task)
            storage_driver_info_mock.assert_called_once_with(task)
            # NOTE: Validate is the primary difference between agent/iscsi
            self.assertFalse(validate_net_mock.called)
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            self.assertTrue(storage_attach_volumes_mock.called)
            self.assertFalse(build_instance_info_mock.called)
            # TODO(TheJulia): We should likely consider executing the
            # next two methods at some point in order to facilitate
            # continuity. While not explicitly required for this feature
            # to work, reboots as part of deployment would need the ramdisk
            # present and ready.
            self.assertFalse(build_options_mock.called)
            self.assertFalse(pxe_prepare_ramdisk_mock.called)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(deploy_utils, 'cache_instance_image', autospec=True)
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
    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(deploy_utils, 'cache_instance_image', autospec=True)
    def test_deploy_with_deployment_reboot(self, mock_cache_instance_image,
                                           mock_check_image_size,
                                           mock_node_power_action):
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['deployment_reboot'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            state = task.driver.deploy.deploy(task)
            self.assertEqual(state, states.DEPLOYWAIT)
            mock_cache_instance_image.assert_called_once_with(
                self.context, task.node)
            mock_check_image_size.assert_called_once_with(task)
            self.assertFalse(mock_node_power_action.called)
            self.assertNotIn(
                'deployment_reboot', task.node.driver_internal_info)

    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'configure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot,
                       'prepare_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(deploy_utils, 'cache_instance_image', autospec=True)
    def test_deploy_storage_check_write_image_false(self,
                                                    mock_cache_instance_image,
                                                    mock_check_image_size,
                                                    mock_node_power_action,
                                                    mock_prepare_instance,
                                                    mock_remove_network,
                                                    mock_tenant_network,
                                                    mock_write):
        mock_write.return_value = False
        self.node.provision_state = states.DEPLOYING
        self.node.deploy_step = {
            'step': 'deploy', 'priority': 50, 'interface': 'deploy'}
        self.node.save()
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            ret = task.driver.deploy.deploy(task)
            self.assertIsNone(ret)
            self.assertFalse(mock_cache_instance_image.called)
            self.assertFalse(mock_check_image_size.called)
            mock_remove_network.assert_called_once_with(mock.ANY, task)
            mock_tenant_network.assert_called_once_with(mock.ANY, task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)
            self.assertEqual(2, mock_node_power_action.call_count)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)

    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(deploy_utils, 'cache_instance_image', autospec=True)
    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'continue_deploy',
                       autospec=True)
    @mock.patch('ironic.conductor.utils.is_fast_track', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def test_deploy_fast_track(self, power_mock, mock_pxe_instance,
                               mock_is_fast_track, continue_deploy_mock,
                               cache_image_mock, check_image_size_mock):
        mock_is_fast_track.return_value = True
        self.node.target_provision_state = states.ACTIVE
        self.node.provision_state = states.DEPLOYING
        i_info = self.node.driver_internal_info
        i_info['agent_url'] = 'http://1.2.3.4:1234'
        self.node.driver_internal_info = i_info
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.driver.deploy.deploy(task)
            self.assertFalse(power_mock.called)
            self.assertFalse(mock_pxe_instance.called)
            task.node.refresh()
            self.assertEqual(states.DEPLOYWAIT, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)
            cache_image_mock.assert_called_with(mock.ANY, task.node)
            check_image_size_mock.assert_called_with(task)
            continue_deploy_mock.assert_called_with(mock.ANY, task)

    @mock.patch.object(noop_storage.NoopStorage, 'detach_volumes',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_tear_down(self, node_power_action_mock,
                       unconfigure_tenant_nets_mock,
                       remove_provisioning_net_mock,
                       storage_detach_volumes_mock):
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            state = task.driver.deploy.tear_down(task)
            self.assertEqual(state, states.DELETED)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            unconfigure_tenant_nets_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            remove_provisioning_net_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            storage_detach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
        # Verify no volumes exist for new task instances.
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            self.assertEqual(0, len(task.volume_targets))

    @mock.patch('ironic.common.dhcp_factory.DHCPFactory._set_dhcp_provider')
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.clean_dhcp')
    @mock.patch.object(pxe.PXEBoot, 'clean_up_instance', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(deploy_utils, 'destroy_images', autospec=True)
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

    @mock.patch.object(agent_base, 'get_steps', autospec=True)
    def test_get_clean_steps(self, mock_get_clean_steps):
        # Test getting clean steps
        self.config(group='deploy', erase_devices_priority=10)
        self.config(group='deploy', erase_devices_metadata_priority=5)
        mock_steps = [{'priority': 10, 'interface': 'deploy',
                       'step': 'erase_devices'}]
        self.node.driver_internal_info = {'agent_url': 'foo'}
        self.node.save()
        mock_get_clean_steps.return_value = mock_steps
        with task_manager.acquire(self.context, self.node.uuid) as task:
            steps = task.driver.deploy.get_clean_steps(task)
            mock_get_clean_steps.assert_called_once_with(
                task, 'clean', interface='deploy',
                override_priorities={
                    'erase_devices': 10,
                    'erase_devices_metadata': 5})
        self.assertEqual(mock_steps, steps)

    @mock.patch.object(agent_base, 'execute_step', autospec=True)
    def test_execute_clean_step(self, agent_execute_clean_step_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.execute_clean_step(
                task, {'some-step': 'step-info'})
            agent_execute_clean_step_mock.assert_called_once_with(
                task, {'some-step': 'step-info'}, 'clean')

    @mock.patch.object(agent_base.AgentDeployMixin,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_netboot(self, do_agent_iscsi_deploy_mock,
                                     reboot_and_finish_deploy_mock):

        self.node.instance_info = {
            'capabilities': {'boot_option': 'netboot'}}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            with mock.patch.object(
                    task.driver.boot, 'prepare_instance') as m_prep_instance:
                task.driver.deploy.continue_deploy(task)
                do_agent_iscsi_deploy_mock.assert_called_once_with(
                    task, task.driver.deploy._client)
                reboot_and_finish_deploy_mock.assert_called_once_with(
                    mock.ANY, task)
                m_prep_instance.assert_called_once_with(task)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_localboot(self, do_agent_iscsi_deploy_mock,
                                       configure_local_boot_mock,
                                       reboot_and_finish_deploy_mock,
                                       set_boot_device_mock):

        self.node.instance_info = {
            'capabilities': {'boot_option': 'local'}}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.continue_deploy(task)
            do_agent_iscsi_deploy_mock.assert_called_once_with(
                task, task.driver.deploy._client)
            configure_local_boot_mock.assert_called_once_with(
                task.driver.deploy, task, root_uuid='some-root-uuid',
                efi_system_part_uuid=None, prep_boot_part_uuid=None)
            reboot_and_finish_deploy_mock.assert_called_once_with(
                task.driver.deploy, task)
            set_boot_device_mock.assert_called_once_with(
                mock.ANY, task, device=boot_devices.DISK, persistent=True)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'reboot_and_finish_deploy', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    @mock.patch.object(iscsi_deploy, 'do_agent_iscsi_deploy', autospec=True)
    def test_continue_deploy_localboot_uefi(self, do_agent_iscsi_deploy_mock,
                                            configure_local_boot_mock,
                                            reboot_and_finish_deploy_mock,
                                            set_boot_device_mock):

        self.node.instance_info = {
            'capabilities': {'boot_option': 'local'}}
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        uuid_dict_returned = {'root uuid': 'some-root-uuid',
                              'efi system partition uuid': 'efi-part-uuid'}
        do_agent_iscsi_deploy_mock.return_value = uuid_dict_returned

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.continue_deploy(task)
            do_agent_iscsi_deploy_mock.assert_called_once_with(
                task, task.driver.deploy._client)
            configure_local_boot_mock.assert_called_once_with(
                task.driver.deploy, task, root_uuid='some-root-uuid',
                efi_system_part_uuid='efi-part-uuid', prep_boot_part_uuid=None)
            reboot_and_finish_deploy_mock.assert_called_once_with(
                task.driver.deploy, task)
            set_boot_device_mock.assert_called_once_with(
                mock.ANY, task, device=boot_devices.DISK, persistent=True)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'attach_volumes',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'populate_storage_driver_internal_info',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch.object(flat_network.FlatNetwork, 'add_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    def test_prepare_node_deploying_with_smartnic_port(
            self, unconfigure_tenant_net_mock, add_provisioning_net_mock,
            mock_prepare_ramdisk, mock_agent_options,
            storage_driver_info_mock, storage_attach_volumes_mock,
            power_on_node_if_needed_mock, restore_power_state_mock):
        mock_agent_options.return_value = {'c': 'd'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.provision_state = states.DEPLOYING
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            task.driver.deploy.prepare(task)
            mock_agent_options.assert_called_once_with(task.node)
            mock_prepare_ramdisk.assert_called_once_with(
                task.driver.boot, task, {'c': 'd'})
            add_provisioning_net_mock.assert_called_once_with(mock.ANY, task)
            unconfigure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            storage_driver_info_mock.assert_called_once_with(task)
            storage_attach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'detach_volumes',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'unconfigure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_tear_down_with_smartnic_port(
            self, node_power_action_mock, unconfigure_tenant_nets_mock,
            remove_provisioning_net_mock, storage_detach_volumes_mock,
            power_on_node_if_needed_mock, restore_power_state_mock):
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            state = task.driver.deploy.tear_down(task)
            self.assertEqual(state, states.DELETED)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_OFF)
            unconfigure_tenant_nets_mock.assert_called_once_with(
                mock.ANY, task)
            remove_provisioning_net_mock.assert_called_once_with(
                mock.ANY, task)
            storage_detach_volumes_mock.assert_called_once_with(
                task.driver.storage, task)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)
        # Verify no volumes exist for new task instances.
        with task_manager.acquire(self.context,
                                  self.node.uuid, shared=False) as task:
            self.assertEqual(0, len(task.volume_targets))

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(noop_storage.NoopStorage, 'should_write_image',
                       autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'configure_tenant_networks',
                       spec_set=True, autospec=True)
    @mock.patch.object(flat_network.FlatNetwork,
                       'remove_provisioning_network',
                       spec_set=True, autospec=True)
    @mock.patch.object(pxe.PXEBoot,
                       'prepare_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_image_size', autospec=True)
    @mock.patch.object(deploy_utils, 'cache_instance_image', autospec=True)
    def test_deploy_storage_check_write_image_false_with_smartnic_port(
            self, mock_cache_instance_image, mock_check_image_size,
            mock_node_power_action, mock_prepare_instance,
            mock_remove_network, mock_tenant_network, mock_write,
            power_on_node_if_needed_mock, restore_power_state_mock):
        mock_write.return_value = False
        self.node.provision_state = states.DEPLOYING
        self.node.deploy_step = {
            'step': 'deploy', 'priority': 50, 'interface': 'deploy'}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            ret = task.driver.deploy.deploy(task)
            self.assertIsNone(ret)
            self.assertFalse(mock_cache_instance_image.called)
            self.assertFalse(mock_check_image_size.called)
            mock_remove_network.assert_called_once_with(mock.ANY, task)
            mock_tenant_network.assert_called_once_with(mock.ANY, task)
            mock_prepare_instance.assert_called_once_with(mock.ANY, task)
            self.assertEqual(2, mock_node_power_action.call_count)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)


# Cleanup of iscsi_deploy with pxe boot interface
class CleanUpFullFlowTestCase(db_base.DbTestCase):
    def setUp(self):
        super(CleanUpFullFlowTestCase, self).setUp()
        self.config(image_cache_size=0, group='pxe')

        # Configure node
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        self.node = obj_utils.create_test_node(
            self.context, boot_interface='pxe', deploy_interface='iscsi',
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
        self.node_image_dir = deploy_utils._get_image_dir_path(self.node.uuid)
        os.makedirs(self.node_image_dir)
        self.image_path = deploy_utils._get_image_file_path(self.node.uuid)
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
    @mock.patch.object(pxe_utils, 'get_instance_image_info', autospec=True)
    @mock.patch.object(pxe_utils, 'get_image_info', autospec=True)
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
            mock_get_instance_image_info.assert_called_with(task,
                                                            ipxe_enabled=False)
            mock_get_deploy_image_info.assert_called_with(
                task.node, mode='deploy', ipxe_enabled=False)
            set_dhcp_provider_mock.assert_called_once_with()
            clean_dhcp_mock.assert_called_once_with(task)
        for path in ([self.kernel_path, self.image_path, self.config_path]
                     + self.files):
            self.assertFalse(os.path.exists(path),
                             '%s is not expected to exist' % path)


@mock.patch.object(time, 'sleep', lambda seconds: None)
class PhysicalWorkTestCase(tests_base.TestCase):

    def setUp(self):
        super(PhysicalWorkTestCase, self).setUp()
        self.address = '127.0.0.1'
        self.port = 3306
        self.iqn = 'iqn.xyz'
        self.lun = 1
        self.image_path = '/tmp/xyz/image'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        self.dev = ("/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-%s"
                    % (self.address, self.port, self.iqn, self.lun))

    def _mock_calls(self, name_list, module):
        patch_list = [mock.patch.object(module, name,
                                        spec_set=types.FunctionType)
                      for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock(spec=[])
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)
        return parent_mock

    @mock.patch.object(disk_utils, 'work_on_disk', autospec=True)
    @mock.patch.object(disk_utils, 'is_block_device', autospec=True)
    @mock.patch.object(disk_utils, 'get_image_mb', autospec=True)
    @mock.patch.object(iscsi_deploy, 'logout_iscsi', autospec=True)
    @mock.patch.object(iscsi_deploy, 'login_iscsi', autospec=True)
    @mock.patch.object(iscsi_deploy, 'discovery', autospec=True)
    @mock.patch.object(iscsi_deploy, 'delete_iscsi', autospec=True)
    def _test_deploy_partition_image(self,
                                     mock_delete_iscsi,
                                     mock_discovery,
                                     mock_login_iscsi,
                                     mock_logout_iscsi,
                                     mock_get_image_mb,
                                     mock_is_block_device,
                                     mock_work_on_disk, **kwargs):
        # Below are the only values we allow callers to modify for testing.
        # Check that values other than this aren't passed in.
        deploy_args = {
            'boot_mode': None,
            'boot_option': None,
            'configdrive': None,
            'cpu_arch': None,
            'disk_label': None,
            'ephemeral_format': None,
            'ephemeral_mb': None,
            'image_mb': 1,
            'preserve_ephemeral': False,
            'root_mb': 128,
            'swap_mb': 64
        }
        disallowed_values = set(kwargs) - set(deploy_args)
        if disallowed_values:
            raise ValueError("Only the following kwargs are allowed in "
                             "_test_deploy_partition_image: %(allowed)s. "
                             "Disallowed values: %(disallowed)s."
                             % {"allowed": ", ".join(deploy_args),
                                "disallowed": ", ".join(disallowed_values)})
        deploy_args.update(kwargs)

        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        mock_is_block_device.return_value = True
        mock_get_image_mb.return_value = deploy_args['image_mb']
        mock_work_on_disk.return_value = {
            'root uuid': root_uuid,
            'efi system partition uuid': None
        }

        deploy_kwargs = {
            'boot_mode': deploy_args['boot_mode'],
            'boot_option': deploy_args['boot_option'],
            'configdrive': deploy_args['configdrive'],
            'disk_label': deploy_args['disk_label'],
            'cpu_arch': deploy_args['cpu_arch'] or '',
            'preserve_ephemeral': deploy_args['preserve_ephemeral']
        }
        iscsi_deploy.deploy_partition_image(
            self.address, self.port, self.iqn, self.lun, self.image_path,
            deploy_args['root_mb'],
            deploy_args['swap_mb'], deploy_args['ephemeral_mb'],
            deploy_args['ephemeral_format'], self.node_uuid, **deploy_kwargs)

        mock_discovery.assert_called_once_with(self.address, self.port)
        mock_login_iscsi.assert_called_once_with(self.address, self.port,
                                                 self.iqn)
        mock_logout_iscsi.assert_called_once_with(self.address, self.port,
                                                  self.iqn)
        mock_delete_iscsi.assert_called_once_with(self.address, self.port,
                                                  self.iqn)
        mock_get_image_mb.assert_called_once_with(self.image_path)
        mock_is_block_device.assert_called_once_with(self.dev)

        work_on_disk_kwargs = {
            'preserve_ephemeral': deploy_args['preserve_ephemeral'],
            'configdrive': deploy_args['configdrive'],
            # boot_option defaults to 'netboot' if
            # not set
            'boot_option': deploy_args['boot_option'] or 'local',
            'boot_mode': deploy_args['boot_mode'],
            'disk_label': deploy_args['disk_label'],
            'cpu_arch': deploy_args['cpu_arch'] or ''
        }
        mock_work_on_disk.assert_called_once_with(
            self.dev, deploy_args['root_mb'], deploy_args['swap_mb'],
            deploy_args['ephemeral_mb'], deploy_args['ephemeral_format'],
            self.image_path, self.node_uuid, **work_on_disk_kwargs)

    def test_deploy_partition_image_without_boot_option(self):
        self._test_deploy_partition_image()

    def test_deploy_partition_image_netboot(self):
        self._test_deploy_partition_image(boot_option="netboot")

    def test_deploy_partition_image_localboot(self):
        self._test_deploy_partition_image(boot_option="local")

    def test_deploy_partition_image_wo_boot_option_and_wo_boot_mode(self):
        self._test_deploy_partition_image()

    def test_deploy_partition_image_netboot_bios(self):
        self._test_deploy_partition_image(boot_option="netboot",
                                          boot_mode="bios")

    def test_deploy_partition_image_localboot_bios(self):
        self._test_deploy_partition_image(boot_option="local",
                                          boot_mode="bios")

    def test_deploy_partition_image_netboot_uefi(self):
        self._test_deploy_partition_image(boot_option="netboot",
                                          boot_mode="uefi")

    def test_deploy_partition_image_disk_label(self):
        self._test_deploy_partition_image(disk_label='gpt')

    def test_deploy_partition_image_image_exceeds_root_partition(self):
        self.assertRaises(exception.InstanceDeployFailure,
                          self._test_deploy_partition_image, image_mb=129,
                          root_mb=128)

    def test_deploy_partition_image_localboot_uefi(self):
        self._test_deploy_partition_image(boot_option="local",
                                          boot_mode="uefi")

    def test_deploy_partition_image_without_swap(self):
        self._test_deploy_partition_image(swap_mb=0)

    def test_deploy_partition_image_with_ephemeral(self):
        self._test_deploy_partition_image(ephemeral_format='exttest',
                                          ephemeral_mb=256)

    def test_deploy_partition_image_preserve_ephemeral(self):
        self._test_deploy_partition_image(ephemeral_format='exttest',
                                          ephemeral_mb=256,
                                          preserve_ephemeral=True)

    def test_deploy_partition_image_with_configdrive(self):
        self._test_deploy_partition_image(configdrive='http://1.2.3.4/cd')

    def test_deploy_partition_image_with_cpu_arch(self):
        self._test_deploy_partition_image(cpu_arch='generic')

    @mock.patch.object(disk_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image(self, mock_gdi, create_config_drive_mock):
        """Check loosely all functions are called with right args."""

        name_list = ['discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi']
        disk_utils_name_list = ['is_block_device', 'populate_image']

        iscsi_mock = self._mock_calls(name_list, iscsi_deploy)

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        utils_calls_expected = [mock.call.discovery(self.address, self.port),
                                mock.call.login_iscsi(self.address, self.port,
                                                      self.iqn),
                                mock.call.logout_iscsi(self.address, self.port,
                                                       self.iqn),
                                mock.call.delete_iscsi(self.address, self.port,
                                                       self.iqn)]
        disk_utils_calls_expected = [mock.call.is_block_device(self.dev),
                                     mock.call.populate_image(self.image_path,
                                                              self.dev,
                                                              conv_flags=None)]
        uuid_dict_returned = iscsi_deploy.deploy_disk_image(
            self.address, self.port, self.iqn, self.lun, self.image_path,
            self.node_uuid)

        self.assertEqual(utils_calls_expected, iscsi_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertFalse(create_config_drive_mock.called)
        self.assertEqual('0x12345678', uuid_dict_returned['disk identifier'])

    @mock.patch.object(disk_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image_with_config_drive(self, mock_gdi,
                                                       create_partition_mock):
        """Check loosely all functions are called with right args."""
        config_url = 'http://1.2.3.4/cd'

        iscsi_list = ['discovery', 'login_iscsi', 'logout_iscsi',
                      'delete_iscsi']

        disk_utils_list = ['is_block_device', 'populate_image']
        iscsi_mock = self._mock_calls(iscsi_list, iscsi_deploy)
        disk_utils_mock = self._mock_calls(disk_utils_list, disk_utils)
        disk_utils_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        utils_calls_expected = [mock.call.discovery(self.address, self.port),
                                mock.call.login_iscsi(self.address, self.port,
                                                      self.iqn),
                                mock.call.logout_iscsi(self.address, self.port,
                                                       self.iqn),
                                mock.call.delete_iscsi(self.address, self.port,
                                                       self.iqn)]

        disk_utils_calls_expected = [mock.call.is_block_device(self.dev),
                                     mock.call.populate_image(self.image_path,
                                                              self.dev,
                                                              conv_flags=None)]

        uuid_dict_returned = iscsi_deploy.deploy_disk_image(
            self.address, self.port, self.iqn, self.lun, self.image_path,
            self.node_uuid, configdrive=config_url)

        iscsi_mock.assert_has_calls(utils_calls_expected)
        disk_utils_mock.assert_has_calls(disk_utils_calls_expected)
        create_partition_mock.assert_called_once_with(self.node_uuid, self.dev,
                                                      config_url)
        self.assertEqual('0x12345678', uuid_dict_returned['disk identifier'])

    @mock.patch.object(disk_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image_sparse(self, mock_gdi,
                                            create_config_drive_mock):
        """Check loosely all functions are called with right args."""
        iscsi_name_list = ['discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']
        disk_utils_name_list = ['is_block_device', 'populate_image']

        iscsi_mock = self._mock_calls(iscsi_name_list, iscsi_deploy)

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        utils_calls_expected = [mock.call.discovery(self.address, self.port),
                                mock.call.login_iscsi(self.address, self.port,
                                                      self.iqn),
                                mock.call.logout_iscsi(self.address, self.port,
                                                       self.iqn),
                                mock.call.delete_iscsi(self.address, self.port,
                                                       self.iqn)]
        disk_utils_calls_expected = [mock.call.is_block_device(self.dev),
                                     mock.call.populate_image(
                                         self.image_path, self.dev,
                                         conv_flags='sparse')]

        uuid_dict_returned = iscsi_deploy.deploy_disk_image(
            self.address, self.port, self.iqn, self.lun, self.image_path,
            self.node_uuid, configdrive=None, conv_flags='sparse')

        self.assertEqual(utils_calls_expected, iscsi_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertFalse(create_config_drive_mock.called)
        self.assertEqual('0x12345678', uuid_dict_returned['disk identifier'])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_verify_iscsi_connection_raises(self, mock_exec):
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.abc', '']
        self.assertRaises(exception.InstanceDeployFailure,
                          iscsi_deploy.verify_iscsi_connection, iqn)
        self.assertEqual(3, mock_exec.call_count)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_verify_iscsi_connection_override_attempts(self, mock_exec):
        utils.CONF.set_override('verify_attempts', 2, group='iscsi')
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.abc', '']
        self.assertRaises(exception.InstanceDeployFailure,
                          iscsi_deploy.verify_iscsi_connection, iqn)
        self.assertEqual(2, mock_exec.call_count)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_check_file_system_for_iscsi_device_raises(self, mock_os):
        iqn = 'iqn.xyz'
        ip = "127.0.0.1"
        port = "22"
        mock_os.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          iscsi_deploy.check_file_system_for_iscsi_device,
                          ip, port, iqn)
        self.assertEqual(3, mock_os.call_count)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_check_file_system_for_iscsi_device(self, mock_os):
        iqn = 'iqn.xyz'
        ip = "127.0.0.1"
        port = "22"
        check_dir = "/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-1" % (ip,
                                                                   port,
                                                                   iqn)

        mock_os.return_value = True
        iscsi_deploy.check_file_system_for_iscsi_device(ip, port, iqn)
        mock_os.assert_called_once_with(check_dir)

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_verify_iscsi_connection(self, mock_exec):
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        iscsi_deploy.verify_iscsi_connection(iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-S',
            run_as_root=True,
            check_exit_code=[0])

    @mock.patch.object(utils, 'execute', autospec=True)
    def test_force_iscsi_lun_update(self, mock_exec):
        iqn = 'iqn.xyz'
        iscsi_deploy.force_iscsi_lun_update(iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-T', iqn,
            '-R',
            run_as_root=True,
            check_exit_code=[0])

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(iscsi_deploy, 'verify_iscsi_connection', autospec=True)
    @mock.patch.object(iscsi_deploy, 'force_iscsi_lun_update', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_file_system_for_iscsi_device',
                       autospec=True)
    def test_login_iscsi_calls_verify_and_update(self,
                                                 mock_check_dev,
                                                 mock_update,
                                                 mock_verify,
                                                 mock_exec):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        iscsi_deploy.login_iscsi(address, port, iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-p', '%s:%s' % (address, port),
            '-T', iqn,
            '--login',
            run_as_root=True,
            check_exit_code=[0],
            attempts=5,
            delay_on_retry=True)

        mock_verify.assert_called_once_with(iqn)
        mock_update.assert_called_once_with(iqn)
        mock_check_dev.assert_called_once_with(address, port, iqn)

    @mock.patch.object(iscsi_deploy, 'LOG', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(iscsi_deploy, 'verify_iscsi_connection', autospec=True)
    @mock.patch.object(iscsi_deploy, 'force_iscsi_lun_update', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_file_system_for_iscsi_device',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'delete_iscsi', autospec=True)
    @mock.patch.object(iscsi_deploy, 'logout_iscsi', autospec=True)
    def test_login_iscsi_calls_raises(
            self, mock_loiscsi, mock_discsi, mock_check_dev, mock_update,
            mock_verify, mock_exec, mock_log):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        mock_check_dev.side_effect = exception.InstanceDeployFailure('boom')
        self.assertRaises(exception.InstanceDeployFailure,
                          iscsi_deploy.login_iscsi,
                          address, port, iqn)
        mock_verify.assert_called_once_with(iqn)
        mock_update.assert_called_once_with(iqn)
        mock_loiscsi.assert_called_once_with(address, port, iqn)
        mock_discsi.assert_called_once_with(address, port, iqn)
        self.assertIsInstance(mock_log.error.call_args[0][1],
                              exception.InstanceDeployFailure)

    @mock.patch.object(iscsi_deploy, 'LOG', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(iscsi_deploy, 'verify_iscsi_connection', autospec=True)
    @mock.patch.object(iscsi_deploy, 'force_iscsi_lun_update', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_file_system_for_iscsi_device',
                       autospec=True)
    @mock.patch.object(iscsi_deploy, 'delete_iscsi', autospec=True)
    @mock.patch.object(iscsi_deploy, 'logout_iscsi', autospec=True)
    def test_login_iscsi_calls_raises_during_cleanup(
            self, mock_loiscsi, mock_discsi, mock_check_dev, mock_update,
            mock_verify, mock_exec, mock_log):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        mock_check_dev.side_effect = exception.InstanceDeployFailure('boom')
        mock_discsi.side_effect = processutils.ProcessExecutionError('boom')
        self.assertRaises(exception.InstanceDeployFailure,
                          iscsi_deploy.login_iscsi,
                          address, port, iqn)
        mock_verify.assert_called_once_with(iqn)
        mock_update.assert_called_once_with(iqn)
        mock_loiscsi.assert_called_once_with(address, port, iqn)
        mock_discsi.assert_called_once_with(address, port, iqn)
        self.assertIsInstance(mock_log.error.call_args[0][1],
                              exception.InstanceDeployFailure)
        self.assertIsInstance(mock_log.warning.call_args[0][1],
                              processutils.ProcessExecutionError)

    @mock.patch.object(disk_utils, 'is_block_device', lambda d: True)
    def test_always_logout_and_delete_iscsi(self):
        """Check if logout_iscsi() and delete_iscsi() are called.

        Make sure that logout_iscsi() and delete_iscsi() are called once
        login_iscsi() is invoked.

        """
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        ephemeral_format = 'exttest'
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        class TestException(Exception):
            pass

        iscsi_name_list = ['discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['get_image_mb', 'work_on_disk']

        iscsi_mock = self._mock_calls(iscsi_name_list, iscsi_deploy)

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.work_on_disk.side_effect = TestException
        utils_calls_expected = [mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.work_on_disk(
                                         self.dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         ephemeral_format, image_path,
                                         node_uuid, configdrive=None,
                                         preserve_ephemeral=False,
                                         boot_option="local",
                                         boot_mode="bios",
                                         disk_label=None,
                                         cpu_arch="")]

        self.assertRaises(TestException, iscsi_deploy.deploy_partition_image,
                          address, port, iqn, lun, image_path,
                          root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                          node_uuid)

        self.assertEqual(utils_calls_expected, iscsi_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)

    @mock.patch.object(utils, 'execute', autospec=True)
    @mock.patch.object(iscsi_deploy, 'verify_iscsi_connection', autospec=True)
    @mock.patch.object(iscsi_deploy, 'force_iscsi_lun_update', autospec=True)
    @mock.patch.object(iscsi_deploy, 'check_file_system_for_iscsi_device',
                       autospec=True)
    def test_ipv6_address_wrapped(self,
                                  mock_check_dev,
                                  mock_update,
                                  mock_verify,
                                  mock_exec):
        address = '2001:DB8::1111'
        port = 3306
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        iscsi_deploy.login_iscsi(address, port, iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-p', '[%s]:%s' % (address, port),
            '-T', iqn,
            '--login',
            run_as_root=True,
            check_exit_code=[0],
            attempts=5,
            delay_on_retry=True)


@mock.patch.object(disk_utils, 'is_block_device', autospec=True)
@mock.patch.object(iscsi_deploy, 'login_iscsi', lambda *_: None)
@mock.patch.object(iscsi_deploy, 'discovery', lambda *_: None)
@mock.patch.object(iscsi_deploy, 'logout_iscsi', lambda *_: None)
@mock.patch.object(iscsi_deploy, 'delete_iscsi', lambda *_: None)
class ISCSISetupAndHandleErrorsTestCase(tests_base.TestCase):

    def test_no_parent_device(self, mock_ibd):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        mock_ibd.return_value = False
        expected_dev = ("/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-%s"
                        % (address, port, iqn, lun))
        with testtools.ExpectedException(exception.InstanceDeployFailure):
            with iscsi_deploy._iscsi_setup_and_handle_errors(
                    address, port, iqn, lun) as dev:
                self.assertEqual(expected_dev, dev)

        mock_ibd.assert_called_once_with(expected_dev)

    def test_parent_device_yield(self, mock_ibd):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        expected_dev = ("/dev/disk/by-path/ip-%s:%s-iscsi-%s-lun-%s"
                        % (address, port, iqn, lun))
        mock_ibd.return_value = True
        with iscsi_deploy._iscsi_setup_and_handle_errors(
                address, port, iqn, lun) as dev:
            self.assertEqual(expected_dev, dev)

        mock_ibd.assert_called_once_with(expected_dev)
