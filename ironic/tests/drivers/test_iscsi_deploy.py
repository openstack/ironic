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

import mock
import os
import tempfile

from oslo.config import cfg

from ironic.common import exception
from ironic.common import utils
from ironic.db import api as dbapi
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import iscsi_deploy
from ironic.openstack.common import context
from ironic.openstack.common import fileutils
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()


class IscsiDeployValidateParametersTestCase(base.TestCase):

    def setUp(self):
        super(IscsiDeployValidateParametersTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()

    def test_parse_instance_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_pxe',
                                          instance_info=INST_INFO_DICT)
        info = iscsi_deploy.parse_instance_info(node)
        self.assertIsNotNone(info.get('image_source'))
        self.assertIsNotNone(info.get('root_gb'))
        self.assertEqual(0, info.get('ephemeral_gb'))

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
        for _id, opt in enumerate(['true', 'TRUE', 'True', 't',
                                   'on', 'yes', 'y', '1']):
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(self.context, id=_id,
                                              uuid=utils.generate_uuid(),
                                              instance_info=info)
            data = iscsi_deploy.parse_instance_info(node)
            self.assertTrue(data.get('preserve_ephemeral'))

    def test_parse_instance_info_valid_preserve_ephemeral_false(self):
        info = dict(INST_INFO_DICT)
        for _id, opt in enumerate(['false', 'FALSE', 'False', 'f',
                                   'off', 'no', 'n', '0']):
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(self.context, id=_id,
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


class IscsiDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IscsiDeployPrivateMethodsTestCase, self).setUp()
        n = {
              'driver': 'fake_pxe',
              'instance_info': INST_INFO_DICT,
              'driver_info': DRV_INFO_DICT,
        }
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
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
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
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
                                                 [(uuid, image_path)])
        self.assertEqual('glance://image_uuid', uuid)
        self.assertEqual(os.path.join(temp_dir,
                                      self.node.uuid,
                                      'disk'),
                         image_path)
