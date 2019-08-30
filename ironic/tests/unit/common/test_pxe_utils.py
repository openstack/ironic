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
from oslo_config import cfg
from oslo_utils import uuidutils
import six

from ironic.common import exception
from ironic.common import pxe_utils
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils

CONF = cfg.CONF


# Prevent /httpboot validation on creating the node
@mock.patch('ironic.drivers.modules.pxe.PXEBoot.__init__', lambda self: None)
class TestPXEUtils(db_base.DbTestCase):

    def setUp(self):
        super(TestPXEUtils, self).setUp()

        self.pxe_options = {
            'deployment_aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-'
                                   u'c02d7f33c123/deploy_kernel',
            'aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'kernel',
            'ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'ramdisk',
            'pxe_append_params': 'test_param',
            'deployment_ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7'
                                   u'f33c123/deploy_ramdisk',
            'ipa-api-url': 'http://192.168.122.184:6385',
            'ipxe_timeout': 0,
            'ramdisk_opts': 'ramdisk_param',
        }

        self.ipxe_options = self.pxe_options.copy()
        self.ipxe_options.update({
            'deployment_aki_path': 'http://1.2.3.4:1234/deploy_kernel',
            'deployment_ari_path': 'http://1.2.3.4:1234/deploy_ramdisk',
            'aki_path': 'http://1.2.3.4:1234/kernel',
            'ari_path': 'http://1.2.3.4:1234/ramdisk',
            'initrd_filename': 'deploy_ramdisk',
        })

        self.ipxe_options_timeout = self.ipxe_options.copy()
        self.ipxe_options_timeout.update({
            'ipxe_timeout': 120
        })

        self.ipxe_options_boot_from_volume_no_extra_volume = \
            self.ipxe_options.copy()
        self.ipxe_options_boot_from_volume_no_extra_volume.update({
            'boot_from_volume': True,
            'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn',
            'iscsi_initiator_iqn': 'fake_iqn',
            'iscsi_volumes': [],
            'username': 'fake_username',
            'password': 'fake_password',
        })

        self.ipxe_options_boot_from_volume_extra_volume = \
            self.ipxe_options.copy()
        self.ipxe_options_boot_from_volume_extra_volume.update({
            'boot_from_volume': True,
            'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn',
            'iscsi_initiator_iqn': 'fake_iqn',
            'iscsi_volumes': [{'url': 'iscsi:fake_host::3260:1:fake_iqn',
                               'username': 'fake_username_1',
                               'password': 'fake_password_1',
                               }],
            'username': 'fake_username',
            'password': 'fake_password',
        })

        self.ipxe_options_boot_from_volume_no_extra_volume.pop(
            'initrd_filename', None)
        self.ipxe_options_boot_from_volume_extra_volume.pop(
            'initrd_filename', None)

        self.node = object_utils.create_test_node(self.context)

    def test_default_pxe_config(self):

        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.pxe_options,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        with open('ironic/tests/unit/drivers/pxe_config.template') as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_ipxe_boot_script(self):
        rendered_template = utils.render_template(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

        with open('ironic/tests/unit/drivers/boot.ipxe') as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_ipxe_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # https://docs.openstack.org/ironic/latest/install/
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.ipxe_options,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/ipxe_config.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_ipxe_timeout_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # https://docs.openstack.org/ironic/latest/install/
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.ipxe_options_timeout,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/ipxe_config_timeout.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_ipxe_boot_from_volume_config(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.ipxe_options_boot_from_volume_extra_volume,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_volume_extra_volume.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_ipxe_boot_from_volume_config_no_extra_volumes(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')

        pxe_options = self.ipxe_options_boot_from_volume_no_extra_volume
        pxe_options['iscsi_volumes'] = []

        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': pxe_options,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_volume_no_extra_volumes.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()
        self.assertEqual(six.text_type(expected_template), rendered_template)

    # NOTE(TheJulia): Remove elilo support after the deprecation period,
    # in the Queens release.
    def test_default_elilo_config(self):
        pxe_opts = self.pxe_options
        pxe_opts['boot_mode'] = 'uefi'
        self.config(
            uefi_pxe_config_template=('ironic/drivers/modules/'
                                      'elilo_efi_pxe_config.template'),
            group='pxe'
        )
        rendered_template = utils.render_template(
            CONF.pxe.uefi_pxe_config_template,
            {'pxe_options': pxe_opts,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/elilo_efi_pxe_config.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test_default_grub_config(self):
        pxe_opts = self.pxe_options
        pxe_opts['boot_mode'] = 'uefi'
        pxe_opts['tftp_server'] = '192.0.2.1'
        rendered_template = utils.render_template(
            CONF.pxe.uefi_pxe_config_template,
            {'pxe_options': pxe_opts,
             'ROOT': '(( ROOT ))',
             'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'})

        templ_file = 'ironic/tests/unit/drivers/pxe_grub_config.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test__write_mac_pxe_configs(self, unlink_mock, create_link_mock):
        port_1 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:66', uuid=uuidutils.generate_uuid())
        port_2 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:67', uuid=uuidutils.generate_uuid())
        create_link_calls = [
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-66'),
            mock.call('/tftpboot/11:22:33:44:55:66.conf'),
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67'),
            mock.call('/tftpboot/11:22:33:44:55:67.conf')
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port_1, port_2]
            pxe_utils._link_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test__write_infiniband_mac_pxe_configs(
            self, unlink_mock, create_link_mock):
        client_id1 = (
            '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:13:92')
        port_1 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:66', uuid=uuidutils.generate_uuid(),
            extra={'client-id': client_id1})
        client_id2 = (
            '20:00:55:04:01:fe:80:00:00:00:00:00:00:00:02:c9:02:00:23:45:12')
        port_2 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:67', uuid=uuidutils.generate_uuid(),
            extra={'client-id': client_id2})
        create_link_calls = [
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/20-11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-66'),
            mock.call('/tftpboot/11:22:33:44:55:66.conf'),
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67'),
            mock.call('/tftpboot/11:22:33:44:55:67.conf')
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port_1, port_2]
            pxe_utils._link_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test__write_mac_ipxe_configs(self, unlink_mock, create_link_mock):
        self.config(ipxe_enabled=True, group='pxe')
        port_1 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:66', uuid=uuidutils.generate_uuid())
        port_2 = object_utils.create_test_port(
            self.context, node_id=self.node.id,
            address='11:22:33:44:55:67', uuid=uuidutils.generate_uuid())
        create_link_calls = [
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-66'),
            mock.call('/httpboot/11:22:33:44:55:66.conf'),
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
            mock.call('/httpboot/11:22:33:44:55:67.conf'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port_1, port_2]
            pxe_utils._link_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider',
                autospec=True)
    def test__link_ip_address_pxe_configs(self, provider_mock, unlink_mock,
                                          create_link_mock):
        ip_address = '10.10.0.1'
        address = "aa:aa:aa:aa:aa:aa"
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        provider_mock.get_ip_addresses.return_value = [ip_address]
        create_link_calls = [
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      u'/tftpboot/10.10.0.1.conf'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils._link_ip_address_pxe_configs(task, False)

        unlink_mock.assert_called_once_with('/tftpboot/10.10.0.1.conf')
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config(self, ensure_tree_mock, render_mock,
                               write_mock, chmod_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'}
            )
        node_dir = os.path.join(CONF.pxe.tftp_root, self.node.uuid)
        pxe_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
        ensure_calls = [
            mock.call(node_dir), mock.call(pxe_dir),
        ]
        ensure_tree_mock.assert_has_calls(ensure_calls)
        chmod_mock.assert_not_called()

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_set_dir_permission(self, ensure_tree_mock,
                                                  render_mock,
                                                  write_mock, chmod_mock):
        self.config(dir_permission=0o755, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'}
            )
        node_dir = os.path.join(CONF.pxe.tftp_root, self.node.uuid)
        pxe_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
        ensure_calls = [
            mock.call(node_dir), mock.call(pxe_dir),
        ]
        ensure_tree_mock.assert_has_calls(ensure_calls)
        chmod_calls = [mock.call(node_dir, 0o755), mock.call(pxe_dir, 0o755)]
        chmod_mock.assert_has_calls(chmod_calls)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_existing_dirs(self, ensure_tree_mock,
                                             render_mock,
                                             write_mock, chmod_mock,
                                             isdir_mock):
        self.config(dir_permission=0o755, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            isdir_mock.return_value = True
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'}
            )
        ensure_tree_mock.assert_has_calls([])
        chmod_mock.assert_not_called()
        isdir_mock.assert_has_calls([])
        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    # NOTE(TheJulia): Remove elilo support after the deprecation period,
    # in the Queens release.
    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_elilo(self, ensure_tree_mock, render_mock,
                                          write_mock, link_ip_configs_mock,
                                          chmod_mock):
        self.config(
            uefi_pxe_config_template=('ironic/drivers/modules/'
                                      'elilo_efi_pxe_config.template'),
            group='pxe'
        )
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.uefi_pxe_config_template)

            ensure_calls = [
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')),
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            chmod_mock.assert_not_called()
            render_mock.assert_called_with(
                CONF.pxe.uefi_pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})
            link_ip_configs_mock.assert_called_once_with(task, True)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_grub(self, ensure_tree_mock, render_mock,
                                         write_mock, link_ip_configs_mock,
                                         chmod_mock):
        grub_tmplte = "ironic/drivers/modules/pxe_grub_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        grub_tmplte)

            ensure_calls = [
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')),
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            chmod_mock.assert_not_called()
            render_mock.assert_called_with(
                grub_tmplte,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'})
            link_ip_configs_mock.assert_called_once_with(task, False)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_mac_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_mac_address(
            self, ensure_tree_mock, render_mock,
            write_mock, link_ip_configs_mock,
            link_mac_pxe_configs_mock, chmod_mock):
        # TODO(TheJulia): We should... like... fix the template to
        # enable mac address usage.....
        grub_tmplte = "ironic/drivers/modules/pxe_grub_config.template"
        self.config(dhcp_provider='none', group='dhcp')
        link_ip_configs_mock.side_effect = \
            exception.FailedToGetIPAddressOnPort(port_id='blah')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        grub_tmplte)

            ensure_calls = [
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')),
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            chmod_mock.assert_not_called()
            render_mock.assert_called_with(
                grub_tmplte,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'})
            link_mac_pxe_configs_mock.assert_called_once_with(task)
            link_ip_configs_mock.assert_called_once_with(task, False)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_mac_pxe_configs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_ipxe(self, ensure_tree_mock, render_mock,
                                         write_mock, link_mac_pxe_mock,
                                         chmod_mock):
        self.config(ipxe_enabled=True, group='pxe')
        ipxe_template = "ironic/drivers/modules/ipxe_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.ipxe_options,
                                        ipxe_template)

            ensure_calls = [
                mock.call(os.path.join(CONF.deploy.http_root, self.node.uuid)),
                mock.call(os.path.join(CONF.deploy.http_root, 'pxelinux.cfg')),
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            chmod_mock.assert_not_called()
            render_mock.assert_called_with(
                ipxe_template,
                {'pxe_options': self.ipxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})
            link_mac_pxe_mock.assert_called_once_with(task)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test_clean_up_pxe_config(self, unlink_mock, rmtree_mock):
        address = "aa:aa:aa:aa:aa:aa"
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.clean_up_pxe_config(task)

        ensure_calls = [
            mock.call("/tftpboot/pxelinux.cfg/01-%s"
                      % address.replace(':', '-')),
            mock.call("/tftpboot/%s.conf" % address)
        ]

        unlink_mock.assert_has_calls(ensure_calls)
        rmtree_mock.assert_called_once_with(
            os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch.object(os.path, 'isfile', lambda path: False)
    @mock.patch('ironic.common.utils.file_has_content', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_ipxe_boot_script(self, render_mock, write_mock,
                                     file_has_content_mock):
        render_mock.return_value = 'foo'
        pxe_utils.create_ipxe_boot_script()
        self.assertFalse(file_has_content_mock.called)
        write_mock.assert_called_once_with(
            os.path.join(CONF.deploy.http_root,
                         os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

    @mock.patch.object(os.path, 'isfile', lambda path: True)
    @mock.patch('ironic.common.utils.file_has_content', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_ipxe_boot_script_copy_file_different(
            self, render_mock, write_mock, file_has_content_mock):
        file_has_content_mock.return_value = False
        render_mock.return_value = 'foo'
        pxe_utils.create_ipxe_boot_script()
        file_has_content_mock.assert_called_once_with(
            os.path.join(CONF.deploy.http_root,
                         os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')
        write_mock.assert_called_once_with(
            os.path.join(CONF.deploy.http_root,
                         os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo')
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

    @mock.patch.object(os.path, 'isfile', lambda path: True)
    @mock.patch('ironic.common.utils.file_has_content', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_ipxe_boot_script_already_exists(self, render_mock,
                                                    write_mock,
                                                    file_has_content_mock):
        file_has_content_mock.return_value = True
        pxe_utils.create_ipxe_boot_script()
        self.assertFalse(write_mock.called)

    def test__get_pxe_mac_path(self):
        mac = '00:11:22:33:44:55:66'
        self.assertEqual('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-66',
                         pxe_utils._get_pxe_mac_path(mac))

    def test__get_pxe_mac_path_ipxe(self):
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root='/httpboot', group='deploy')
        mac = '00:11:22:33:AA:BB:CC'
        self.assertEqual('/httpboot/pxelinux.cfg/00-11-22-33-aa-bb-cc',
                         pxe_utils._get_pxe_mac_path(mac))

    def test__get_pxe_ip_address_path(self):
        ipaddress = '10.10.0.1'
        self.assertEqual('/tftpboot/10.10.0.1.conf',
                         pxe_utils._get_pxe_ip_address_path(ipaddress, False))

    def test_get_root_dir(self):
        expected_dir = '/tftproot'
        self.config(ipxe_enabled=False, group='pxe')
        self.config(tftp_root=expected_dir, group='pxe')
        self.assertEqual(expected_dir, pxe_utils.get_root_dir())

    def test_get_root_dir_ipxe(self):
        expected_dir = '/httpboot'
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root=expected_dir, group='deploy')
        self.assertEqual(expected_dir, pxe_utils.get_root_dir())

    def test_get_pxe_config_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.tftp_root,
                                      self.node.uuid,
                                      'config'),
                         pxe_utils.get_pxe_config_file_path(self.node.uuid))

    def _dhcp_options_for_instance(self, ip_version=4):
        self.config(ip_version=ip_version, group='pxe')
        self.config(tftp_server='192.0.2.1', group='pxe')
        self.config(pxe_bootfile_name='fake-bootfile', group='pxe')
        self.config(tftp_root='/tftp-path/', group='pxe')
        expected_info = [{'opt_name': '67',
                          'opt_value': 'fake-bootfile',
                          'ip_version': ip_version},
                         {'opt_name': '210',
                          'opt_value': '/tftp-path/',
                          'ip_version': ip_version},
                         {'opt_name': '66',
                          'opt_value': '192.0.2.1',
                          'ip_version': ip_version},
                         {'opt_name': '150',
                          'opt_value': '192.0.2.1',
                          'ip_version': ip_version},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': ip_version}
                         ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected_info,
                             pxe_utils.dhcp_options_for_instance(task))

    def test_dhcp_options_for_instance(self):
        self._dhcp_options_for_instance(ip_version=4)

    def test_dhcp_options_for_instance_ipv6(self):
        self._dhcp_options_for_instance(ip_version=6)

    def _test_get_kernel_ramdisk_info(self, expected_dir, mode='deploy'):
        node_uuid = 'fake-node'

        driver_info = {
            '%s_kernel' % mode: 'glance://%s-kernel' % mode,
            '%s_ramdisk' % mode: 'glance://%s-ramdisk' % mode,
        }

        expected = {}
        for k, v in driver_info.items():
            expected[k] = (v, expected_dir + '/fake-node/%s' % k)
        kr_info = pxe_utils.get_kernel_ramdisk_info(node_uuid,
                                                    driver_info,
                                                    mode=mode)
        self.assertEqual(expected, kr_info)

    def test_get_kernel_ramdisk_info(self):
        expected_dir = '/tftp'
        self.config(tftp_root=expected_dir, group='pxe')
        self._test_get_kernel_ramdisk_info(expected_dir)

    def test_get_kernel_ramdisk_info_ipxe(self):
        expected_dir = '/http'
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root=expected_dir, group='deploy')
        self._test_get_kernel_ramdisk_info(expected_dir)

    def test_get_kernel_ramdisk_info_bad_driver_info(self):
        self.config(tftp_root='/tftp', group='pxe')
        node_uuid = 'fake-node'
        driver_info = {}
        self.assertRaises(KeyError,
                          pxe_utils.get_kernel_ramdisk_info,
                          node_uuid,
                          driver_info)

    def test_get_rescue_kr_info(self):
        expected_dir = '/tftp'
        self.config(tftp_root=expected_dir, group='pxe')
        self._test_get_kernel_ramdisk_info(expected_dir, mode='rescue')

    def test_get_rescue_kr_info_ipxe(self):
        expected_dir = '/http'
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root=expected_dir, group='deploy')
        self._test_get_kernel_ramdisk_info(expected_dir, mode='rescue')

    def _dhcp_options_for_instance_ipxe(self, task, boot_file):
        self.config(tftp_server='192.0.2.1', group='pxe')
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_url='http://192.0.3.2:1234', group='deploy')
        self.config(ipxe_boot_script='/test/boot.ipxe', group='pxe')

        self.config(dhcp_provider='isc', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': '!175,67',
                          'opt_value': boot_file,
                          'ip_version': 4},
                         {'opt_name': '66',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': '150',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': '67',
                          'opt_value': expected_boot_script_url,
                          'ip_version': 4},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4}]

        self.assertItemsEqual(expected_info,
                              pxe_utils.dhcp_options_for_instance(task))

        self.config(dhcp_provider='neutron', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': 'tag:!ipxe,67',
                          'opt_value': boot_file,
                          'ip_version': 4},
                         {'opt_name': '66',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': '150',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': 'tag:ipxe,67',
                          'opt_value': expected_boot_script_url,
                          'ip_version': 4},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4}]

        self.assertItemsEqual(expected_info,
                              pxe_utils.dhcp_options_for_instance(task))

    def test_dhcp_options_for_instance_ipxe_bios(self):
        boot_file = 'fake-bootfile-bios'
        self.config(pxe_bootfile_name=boot_file, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self._dhcp_options_for_instance_ipxe(task, boot_file)

    def test_dhcp_options_for_instance_ipxe_uefi(self):
        boot_file = 'fake-bootfile-uefi'
        self.config(uefi_pxe_bootfile_name=boot_file, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            self._dhcp_options_for_instance_ipxe(task, boot_file)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider',
                autospec=True)
    def test_clean_up_pxe_config_uefi(self, provider_mock, unlink_mock,
                                      rmtree_mock):
        ip_address = '10.10.0.1'
        address = "aa:aa:aa:aa:aa:aa"
        properties = {'capabilities': 'boot_mode:uefi'}
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        provider_mock.get_ip_addresses.return_value = [ip_address]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = properties
            pxe_utils.clean_up_pxe_config(task)

            unlink_calls = [
                mock.call('/tftpboot/10.10.0.1.conf'),
                mock.call('/tftpboot/0A0A0001.conf')
            ]
            unlink_mock.assert_has_calls(unlink_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider',
                autospec=True)
    def test_clean_up_pxe_config_uefi_mac_address(
            self, provider_mock, unlink_mock, rmtree_mock):
        ip_address = '10.10.0.1'
        address = "aa:aa:aa:aa:aa:aa"
        properties = {'capabilities': 'boot_mode:uefi'}
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        provider_mock.get_ip_addresses.return_value = [ip_address]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = properties
            pxe_utils.clean_up_pxe_config(task)

            unlink_calls = [
                mock.call('/tftpboot/10.10.0.1.conf'),
                mock.call('/tftpboot/0A0A0001.conf'),
                mock.call('/tftpboot/pxelinux.cfg/01-%s' %
                          address.replace(':', '-'))
            ]

            unlink_mock.assert_has_calls(unlink_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider',
                autospec=True)
    def test_clean_up_pxe_config_uefi_instance_info(self,
                                                    provider_mock, unlink_mock,
                                                    rmtree_mock):
        ip_address = '10.10.0.1'
        address = "aa:aa:aa:aa:aa:aa"
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        provider_mock.get_ip_addresses.return_value = [ip_address]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.instance_info['deploy_boot_mode'] = 'uefi'
            pxe_utils.clean_up_pxe_config(task)

            unlink_calls = [
                mock.call('/tftpboot/10.10.0.1.conf'),
                mock.call('/tftpboot/0A0A0001.conf')
            ]
            unlink_mock.assert_has_calls(unlink_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test_clean_up_ipxe_config_uefi(self, unlink_mock, rmtree_mock):
        self.config(ipxe_enabled=True, group='pxe')
        address = "aa:aa:aa:aa:aa:aa"
        properties = {'capabilities': 'boot_mode:uefi'}
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = properties
            pxe_utils.clean_up_pxe_config(task)

            ensure_calls = [
                mock.call("/httpboot/pxelinux.cfg/%s"
                          % address.replace(':', '-')),
                mock.call("/httpboot/%s.conf" % address)
            ]

            unlink_mock.assert_has_calls(ensure_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.deploy.http_root, self.node.uuid))

    def test_get_tftp_path_prefix_with_trailing_slash(self):
        self.config(tftp_root='/tftpboot-path/', group='pxe')
        path_prefix = pxe_utils.get_tftp_path_prefix()
        self.assertEqual(path_prefix, '/tftpboot-path/')

    def test_get_tftp_path_prefix_without_trailing_slash(self):
        self.config(tftp_root='/tftpboot-path', group='pxe')
        path_prefix = pxe_utils.get_tftp_path_prefix()
        self.assertEqual(path_prefix, '/tftpboot-path/')

    def test_get_path_relative_to_tftp_root_with_trailing_slash(self):
        self.config(tftp_root='/tftpboot-path/', group='pxe')
        test_file_path = '/tftpboot-path/pxelinux.cfg/test'
        relpath = pxe_utils.get_path_relative_to_tftp_root(test_file_path)
        self.assertEqual(relpath, 'pxelinux.cfg/test')

    def test_get_path_relative_to_tftp_root_without_trailing_slash(self):
        self.config(tftp_root='/tftpboot-path', group='pxe')
        test_file_path = '/tftpboot-path/pxelinux.cfg/test'
        relpath = pxe_utils.get_path_relative_to_tftp_root(test_file_path)
        self.assertEqual(relpath, 'pxelinux.cfg/test')
