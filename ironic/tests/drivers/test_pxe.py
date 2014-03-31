# coding=utf-8

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

import fixtures
import mock
import os
import tempfile
import threading
import time

from oslo.config import cfg

from ironic.common import exception
from ironic.common.glance_service import base_image_service
from ironic.common.glance_service import service_utils
from ironic.common import images
from ironic.common import keystone
from ironic.common import neutron
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.db import api as dbapi
from ironic.drivers.modules import pxe
from ironic.openstack.common import context
from ironic.openstack.common import fileutils
from ironic.openstack.common import jsonutils as json
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils


CONF = cfg.CONF

INFO_DICT = db_utils.get_test_pxe_info()


class PXEValidateParametersTestCase(base.TestCase):

    def setUp(self):
        super(PXEValidateParametersTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()

    def _create_test_node(self, **kwargs):
        n = db_utils.get_test_node(**kwargs)
        return self.dbapi.create_node(n)

    def test__parse_driver_info_good(self):
        # make sure we get back the expected things
        node = self._create_test_node(
                    driver='fake_pxe',
                    driver_info=INFO_DICT)
        info = pxe._parse_driver_info(node)
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('deploy_kernel'))
        self.assertIsNotNone(info.get('deploy_ramdisk'))
        self.assertIsNotNone(info.get('root_gb'))
        self.assertEqual(0, info.get('ephemeral_gb'))

    def test__parse_driver_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['pxe_image_source']
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_missing_deploy_kernel(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['pxe_deploy_kernel']
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_missing_deploy_ramdisk(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['pxe_deploy_ramdisk']
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['pxe_root_gb']
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_invalid_root_gb(self):
        info = dict(INFO_DICT)
        info['pxe_root_gb'] = 'foobar'
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_valid_ephemeral_gb(self):
        ephemeral_gb = 10
        info = dict(INFO_DICT)
        info['pxe_ephemeral_gb'] = ephemeral_gb
        info['pxe_ephemeral_format'] = 'exttest'
        node = self._create_test_node(driver_info=info)
        data = pxe._parse_driver_info(node)
        self.assertEqual(ephemeral_gb, data.get('ephemeral_gb'))

    def test__parse_driver_info_invalid_ephemeral_gb(self):
        info = dict(INFO_DICT)
        info['pxe_ephemeral_gb'] = 'foobar'
        info['pxe_ephemeral_format'] = 'exttest'
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_valid_ephemeral_missing_format(self):
        ephemeral_gb = 10
        info = dict(INFO_DICT)
        info['pxe_ephemeral_gb'] = ephemeral_gb
        info['pxe_ephemeral_format'] = None
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_valid_preserve_ephemeral_true(self):
        info = dict(INFO_DICT)
        for _id, opt in enumerate(['true', 'TRUE', 'True', 't',
                                   'on', 'yes', 'y', '1']):
            info['pxe_preserve_ephemeral'] = opt
            node = self._create_test_node(id=_id, uuid=utils.generate_uuid(),
                                          driver_info=info)
            data = pxe._parse_driver_info(node)
            self.assertTrue(data.get('preserve_ephemeral'))

    def test__parse_driver_info_valid_preserve_ephemeral_false(self):
        info = dict(INFO_DICT)
        for _id, opt in enumerate(['false', 'FALSE', 'False', 'f',
                                   'off', 'no', 'n', '0']):
            info['pxe_preserve_ephemeral'] = opt
            node = self._create_test_node(id=_id, uuid=utils.generate_uuid(),
                                          driver_info=info)
            data = pxe._parse_driver_info(node)
            self.assertFalse(data.get('preserve_ephemeral'))

    def test__parse_driver_info_invalid_preserve_ephemeral(self):
        info = dict(INFO_DICT)
        info['pxe_preserve_ephemeral'] = 'foobar'
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

    def test__parse_driver_info_swap_defaults_to_1mb(self):
        info = dict(INFO_DICT)
        info['pxe_swap_mb'] = 0
        node = self._create_test_node(driver_info=info)
        data = pxe._parse_driver_info(node)
        self.assertEqual(1, data.get('swap_mb'))

    def test__get_pxe_mac_path(self):
        mac = '00:11:22:33:44:55:66'
        self.assertEqual('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66',
                         pxe._get_pxe_mac_path(mac))

    def test__link_master_image(self):
        temp_dir = tempfile.mkdtemp()
        orig_path = os.path.join(temp_dir, 'orig_path')
        dest_path = os.path.join(temp_dir, 'dest_path')
        open(orig_path, 'w').close()
        pxe._link_master_image(orig_path, dest_path)
        self.assertIsNotNone(os.path.exists(dest_path))
        self.assertEqual(2, os.stat(dest_path).st_nlink)

    def test__unlink_master_image(self):
        temp_dir = tempfile.mkdtemp()
        orig_path = os.path.join(temp_dir, 'orig_path')
        open(orig_path, 'w').close()
        pxe._unlink_master_image(orig_path)
        self.assertFalse(os.path.exists(orig_path))

    def test__create_master_image(self):
        temp_dir = tempfile.mkdtemp()
        master_path = os.path.join(temp_dir, 'master_path')
        instance_path = os.path.join(temp_dir, 'instance_path')
        tmp_path = os.path.join(temp_dir, 'tmp_path')
        open(tmp_path, 'w').close()
        pxe._create_master_image(tmp_path, master_path, instance_path)
        self.assertTrue(os.path.exists(master_path))
        self.assertTrue(os.path.exists(instance_path))
        self.assertFalse(os.path.exists(tmp_path))
        self.assertEqual(2, os.stat(master_path).st_nlink)

    def test__download_in_progress(self):
        temp_dir = tempfile.mkdtemp()
        lock_file = os.path.join(temp_dir, 'lock_file')
        self.assertFalse(pxe._download_in_progress(lock_file))
        self.assertTrue(os.path.exists(lock_file))

    def test__download_in_progress_wait(self):
        try:
            self.config(auth_strategy='keystone')
        except Exception:
            opts = [
                cfg.StrOpt('auth_strategy', default='keystone'),
                ]
            CONF.register_opts(opts)

        ctx = context.RequestContext(auth_token=True)
        uuid = 'node_uuid'
        temp_dir = tempfile.mkdtemp()
        master_path = os.path.join(temp_dir, 'master_path')
        instance_path = os.path.join(temp_dir, 'instance_path')
        os.mkdir(master_path)
        os.mkdir(instance_path)
        lock_file = os.path.join(master_path, 'node_uuid.lock')
        open(lock_file, 'w').close()

        class handler_deploying(threading.Thread):
            def __init__(self, lock_file):
                threading.Thread.__init__(self)
                self.lock_file = lock_file

            def run(self):
                time.sleep(0.2)
                open(os.path.join(master_path, 'node_uuid'), 'w').close()
                pxe._remove_download_in_progress_lock(self.lock_file)

        handler = handler_deploying(lock_file)
        handler.start()
        pxe._get_image(ctx, os.path.join(instance_path, 'node_uuid'),
                       uuid, master_path)
        self.assertFalse(os.path.exists(lock_file))
        self.assertTrue(os.path.exists(os.path.join(instance_path,
                                                    'node_uuid')))
        self.assertEqual(2, os.stat(os.path.join(master_path, 'node_uuid')).
                             st_nlink)


class PXEPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEPrivateMethodsTestCase, self).setUp()
        n = {
              'driver': 'fake_pxe',
              'driver_info': INFO_DICT
        }
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.dbapi = dbapi.get_instance()
        self.node = self._create_test_node(**n)
        self.context = context.get_admin_context()

    def _create_test_node(self, **kwargs):
        n = db_utils.get_test_node(**kwargs)
        return self.dbapi.create_node(n)

    def _create_test_port(self, **kwargs):
        p = db_utils.get_test_port(**kwargs)
        return self.dbapi.create_port(p)

    def test__get_tftp_image_info(self):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                     u'ramdisk_id': u'instance_ramdisk_uuid'}}

        expected_info = {'ramdisk':
                         ['instance_ramdisk_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')],
                         'kernel':
                         ['instance_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel')],
                         'deploy_ramdisk':
                         ['deploy_ramdisk_uuid',
                           os.path.join(CONF.pxe.tftp_root,
                                        self.node.uuid,
                                        'deploy_ramdisk')],
                         'deploy_kernel':
                         ['deploy_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'deploy_kernel')]}
        with mock.patch.object(base_image_service.BaseImageService, '_show') \
                as show_mock:
            show_mock.return_value = properties
            image_info = pxe._get_tftp_image_info(self.node, self.context)
            show_mock.assert_called_once_with('glance://image_uuid',
                                               method='get')
            self.assertEqual(expected_info, image_info)

    def test__build_pxe_config(self):
        self.config(pxe_append_params='test_param', group='pxe')
        # NOTE: right '/' should be removed from url string
        self.config(api_url='http://192.168.122.184:6385/', group='conductor')

        template = 'ironic/tests/drivers/pxe_config.template'
        pxe_config_template = open(template, 'r').read()

        fake_key = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
        with mock.patch.object(utils, 'random_alnum') as random_alnum_mock:
            random_alnum_mock.return_value = fake_key

            image_info = {'deploy_kernel': ['deploy_kernel',
                                            os.path.join(CONF.pxe.tftp_root,
                                                         self.node.uuid,
                                                         'deploy_kernel')],
                          'deploy_ramdisk': ['deploy_ramdisk',
                                            os.path.join(CONF.pxe.tftp_root,
                                                         self.node.uuid,
                                                         'deploy_ramdisk')],
                          'kernel': ['kernel_id',
                                     os.path.join(CONF.pxe.tftp_root,
                                                  self.node.uuid,
                                                  'kernel')],
                          'ramdisk': ['ramdisk_id',
                                     os.path.join(CONF.pxe.tftp_root,
                                                  self.node.uuid,
                                                  'ramdisk')]
                      }
            pxe_config = pxe._build_pxe_config(self.node,
                                               image_info,
                                               self.context)

            random_alnum_mock.assert_called_once_with(32)
            self.assertEqual(pxe_config_template, pxe_config)

        # test that deploy_key saved
        db_node = self.dbapi.get_node(self.node['uuid'])
        db_key = db_node['driver_info'].get('pxe_deploy_key')
        self.assertEqual(fake_key, db_key)

    def test__get_nodes_mac_addresses(self):
        self._create_test_port(node_id=self.node.id,
                               address='aa:bb:cc',
                               uuid=utils.generate_uuid(),
                               id=6)
        self._create_test_port(node_id=self.node.id,
                               address='dd:ee:ff',
                               uuid=utils.generate_uuid(),
                               id=7)

        expected = ['aa:bb:cc', 'dd:ee:ff']
        with task_manager.acquire(self.context, self.node.uuid) as task:
            node_macs = pxe._get_node_mac_addresses(task, self.node)
        self.assertEqual(expected, node_macs)

    def test__get_node_vif_ids_no_ports(self):
        expected = {}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = pxe._get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test__get_node_vif_ids_one_port(self):
        port1 = self._create_test_port(node_id=self.node.id, id=6,
                                       address='aa:bb:cc',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-A'})
        expected = {port1.uuid: 'test-vif-A'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = pxe._get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test__get_node_vif_ids_two_ports(self):
        port1 = self._create_test_port(node_id=self.node.id, id=6,
                                       address='aa:bb:cc',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-A'})
        port2 = self._create_test_port(node_id=self.node.id, id=7,
                                       address='dd:ee:ff',
                                       uuid=utils.generate_uuid(),
                                       extra={'vif_port_id': 'test-vif-B'})
        expected = {port1.uuid: 'test-vif-A', port2.uuid: 'test-vif-B'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = pxe._get_node_vif_ids(task)
        self.assertEqual(expected, result)

    def test__update_neutron(self):
        opts = pxe._dhcp_options_for_instance()
        with mock.patch.object(pxe, '_get_node_vif_ids') as mock_gnvi:
            mock_gnvi.return_value = {'port-uuid': 'vif-uuid'}
            with mock.patch.object(neutron.NeutronAPI,
                                   'update_port_dhcp_opts') as mock_updo:
                with task_manager.acquire(self.context,
                                          self.node.uuid) as task:
                    pxe._update_neutron(task, self.node)
                mock_updo.assertCalleOnceWith('vif-uuid', opts)

    def test__update_neutron_no_vif_data(self):
        with mock.patch.object(pxe, '_get_node_vif_ids') as mock_gnvi:
            mock_gnvi.return_value = {}
            with mock.patch.object(neutron.NeutronAPI,
                                   '__init__') as mock_init:
                with task_manager.acquire(self.context,
                                          self.node.uuid) as task:
                    pxe._update_neutron(task, self.node)
                mock_init.assert_not_called()

    def test__update_neutron_some_failures(self):
        # confirm update is called twice, one fails, but no exception raised
        with mock.patch.object(pxe, '_get_node_vif_ids') as mock_gnvi:
            mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
            with mock.patch.object(neutron.NeutronAPI,
                                   'update_port_dhcp_opts') as mock_updo:
                exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
                mock_updo.side_effect = [None, exc]
                with task_manager.acquire(self.context,
                                          self.node.uuid) as task:
                    pxe._update_neutron(task, self.node)
                self.assertEqual(2, mock_updo.call_count)

    def test__update_neutron_fails(self):
        # confirm update is called twice, both fail, and exception is raised
        with mock.patch.object(pxe, '_get_node_vif_ids') as mock_gnvi:
            mock_gnvi.return_value = {'p1': 'v1', 'p2': 'v2'}
            with mock.patch.object(neutron.NeutronAPI,
                                   'update_port_dhcp_opts') as mock_updo:
                exc = exception.FailedToUpdateDHCPOptOnPort('fake exception')
                mock_updo.side_effect = [exc, exc]
                with task_manager.acquire(self.context,
                                          self.node.uuid) as task:
                    self.assertRaises(exception.FailedToUpdateDHCPOptOnPort,
                                      pxe._update_neutron,
                                      task, self.node)
                self.assertEqual(2, mock_updo.call_count)

    def test__dhcp_options_for_instance(self):
        self.config(pxe_bootfile_name='test_pxe_bootfile', group='pxe')
        self.config(tftp_server='192.0.2.1', group='pxe')
        expected_info = [{'opt_name': 'bootfile-name',
                          'opt_value': 'test_pxe_bootfile'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1'}
                         ]
        self.assertEqual(expected_info, pxe._dhcp_options_for_instance())

    def test__get_pxe_config_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.tftp_root,
                                      self.node.uuid,
                                      'config'),
                         pxe._get_pxe_config_file_path(self.node.uuid))

    def test__get_image_dir_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path, self.node.uuid),
                         pxe._get_image_dir_path(self.node.uuid))

    def test__get_image_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.images_path,
                                      self.node.uuid,
                                      'disk'),
                         pxe._get_image_file_path(self.node.uuid))

    def test_get_token_file_path(self):
        node_uuid = self.node['uuid']
        self.assertEqual('/tftpboot/token-' + node_uuid,
                         pxe._get_token_file_path(node_uuid))

    def test__cache_tftp_images_master_path(self):
        temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=temp_dir, group='pxe')
        self.config(tftp_master_path=os.path.join(temp_dir,
                                                  'tftp_master_path'),
                    group='pxe')
        image_info = {'deploy_kernel': ['deploy_kernel',
                                        os.path.join(temp_dir,
                                                     self.node.uuid,
                                                     'deploy_kernel')]}
        fileutils.ensure_tree(CONF.pxe.tftp_master_path)
        fd, tmp_master_image = tempfile.mkstemp(dir=CONF.pxe.tftp_master_path)

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            with mock.patch.object(tempfile, 'mkstemp') as mkstemp_mock:
                fetch_to_raw_mock.return_value = None
                mkstemp_mock.return_value = (fd, tmp_master_image)

                pxe._cache_tftp_images(None, self.node, image_info)

                fetch_to_raw_mock.assert_called_once_with(None,
                                                          'deploy_kernel',
                                                          tmp_master_image,
                                                          None)
                mkstemp_mock.assert_called_once_with(
                                                dir=CONF.pxe.tftp_master_path)

    def test__cache_tftp_images_no_master_path(self):
        temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=temp_dir, group='pxe')
        self.config(tftp_master_path=None, group='pxe')
        image_info = {'deploy_kernel': ['deploy_kernel',
                                        os.path.join(temp_dir,
                                        self.node.uuid, 'deploy_kernel')]}

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            fetch_to_raw_mock.return_value = None

            pxe._cache_tftp_images(None, self.node, image_info)

            fetch_to_raw_mock.assert_called_once_with(None,
                    'deploy_kernel',
                    os.path.join(temp_dir, self.node.uuid, 'deploy_kernel'),
                    None)

    def test__cache_instance_images_no_master_path(self):
        temp_dir = tempfile.mkdtemp()
        self.config(images_path=temp_dir, group='pxe')
        self.config(instance_master_path=None, group='pxe')

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            fetch_to_raw_mock.return_value = None

            (uuid, image_path) = pxe._cache_instance_image(None, self.node)

            fetch_to_raw_mock.assert_called_once_with(None,
                            'glance://image_uuid',
                            os.path.join(temp_dir, self.node.uuid, 'disk'),
                            None)
            self.assertEqual('glance://image_uuid', uuid)
            self.assertEqual(os.path.join(temp_dir, self.node.uuid, 'disk'),
                             image_path)

    def test__cache_instance_images_master_path(self):
        temp_dir = tempfile.mkdtemp()
        self.config(images_path=temp_dir, group='pxe')
        self.config(instance_master_path=os.path.join(temp_dir,
                                                      'instance_master_path'),
                         group='pxe')
        fileutils.ensure_tree(CONF.pxe.instance_master_path)
        fd, tmp_master_image = tempfile.mkstemp(
            dir=CONF.pxe.instance_master_path)

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            with mock.patch.object(tempfile, 'mkstemp') as mkstemp_mock:
                with mock.patch.object(service_utils, 'parse_image_ref') \
                        as parse_image_ref_mock:
                    mkstemp_mock.return_value = (fd, tmp_master_image)
                    fetch_to_raw_mock.return_value = None
                    parse_image_ref_mock.return_value = ('image_uuid',
                                                         None,
                                                         None,
                                                         None)

                    (uuid, image_path) = pxe._cache_instance_image(None,
                                                                   self.node)

                    mkstemp_mock.assert_called_once_with(
                         dir=CONF.pxe.instance_master_path)
                    fetch_to_raw_mock.assert_called_once_with(None,
                                                       'glance://image_uuid',
                                                       tmp_master_image,
                                                       None)
                    parse_image_ref_mock.assert_called_once_with(
                                                       'glance://image_uuid')
                    self.assertEqual('glance://image_uuid', uuid)
                    self.assertEqual(os.path.join(temp_dir,
                                                  self.node.uuid,
                                                  'disk'),
                                     image_path)

    def test__get_image_download_in_progress(self):
        def _create_instance_path(*args):
            open(master_path, 'w').close()
            return True
        temp_dir = tempfile.mkdtemp()
        instance_path = os.path.join(temp_dir, 'instance_path')
        fileutils.ensure_tree(temp_dir)
        master_path = os.path.join(temp_dir, self.node.uuid)
        lock_file = os.path.join(temp_dir, self.node.uuid + '.lock')

        with mock.patch.object(pxe, '_download_in_progress') \
                as download_in_progress_mock:
            download_in_progress_mock.side_effect = _create_instance_path

            pxe._get_image(None, instance_path, self.node.uuid, temp_dir)

            download_in_progress_mock.assert_called_once_with(lock_file)
            self.assertTrue(os.path.exists(instance_path))


class PXEDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEDriverTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.context.auth_token = '4562138218392831'
        self.temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=self.temp_dir, group='pxe')
        self.temp_dir = tempfile.mkdtemp()
        self.config(images_path=self.temp_dir, group='pxe')
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        driver_info = INFO_DICT
        driver_info['pxe_deploy_key'] = 'fake-56789'
        n = db_utils.get_test_node(
                driver='fake_pxe',
                driver_info=driver_info)
        self.dbapi = dbapi.get_instance()
        self.node = self.dbapi.create_node(n)
        self.port = self.dbapi.create_port(db_utils.get_test_port(
                                                         node_id=self.node.id))
        self.config(group='conductor', api_url='http://127.0.0.1:1234/')

    def _create_token_file(self):
        token_path = pxe._get_token_file_path(self.node['uuid'])
        open(token_path, 'w').close()
        return token_path

    def test_validate_good(self):
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=True) as task:
            task.resources[0].driver.deploy.validate(task, self.node)

    def test_validate_fail(self):
        info = dict(INFO_DICT)
        del info['pxe_image_source']
        self.node['driver_info'] = json.dumps(info)
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.deploy.validate,
                              task, self.node)

    def test_validate_fail_no_port(self):
        new_node = self.dbapi.create_node(db_utils.get_test_node(id=321,
                                   uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                                   driver='fake_pxe', driver_info=INFO_DICT))
        with task_manager.acquire(self.context, [new_node.uuid],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.deploy.validate,
                              task, new_node)

    @mock.patch.object(keystone, 'get_service_url')
    def test_validate_good_api_url_from_config_file(self, mock_ks):
        # not present in the keystone catalog
        mock_ks.side_effect = exception.CatalogFailure

        with task_manager.acquire(self.context, [self.node.uuid],
                                  shared=True) as task:
            task.resources[0].driver.deploy.validate(task, self.node)
            self.assertFalse(mock_ks.called)

    @mock.patch.object(keystone, 'get_service_url')
    def test_validate_good_api_url_from_keystone(self, mock_ks):
        # present in the keystone catalog
        mock_ks.return_value = 'http://127.0.0.1:1234'
        # not present in the config file
        self.config(group='conductor', api_url=None)

        with task_manager.acquire(self.context, [self.node.uuid],
                                  shared=True) as task:
            task.resources[0].driver.deploy.validate(task, self.node)
            mock_ks.assert_called_once_with()

    @mock.patch.object(keystone, 'get_service_url')
    def test_validate_fail_no_api_url(self, mock_ks):
        # not present in the keystone catalog
        mock_ks.side_effect = exception.CatalogFailure
        # not present in the config file
        self.config(group='conductor', api_url=None)

        with task_manager.acquire(self.context, [self.node.uuid],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.deploy.validate,
                              task, self.node)
            mock_ks.assert_called_once_with()

    def test__get_nodes_mac_addresses(self):
        ports = []
        ports.append(self.port)
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=6,
                    address='aa:bb:cc',
                    uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                    node_id='123')))
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=7,
                    address='dd:ee:ff',
                    uuid='4fc26c0b-03f2-4d2e-ae87-c02d7f33c234',
                    node_id='123')))
        with task_manager.acquire(self.context, [self.node['uuid']]) as task:
            node_macs = pxe._get_node_mac_addresses(task, self.node)
        self.assertEqual(sorted([p.address for p in ports]), sorted(node_macs))

    def test_vendor_passthru_validate_good(self):
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=True) as task:
            task.resources[0].driver.vendor.validate(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')

    def test_vendor_passthru_validate_fail(self):
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.vendor.validate,
                              task, self.node, method='pass_deploy_info',
                              key='fake-56789')

    def test_vendor_passthru_validate_key_notmatch(self):
        with task_manager.acquire(self.context, [self.node['uuid']],
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.vendor.validate,
                              task, self.node, method='pass_deploy_info',
                              address='123456', iqn='aaa-bbb',
                              key='fake-12345')

    def test_prepare(self):
        with mock.patch.object(pxe,
                '_create_pxe_config') as create_pxe_config_mock:
            with mock.patch.object(pxe, '_cache_images') as cache_images_mock:
                with mock.patch.object(pxe,
                        '_get_tftp_image_info') as get_tftp_image_info_mock:
                    get_tftp_image_info_mock.return_value = None
                    create_pxe_config_mock.return_value = None
                    cache_images_mock.return_value = None

                    with task_manager.acquire(self.context,
                                    self.node['uuid'], shared=True) as task:
                        task.driver.deploy.prepare(task, self.node)
                        get_tftp_image_info_mock.assert_called_once_with(
                                                                  self.node,
                                                                  self.context)
                        create_pxe_config_mock.assert_called_once_with(task,
                                                                    self.node,
                                                                    None)
                        cache_images_mock.assert_called_once_with(self.node,
                                                                  None,
                                                                  self.context)

    def test_deploy(self):
        with mock.patch.object(pxe, '_update_neutron') as update_neutron_mock:
            with mock.patch.object(manager_utils,
                    'node_power_action') as node_power_mock:
                with mock.patch.object(manager_utils,
                        'node_set_boot_device') as node_set_boot_mock:
                    with task_manager.acquire(self.context,
                        self.node['uuid'], shared=False) as task:
                        state = task.driver.deploy.deploy(task, self.node)
                        self.assertEqual(state, states.DEPLOYWAIT)
                        update_neutron_mock.assert_called_once_with(task,
                                                                    self.node)
                        node_set_boot_mock.assert_called_once_with(task,
                                                            self.node,
                                                            'pxe',
                                                            persistent=True)
                        node_power_mock.assert_called_once_with(task,
                                                                self.node,
                                                                states.REBOOT)

                        # ensure token file created
                        t_path = pxe._get_token_file_path(self.node['uuid'])
                        token = open(t_path, 'r').read()
                        self.assertEqual(self.context.auth_token, token)

    def test_tear_down(self):
        with mock.patch.object(manager_utils,
                'node_power_action') as node_power_mock:
            with task_manager.acquire(self.context,
                    self.node['uuid']) as task:
                state = task.driver.deploy.tear_down(task, self.node)
                self.assertEqual(states.DELETED, state)
                node_power_mock.assert_called_once_with(task, self.node,
                                                        states.POWER_OFF)

    @mock.patch.object(manager_utils, 'node_power_action')
    def test_tear_down_removes_pxe_deploy_key(self, mock_npa):
        self.assertIn('pxe_deploy_key', self.node.driver_info)
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.deploy.tear_down(task, self.node)

        self.node.refresh(self.context)
        self.assertNotIn('pxe_deploy_key', self.node.driver_info)
        mock_npa.assert_called_once_with(task, self.node, states.POWER_OFF)

    def test_take_over(self):
        with mock.patch.object(pxe, '_update_neutron') as update_neutron_mock:
            with task_manager.acquire(
                    self.context, self.node['uuid'], shared=True) as task:
                task.driver.deploy.take_over(task, self.node)
                update_neutron_mock.assert_called_once_with(task, self.node)

    def test_continue_deploy_good(self):
        token_path = self._create_token_file()
        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save(self.context)

        def fake_deploy(**kwargs):
            pass

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.drivers.modules.deploy_utils.deploy',
                fake_deploy))

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.resources[0].driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')
        self.assertEqual(states.ACTIVE, self.node.provision_state)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertIsNone(self.node.last_error)
        self.assertFalse(os.path.exists(token_path))

    def test_continue_deploy_fail(self):
        token_path = self._create_token_file()
        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save(self.context)

        def fake_deploy(**kwargs):
            raise exception.InstanceDeployFailure("test deploy error")

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.drivers.modules.deploy_utils.deploy',
                fake_deploy))

        with task_manager.acquire(self.context, [self.node.uuid]) as task:
            task.resources[0].driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')
        self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertIsNotNone(self.node.last_error)
        self.assertFalse(os.path.exists(token_path))

    def test_continue_deploy_ramdisk_fails(self):
        token_path = self._create_token_file()
        self.node.power_state = states.POWER_ON
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save(self.context)

        def fake_deploy(**kwargs):
            pass

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.drivers.modules.deploy_utils.deploy',
                fake_deploy))

        with task_manager.acquire(self.context, [self.node.uuid]) as task:
            task.resources[0].driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789', error='test ramdisk error')
        self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertIsNotNone(self.node.last_error)
        self.assertFalse(os.path.exists(token_path))

    def test_continue_deploy_invalid(self):
        self.node.power_state = states.POWER_ON
        self.node.provision_state = 'FAKE'
        self.node.save(self.context)

        with task_manager.acquire(self.context, [self.node.uuid]) as task:
            task.resources[0].driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789', error='test ramdisk error')
        self.assertEqual('FAKE', self.node.provision_state)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    def test_lock_elevated(self):
        with task_manager.acquire(self.context, [self.node['uuid']]) as task:
            with mock.patch.object(task.driver.vendor, '_continue_deploy') \
                    as _continue_deploy_mock:
                task.driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')
                # lock elevated w/o exception
                self.assertEqual(1, _continue_deploy_mock.call_count,
                            "_continue_deploy was not called once.")

    def clean_up_config(self, master=None):
        ports = []
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=6,
                    address='aa:bb:cc',
                    uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                    node_id='123')))

        d_kernel_path = os.path.join(CONF.pxe.tftp_root,
                                     self.node.uuid, 'deploy_kernel')
        image_info = {'deploy_kernel': ['deploy_kernel_uuid', d_kernel_path]}

        with mock.patch.object(pxe, '_get_tftp_image_info') \
                as get_tftp_image_info_mock:
            get_tftp_image_info_mock.return_value = image_info

            pxecfg_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
            os.makedirs(pxecfg_dir)

            instance_dir = os.path.join(CONF.pxe.tftp_root,
                                        self.node.uuid)
            image_dir = os.path.join(CONF.pxe.images_path, self.node.uuid)
            os.makedirs(instance_dir)
            os.makedirs(image_dir)
            config_path = os.path.join(instance_dir, 'config')
            deploy_kernel_path = os.path.join(instance_dir, 'deploy_kernel')
            pxe_mac_path = os.path.join(pxecfg_dir, '01-aa-bb-cc')
            image_path = os.path.join(image_dir, 'disk')
            open(config_path, 'w').close()
            os.link(config_path, pxe_mac_path)
            if master:
                tftp_master_dir = os.path.join(CONF.pxe.tftp_root,
                                               'tftp_master')
                instance_master_dir = os.path.join(CONF.pxe.images_path,
                                                   'instance_master')
                self.config(tftp_master_path=tftp_master_dir, group='pxe')
                self.config(instance_master_path=instance_master_dir,
                            group='pxe')
                os.makedirs(tftp_master_dir)
                os.makedirs(instance_master_dir)
                master_deploy_kernel_path = os.path.join(tftp_master_dir,
                                                         'deploy_kernel_uuid')
                master_instance_path = os.path.join(instance_master_dir,
                                                    'image_uuid')
                open(master_deploy_kernel_path, 'w').close()
                open(master_instance_path, 'w').close()

                os.link(master_deploy_kernel_path, deploy_kernel_path)
                os.link(master_instance_path, image_path)
                if master == 'in_use':
                    deploy_kernel_link = os.path.join(CONF.pxe.tftp_root,
                                                      'deploy_kernel_link')
                    image_link = os.path.join(CONF.pxe.images_path,
                                              'image_link')
                    os.link(master_deploy_kernel_path, deploy_kernel_link)
                    os.link(master_instance_path, image_link)

            else:
                self.config(tftp_master_path='', group='pxe')
                self.config(instance_master_path='', group='pxe')
                open(deploy_kernel_path, 'w').close()
                open(image_path, 'w').close()

            with task_manager.acquire(self.context, [self.node['uuid']],
                                      shared=True) as task:
                task.resources[0].driver.deploy.clean_up(task, self.node)
            get_tftp_image_info_mock.called_once_with(self.node)
            assert_false_path = [config_path, deploy_kernel_path, image_path,
                                 pxe_mac_path, image_dir, instance_dir]
            for path in assert_false_path:
                self.assertFalse(os.path.exists(path))

    def test_clean_up_removes_token_file(self):
        token_path = self._create_token_file()
        self.clean_up_config(master=None)
        self.assertFalse(os.path.exists(token_path))

    def test_clean_up_no_master_images(self):
        self.clean_up_config(master=None)

    def test_clean_up_master_images_not_in_use(self):
        self.clean_up_config(master='not_in_use')

        master_d_kernel_path = os.path.join(CONF.pxe.tftp_master_path,
                                            'deploy_kernel_uuid')
        master_instance_path = os.path.join(CONF.pxe.instance_master_path,
                                            'image_uuid')

        self.assertFalse(os.path.exists(master_d_kernel_path))
        self.assertFalse(os.path.exists(master_instance_path))

    def test_clean_up_master_images_in_use(self):
        self.clean_up_config(master='in_use')

        master_d_kernel_path = os.path.join(CONF.pxe.tftp_master_path,
                                            'deploy_kernel_uuid')
        master_instance_path = os.path.join(CONF.pxe.instance_master_path,
                                             'image_uuid')

        self.assertTrue(os.path.exists(master_d_kernel_path))
        self.assertTrue(os.path.exists(master_instance_path))
