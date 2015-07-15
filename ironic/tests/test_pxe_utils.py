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

from ironic.common import pxe_utils
from ironic.conductor import task_manager
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.objects import utils as object_utils

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
            'pxe_append_params': 'test_param',
            'deployment_ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7'
                                   u'f33c123/deploy_ramdisk',
            'root_device': 'vendor=fake,size=123',
            'ipa-api-url': 'http://192.168.122.184:6385',
        }

        self.pxe_options = {
            'deployment_key': '0123456789ABCDEFGHIJKLMNOPQRSTUV',
            'ari_path': u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/'
                        u'ramdisk',
            'iscsi_target_iqn': u'iqn-1be26c0b-03f2-4d2e-ae87-c02d7f33'
                                u'c123',
            'deployment_id': u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
            'ironic_api_url': 'http://192.168.122.184:6385',
            'disk': 'cciss/c0d0,sda,hda,vda',
            'boot_option': 'netboot',
            'ipa-driver-name': 'pxe_ssh',
            'boot_mode': 'bios',
        }
        self.pxe_options.update(common_pxe_options)

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

        self.node = object_utils.create_test_node(self.context)

    def test__build_pxe_config(self):

        rendered_template = pxe_utils._build_pxe_config(
                self.pxe_options, CONF.pxe.pxe_config_template)

        expected_template = open(
            'ironic/tests/drivers/pxe_config.template').read().rstrip()

        self.assertEqual(unicode(expected_template), rendered_template)

    def test__build_pxe_config_with_agent(self):

        rendered_template = pxe_utils._build_pxe_config(
                self.agent_pxe_options, CONF.agent.agent_pxe_config_template)

        expected_template = open(
            'ironic/tests/drivers/agent_pxe_config.template').read().rstrip()

        self.assertEqual(unicode(expected_template), rendered_template)

    def test__build_ipxe_config(self):
        # NOTE(lucasagomes): iPXE is just an extension of the PXE driver,
        # it doesn't have it's own configuration option for template.
        # More info:
        # http://docs.openstack.org/developer/ironic/deploy/install-guide.html
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='pxe')
        rendered_template = pxe_utils._build_pxe_config(
                self.ipxe_options, CONF.pxe.pxe_config_template)

        expected_template = open(
            'ironic/tests/drivers/ipxe_config.template').read().rstrip()

        self.assertEqual(unicode(expected_template), rendered_template)

    def test__build_elilo_config(self):
        pxe_opts = self.pxe_options
        pxe_opts['boot_mode'] = 'uefi'
        rendered_template = pxe_utils._build_pxe_config(
                pxe_opts, CONF.pxe.uefi_pxe_config_template)

        expected_template = open(
            'ironic/tests/drivers/elilo_efi_pxe_config.template'
            ).read().rstrip()

        self.assertEqual(unicode(expected_template), rendered_template)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.drivers.utils.get_node_mac_addresses', autospec=True)
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
            mock.call('/tftpboot/pxelinux.cfg/01-00-11-22-33-44-55-67'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils._link_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.drivers.utils.get_node_mac_addresses', autospec=True)
    def test__write_mac_ipxe_configs(self, get_macs_mock, unlink_mock,
                                     create_link_mock):
        self.config(ipxe_enabled=True, group='pxe')
        macs = [
            '00:11:22:33:44:55:66',
            '00:11:22:33:44:55:67'
        ]
        get_macs_mock.return_value = macs
        create_link_calls = [
            mock.call(u'/httpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/00-11-22-33-44-55-66'),
            mock.call(u'/httpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/00112233445566'),
            mock.call(u'/httpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/00-11-22-33-44-55-67'),
            mock.call(u'/httpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/00112233445567'),
        ]
        unlink_calls = [
            mock.call('/httpboot/pxelinux.cfg/00-11-22-33-44-55-66'),
            mock.call('/httpboot/pxelinux.cfg/00112233445566'),
            mock.call('/httpboot/pxelinux.cfg/00-11-22-33-44-55-67'),
            mock.call('/httpboot/pxelinux.cfg/00112233445567'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils._link_mac_pxe_configs(task)

        unlink_mock.assert_has_calls(unlink_calls)
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.create_link_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
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
            mock.call(u'/tftpboot/1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      u'/tftpboot/0A0A0001.conf'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils._link_ip_address_pxe_configs(task)

        unlink_mock.assert_called_once_with('/tftpboot/0A0A0001.conf')
        create_link_mock.assert_has_calls(create_link_calls)

    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch.object(pxe_utils, '_build_pxe_config', autospec=True)
    @mock.patch('ironic.openstack.common.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config(self, ensure_tree_mock, build_mock,
                               write_mock):
        build_mock.return_value = self.pxe_options
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            build_mock.assert_called_with(self.pxe_options,
                                          CONF.pxe.pxe_config_template)
        ensure_calls = [
            mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid)),
            mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'))
        ]
        ensure_tree_mock.assert_has_calls(ensure_calls)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path, self.pxe_options)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
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
        self.config(http_root='/httpboot', group='pxe')
        mac = '00:11:22:33:AA:BB:CC'
        self.assertEqual('/httpboot/pxelinux.cfg/00-11-22-33-aa-bb-cc',
                         pxe_utils._get_pxe_mac_path(mac))

    def test__get_pxe_ip_address_path(self):
        ipaddress = '10.10.0.1'
        self.assertEqual('/tftpboot/0A0A0001.conf',
                         pxe_utils._get_pxe_ip_address_path(ipaddress))

    def test_get_root_dir(self):
        expected_dir = '/tftproot'
        self.config(ipxe_enabled=False, group='pxe')
        self.config(tftp_root=expected_dir, group='pxe')
        self.assertEqual(expected_dir, pxe_utils.get_root_dir())

    def test_get_root_dir_ipxe(self):
        expected_dir = '/httpboot'
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_root=expected_dir, group='pxe')
        self.assertEqual(expected_dir, pxe_utils.get_root_dir())

    def test_get_pxe_config_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.tftp_root,
                                      self.node.uuid,
                                      'config'),
                         pxe_utils.get_pxe_config_file_path(self.node.uuid))

    def test_dhcp_options_for_instance(self):
        self.config(tftp_server='192.0.2.1', group='pxe')
        self.config(pxe_bootfile_name='fake-bootfile', group='pxe')
        expected_info = [{'opt_name': 'bootfile-name',
                          'opt_value': 'fake-bootfile'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1'}
                         ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected_info,
                             pxe_utils.dhcp_options_for_instance(task))

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
        self.config(http_root=expected_dir, group='pxe')
        self._test_get_deploy_kr_info(expected_dir)

    def test_get_deploy_kr_info_bad_driver_info(self):
        self.config(tftp_root='/tftp', group='pxe')
        node_uuid = 'fake-node'
        driver_info = {}
        self.assertRaises(KeyError,
                          pxe_utils.get_deploy_kr_info,
                          node_uuid,
                          driver_info)

    def test_dhcp_options_for_instance_ipxe(self):
        self.config(tftp_server='192.0.2.1', group='pxe')
        self.config(pxe_bootfile_name='fake-bootfile', group='pxe')
        self.config(ipxe_enabled=True, group='pxe')
        self.config(http_url='http://192.0.3.2:1234', group='pxe')
        self.config(ipxe_boot_script='/test/boot.ipxe', group='pxe')

        self.config(dhcp_provider='isc', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': '!175,bootfile-name',
                          'opt_value': 'fake-bootfile'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'bootfile-name',
                          'opt_value': expected_boot_script_url}]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(sorted(expected_info),
                             sorted(pxe_utils.dhcp_options_for_instance(task)))

        self.config(dhcp_provider='neutron', group='dhcp')
        expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
        expected_info = [{'opt_name': 'tag:!ipxe,bootfile-name',
                          'opt_value': 'fake-bootfile'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '192.0.2.1'},
                         {'opt_name': 'tag:ipxe,bootfile-name',
                          'opt_value': expected_boot_script_url}]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(sorted(expected_info),
                             sorted(pxe_utils.dhcp_options_for_instance(task)))

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic.common.utils.unlink_without_raise', autospec=True)
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

            unlink_mock.assert_called_once_with('/tftpboot/0A0A0001.conf')
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch('ironic.common.utils.rmtree_without_raise')
    @mock.patch('ironic.common.utils.unlink_without_raise')
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

            unlink_mock.assert_called_once_with('/tftpboot/0A0A0001.conf')
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))
