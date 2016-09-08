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

from ironic.common import pxe_utils
from ironic.conductor import task_manager
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils

CONF = cfg.CONF


class TestPXEUtils(db_base.DbTestCase):

    def setUp(self):
        super(TestPXEUtils, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake")

        common_pxe_options = {
            'deployment_aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-'
                                   u'c02d7f33c123/deploy_kernel',
            'aki_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'kernel',
            'ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'ramdisk',
            'pxe_append_params': 'test_param',
            'deployment_ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7'
                                   u'f33c123/deploy_ramdisk',
            'root_device': 'vendor=fake,size=123',
            'ipa-api-url': 'http://192.168.122.184:6385',
            'ipxe_timeout': 0,
        }

        self.pxe_options = {
            'deployment_key': '0123456789ABCDEFGHIJKLMNOPQRSTUV',
            'iscsi_target_iqn': u'iqn-1be26c0b-03f2-4d2e-ae87-c02d7f33'
                                u'c123',
            'deployment_id': u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'ironic_api_url': 'http://192.168.122.184:6385',
            'disk': 'cciss/c0d0,sda,hda,vda',
            'boot_option': 'netboot',
            'ipa-driver-name': 'pxe_ssh',
        }
        self.pxe_options.update(common_pxe_options)

        self.pxe_options_bios = {
            'boot_mode': 'bios',
        }
        self.pxe_options_bios.update(self.pxe_options)

        self.pxe_options_uefi = {
            'boot_mode': 'uefi',
        }
        self.pxe_options_uefi.update(self.pxe_options)

        self.agent_pxe_options = {
            'ipa-driver-name': 'agent_ipmitool',
        }
        self.agent_pxe_options.update(common_pxe_options)

        self.ipxe_options = self.pxe_options.copy()
        self.ipxe_options.update({
            'deployment_aki_path': 'http://1.2.3.4:1234/deploy_kernel',
            'deployment_ari_path': 'http://1.2.3.4:1234/deploy_ramdisk',
            'aki_path': 'http://1.2.3.4:1234/kernel',
            'ari_path': 'http://1.2.3.4:1234/ramdisk',
        })

        self.ipxe_options_bios = {
            'boot_mode': 'bios',
        }
        self.ipxe_options_bios.update(self.ipxe_options)

        self.ipxe_options_timeout = self.ipxe_options_bios.copy()
        self.ipxe_options_timeout.update({
            'ipxe_timeout': 120
        })

        self.ipxe_options_uefi = {
            'boot_mode': 'uefi',
        }
        self.ipxe_options_uefi.update(self.ipxe_options)

        self.node = object_utils.create_test_node(self.context)

    def test__build_pxe_config(self):

        rendered_template = pxe_utils._build_pxe_config(
            self.pxe_options_bios, CONF.pxe.pxe_config_template,
            '{{ ROOT }}', '{{ DISK_IDENTIFIER }}')

        expected_template = open(
            'ironic/tests/unit/drivers/pxe_config.template').read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test__build_ipxe_bios_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # http://docs.openstack.org/developer/ironic/deploy/install-guide.html
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = pxe_utils._build_pxe_config(
            self.ipxe_options_bios, CONF.pxe.pxe_config_template,
            '{{ ROOT }}', '{{ DISK_IDENTIFIER }}')

        expected_template = open(
            'ironic/tests/unit/drivers/ipxe_config.template').read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test__build_ipxe_timeout_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # http://docs.openstack.org/developer/ironic/deploy/install-guide.html
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = pxe_utils._build_pxe_config(
            self.ipxe_options_timeout, CONF.pxe.pxe_config_template,
            '{{ ROOT }}', '{{ DISK_IDENTIFIER }}')

        tpl_file = 'ironic/tests/unit/drivers/ipxe_config_timeout.template'
        expected_template = open(tpl_file).read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test__build_ipxe_uefi_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # http://docs.openstack.org/developer/ironic/deploy/install-guide.html
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = pxe_utils._build_pxe_config(
            self.ipxe_options_uefi, CONF.pxe.pxe_config_template,
            '{{ ROOT }}', '{{ DISK_IDENTIFIER }}')

        expected_template = open(
            'ironic/tests/unit/drivers/'
            'ipxe_uefi_config.template').read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test__build_elilo_config(self):
        pxe_opts = self.pxe_options
        pxe_opts['boot_mode'] = 'uefi'
        self.config(
            uefi_pxe_config_template=('ironic/drivers/modules/'
                                      'elilo_efi_pxe_config.template'),
            group='pxe'
        )
        rendered_template = pxe_utils._build_pxe_config(
            pxe_opts, CONF.pxe.uefi_pxe_config_template,
            '{{ ROOT }}', '{{ DISK_IDENTIFIER }}')

        expected_template = open(
            'ironic/tests/unit/drivers/elilo_efi_pxe_config.template'
        ).read().rstrip()

        self.assertEqual(six.text_type(expected_template), rendered_template)

    def test__build_grub_config(self):
        pxe_opts = self.pxe_options
        pxe_opts['boot_mode'] = 'uefi'
        pxe_opts['tftp_server'] = '192.0.2.1'
        rendered_template = pxe_utils._build_pxe_config(
            pxe_opts, CONF.pxe.uefi_pxe_config_template,
            '(( ROOT ))', '(( DISK_IDENTIFIER ))')

        template_file = 'ironic/tests/unit/drivers/pxe_grub_config.template'
        expected_template = open(template_file).read().rstrip()

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
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-66'),
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67'),
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
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-66'),
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67'),
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
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
        ]
        unlink_calls = [
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-66'),
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
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

    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch.object(pxe_utils, '_build_pxe_config', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config(self, ensure_tree_mock, build_mock,
                               write_mock):
        build_mock.return_value = self.pxe_options_bios
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options_bios,
                                        CONF.pxe.pxe_config_template)
            build_mock.assert_called_with(self.pxe_options_bios,
                                          CONF.pxe.pxe_config_template,
                                          '{{ ROOT }}',
                                          '{{ DISK_IDENTIFIER }}')
        ensure_calls = [
            mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
            mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'))
        ]
        ensure_tree_mock.assert_has_calls(ensure_calls)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path, self.pxe_options_bios)

    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.pxe_utils._build_pxe_config', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_elilo(self, ensure_tree_mock, build_mock,
                                          write_mock, link_ip_configs_mock):
        self.config(
            uefi_pxe_config_template=('ironic/drivers/modules/'
                                      'elilo_efi_pxe_config.template'),
            group='pxe'
        )
        build_mock.return_value = self.pxe_options_uefi
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options_uefi,
                                        CONF.pxe.uefi_pxe_config_template)

            ensure_calls = [
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'))
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            build_mock.assert_called_with(self.pxe_options_uefi,
                                          CONF.pxe.uefi_pxe_config_template,
                                          '{{ ROOT }}',
                                          '{{ DISK_IDENTIFIER }}')
            link_ip_configs_mock.assert_called_once_with(task, True)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path, self.pxe_options_uefi)

    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.pxe_utils._build_pxe_config', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_grub(self, ensure_tree_mock, build_mock,
                                         write_mock, link_ip_configs_mock):
        build_mock.return_value = self.pxe_options_uefi
        grub_tmplte = "ironic/drivers/modules/pxe_grub_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options_uefi,
                                        grub_tmplte)

            ensure_calls = [
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'))
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            build_mock.assert_called_with(self.pxe_options_uefi,
                                          grub_tmplte,
                                          '(( ROOT ))',
                                          '(( DISK_IDENTIFIER ))')
            link_ip_configs_mock.assert_called_once_with(task, False)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path, self.pxe_options_uefi)

    @mock.patch('ironic.common.pxe_utils._link_mac_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.pxe_utils._build_pxe_config', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_uefi_ipxe(self, ensure_tree_mock, build_mock,
                                         write_mock, link_mac_pxe_mock):
        self.config(ipxe_enabled=True, group='pxe')
        build_mock.return_value = self.ipxe_options_uefi
        ipxe_template = "ironic/drivers/modules/ipxe_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.ipxe_options_uefi,
                                        ipxe_template)

            ensure_calls = [
                mock.call(os.path.join(CONF.deploy.http_root, self.node.uuid)),
                mock.call(os.path.join(CONF.deploy.http_root, 'pxelinux.cfg'))
            ]
            ensure_tree_mock.assert_has_calls(ensure_calls)
            build_mock.assert_called_with(self.ipxe_options_uefi,
                                          ipxe_template,
                                          '{{ ROOT }}',
                                          '{{ DISK_IDENTIFIER }}')
            link_mac_pxe_mock.assert_called_once_with(task)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      self.ipxe_options_uefi)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test_clean_up_pxe_config(self, unlink_mock, rmtree_mock):
        address = "aa:aa:aa:aa:aa:aa"
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.clean_up_pxe_config(task)

        unlink_mock.assert_called_once_with("/tftpboot/pxelinux.cfg/01-%s"
                                            % address.replace(':', '-'))
        rmtree_mock.assert_called_once_with(
            os.path.join(CONF.pxe.tftp_root, self.node.uuid))

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
        expected_info = [{'opt_name': 'bootfile-name',
                          'opt_value': 'fake-bootfile',
                          'ip_version': ip_version},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': ip_version},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1',
                          'ip_version': ip_version},
                         ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected_info,
                             pxe_utils.dhcp_options_for_instance(task))

    def test_dhcp_options_for_instance(self):
        self._dhcp_options_for_instance(ip_version=4)

    def test_dhcp_options_for_instance_ipv6(self):
        self._dhcp_options_for_instance(ip_version=6)

    def _test_get_deploy_kr_info(self, expected_dir):
        node_uuid = 'fake-node'
        driver_info = {
            'deploy_kernel': 'glance://deploy-kernel',
            'deploy_ramdisk': 'glance://deploy-ramdisk',
        }

        expected = {
            'deploy_kernel': ('glance://deploy-kernel',
                              expected_dir + '/fake-node/deploy_kernel'),
            'deploy_ramdisk': ('glance://deploy-ramdisk',
                               expected_dir + '/fake-node/deploy_ramdisk'),
        }

        kr_info = pxe_utils.get_deploy_kr_info(node_uuid, driver_info)
        self.assertEqual(expected, kr_info)

    def test_get_deploy_kr_info(self):
        expected_dir = '/tftp'
        self.config(tftp_root=expected_dir, group='pxe')
        self._test_get_deploy_kr_info(expected_dir)

    def test_get_deploy_kr_info_ipxe(self):
        expected_dir = '/http'
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root=expected_dir, group='deploy')
        self._test_get_deploy_kr_info(expected_dir)

    def test_get_deploy_kr_info_bad_driver_info(self):
        self.config(tftp_root='/tftp', group='pxe')
        node_uuid = 'fake-node'
        driver_info = {}
        self.assertRaises(KeyError,
                          pxe_utils.get_deploy_kr_info,
                          node_uuid,
                          driver_info)

    def _dhcp_options_for_instance_ipxe(self, task, boot_file):
        self.config(tftp_server='192.0.2.1', group='pxe')
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_url='http://192.0.3.2:1234', group='deploy')
        self.config(ipxe_boot_script='/test/boot.ipxe', group='pxe')

        self.config(dhcp_provider='isc', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': '!175,bootfile-name',
                          'opt_value': boot_file,
                          'ip_version': 4},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': 'bootfile-name',
                          'opt_value': expected_boot_script_url,
                          'ip_version': 4}]

        self.assertItemsEqual(expected_info,
                              pxe_utils.dhcp_options_for_instance(task))

        self.config(dhcp_provider='neutron', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': 'tag:!ipxe,bootfile-name',
                          'opt_value': boot_file,
                          'ip_version': 4},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1',
                          'ip_version': 4},
                         {'opt_name': 'tag:ipxe,bootfile-name',
                          'opt_value': expected_boot_script_url,
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
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider')
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

    @mock.patch('ironic.common.utils.rmtree_without_raise')
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider')
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

            unlink_mock.assert_called_once_with(
                '/httpboot/pxelinux.cfg/aa-aa-aa-aa-aa-aa')
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.deploy.http_root, self.node.uuid))
