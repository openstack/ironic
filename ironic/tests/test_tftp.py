#
# Copyright 2014 Rackspace, Inc
# All Rights Reserved
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

import os

import mock
from oslo.config import cfg

from ironic.common import tftp
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.objects import utils as object_utils

CONF = cfg.CONF


class TestNetworkUtils(db_base.DbTestCase):
    def setUp(self):
        super(TestNetworkUtils, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake")
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()
        self.pxe_options = {
            'deployment_key': '0123456789ABCDEFGHIJKLMNOPQRSTUV',
            'ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'ramdisk',
            'deployment_iscsi_iqn': u'iqn-1be26c0b-03f2-4d2e-ae87-c02d7f33'
                                    u'c123',
            'deployment_ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7'
                                   u'f33c123/deploy_ramdisk',
            'pxe_append_params': 'test_param',
            'aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'kernel',
            'deployment_id': u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'ironic_api_url': 'http://192.168.122.184:6385',
            'deployment_aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-'
                                   u'c02d7f33c123/deploy_kernel'
        }
        self.node = object_utils.create_test_node(self.context)

    def test_build_pxe_config(self):

        rendered_template = tftp.build_pxe_config(
            self.node, self.pxe_options, CONF.pxe.pxe_config_template)

        expected_template = open(
            'ironic/tests/drivers/pxe_config.template').read()

        self.assertEqual(rendered_template, expected_template)

    @mock.patch('ironic.common.utils.create_link_without_raise')
    @mock.patch('ironic.common.utils.unlink_without_raise')
    @mock.patch('ironic.drivers.utils.get_node_mac_addresses')
    def test__write_mac_pxe_configs(self, get_macs_mock, unlink_mock,
                                    create_link_mock):
        macs = [
            '00:11:22:33:44:55:66',
            '00:11:22:33:44:55:67'
        ]
        get_macs_mock.return_value = macs
        create_link_calls = [
            mock.call(u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66'),
            mock.call(u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-67')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66'),
            mock.call('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-67')
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            tftp._write_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.write_to_file')
    @mock.patch('ironic.common.tftp.build_pxe_config')
    @mock.patch('ironic.openstack.common.fileutils.ensure_tree')
    def test_create_pxe_config(self, ensure_tree_mock, build_mock,
                               write_mock):
        build_mock.return_value = self.pxe_options
        with task_manager.acquire(self.context, self.node.uuid) as task:
            tftp.create_pxe_config(task, self.pxe_options,
                                   CONF.pxe.pxe_config_template)
            build_mock.assert_called_with(task.node, self.pxe_options,
                                      CONF.pxe.pxe_config_template)
        ensure_calls = [
            mock.call(os.path.join(CONF.tftp.tftp_root, self.node.uuid)),
            mock.call(os.path.join(CONF.tftp.tftp_root, 'pxelinux.cfg'))
        ]
        ensure_tree_mock.has_calls(ensure_calls)

        pxe_config_file_path = tftp.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_config_file_path, self.pxe_options)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
    def test_clean_up_pxe_config(self, unlink_mock, rmtree_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            tftp.clean_up_pxe_config(task)

        unlink_mock.assert_called_once_with(
                tftp.get_pxe_config_file_path(self.node.uuid))
        rmtree_mock.assert_called_once_with(
                os.path.join(CONF.tftp.tftp_root, self.node.uuid))

    def test_get_pxe_mac_path(self):
        mac = '00:11:22:33:44:55:66'
        self.assertEqual('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66',
                         tftp.get_pxe_mac_path(mac))

    def test_get_pxe_config_file_path(self):
        self.assertEqual(os.path.join(CONF.tftp.tftp_root,
                                      self.node.uuid,
                                      'config'),
                         tftp.get_pxe_config_file_path(self.node.uuid))

    def test_dhcp_options_for_instance(self):
        self.config(tftp_server='192.0.2.1', group='tftp')
        expected_info = [{'opt_name': 'bootfile-name',
                          'opt_value': CONF.pxe.pxe_bootfile_name},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1'}
                         ]
        self.assertEqual(expected_info, tftp.dhcp_options_for_instance(
            CONF.pxe.pxe_bootfile_name))
