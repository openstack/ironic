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

import mox
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

INFO_DICT = json.loads(db_utils.pxe_info).get('pxe')


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
                    driver_info=json.loads(db_utils.pxe_info))
        info = pxe._parse_driver_info(node)
        self.assertIsNotNone(info.get('instance_name'))
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('deploy_kernel'))
        self.assertIsNotNone(info.get('deploy_ramdisk'))
        self.assertIsNotNone(info.get('root_gb'))
        self.mox.VerifyAll()

    def test__parse_driver_info_missing_instance_name(self):
        # make sure error is raised when info is missing
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['instance_name']
        info = {'pxe': tmp_dict}
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)
        self.mox.VerifyAll()

    def test__parse_driver_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['image_source']
        info = {'pxe': tmp_dict}
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)
        self.mox.VerifyAll()

    def test__parse_driver_info_missing_deploy_kernel(self):
        # make sure error is raised when info is missing
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['deploy_kernel']
        info = {'pxe': tmp_dict}
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)
        self.mox.VerifyAll()

    def test__parse_driver_info_missing_deploy_ramdisk(self):
        # make sure error is raised when info is missing
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['deploy_ramdisk']
        info = {'pxe': tmp_dict}
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)
        self.mox.VerifyAll()

    def test__parse_driver_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['root_gb']
        info = {'pxe': tmp_dict}
        node = self._create_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                pxe._parse_driver_info,
                node)
        self.mox.VerifyAll()

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
              'driver_info': json.loads(db_utils.pxe_info),
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
        self.mox.StubOutWithMock(base_image_service.BaseImageService, '_show')
        base_image_service.BaseImageService._show(
            'glance://image_uuid',
            method='get').AndReturn(properties)
        self.mox.ReplayAll()
        image_info = pxe._get_tftp_image_info(self.node)

        self.assertEqual(image_info, expected_info)

    def test__build_pxe_config(self):
        instance_uuid = 'instance_uuid_123'
        CONF.set_default('pxe_append_params', 'test_param', group='pxe')

        template = 'ironic/tests/drivers/pxe_config.template'
        pxe_config_template = open(template, 'r').read()

        self.mox.StubOutWithMock(utils, 'random_alnum')

        utils.random_alnum(32).AndReturn('0123456789ABCDEFGHIJKLMNOPQRSTUV')

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

        self.mox.ReplayAll()

        pxe_config = pxe._build_pxe_config(self.node, image_info)

        self.assertEqual(pxe_config, pxe_config_template)

    def test__get_pxe_config_file_path(self):
        self.assertEqual('/tftpboot/instance_uuid_123/config',
                         pxe._get_pxe_config_file_path('instance_uuid_123'))

    def test__get_image_dir_path(self):
        node = self._create_test_node(
            id=345,
            driver='fake_pxe',
            driver_info=json.loads(db_utils.pxe_info),
        )
        info = pxe._parse_driver_info(node)
        self.assertEqual('/var/lib/ironic/images/fake_instance_name',
                         pxe._get_image_dir_path(info))

    def test__get_image_file_path(self):
        node = self._create_test_node(
            id=345,
            driver='fake_pxe',
            driver_info=json.loads(db_utils.pxe_info),
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
        self.mox.StubOutWithMock(images, 'fetch_to_raw')
        self.mox.StubOutWithMock(tempfile, 'mkstemp')
        tempfile.mkstemp(dir=CONF.pxe.tftp_master_path).\
            AndReturn((fd, tmp_master_image))
        images.fetch_to_raw(None, 'deploy_kernel', tmp_master_image, None).\
            AndReturn(None)
        self.mox.ReplayAll()
        pxe._cache_tftp_images(None, self.node, image_info)
        self.mox.VerifyAll()

    def test__cache_tftp_images_no_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('tftp_root', temp_dir, group='pxe')
        CONF.set_default('tftp_master_path', None, group='pxe')
        image_info = {'deploy_kernel': ['deploy_kernel',
                                        os.path.join(temp_dir,
                                        'instance_uuid_123/deploy_kernel')]}
        self.mox.StubOutWithMock(images, 'fetch_to_raw')
        images.fetch_to_raw(None, 'deploy_kernel',
                            os.path.join(temp_dir,
                                         'instance_uuid_123/deploy_kernel'),
                            None).AndReturn(None)
        self.mox.ReplayAll()
        pxe._cache_tftp_images(None, self.node, image_info)
        self.mox.VerifyAll()

    def test__cache_instance_images_no_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('images_path', temp_dir, group='pxe')
        CONF.set_default('instance_master_path', None, group='pxe')
        self.mox.StubOutWithMock(images, 'fetch_to_raw')
        images.fetch_to_raw(None, 'glance://image_uuid',
                            os.path.join(temp_dir,
                                          'fake_instance_name/disk'),
                            None).AndReturn(None)
        self.mox.ReplayAll()
        (uuid, image_path) = pxe._cache_instance_image(None, self.node)
        self.mox.VerifyAll()
        self.assertEqual(uuid, 'glance://image_uuid')
        self.assertEqual(image_path,
                         os.path.join(temp_dir,
                                      'fake_instance_name/disk'))

    def test__cache_instance_images_master_path(self):
        temp_dir = tempfile.mkdtemp()
        CONF.set_default('images_path', temp_dir, group='pxe')
        CONF.set_default('instance_master_path',
                         os.path.join(temp_dir, 'instance_master_path'),
                         group='pxe')
        fileutils.ensure_tree(CONF.pxe.instance_master_path)
        fd, tmp_master_image = tempfile.mkstemp(
            dir=CONF.pxe.instance_master_path)
        self.mox.StubOutWithMock(images, 'fetch_to_raw')
        self.mox.StubOutWithMock(tempfile, 'mkstemp')
        self.mox.StubOutWithMock(service_utils, 'parse_image_ref')
        tempfile.mkstemp(dir=CONF.pxe.instance_master_path).\
            AndReturn((fd, tmp_master_image))
        images.fetch_to_raw(None, 'glance://image_uuid',
                            tmp_master_image,
                            None).\
            AndReturn(None)
        service_utils.parse_image_ref('glance://image_uuid').\
            AndReturn(('image_uuid', None, None, None))
        self.mox.ReplayAll()
        (uuid, image_path) = pxe._cache_instance_image(None, self.node)
        self.mox.VerifyAll()
        self.assertEqual(uuid, 'glance://image_uuid')
        self.assertEqual(image_path, temp_dir + '/fake_instance_name/disk')

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
        self.mox.StubOutWithMock(pxe, '_download_in_progress')
        pxe._download_in_progress(lock_file).\
            WithSideEffects(_create_instance_path).\
            AndReturn(True)
        self.mox.ReplayAll()
        pxe._get_image(None, instance_path, master_uuid, temp_dir)
        self.mox.VerifyAll()
        self.assertTrue(os.path.exists(instance_path))


class PXEDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEDriverTestCase, self).setUp()
        self.driver = mgr_utils.get_mocked_node_manager(driver='fake_pxe')
        n = db_utils.get_test_node(
                driver='fake_pxe',
                driver_info=json.loads(db_utils.pxe_info),
                instance_uuid='instance_uuid_123')
        self.dbapi = dbapi.get_instance()
        self.node = self.dbapi.create_node(n)

    def test_validate_good(self):
        with task_manager.acquire([self.node['uuid']], shared=True) as task:
            task.resources[0].driver.deploy.validate(self.node)

    def test_validate_fail(self):
        tmp_dict = dict(INFO_DICT)
        del tmp_dict['image_source']
        self.node['driver_info'] = json.dumps({'pxe': tmp_dict})
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

    def test_deploy_good(self):

        def refresh():
            pass

        self.node.refresh = refresh

        self.mox.StubOutWithMock(pxe, '_create_pxe_config')
        self.mox.StubOutWithMock(pxe, '_cache_images')
        self.mox.StubOutWithMock(pxe, '_get_tftp_image_info')
        pxe._get_tftp_image_info(self.node).AndReturn(None)
        pxe._create_pxe_config(mox.IgnoreArg(), self.node, None).\
            AndReturn(None)
        pxe._cache_images(self.node, None).AndReturn(None)
        self.mox.ReplayAll()

        class handler_deploying(threading.Thread):
            def __init__(self, node):
                threading.Thread.__init__(self)
                self.node = node

            def run(self):
                self.node['provision_state'] = states.DEPLOYING
                time.sleep(2)
                self.node['provision_state'] = states.ACTIVE

        handler = handler_deploying(self.node)
        handler.start()

        with task_manager.acquire([self.node['uuid']], shared=False) as task:
            task.resources[0].driver.deploy.deploy(task, self.node)
        self.mox.VerifyAll()

    def test_deploy_fail(self):

        def refresh():
            pass

        self.node.refresh = refresh

        self.mox.StubOutWithMock(pxe, '_create_pxe_config')
        self.mox.StubOutWithMock(pxe, '_cache_images')
        self.mox.StubOutWithMock(pxe, '_get_tftp_image_info')
        pxe._get_tftp_image_info(self.node).AndReturn(None)
        pxe._create_pxe_config(mox.IgnoreArg(), self.node, None).\
            AndReturn(None)
        pxe._cache_images(self.node, None).AndReturn(None)
        self.mox.ReplayAll()

        class handler_deploying(threading.Thread):
            def __init__(self, node):
                threading.Thread.__init__(self)
                self.node = node

            def run(self):
                self.node['provision_state'] = states.DEPLOYING
                time.sleep(2)
                self.node['provision_state'] = states.DEPLOYFAIL

        handler = handler_deploying(self.node)
        handler.start()
        with task_manager.acquire([self.node['uuid']], shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              task.resources[0].driver.deploy.deploy,
                              task,
                              self.node)
        self.mox.VerifyAll()

    def test_deploy_timeout_fail(self):

        def refresh():
            pass

        self.node.refresh = refresh

        self.mox.StubOutWithMock(pxe, '_create_pxe_config')
        self.mox.StubOutWithMock(pxe, '_cache_images')
        self.mox.StubOutWithMock(pxe, '_get_tftp_image_info')
        pxe._get_tftp_image_info(self.node).AndReturn(None)
        pxe._create_pxe_config(mox.IgnoreArg(), self.node, None).\
            AndReturn(None)
        pxe._cache_images(self.node, None).AndReturn(None)
        self.mox.ReplayAll()

        CONF.set_default('pxe_deploy_timeout', 2, group='pxe')

        with task_manager.acquire([self.node['uuid']], shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              task.resources[0].driver.deploy.deploy,
                              task,
                              self.node)
        self.mox.VerifyAll()

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

        self.mox.StubOutWithMock(pxe, '_get_tftp_image_info')
        pxe._get_tftp_image_info(self.node).AndReturn(image_info)
        self.mox.ReplayAll()

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
            CONF.set_default('tftp_master_path', tftp_master_dir, group='pxe')
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

        with task_manager.acquire([self.node['uuid']], shared=False) as task:
            task.resources[0].driver.deploy.tear_down(task, self.node)
        self.mox.VerifyAll()
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
