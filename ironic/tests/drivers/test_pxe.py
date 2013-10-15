# vim: tabstop=4 shiftwidth=4 softtabstop=4
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
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
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

INFO_DICT = json.loads(db_utils.pxe_info)


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
        self.assertIsNotNone(info.get('instance_name'))
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('deploy_kernel'))
        self.assertIsNotNone(info.get('deploy_ramdisk'))
        self.assertIsNotNone(info.get('root_gb'))

    def test__parse_driver_info_missing_instance_name(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['pxe_instance_name']
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)

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

    def test__get_pxe_mac_path(self):
        mac = '00:11:22:33:44:55:66'
        self.assertEqual(pxe._get_pxe_mac_path(mac),
                         '/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66')

    def test__link_master_image(self):
        temp_dir = tempfile.mkdtemp()
        orig_path = os.path.join(temp_dir, 'orig_path')
        dest_path = os.path.join(temp_dir, 'dest_path')
        open(orig_path, 'w').close()
        pxe._link_master_image(orig_path, dest_path)
        self.assertIsNotNone(os.path.exists(dest_path))
        self.assertEqual(os.stat(dest_path).st_nlink, 2)

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
        self.assertEqual(os.stat(master_path).st_nlink, 2)

    def test__download_in_progress(self):
        temp_dir = tempfile.mkdtemp()
        lock_file = os.path.join(temp_dir, 'lock_file')
        self.assertFalse(pxe._download_in_progress(lock_file))
        self.assertTrue(os.path.exists(lock_file))

    def test__download_in_progress_wait(self):
        try:
            CONF.set_default('auth_strategy', 'keystone')
        except Exception:
            opts = [
                cfg.StrOpt('auth_strategy', default='keystone'),
                ]
            CONF.register_opts(opts)

        ctx = context.RequestContext(auth_token=True)
        uuid = 'instance_uuid'
        temp_dir = tempfile.mkdtemp()
        master_path = os.path.join(temp_dir, 'master_path')
        instance_path = os.path.join(temp_dir, 'instance_path')
        os.mkdir(master_path)
        os.mkdir(instance_path)
        lock_file = os.path.join(master_path, 'instance_uuid.lock')
        open(lock_file, 'w').close()

        class handler_deploying(threading.Thread):
            def __init__(self, lock_file):
                threading.Thread.__init__(self)
                self.lock_file = lock_file

            def run(self):
                time.sleep(2)
                open(os.path.join(master_path, 'instance_uuid'), 'w').close()
                pxe._remove_download_in_progress_lock(self.lock_file)

        handler = handler_deploying(lock_file)
        handler.start()
        pxe._get_image(ctx, os.path.join(instance_path, 'instance_uuid'),
                       uuid, master_path)
        self.assertFalse(os.path.exists(lock_file))
        self.assertTrue(os.path.exists(os.path.join(instance_path,
                                                    'instance_uuid')))
        self.assertEqual(os.stat(os.path.join(master_path, 'instance_uuid')).
                             st_nlink, 2)


class PXEPrivateMethodsTestCase(base.TestCase):

    def setUp(self):
        super(PXEPrivateMethodsTestCase, self).setUp()
        n = {
              'driver': 'fake_pxe',
              'driver_info': INFO_DICT,
              'instance_uuid': 'instance_uuid_123',
              'id': 123}
        self.dbapi = dbapi.get_instance()
        self.node = self._create_test_node(**n)

    def _create_test_node(self, **kwargs):
        n = db_utils.get_test_node(**kwargs)
        return self.dbapi.create_node(n)

    def test__get_tftp_image_info(self):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                     u'ramdisk_id': u'instance_ramdisk_uuid'}}

        expected_info = {'ramdisk':
                         ['instance_ramdisk_uuid',
                          '/tftpboot/instance_uuid_123/ramdisk'],
                         'kernel':
                         ['instance_kernel_uuid',
                          '/tftpboot/instance_uuid_123/kernel'],
                         'deploy_ramdisk':
                         ['deploy_ramdisk_uuid',
                           '/tftpboot/instance_uuid_123/deploy_ramdisk'],
                         'deploy_kernel':
                         ['deploy_kernel_uuid',
                          '/tftpboot/instance_uuid_123/deploy_kernel']}
        with mock.patch.object(base_image_service.BaseImageService, '_show') \
                as show_mock:
            show_mock.return_value = properties
            image_info = pxe._get_tftp_image_info(self.node)
            show_mock.assert_called_once_with('glance://image_uuid',
                                               method='get')
            self.assertEqual(image_info, expected_info)

    def test__build_pxe_config(self):
        instance_uuid = 'instance_uuid_123'
        CONF.set_default('pxe_append_params', 'test_param', group='pxe')

        template = 'ironic/tests/drivers/pxe_config.template'
        pxe_config_template = open(template, 'r').read()

        fake_key = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
        with mock.patch.object(utils, 'random_alnum') as random_alnum_mock:
            random_alnum_mock.return_value = fake_key

            image_info = {'deploy_kernel': ['deploy_kernel',
                                            CONF.pxe.tftp_root + '/' +
                                            instance_uuid + '/deploy_kernel'],
                          'deploy_ramdisk': ['deploy_ramdisk',
                                            CONF.pxe.tftp_root + '/' +
                                            instance_uuid + '/deploy_ramdisk'],
                          'kernel': ['kernel_id',
                                     CONF.pxe.tftp_root + '/' + instance_uuid +
                                     '/kernel'],
                          'ramdisk': ['ramdisk_id',
                                     CONF.pxe.tftp_root + '/' + instance_uuid +
                                     '/ramdisk']
                      }
            pxe_config = pxe._build_pxe_config(self.node, image_info)

            random_alnum_mock.assert_called_once_with(32)
            self.assertEqual(pxe_config, pxe_config_template)

        # test that deploy_key saved
        db_node = self.dbapi.get_node(self.node['uuid'])
        db_key = db_node['driver_info'].get('pxe_deploy_key')
        self.assertEqual(db_key, fake_key)

    def test__get_pxe_config_file_path(self):
        self.assertEqual('/tftpboot/instance_uuid_123/config',
                         pxe._get_pxe_config_file_path('instance_uuid_123'))

    def test__get_image_dir_path(self):
        node = self._create_test_node(
            id=345,
            driver='fake_pxe',
            driver_info=INFO_DICT,
        )
        info = pxe._parse_driver_info(node)
        self.assertEqual('/var/lib/ironic/images/fake_instance_name',
                         pxe._get_image_dir_path(info))

    def test__get_image_file_path(self):
        node = self._create_test_node(
            id=345,
            driver='fake_pxe',
            driver_info=INFO_DICT,
        )
        info = pxe._parse_driver_info(node)
        self.assertEqual('/var/lib/ironic/images/fake_instance_name/disk',
                         pxe._get_image_file_path(info))

    def test__cache_tftp_images_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('tftp_root', temp_dir, group='pxe')
        CONF.set_default('tftp_master_path', os.path.join(temp_dir,
                                                          'tftp_master_path'),
                         group='pxe')
        image_info = {'deploy_kernel': ['deploy_kernel', temp_dir +
                                        '/instance_uuid_123/deploy_kernel']}
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
        CONF.set_default('tftp_root', temp_dir, group='pxe')
        CONF.set_default('tftp_master_path', None, group='pxe')
        image_info = {'deploy_kernel': ['deploy_kernel',
                                        os.path.join(temp_dir,
                                        'instance_uuid_123/deploy_kernel')]}

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            fetch_to_raw_mock.return_value = None

            pxe._cache_tftp_images(None, self.node, image_info)

            fetch_to_raw_mock.assert_called_once_with(None,
                    'deploy_kernel',
                    os.path.join(temp_dir, 'instance_uuid_123/deploy_kernel'),
                    None)

    def test__cache_instance_images_no_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('images_path', temp_dir, group='pxe')
        CONF.set_default('instance_master_path', None, group='pxe')

        with mock.patch.object(images, 'fetch_to_raw') as fetch_to_raw_mock:
            fetch_to_raw_mock.return_value = None

            (uuid, image_path) = pxe._cache_instance_image(None, self.node)

            fetch_to_raw_mock.assert_called_once_with(None,
                            'glance://image_uuid',
                            os.path.join(temp_dir, 'fake_instance_name/disk'),
                            None)
            self.assertEqual(uuid, 'glance://image_uuid')
            self.assertEqual(image_path,
                             os.path.join(temp_dir, 'fake_instance_name/disk'))

    def test__cache_instance_images_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('images_path', temp_dir, group='pxe')
        CONF.set_default('instance_master_path',
                         os.path.join(temp_dir, 'instance_master_path'),
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
                    self.assertEqual(uuid, 'glance://image_uuid')
                    self.assertEqual(
                            image_path, temp_dir + '/fake_instance_name/disk')

    def test__get_image_download_in_progress(self):
        def _create_instance_path(*args):
            open(master_path, 'w').close()
            return True
        temp_dir = tempfile.mkdtemp()
        instance_path = os.path.join(temp_dir, 'instance_path')
        fileutils.ensure_tree(temp_dir)
        master_uuid = 'instance_uuid'
        master_path = os.path.join(temp_dir, master_uuid)
        lock_file = os.path.join(temp_dir, 'instance_uuid.lock')

        with mock.patch.object(pxe, '_download_in_progress') \
                as download_in_progress_mock:
            download_in_progress_mock.side_effect = _create_instance_path

            pxe._get_image(None, instance_path, master_uuid, temp_dir)

            download_in_progress_mock.assert_called_once_with(lock_file)
            self.assertTrue(os.path.exists(instance_path))


class PXEDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEDriverTestCase, self).setUp()
        mgr_utils.get_mocked_node_manager(driver='fake_pxe')
        driver_info = INFO_DICT
        driver_info['pxe_deploy_key'] = 'fake-56789'
        n = db_utils.get_test_node(
                driver='fake_pxe',
                driver_info=driver_info,
                instance_uuid='instance_uuid_123')
        self.dbapi = dbapi.get_instance()
        self.node = self.dbapi.create_node(n)

    def test_validate_good(self):
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            task.resources[0].driver.deploy.validate(self.node)

    def test_validate_fail(self):
        info = dict(INFO_DICT)
        del info['pxe_image_source']
        self.node['driver_info'] = json.dumps(info)
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.deploy.validate,
                              self.node)

    def test__get_nodes_mac_addresses(self):
        ports = []
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
        with task_manager.acquire([self.node['uuid']]) as task:
            node_macs = pxe._get_node_mac_addresses(task, self.node)
        self.assertEqual(node_macs, ['aa:bb:cc', 'dd:ee:ff'])

    def test_vendor_passthru_validate_good(self):
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            task.resources[0].driver.vendor.validate(self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')

    def test_vendor_passthru_validate_fail(self):
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.vendor.validate,
                              self.node, method='pass_deploy_info',
                              key='fake-56789')

    def test_vendor_passthru_validate_key_notmatch(self):
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.resources[0].driver.vendor.validate,
                              self.node, method='pass_deploy_info',
                              address='123456', iqn='aaa-bbb',
                              key='fake-12345')

    def test_start_deploy(self):
        with mock.patch.object(pxe, '_create_pxe_config') \
                as create_pxe_config_mock:
            with mock.patch.object(pxe, '_cache_images') as cache_images_mock:
                with mock.patch.object(pxe, '_get_tftp_image_info') \
                        as get_tftp_image_info_mock:
                    get_tftp_image_info_mock.return_value = None
                    create_pxe_config_mock.return_value = None
                    cache_images_mock.return_value = None

                    with task_manager.acquire([self.node['uuid']],
                                              shared=False) as task:
                        state = task.resources[0].driver.deploy.deploy(task,
                                                                    self.node)
                        get_tftp_image_info_mock.assert_called_once_with(
                                                                  self.node)
                        create_pxe_config_mock.assert_called_once_with(task,
                                                                    self.node,
                                                                    None)
                        cache_images_mock.assert_called_once_with(self.node,
                                                                  None)
                        self.assertEqual(state, states.DEPLOYING)

    def test_continue_deploy_good(self):

        def fake_deploy(**kwargs):
            pass

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.drivers.modules.deploy_utils.deploy', fake_deploy))
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            task.resources[0].driver.vendor.vendor_passthru(task, self.node,
                    method='pass_deploy_info', address='123456', iqn='aaa-bbb',
                    key='fake-56789')
        self.assertEqual(self.node['provision_state'], states.DEPLOYDONE)

    def test_continue_deploy_fail(self):

        def fake_deploy(**kwargs):
            raise exception.InstanceDeployFailure()

        self.useFixture(fixtures.MonkeyPatch(
                'ironic.drivers.modules.deploy_utils.deploy', fake_deploy))
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                            task.resources[0].driver.vendor.vendor_passthru,
                            task, self.node, method='pass_deploy_info',
                            address='123456', iqn='aaa-bbb', key='fake-56789')
        self.assertEqual(self.node['provision_state'], states.DEPLOYFAIL)

    def tear_down_config(self, master=None):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('tftp_root', temp_dir, group='pxe')
        CONF.set_default('images_path', temp_dir, group='pxe')

        ports = []
        ports.append(
            self.dbapi.create_port(
                db_utils.get_test_port(
                    id=6,
                    address='aa:bb:cc',
                    uuid='bb43dc0b-03f2-4d2e-ae87-c02d7f33cc53',
                    node_id='123')))

        d_kernel_path = os.path.join(temp_dir,
                                     'instance_uuid_123/deploy_kernel')
        image_info = {'deploy_kernel': ['deploy_kernel_uuid', d_kernel_path]}

        with mock.patch.object(pxe, '_get_tftp_image_info') \
                as get_tftp_image_info_mock:
            get_tftp_image_info_mock.return_value = image_info

            pxecfg_dir = os.path.join(temp_dir, 'pxelinux.cfg')
            os.makedirs(pxecfg_dir)

            instance_dir = os.path.join(temp_dir, 'instance_uuid_123')
            image_dir = os.path.join(temp_dir, 'fake_instance_name')
            os.makedirs(instance_dir)
            os.makedirs(image_dir)
            config_path = os.path.join(instance_dir, 'config')
            deploy_kernel_path = os.path.join(instance_dir, 'deploy_kernel')
            pxe_mac_path = os.path.join(pxecfg_dir, '01-aa-bb-cc')
            image_path = os.path.join(image_dir, 'disk')
            open(config_path, 'w').close()
            os.link(config_path, pxe_mac_path)
            if master:
                tftp_master_dir = os.path.join(temp_dir, 'tftp_master')
                instance_master_dir = os.path.join(temp_dir, 'instance_master')
                CONF.set_default('tftp_master_path',
                                 tftp_master_dir,
                                 group='pxe')
                CONF.set_default('instance_master_path', instance_master_dir,
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
                    deploy_kernel_link = os.path.join(temp_dir,
                                                      'deploy_kernel_link')
                    image_link = os.path.join(temp_dir, 'image_link')
                    os.link(master_deploy_kernel_path, deploy_kernel_link)
                    os.link(master_instance_path, image_link)

            else:
                CONF.set_default('tftp_master_path', '', group='pxe')
                CONF.set_default('instance_master_path', '', group='pxe')
                open(deploy_kernel_path, 'w').close()
                open(image_path, 'w').close()

            with task_manager.acquire([self.node['uuid']], shared=False) \
                    as task:
                task.resources[0].driver.deploy.tear_down(task, self.node)
            get_tftp_image_info_mock.called_once_with(self.node)
            assert_false_path = [config_path, deploy_kernel_path, image_path,
                                 pxe_mac_path, image_dir, instance_dir]
            for path in assert_false_path:
                self.assertFalse(os.path.exists(path))

            return temp_dir

    def test_tear_down_no_master_images(self):
        self.tear_down_config(master=None)

    def test_tear_down_master_images_not_in_use(self):
        temp_dir = self.tear_down_config(master='not_in_use')

        master_d_kernel_path = os.path.join(temp_dir,
                                            'tftp_master/deploy_kernel_uuid')
        master_instance_path = os.path.join(temp_dir,
                                            'instance_master/image_uuid')

        self.assertFalse(os.path.exists(master_d_kernel_path))
        self.assertFalse(os.path.exists(master_instance_path))

    def test_tear_down_master_images_in_use(self):
        temp_dir = self.tear_down_config(master='in_use')

        master_d_kernel_path = os.path.join(temp_dir,
                                            'tftp_master/deploy_kernel_uuid')
        master_instance_path = os.path.join(temp_dir,
                                             'instance_master/image_uuid')

        self.assertTrue(os.path.exists(master_d_kernel_path))
        self.assertTrue(os.path.exists(master_instance_path))
