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

import collections
import os
import shutil
import tempfile
from unittest import mock

from ironic_lib import utils as ironic_utils
from oslo_config import cfg
from oslo_utils import fileutils
from oslo_utils import uuidutils

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common.glance_service import image_service
from ironic.common import image_service as base_image_service
from ironic.common import pxe_utils
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import ipxe
from ironic.drivers.modules import pxe
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils

CONF = cfg.CONF
INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()


def _reset_dhcp_provider(config, provider_name):
    config(dhcp_provider=provider_name, group='dhcp')
    dhcp_factory.DHCPFactory._dhcp_provider = None


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
            'ks_cfg_url': 'http://fake/ks.cfg',
            'stage2_url': 'http://fake/stage2'
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

        self.ipxe_options_boot_from_volume_multipath = \
            self.ipxe_options.copy()
        self.ipxe_options_boot_from_volume_multipath.update({
            'boot_from_volume': True,
            'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn '
                              'iscsi:faker_host::3260:0:fake_iqn',
            'iscsi_initiator_iqn': 'fake_iqn',
            'username': 'fake_username',
            'password': 'fake_password',
        })

        self.ipxe_options_boot_from_volume_no_extra_volume.pop(
            'initrd_filename', None)
        self.ipxe_options_boot_from_volume_extra_volume.pop(
            'initrd_filename', None)

        self.ipxe_options_boot_from_iso = self.ipxe_options.copy()
        self.ipxe_options_boot_from_iso.update({
            'boot_from_iso': True,
            'boot_iso_url': 'http://1.2.3.4:1234/uuid/iso'
        })
        self.ipxe_options_boot_from_ramdisk = self.ipxe_options.copy()
        self.ipxe_options_boot_from_ramdisk.update({
            'ramdisk_kernel_arguments': 'ramdisk_params'
        })

        self.ipxe_kickstart_deploy = self.pxe_options.copy()
        self.ipxe_kickstart_deploy.update({
            'deployment_aki_path': 'http://1.2.3.4:1234/deploy_kernel',
            'deployment_ari_path': 'http://1.2.3.4:1234/deploy_ramdisk',
            'aki_path': 'http://1.2.3.4:1234/kernel',
            'ari_path': 'http://1.2.3.4:1234/ramdisk',
            'initrd_filename': 'deploy_ramdisk',
            'repo_url': 'http://1.2.3.4/path/to/os/',
        })
        self.ipxe_kickstart_deploy.pop('stage2_url')

        self.node = object_utils.create_test_node(self.context)

    def test_default_pxe_config(self):

        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.pxe_options,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        with open('ironic/tests/unit/drivers/pxe_config.template') as f:
            expected_template = f.read().rstrip()

        self.assertEqual(str(expected_template), rendered_template)

    def test_default_ipxe_boot_script(self):
        rendered_template = utils.render_template(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/'})

        with open('ironic/tests/unit/drivers/boot.ipxe') as f:
            expected_template = f.read().rstrip()

        self.assertEqual(str(expected_template), rendered_template)

    def test_fallback_ipxe_boot_script(self):
        rendered_template = utils.render_template(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/',
             'ipxe_fallback_script': 'inspector.ipxe'})

        with open('ironic/tests/unit/drivers/boot-fallback.ipxe') as f:
            expected_template = f.read().rstrip()

        self.assertEqual(str(expected_template), rendered_template)

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

        self.assertEqual(str(expected_template), rendered_template)

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

        self.assertEqual(str(expected_template), rendered_template)

    def test_default_ipxe_boot_from_volume_config_multipath(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')
        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': self.ipxe_options_boot_from_volume_multipath,
             'ROOT': '{{ ROOT }}',
             'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_volume_multipath.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()

        self.assertEqual(str(expected_template), rendered_template)

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

        self.assertEqual(str(expected_template), rendered_template)

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
        self.assertEqual(str(expected_template), rendered_template)

    def test_default_ipxe_boot_from_iso(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')

        pxe_options = self.ipxe_options_boot_from_iso

        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': pxe_options,
             'ROOT': '{{ ROOT }}'},
        )

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_iso.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()
        self.assertEqual(str(expected_template), rendered_template)

    def test_default_ipxe_boot_from_ramdisk(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')

        pxe_options = self.ipxe_options_boot_from_ramdisk

        rendered_template = utils.render_template(
            CONF.pxe.pxe_config_template,
            {'pxe_options': pxe_options,
             'ROOT': '{{ ROOT }}'},
        )

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_ramdisk.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()
        self.assertEqual(str(expected_template), rendered_template)

    def test_default_ipxe_boot_from_anaconda(self):
        self.config(
            pxe_config_template='ironic/drivers/modules/ipxe_config.template',
            group='pxe'
        )
        self.config(http_url='http://1.2.3.4:1234', group='deploy')

        pxe_options = self.ipxe_kickstart_deploy

        rendered_template = utils.render_template(
            CONF.pxe.ipxe_config_template,
            {'pxe_options': pxe_options,
             'ROOT': '{{ ROOT }}'},
        )

        templ_file = 'ironic/tests/unit/drivers/' \
                     'ipxe_config_boot_from_anaconda.template'
        with open(templ_file) as f:
            expected_template = f.read().rstrip()
        self.assertEqual(str(expected_template), rendered_template)

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

        self.assertEqual(str(expected_template), rendered_template)

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
                      '/tftpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/grub.cfg-01-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-66'),
            mock.call('/tftpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call('/tftpboot/11:22:33:44:55:66.conf'),
            mock.call('/tftpboot/pxelinux.cfg/01-11-22-33-44-55-67'),
            mock.call('/tftpboot/grub.cfg-01-11-22-33-44-55-67'),
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
                      '/tftpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/grub.cfg-01-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/tftpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-66'),
            mock.call('/tftpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call('/tftpboot/11:22:33:44:55:66.conf'),
            mock.call('/tftpboot/pxelinux.cfg/20-11-22-33-44-55-67'),
            mock.call('/tftpboot/grub.cfg-01-11-22-33-44-55-67'),
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
                      '/httpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/11:22:33:44:55:66.conf'),
            mock.call(u'../1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/grub.cfg-01-11-22-33-44-55-67'),
            mock.call(u'1be26c0b-03f2-4d2e-ae87-c02d7f33c123/config',
                      '/httpboot/11:22:33:44:55:67.conf')
        ]
        unlink_calls = [
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-66'),
            mock.call('/httpboot/grub.cfg-01-11-22-33-44-55-66'),
            mock.call('/httpboot/11:22:33:44:55:66.conf'),
            mock.call('/httpboot/pxelinux.cfg/11-22-33-44-55-67'),
            mock.call('/httpboot/grub.cfg-01-11-22-33-44-55-67'),
            mock.call('/httpboot/11:22:33:44:55:67.conf'),
        ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.ports = [port_1, port_2]
            pxe_utils._link_mac_pxe_configs(task, ipxe_enabled=True)

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

    @mock.patch.object(pxe_utils, '_link_ip_address_pxe_configs',
                       autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config(self, ensure_tree_mock, render_mock,
                               write_mock, makedirs_mock, mock_link_ip_addr):
        self.config(tftp_root=tempfile.mkdtemp(), group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'}
            )
        node_dir = os.path.join(CONF.pxe.tftp_root, self.node.uuid)
        pxe_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
        makedirs_mock.assert_has_calls([
            mock.call(node_dir, 0o755, exist_ok=True),
            mock.call(pxe_dir, 0o755, exist_ok=True),
        ])

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)
        self.assertTrue(mock_link_ip_addr.called)

    @mock.patch.object(pxe_utils, '_link_ip_address_pxe_configs',
                       autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_set_dir_permission(self, ensure_tree_mock,
                                                  render_mock,
                                                  write_mock, makedirs_mock,
                                                  mock_link_ip_addr):
        self.config(tftp_root=tempfile.mkdtemp(), group='pxe')
        self.config(dir_permission=0o755, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'}
            )
        node_dir = os.path.join(CONF.pxe.tftp_root, self.node.uuid)
        pxe_dir = os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg')
        makedirs_mock.assert_has_calls([
            mock.call(node_dir, 0o755, exist_ok=True),
            mock.call(pxe_dir, 0o755, exist_ok=True),
        ])

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)
        self.assertTrue(mock_link_ip_addr.called)

    @mock.patch.object(pxe_utils, '_link_ip_address_pxe_configs',
                       autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_existing_dirs_uefi(
            self, ensure_tree_mock,
            render_mock,
            write_mock, makedirs_mock,
            isdir_mock, mock_link_ip_address):
        self.config(dir_permission=0o755, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            isdir_mock.return_value = True
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        CONF.pxe.pxe_config_template)
            render_mock.assert_called_with(
                CONF.pxe.pxe_config_template,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'}
            )
        ensure_tree_mock.assert_has_calls([])
        makedirs_mock.assert_not_called()
        isdir_mock.assert_has_calls([])
        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)
        self.assertTrue(mock_link_ip_address.called)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('oslo_utils.fileutils.ensure_tree', autospec=True)
    def test_create_pxe_config_existing_dirs_bios(
            self, ensure_tree_mock,
            render_mock,
            write_mock, makedirs_mock,
            isdir_mock):
        self.config(dir_permission=0o755, group='pxe')
        self.config(default_boot_mode='bios', group='deploy')
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
        makedirs_mock.assert_not_called()
        isdir_mock.assert_has_calls([])
        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_pxe_config_uefi_grub(self, render_mock,
                                         write_mock, link_ip_configs_mock,
                                         makedirs_mock):
        self.config(tftp_root=tempfile.mkdtemp(), group='pxe')
        grub_tmplte = "ironic/drivers/modules/pxe_grub_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        grub_tmplte)

            makedirs_mock.assert_has_calls([
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid),
                          0o755, exist_ok=True),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'),
                          0o755, exist_ok=True),
            ])
            render_mock.assert_called_with(
                grub_tmplte,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'})
            link_ip_configs_mock.assert_called_once_with(task, False)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_mac_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_ip_address_pxe_configs',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_pxe_config_uefi_mac_address(
            self, render_mock, write_mock, link_ip_configs_mock,
            link_mac_pxe_configs_mock, makedirs_mock):
        # TODO(TheJulia): We should... like... fix the template to
        # enable mac address usage.....
        grub_tmplte = "ironic/drivers/modules/pxe_grub_config.template"
        _reset_dhcp_provider(self.config, 'none')
        self.config(tftp_root=tempfile.mkdtemp(), group='pxe')
        link_ip_configs_mock.side_effect = \
            exception.FailedToGetIPAddressOnPort(port_id='blah')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.pxe_options,
                                        grub_tmplte)

            makedirs_mock.assert_has_calls([
                mock.call(os.path.join(CONF.pxe.tftp_root, self.node.uuid),
                          0o755, exist_ok=True),
                mock.call(os.path.join(CONF.pxe.tftp_root, 'pxelinux.cfg'),
                          0o755, exist_ok=True),
            ])
            render_mock.assert_called_with(
                grub_tmplte,
                {'pxe_options': self.pxe_options,
                 'ROOT': '(( ROOT ))',
                 'DISK_IDENTIFIER': '(( DISK_IDENTIFIER ))'})
            link_mac_pxe_configs_mock.assert_called_once_with(
                task, ipxe_enabled=False)
            link_ip_configs_mock.assert_called_once_with(task, False)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(self.node.uuid)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch('ironic.common.pxe_utils._link_mac_pxe_configs', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_pxe_config_uefi_ipxe(self, render_mock,
                                         write_mock, link_mac_pxe_mock,
                                         makedirs_mock):

        self.config(http_root=tempfile.mkdtemp(), group='deploy')
        ipxe_template = "ironic/drivers/modules/ipxe_config.template"
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            pxe_utils.create_pxe_config(task, self.ipxe_options,
                                        ipxe_template, ipxe_enabled=True)

            makedirs_mock.assert_has_calls([
                mock.call(os.path.join(CONF.deploy.http_root, self.node.uuid),
                          0o755, exist_ok=True),
                mock.call(os.path.join(CONF.deploy.http_root, 'pxelinux.cfg'),
                          0o755, exist_ok=True),
            ])
            render_mock.assert_called_with(
                ipxe_template,
                {'pxe_options': self.ipxe_options,
                 'ROOT': '{{ ROOT }}',
                 'DISK_IDENTIFIER': '{{ DISK_IDENTIFIER }}'})
            link_mac_pxe_mock.assert_called_once_with(task, ipxe_enabled=True)

        pxe_cfg_file_path = pxe_utils.get_pxe_config_file_path(
            self.node.uuid, ipxe_enabled=True)
        write_mock.assert_called_with(pxe_cfg_file_path,
                                      render_mock.return_value, 0o644)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.get_ip_addresses',
                autospec=True)
    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test_clean_up_pxe_config(self, unlink_mock, rmtree_mock,
                                 mock_get_ip_addr):
        address = "aa:aa:aa:aa:aa:aa"
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            pxe_utils.clean_up_pxe_config(task)

        ensure_calls = [
            mock.call("/tftpboot/pxelinux.cfg/01-%s"
                      % address.replace(':', '-')),
            mock.call("/tftpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa"),
            mock.call("/tftpboot/%s.conf" % address)
        ]

        unlink_mock.assert_has_calls(ensure_calls)
        rmtree_mock.assert_called_once_with(
            os.path.join(CONF.pxe.tftp_root, self.node.uuid))
        self.assertTrue(mock_get_ip_addr.called)

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
            'foo', 0o644)
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/',
             'ipxe_fallback_script': None})

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
            'foo', 0o644)
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/',
             'ipxe_fallback_script': None})

    @mock.patch.object(os.path, 'isfile', lambda path: False)
    @mock.patch('ironic.common.utils.file_has_content', autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_create_ipxe_boot_script_fallback(self, render_mock, write_mock,
                                              file_has_content_mock):
        self.config(ipxe_fallback_script='inspector.ipxe', group='pxe')
        render_mock.return_value = 'foo'
        pxe_utils.create_ipxe_boot_script()
        self.assertFalse(file_has_content_mock.called)
        write_mock.assert_called_once_with(
            os.path.join(CONF.deploy.http_root,
                         os.path.basename(CONF.pxe.ipxe_boot_script)),
            'foo', 0o644)
        render_mock.assert_called_once_with(
            CONF.pxe.ipxe_boot_script,
            {'ipxe_for_mac_uri': 'pxelinux.cfg/',
             'ipxe_fallback_script': 'inspector.ipxe'})

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
        self.config(http_root='/httpboot', group='deploy')
        mac = '00:11:22:33:AA:BB:CC'
        self.assertEqual('/httpboot/pxelinux.cfg/00-11-22-33-aa-bb-cc',
                         pxe_utils._get_pxe_mac_path(mac, ipxe_enabled=True))

    def test__get_pxe_ip_address_path(self):
        ipaddress = '10.10.0.1'
        self.assertEqual('/tftpboot/10.10.0.1.conf',
                         pxe_utils._get_pxe_ip_address_path(ipaddress))

    def test_get_pxe_config_file_path(self):
        self.assertEqual(os.path.join(CONF.pxe.tftp_root,
                                      self.node.uuid,
                                      'config'),
                         pxe_utils.get_pxe_config_file_path(self.node.uuid))

    def _dhcp_options_for_instance(self, ip_version=4, ipxe=False):
        self.config(ip_version=ip_version, group='pxe')
        if ip_version == 4:
            self.config(tftp_server='192.0.2.1', group='pxe')
        elif ip_version == 6:
            self.config(tftp_server='ff80::1', group='pxe')
        if CONF.deploy.default_boot_mode == 'uefi':
            if ipxe:
                self.config(uefi_ipxe_bootfile_name='fake-bootfile-ipxe',
                            group='pxe')
            else:
                self.config(uefi_pxe_bootfile_name='fake-bootfile',
                            group='pxe')
        else:
            if ipxe:
                self.config(ipxe_bootfile_name='fake-bootfile-ipxe',
                            group='pxe')
            else:
                self.config(pxe_bootfile_name='fake-bootfile', group='pxe')
        self.config(tftp_root='/tftp-path', group='pxe')
        if ipxe:
            bootfile = 'fake-bootfile-ipxe'
        else:
            bootfile = 'fake-bootfile'

        if ip_version == 6:
            # NOTE(TheJulia): DHCPv6 RFCs seem to indicate that the prior
            # options are not imported, although they may be supported
            # by vendors. The apparent proper option is to return a
            # URL in the field https://tools.ietf.org/html/rfc5970#section-3
            expected_info = [{'opt_name': '59',
                              'opt_value': 'tftp://[ff80::1]/%s' % bootfile,
                              'ip_version': ip_version}]
        elif ip_version == 4:
            expected_info = [{'opt_name': '67',
                              'opt_value': bootfile,
                              'ip_version': ip_version},
                             {'opt_name': '66',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': '150',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': '255',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version}
                             ]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertEqual(expected_info,
                             pxe_utils.dhcp_options_for_instance(task))

    def test_dhcp_options_for_instance(self):
        self.config(default_boot_mode='uefi', group='deploy')
        self._dhcp_options_for_instance(ip_version=4)

    def test_dhcp_options_for_instance_bios(self):
        self.config(default_boot_mode='bios', group='deploy')
        self._dhcp_options_for_instance(ip_version=4)

    def test_dhcp_options_for_instance_ipv6(self):
        self.config(tftp_server='ff80::1', group='pxe')
        self._dhcp_options_for_instance(ip_version=6)

    def test_dhcp_options_for_instance_ipv6_bios(self):
        self.config(tftp_server='ff80::1', group='pxe')
        self.config(default_boot_mode='bios', group='deploy')
        self._dhcp_options_for_instance(ip_version=6)

    def _test_get_kernel_ramdisk_info(self, expected_dir, mode='deploy',
                                      ipxe_enabled=False):
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
                                                    mode=mode,
                                                    ipxe_enabled=ipxe_enabled)
        self.assertEqual(expected, kr_info)

    def test_get_kernel_ramdisk_info(self):
        expected_dir = '/tftp'
        self.config(tftp_root=expected_dir, group='pxe')
        self._test_get_kernel_ramdisk_info(expected_dir)

    def test_get_kernel_ramdisk_info_ipxe(self):
        expected_dir = '/http'
        self.config(http_root=expected_dir, group='deploy')
        self._test_get_kernel_ramdisk_info(expected_dir, ipxe_enabled=True)

    def test_get_kernel_ramdisk_info_bad_driver_info(self):
        self.config(tftp_root='/tftp', group='pxe')
        node_uuid = 'fake-node'
        self.assertEqual({}, pxe_utils.get_kernel_ramdisk_info(node_uuid, {}))

    def test_get_rescue_kr_info(self):
        expected_dir = '/tftp'
        self.config(tftp_root=expected_dir, group='pxe')
        self._test_get_kernel_ramdisk_info(expected_dir, mode='rescue')

    def test_get_rescue_kr_info_ipxe(self):
        expected_dir = '/http'
        self.config(http_root=expected_dir, group='deploy')
        self._test_get_kernel_ramdisk_info(expected_dir, mode='rescue',
                                           ipxe_enabled=True)

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
                mock.call('/tftpboot/pxelinux.cfg/01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/' + address + '.conf')
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
                mock.call('/tftpboot/pxelinux.cfg/01-%s' %
                          address.replace(':', '-')),
                mock.call('/tftpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/' + address + '.conf')
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
                mock.call('/tftpboot/pxelinux.cfg/01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/' + address + ".conf")
            ]
            unlink_mock.assert_has_calls(unlink_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    @mock.patch('ironic.common.dhcp_factory.DHCPFactory.provider',
                autospec=True)
    def test_clean_up_pxe_config_uefi_no_ipaddress(self, provider_mock,
                                                   unlink_mock,
                                                   rmtree_mock):
        address = "aa:aa:aa:aa:aa:aa"
        properties = {'capabilities': 'boot_mode:uefi'}
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        provider_mock.get_ip_addresses.return_value = []

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = properties
            pxe_utils.clean_up_pxe_config(task)

            unlink_calls = [
                mock.call('/tftpboot/pxelinux.cfg/01-%s' %
                          address.replace(':', '-')),
                mock.call('/tftpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa'),
                mock.call('/tftpboot/aa:aa:aa:aa:aa:aa.conf')
            ]
            unlink_mock.assert_has_calls(unlink_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.pxe.tftp_root, self.node.uuid))

    def test__get_pxe_grub_mac_path(self):
        self.config(tftp_root='/tftpboot-path/', group='pxe')
        address = "aa:aa:aa:aa:aa:aa"
        actual = pxe_utils._get_pxe_grub_mac_path(address)
        self.assertEqual('/tftpboot-path/grub.cfg-01-aa-aa-aa-aa-aa-aa',
                         next(actual))
        self.assertEqual('/tftpboot-path/' + address + '.conf', next(actual))

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_place_common_config(self, mock_chmod, mock_isdir,
                                 mock_makedirs):
        self.config(initial_grub_template=os.path.join(
                    '$pybasedir',
                    'drivers/modules/initial_grub_cfg.template'),
                    group='pxe')
        mock_isdir.return_value = False
        self.config(group='pxe', dir_permission=0o777)

        def write_to_file(path, contents):
            self.assertEqual('/tftpboot/grub/grub.cfg', path)
            self.assertIn(
                'configfile /tftpboot/$net_default_mac.conf',
                contents
            )

        with mock.patch('ironic.common.utils.write_to_file',
                        wraps=write_to_file):
            pxe_utils.place_common_config()

        mock_isdir.assert_called_once_with('/tftpboot/grub')
        mock_makedirs.assert_called_once_with('/tftpboot/grub', 511)
        mock_chmod.assert_called_once_with('/tftpboot/grub', 0o777)

    @mock.patch.object(os, 'makedirs', autospec=True)
    @mock.patch.object(os.path, 'isdir', autospec=True)
    @mock.patch.object(os, 'chmod', autospec=True)
    def test_place_common_config_existing_dirs(self, mock_chmod, mock_isdir,
                                               mock_makedirs):
        self.config(initial_grub_template=os.path.join(
                    '$pybasedir',
                    'drivers/modules/initial_grub_cfg.template'),
                    group='pxe')
        mock_isdir.return_value = True

        with mock.patch('ironic.common.utils.write_to_file',
                        autospec=True) as mock_write:
            pxe_utils.place_common_config()
            mock_write.assert_called_once()

        mock_isdir.assert_called_once_with('/tftpboot/grub')
        mock_makedirs.assert_not_called()
        mock_chmod.assert_not_called()


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
@mock.patch.object(pxe.PXEBoot, '__init__', lambda self: None)
class PXEInterfacesTestCase(db_base.DbTestCase):

    def setUp(self):
        super(PXEInterfacesTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'pxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)

    def _test_parse_driver_info_missing_kernel(self, mode='deploy'):
        del self.node.driver_info['%s_kernel' % mode]
        if mode == 'rescue':
            self.node.provision_state = states.RESCUING
        self.assertRaises(exception.MissingParameterValue,
                          pxe_utils.parse_driver_info, self.node, mode=mode)

    def test_parse_driver_info_missing_deploy_kernel(self):
        self._test_parse_driver_info_missing_kernel()

    def test_parse_driver_info_missing_rescue_kernel(self):
        self._test_parse_driver_info_missing_kernel(mode='rescue')

    def _test_parse_driver_info_missing_ramdisk(self, mode='deploy'):
        del self.node.driver_info['%s_ramdisk' % mode]
        if mode == 'rescue':
            self.node.provision_state = states.RESCUING
        self.assertRaises(exception.MissingParameterValue,
                          pxe_utils.parse_driver_info, self.node, mode=mode)

    def test_parse_driver_info_missing_deploy_ramdisk(self):
        self._test_parse_driver_info_missing_ramdisk()

    def test_parse_driver_info_missing_rescue_ramdisk(self):
        self._test_parse_driver_info_missing_ramdisk(mode='rescue')

    def _test_parse_driver_info(self, mode='deploy'):
        exp_info = {'%s_ramdisk' % mode: 'glance://%s_ramdisk_uuid' % mode,
                    '%s_kernel' % mode: 'glance://%s_kernel_uuid' % mode}
        image_info = pxe_utils.parse_driver_info(self.node, mode=mode)
        self.assertEqual(exp_info, image_info)

    def test_parse_driver_info_deploy(self):
        self._test_parse_driver_info()

    def test_parse_driver_info_rescue(self):
        self._test_parse_driver_info(mode='rescue')

    def _test_parse_driver_info_from_conf(self, mode='deploy', by_arch=False):
        ramdisk = 'glance://%s_ramdisk_uuid' % mode
        kernel = 'glance://%s_kernel_uuid' % mode
        if by_arch:
            exp_info = {'%s_ramdisk' % mode: ramdisk,
                        '%s_kernel' % mode: kernel}
            config = {'%s_ramdisk_by_arch' % mode: ramdisk,
                      '%s_kernel_by_arch' % mode: kernel}
        else:
            del self.node.driver_info['%s_kernel' % mode]
            del self.node.driver_info['%s_ramdisk' % mode]
            exp_info = {'%s_ramdisk' % mode: ramdisk,
                        '%s_kernel' % mode: kernel}
            config = exp_info
        self.config(group='conductor', **config)
        image_info = pxe_utils.parse_driver_info(self.node, mode=mode)
        self.assertEqual(exp_info, image_info)

    def test_parse_driver_info_from_conf_deploy(self):
        self._test_parse_driver_info_from_conf()

    def test_parse_driver_info_from_conf_rescue(self):
        self._test_parse_driver_info_from_conf(mode='rescue')

    def test_parse_driver_info_from_conf_deploy_by_arch(self):
        self._test_parse_driver_info_from_conf(by_arch=True)

    def test_parse_driver_info_from_conf_rescue_by_arch(self):
        self._test_parse_driver_info_from_conf(mode='rescue', by_arch=True)

    def test_parse_driver_info_mixed_source_deploy(self):
        self.config(deploy_kernel='file:///image',
                    deploy_ramdisk='file:///image',
                    group='conductor')
        self._test_parse_driver_info_missing_ramdisk()

    def test_parse_driver_info_mixed_source_deploy_by_arch(self):
        self.config(deploy_kernel_by_arch={'x86_64': 'file:///image'},
                    deploy_ramdisk_by_arch={'x86_64': 'file:///image'},
                    group='conductor')
        self._test_parse_driver_info_missing_ramdisk()

    def test_parse_driver_info_mixed_source_rescue(self):
        self.config(rescue_kernel='file:///image',
                    rescue_ramdisk='file:///image',
                    group='conductor')
        self._test_parse_driver_info_missing_ramdisk(mode='rescue')

    @mock.patch.object(deploy_utils, 'get_boot_option', lambda node: 'ramdisk')
    def test_parse_driver_info_ramdisk(self):
        self.node.driver_info = {}
        self.node.automated_clean = False
        image_info = pxe_utils.parse_driver_info(self.node, mode='deploy')
        self.assertEqual({}, image_info)

    def test__get_deploy_image_info(self):
        expected_info = {'deploy_ramdisk':
                         (DRV_INFO_DICT['deploy_ramdisk'],
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'deploy_ramdisk')),
                         'deploy_kernel':
                         (DRV_INFO_DICT['deploy_kernel'],
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'deploy_kernel'))}
        image_info = pxe_utils.get_image_info(self.node)
        self.assertEqual(expected_info, image_info)

    def test__get_deploy_image_info_ipxe(self):
        expected_info = {'deploy_ramdisk':
                         (DRV_INFO_DICT['deploy_ramdisk'],
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'deploy_ramdisk')),
                         'deploy_kernel':
                         (DRV_INFO_DICT['deploy_kernel'],
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'deploy_kernel'))}
        image_info = pxe_utils.get_image_info(self.node, ipxe_enabled=True)
        self.assertEqual(expected_info, image_info)

    def test__get_deploy_image_info_missing_deploy_kernel(self):
        del self.node.driver_info['deploy_kernel']
        self.assertRaises(exception.MissingParameterValue,
                          pxe_utils.get_image_info, self.node)

    def test__get_deploy_image_info_deploy_ramdisk(self):
        del self.node.driver_info['deploy_ramdisk']
        self.assertRaises(exception.MissingParameterValue,
                          pxe_utils.get_image_info, self.node)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def _test_get_instance_image_info(self, show_mock):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                      u'ramdisk_id': u'instance_ramdisk_uuid'}}

        expected_info = {'ramdisk':
                         ('instance_ramdisk_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')),
                         'kernel':
                         ('instance_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel'))}
        show_mock.return_value = properties
        self.context.auth_token = 'fake'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_info = pxe_utils.get_instance_image_info(task)
            show_mock.assert_called_once_with(mock.ANY, 'glance://image_uuid')
            self.assertEqual(expected_info, image_info)

            # test with saved info
            show_mock.reset_mock()
            image_info = pxe_utils.get_instance_image_info(task)
            self.assertEqual(expected_info, image_info)
            self.assertFalse(show_mock.called)
            self.assertEqual('instance_kernel_uuid',
                             task.node.instance_info['kernel'])
            self.assertEqual('instance_ramdisk_uuid',
                             task.node.instance_info['ramdisk'])

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='local', autospec=True)
    def test_get_instance_image_info_localboot(self, boot_opt_mock):
        self.node.driver_internal_info['is_whole_disk_image'] = False
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_info = pxe_utils.get_instance_image_info(task)
            self.assertEqual({}, image_info)
            boot_opt_mock.assert_called_once_with(task.node)

    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_get_instance_image_info_whole_disk_image(self, show_mock):
        properties = {'properties': None}
        show_mock.return_value = properties
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            image_info = pxe_utils.get_instance_image_info(task)
        self.assertEqual({}, image_info)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='ramdisk', autospec=True)
    def test_get_instance_image_info_boot_iso(self, boot_opt_mock):
        self.node.instance_info = {'boot_iso': 'http://localhost/boot.iso'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=True)
            self.assertEqual('http://localhost/boot.iso',
                             image_info['boot_iso'][0])

            boot_opt_mock.assert_called_once_with(task.node)

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='kickstart', autospec=True)
    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_get_instance_image_info_with_kickstart_boot_option(
            self, image_show_mock, boot_opt_mock):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                                     u'ramdisk_id': u'instance_ramdisk_uuid',
                                     u'stage2_id': u'instance_stage2_id'}}

        expected_info = {'ramdisk':
                         ('instance_ramdisk_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')),
                         'kernel':
                         ('instance_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel')),
                         'stage2':
                         ('instance_stage2_id',
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'LiveOS',
                                       'squashfs.img')),
                         'ks_template':
                         ('file://' + CONF.anaconda.default_ks_template,
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg.template')),
                         'ks_cfg':
                         ('',
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg'))}
        image_show_mock.return_value = properties
        self.context.auth_token = 'fake'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=False)
            self.assertEqual(expected_info, image_info)
            # In the absense of kickstart template in both instance_info and
            # image default kickstart template is used
            self.assertEqual('file://' + CONF.anaconda.default_ks_template,
                             image_info['ks_template'][0])
            calls = [mock.call(task.node), mock.call(task.node)]
            boot_opt_mock.assert_has_calls(calls)
            # Instance info gets presedence over kickstart template on the
            # image
            properties['properties'] = {'ks_template': 'glance://template_id'}
            task.node.instance_info['ks_template'] = 'https://server/fake.tmpl'
            image_show_mock.return_value = properties
            image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=False)
            self.assertEqual('https://server/fake.tmpl',
                             image_info['ks_template'][0])

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='kickstart', autospec=True)
    @mock.patch.object(base_image_service.HttpImageService, 'show',
                       autospec=True)
    def test_get_instance_image_info_with_kickstart_url_http(
            self, image_show_mock, boot_opt_mock):
        properties = {'properties': {}}
        expected_info = {'ramdisk':
                         ('http://fake.url/ramdisk',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')),
                         'kernel':
                         ('http://fake.url/kernel',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel')),
                         'ks_template':
                         ('file://' + CONF.anaconda.default_ks_template,
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg.template')),
                         'ks_cfg':
                         ('',
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg'))}
        image_show_mock.return_value = properties
        self.context.auth_token = 'fake'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            dii = task.node.driver_internal_info
            dii['is_source_a_path'] = True
            task.node.driver_internal_info = dii
            i_info = task.node.instance_info
            i_info['image_source'] = 'http://fake.url/path'
            i_info['kernel'] = 'http://fake.url/kernel'
            i_info['ramdisk'] = 'http://fake.url/ramdisk'
            task.node.instance_info = i_info
            task.node.save()
            image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=False)
            self.assertEqual(expected_info, image_info)
            # In the absense of kickstart template in both instance_info and
            # image default kickstart template is used
            self.assertEqual('file://' + CONF.anaconda.default_ks_template,
                             image_info['ks_template'][0])
            calls = [mock.call(task.node), mock.call(task.node)]
            boot_opt_mock.assert_has_calls(calls)
            # Instance info gets presedence over kickstart template on the
            # image
            properties['properties'] = {'ks_template': 'glance://template_id'}
            task.node.instance_info['ks_template'] = 'https://server/fake.tmpl'
            image_show_mock.return_value = properties
            image_info = pxe_utils.get_instance_image_info(
                task, ipxe_enabled=False)
            self.assertEqual('https://server/fake.tmpl',
                             image_info['ks_template'][0])

    @mock.patch('ironic.drivers.modules.deploy_utils.get_boot_option',
                return_value='kickstart', autospec=True)
    @mock.patch.object(image_service.GlanceImageService, 'show', autospec=True)
    def test_get_instance_image_info_kickstart_stage2_missing(
            self, image_show_mock, boot_opt_mock):
        properties = {'properties': {u'kernel_id': u'instance_kernel_uuid',
                                     u'ramdisk_id': u'instance_ramdisk_uuid'}}

        image_show_mock.return_value = properties
        self.context.auth_token = 'fake'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(
                exception.ImageUnacceptable, pxe_utils.get_instance_image_info,
                task, ipxe_enabled=False
            )

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test__cache_tftp_images_master_path(self, mock_fetch_image,
                                            mock_chmod):
        temp_dir = tempfile.mkdtemp()
        self.config(tftp_root=temp_dir, group='pxe')
        self.config(tftp_master_path=os.path.join(temp_dir,
                                                  'tftp_master_path'),
                    group='pxe')
        image_path = os.path.join(temp_dir, self.node.uuid,
                                  'deploy_kernel')
        image_info = {'deploy_kernel': ('deploy_kernel', image_path)}
        pxe_utils.ensure_tree(CONF.pxe.tftp_master_path)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.cache_ramdisk_kernel(task, image_info)

        mock_fetch_image.assert_called_once_with(self.context,
                                                 mock.ANY,
                                                 [('deploy_kernel',
                                                   image_path)],
                                                 True)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(pxe_utils, 'TFTPImageCache', lambda: None)
    @mock.patch.object(pxe_utils, 'ensure_tree', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test_cache_ramdisk_kernel(self, mock_fetch_image, mock_ensure_tree,
                                  mock_chmod):
        fake_pxe_info = pxe_utils.get_image_info(self.node)
        expected_path = os.path.join(CONF.pxe.tftp_root, self.node.uuid)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.cache_ramdisk_kernel(task, fake_pxe_info)
        mock_ensure_tree.assert_called_with(expected_path)
        mock_fetch_image.assert_called_once_with(
            self.context, mock.ANY, list(fake_pxe_info.values()), True)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(pxe_utils, 'TFTPImageCache', lambda: None)
    @mock.patch.object(pxe_utils, 'ensure_tree', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test_cache_ramdisk_kernel_ipxe(self, mock_fetch_image,
                                       mock_ensure_tree, mock_chmod):
        fake_pxe_info = pxe_utils.get_image_info(self.node)
        expected_path = os.path.join(CONF.deploy.http_root,
                                     self.node.uuid)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.cache_ramdisk_kernel(task, fake_pxe_info,
                                           ipxe_enabled=True)
        mock_ensure_tree.assert_called_with(expected_path)
        mock_fetch_image.assert_called_once_with(self.context, mock.ANY,
                                                 list(fake_pxe_info.values()),
                                                 True)

    @mock.patch.object(os, 'chmod', autospec=True)
    @mock.patch.object(pxe_utils, 'TFTPImageCache', lambda: None)
    @mock.patch.object(pxe_utils, 'ensure_tree', autospec=True)
    @mock.patch.object(deploy_utils, 'fetch_images', autospec=True)
    def test_cache_ramdisk_kernel_ipxe_anaconda(self, mock_fetch_image,
                                                mock_ensure_tree, mock_chmod):
        expected_path = os.path.join(CONF.deploy.http_root,
                                     self.node.uuid)
        fake_pxe_info = {'ramdisk':
                         ('instance_ramdisk_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'ramdisk')),
                         'kernel':
                         ('instance_kernel_uuid',
                          os.path.join(CONF.pxe.tftp_root,
                                       self.node.uuid,
                                       'kernel')),
                         'ks_template':
                         ('file://' + CONF.anaconda.default_ks_template,
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg.template')),
                         'ks_cfg':
                         ('',
                          os.path.join(CONF.deploy.http_root,
                                       self.node.uuid,
                                       'ks.cfg'))}
        expected = fake_pxe_info.copy()
        expected.pop('ks_cfg')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.cache_ramdisk_kernel(task, fake_pxe_info,
                                           ipxe_enabled=True)
        mock_ensure_tree.assert_called_with(expected_path)
        mock_fetch_image.assert_called_once_with(self.context, mock.ANY,
                                                 list(expected.values()),
                                                 True)


@mock.patch.object(pxe.PXEBoot, '__init__', lambda self: None)
class PXEBuildKickstartConfigOptionsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(PXEBuildKickstartConfigOptionsTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'pxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        n['instance_info']['image_url'] = 'http://ironic/node/os_image.tar'
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    def test_build_kickstart_config_options_pxe(self, api_url_mock):
        api_url_mock.return_value = 'http://ironic-api'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected = {}
            expected['liveimg_url'] = task.node.instance_info['image_url']
            expected['config_drive'] = ''
            expected['heartbeat_url'] = (
                'http://ironic-api/v1/heartbeat/%s' % task.node.uuid
            )
            params = pxe_utils.build_kickstart_config_options(task)
            self.assertTrue(params['ks_options'].pop('agent_token'))
            self.assertEqual(expected, params['ks_options'])

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    def test_build_kickstart_config_options_pxe_source_path(self,
                                                            api_url_mock):
        api_url_mock.return_value = 'http://ironic-api'
        d_info = self.node.driver_internal_info
        d_info['is_source_a_path'] = True
        self.node.driver_internal_info = d_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected = {}
            expected['liveimg_url'] = task.node.instance_info['image_url']
            expected['config_drive'] = ''
            expected['heartbeat_url'] = (
                'http://ironic-api/v1/heartbeat/%s' % task.node.uuid
            )
            expected['is_source_a_path'] = 'true'
            params = pxe_utils.build_kickstart_config_options(task)
            self.assertTrue(params['ks_options'].pop('agent_token'))
            self.assertEqual(expected, params['ks_options'])
            self.assertNotIn('insecure_heartbeat', params)

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    def test_build_kickstart_config_options_pxe_insecure_heartbeat(
            self, api_url_mock):
        api_url_mock.return_value = 'http://ironic-api'
        self.assertFalse(CONF.anaconda.insecure_heartbeat)
        CONF.set_override('insecure_heartbeat', True, 'anaconda')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected = {}
            expected['liveimg_url'] = task.node.instance_info['image_url']
            expected['config_drive'] = ''
            expected['heartbeat_url'] = (
                'http://ironic-api/v1/heartbeat/%s' % task.node.uuid
            )
            expected['insecure_heartbeat'] = 'true'
            params = pxe_utils.build_kickstart_config_options(task)
            self.assertTrue(params['ks_options'].pop('agent_token'))
            self.assertEqual(expected, params['ks_options'])

    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def test_prepare_instance_kickstart_config_not_anaconda_boot(self,
                                                                 render_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertFalse(
                pxe_utils.prepare_instance_kickstart_config(task, {})
            )
            render_mock.assert_not_called()

    @mock.patch('ironic.common.utils.render_template', autospec=True)
    @mock.patch('ironic.common.pxe_utils.build_kickstart_config_options',
                autospec=True)
    @mock.patch('ironic.common.utils.write_to_file', autospec=True)
    def test_prepare_instance_kickstart_config(self, write_mock,
                                               ks_options_mock, render_mock):
        image_info = {
            'ks_cfg': ['', '/http_root/node_uuid/ks.cfg'],
            'ks_template': ['tmpl_id', '/http_root/node_uuid/ks.cfg.template']
        }
        params = {'liveimg_url': 'http://fake', 'agent_token': 'faketoken',
                  'heartbeat_url': 'http://fake_hb'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ks_options_mock.return_value = {'ks_options': params}
            pxe_utils.prepare_instance_kickstart_config(task, image_info,
                                                        anaconda_boot=True)
            render_mock.assert_called_with(
                image_info['ks_template'][1], {'ks_options': params}
            )
            write_mock.assert_called_with(image_info['ks_cfg'][1],
                                          render_mock.return_value, 0o644)

    def test_validate_kickstart_template(self):
        self.config_temp_dir('http_root', group='deploy')
        ks_template_path = 'ironic/drivers/modules/ks.cfg.template'
        pxe_utils.validate_kickstart_template(ks_template_path)

    def test_validate_kickstart_template_missing_variable(self):
        self.config_temp_dir('http_root', group='deploy')
        # required variable is missing from the template
        ks_template_path = 'ironic/tests/unit/drivers/ks_missing_var.tmpl'
        self.assertRaises(
            exception.InvalidKickstartTemplate,
            pxe_utils.validate_kickstart_template,
            ks_template_path)

    def test_validate_kickstart_template_has_additional_variables(self):
        self.config_temp_dir('http_root', group='deploy')
        ks_template_path = 'ironic/tests/unit/drivers/ks_extra_vars.tmpl'
        self.assertRaises(
            exception.InvalidKickstartTemplate,
            pxe_utils.validate_kickstart_template,
            ks_template_path)


@mock.patch.object(pxe.PXEBoot, '__init__', lambda self: None)
class PXEBuildConfigOptionsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(PXEBuildConfigOptionsTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'pxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def _test_build_pxe_config_options_pxe(self, render_mock,
                                           whle_dsk_img=False,
                                           debug=False, mode='deploy',
                                           ramdisk_params=None,
                                           expected_pxe_params=None,
                                           ramdisk_kernel_opt=None):
        self.config(debug=debug)
        self.config(kernel_append_params='test_param', group='pxe')

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = whle_dsk_img
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        tftp_server = CONF.pxe.tftp_server

        kernel_label = '%s_kernel' % mode
        ramdisk_label = '%s_ramdisk' % mode

        pxe_kernel = os.path.join(self.node.uuid, kernel_label)
        pxe_ramdisk = os.path.join(self.node.uuid, ramdisk_label)
        kernel = os.path.join(self.node.uuid, 'kernel')
        ramdisk = os.path.join(self.node.uuid, 'ramdisk')
        root_dir = CONF.pxe.tftp_root

        image_info = {
            kernel_label: (kernel_label,
                           os.path.join(root_dir,
                                        self.node.uuid,
                                        kernel_label)),
            ramdisk_label: (ramdisk_label,
                            os.path.join(root_dir,
                                         self.node.uuid,
                                         ramdisk_label))
        }

        if whle_dsk_img or deploy_utils.get_boot_option(self.node) == 'local':
            ramdisk = 'no_ramdisk'
            kernel = 'no_kernel'
        else:
            image_info.update({
                'kernel': ('kernel_id',
                           os.path.join(root_dir,
                                        self.node.uuid,
                                        'kernel')),
                'ramdisk': ('ramdisk_id',
                            os.path.join(root_dir,
                                         self.node.uuid,
                                         'ramdisk'))
            })

        if expected_pxe_params is None:
            expected_pxe_params = 'test_param'
        if debug:
            expected_pxe_params += ' ipa-debug=1'
        expected_pxe_params += (
            " ipa-global-request-id=%s" % self.context.global_id)

        expected_options = {
            'deployment_ari_path': pxe_ramdisk,
            'pxe_append_params': expected_pxe_params,
            'deployment_aki_path': pxe_kernel,
            'tftp_server': tftp_server,
            'ipxe_timeout': 0,
            'ari_path': ramdisk,
            'aki_path': kernel,
        }
        if ramdisk_kernel_opt:
            expected_options.update({'ramdisk_opts': ramdisk_kernel_opt})

        if mode == 'rescue':
            self.node.provision_state = states.RESCUING
            self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.build_pxe_config_options(
                task, image_info, ramdisk_params=ramdisk_params)
        self.assertEqual(expected_options, options)

    def test_build_pxe_config_options_pxe(self):
        self._test_build_pxe_config_options_pxe(whle_dsk_img=True)

    def test_build_pxe_config_options_pxe_ipa_debug(self):
        self._test_build_pxe_config_options_pxe(debug=True)

    def test_build_pxe_config_options_pxe_rescue(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self._test_build_pxe_config_options_pxe(mode='rescue')

    def test_build_pxe_config_options_ipa_debug_rescue(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self._test_build_pxe_config_options_pxe(debug=True, mode='rescue')

    def test_build_pxe_config_options_pxe_opts_ramdisk_opt(self):
        self.node.instance_info = {'ramdisk_kernel_arguments': 'cat meow'}
        self._test_build_pxe_config_options_pxe(ramdisk_kernel_opt='cat meow')

    def test_build_pxe_config_options_pxe_local_boot(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'local'}})
        self.node.instance_info = i_info
        self.node.save()
        self._test_build_pxe_config_options_pxe(whle_dsk_img=False)

    def test_build_pxe_config_options_pxe_without_is_whole_disk_image(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self.node.save()
        self._test_build_pxe_config_options_pxe(whle_dsk_img=False)

    def test_build_pxe_config_options_kernel_params_from_driver_info(self):
        info = self.node.driver_info
        info['kernel_append_params'] = 'params2'
        self.node.driver_info = info
        self.node.save()
        self._test_build_pxe_config_options_pxe(whle_dsk_img=True,
                                                expected_pxe_params='params2')

    def test_build_pxe_config_options_kernel_params_with_default(self):
        info = self.node.driver_info
        info['kernel_append_params'] = 'param1 %default% params2'
        self.node.driver_info = info
        self.node.save()
        self._test_build_pxe_config_options_pxe(
            whle_dsk_img=True,
            expected_pxe_params='param1 test_param params2')

    def test_build_pxe_config_options_kernel_params_from_instance_info(self):
        info = self.node.instance_info
        info['kernel_append_params'] = 'params2'
        self.node.instance_info = info
        self.node.save()
        self._test_build_pxe_config_options_pxe(whle_dsk_img=True,
                                                expected_pxe_params='params2')

    def test_build_pxe_config_options_ramdisk_params(self):
        self._test_build_pxe_config_options_pxe(
            whle_dsk_img=True,
            ramdisk_params=collections.OrderedDict([('foo', 'bar'),
                                                    ('banana', None)]),
            expected_pxe_params='test_param foo=bar banana')

    def test_build_pxe_config_options_pxe_no_kernel_no_ramdisk(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        self.node.save()
        pxe_params = 'my-pxe-append-params ipa-debug=0'
        self.config(group='pxe', kernel_append_params=pxe_params)
        self.config(group='pxe', tftp_server='my-tftp-server')
        self.config(group='pxe', tftp_root='/tftp-path/')
        image_info = {
            'deploy_kernel': ('deploy_kernel',
                              os.path.join(CONF.pxe.tftp_root,
                                           'path-to-deploy_kernel')),
            'deploy_ramdisk': ('deploy_ramdisk',
                               os.path.join(CONF.pxe.tftp_root,
                                            'path-to-deploy_ramdisk'))}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.build_pxe_config_options(task, image_info)

        expected_options = {
            'aki_path': 'no_kernel',
            'ari_path': 'no_ramdisk',
            'deployment_aki_path': 'path-to-deploy_kernel',
            'deployment_ari_path': 'path-to-deploy_ramdisk',
            'pxe_append_params': pxe_params + (
                " ipa-global-request-id=%s" % self.context.global_id),
            'tftp_server': 'my-tftp-server',
            'ipxe_timeout': 0}
        self.assertEqual(expected_options, options)


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class iPXEBuildConfigOptionsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(iPXEBuildConfigOptionsTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'ipxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config(enabled_boot_interfaces=['ipxe'])
        self.config_temp_dir('http_root', group='deploy')
        self.node = object_utils.create_test_node(self.context, **n)

    def _dhcp_options_for_instance_ipxe(self, task, boot_file, ip_version=4):
        self.config(ipxe_boot_script='/test/boot.ipxe', group='pxe')
        self.config(tftp_root='/tftp-path/', group='pxe')
        if ip_version == 4:
            self.config(tftp_server='192.0.2.1', group='pxe')
            self.config(http_url='http://192.0.3.2:1234', group='deploy')
            self.config(ipxe_boot_script='/test/boot.ipxe', group='pxe')
        elif ip_version == 6:
            self.config(tftp_server='ff80::1', group='pxe')
            self.config(http_url='http://[ff80::1]:1234', group='deploy')

        _reset_dhcp_provider(self.config, 'none')

        if ip_version == 6:
            # NOTE(TheJulia): DHCPv6 RFCs seem to indicate that the prior
            # options are not imported, although they may be supported
            # by vendors. The apparent proper option is to return a
            # URL in the field https://tools.ietf.org/html/rfc5970#section-3
            expected_boot_script_url = 'http://[ff80::1]:1234/boot.ipxe'
            expected_info = [{'opt_name': '!175,59',
                              'opt_value': 'tftp://[ff80::1]/%s' % boot_file,
                              'ip_version': ip_version},
                             {'opt_name': '59',
                              'opt_value': expected_boot_script_url,
                              'ip_version': ip_version}]

        elif ip_version == 4:
            expected_boot_script_url = 'http://192.0.3.2:1234/boot.ipxe'
            expected_info = [{'opt_name': '!175,67',
                              'opt_value': boot_file,
                              'ip_version': ip_version},
                             {'opt_name': '66',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': '150',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': '67',
                              'opt_value': expected_boot_script_url,
                              'ip_version': ip_version},
                             {'opt_name': '255',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version}]

        self.assertCountEqual(expected_info,
                              pxe_utils.dhcp_options_for_instance(
                                  task, ipxe_enabled=True))

        _reset_dhcp_provider(self.config, 'neutron')

        if ip_version == 6:
            # Boot URL variable set from prior test of isc parameters.
            expected_info = [{'opt_name': 'tag:!ipxe6,59',
                              'opt_value': 'tftp://[ff80::1]/%s' % boot_file,
                              'ip_version': ip_version},
                             {'opt_name': 'tag:ipxe6,59',
                              'opt_value': expected_boot_script_url,
                              'ip_version': ip_version}]

        elif ip_version == 4:
            expected_info = [{'opt_name': 'tag:!ipxe,67',
                              'opt_value': boot_file,
                              'ip_version': ip_version},
                             {'opt_name': '66',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': '150',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version},
                             {'opt_name': 'tag:ipxe,67',
                              'opt_value': expected_boot_script_url,
                              'ip_version': ip_version},
                             {'opt_name': '255',
                              'opt_value': '192.0.2.1',
                              'ip_version': ip_version}]

        self.assertCountEqual(expected_info,
                              pxe_utils.dhcp_options_for_instance(
                                  task, ipxe_enabled=True))

    def test_dhcp_options_for_instance_ipxe_bios(self):
        self.config(ip_version=4, group='pxe')
        boot_file = 'fake-bootfile-bios-ipxe'
        self.config(default_boot_mode='bios', group='deploy')
        self.config(ipxe_bootfile_name=boot_file, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self._dhcp_options_for_instance_ipxe(task, boot_file)

    def test_dhcp_options_for_instance_ipxe_uefi(self):
        self.config(ip_version=4, group='pxe')
        boot_file = 'fake-bootfile-uefi-ipxe'
        self.config(uefi_ipxe_bootfile_name=boot_file, group='pxe')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            self._dhcp_options_for_instance_ipxe(task, boot_file)

    def test_dhcp_options_for_ipxe_ipv6(self):
        self.config(ip_version=6, group='pxe')
        boot_file = 'fake-bootfile-ipxe'
        self.config(ipxe_bootfile_name=boot_file, group='pxe')
        self.config(default_boot_mode='bios', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self._dhcp_options_for_instance_ipxe(task, boot_file, ip_version=6)

    def test_dhcp_options_for_ipxe_ipv6_uefi(self):
        self.config(ip_version=6, group='pxe')
        boot_file = 'fake-bootfile-ipxe'
        self.config(uefi_ipxe_bootfile_name=boot_file, group='pxe')
        self.config(default_boot_mode='uefi', group='deploy')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self._dhcp_options_for_instance_ipxe(task, boot_file, ip_version=6)

    @mock.patch('ironic.common.image_service.GlanceImageService',
                autospec=True)
    @mock.patch('ironic.common.utils.render_template', autospec=True)
    def _test_build_pxe_config_options_ipxe(self, render_mock, glance_mock,
                                            whle_dsk_img=False,
                                            ipxe_timeout=0,
                                            ipxe_use_swift=False,
                                            debug=False,
                                            boot_from_volume=False,
                                            mode='deploy',
                                            iso_boot=False,
                                            multipath=False):
        self.config(debug=debug)
        self.config(kernel_append_params='test_param', group='pxe')
        self.config(ipxe_timeout=ipxe_timeout, group='pxe')
        root_dir = CONF.deploy.http_root

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = whle_dsk_img
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        tftp_server = CONF.pxe.tftp_server

        http_url = 'http://192.1.2.3:1234'
        self.config(http_url=http_url, group='deploy')

        kernel_label = '%s_kernel' % mode
        ramdisk_label = '%s_ramdisk' % mode

        if ipxe_use_swift:
            self.config(ipxe_use_swift=True, group='pxe')
            glance = mock.Mock()
            glance_mock.return_value = glance
            glance.swift_temp_url.side_effect = [pxe_kernel, pxe_ramdisk] = [
                'http://example.com/account/swift_kernel',
                'http://example.com/account/swift_ramdisk'
            ]
            image_info = {
                kernel_label: (uuidutils.generate_uuid(),
                               os.path.join(root_dir,
                                            self.node.uuid,
                                            kernel_label)),
                ramdisk_label: (uuidutils.generate_uuid(),
                                os.path.join(root_dir,
                                             self.node.uuid,
                                             ramdisk_label))
            }
            expected_initrd_filename = 'swift_ramdisk'
        else:
            pxe_kernel = os.path.join(http_url, self.node.uuid,
                                      kernel_label)
            pxe_ramdisk = os.path.join(http_url, self.node.uuid,
                                       ramdisk_label)
            image_info = {
                kernel_label: (kernel_label,
                               os.path.join(root_dir,
                                            self.node.uuid,
                                            kernel_label)),
                ramdisk_label: (ramdisk_label,
                                os.path.join(root_dir,
                                             self.node.uuid,
                                             ramdisk_label))
            }
            expected_initrd_filename = ramdisk_label

        kernel = os.path.join(http_url, self.node.uuid, 'kernel')
        ramdisk = os.path.join(http_url, self.node.uuid, 'ramdisk')
        if whle_dsk_img or deploy_utils.get_boot_option(self.node) == 'local':
            ramdisk = 'no_ramdisk'
            kernel = 'no_kernel'
        else:
            image_info.update({
                'kernel': ('kernel_id',
                           os.path.join(root_dir,
                                        self.node.uuid,
                                        'kernel')),
                'ramdisk': ('ramdisk_id',
                            os.path.join(root_dir,
                                         self.node.uuid,
                                         'ramdisk'))
            })

        ipxe_timeout_in_ms = ipxe_timeout * 1000

        expected_pxe_params = 'test_param'
        if debug:
            expected_pxe_params += ' ipa-debug=1'
        expected_pxe_params += (
            ' ipa-global-request-id=%s' % self.context.global_id)

        expected_options = {
            'deployment_ari_path': pxe_ramdisk,
            'pxe_append_params': expected_pxe_params,
            'deployment_aki_path': pxe_kernel,
            'tftp_server': tftp_server,
            'ipxe_timeout': ipxe_timeout_in_ms,
            'ari_path': ramdisk,
            'aki_path': kernel,
            'initrd_filename': expected_initrd_filename,
        }

        if mode == 'rescue':
            self.node.provision_state = states.RESCUING
            self.node.save()

        if boot_from_volume:
            expected_options.update({
                'boot_from_volume': True,
                'iscsi_initiator_iqn': 'fake_iqn_initiator',
                'iscsi_volumes': [{'url': 'iscsi:fake_host::3260:1:fake_iqn',
                                   'username': 'fake_username_1',
                                   'password': 'fake_password_1'
                                   }],
                'username': 'fake_username',
                'password': 'fake_password'
            })
            if multipath:
                expected_options.update({
                    'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn '
                                      'iscsi:faker_host::3261:0:fake_iqn',
                })
            else:
                expected_options.update({
                    'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn',
                })
            expected_options.pop('deployment_aki_path')
            expected_options.pop('deployment_ari_path')
            expected_options.pop('initrd_filename')

        if iso_boot:
            self.node.instance_info = {'boot_iso': 'http://test.url/file.iso'}
            self.node.save()
            iso_url = os.path.join(http_url, self.node.uuid, 'boot_iso')
            expected_options.update(
                {
                    'boot_iso_url': iso_url

                }
            )

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.build_pxe_config_options(task,
                                                         image_info,
                                                         ipxe_enabled=True)
        self.assertEqual(expected_options, options)

    def test_build_pxe_config_options_ipxe(self):
        self._test_build_pxe_config_options_ipxe(whle_dsk_img=True)

    def test_build_pxe_config_options_ipxe_ipa_debug(self):
        self._test_build_pxe_config_options_ipxe(debug=True)

    def test_build_pxe_config_options_ipxe_local_boot(self):
        del self.node.driver_internal_info['is_whole_disk_image']
        i_info = self.node.instance_info
        i_info.update({'capabilities': {'boot_option': 'local'}})
        self.node.instance_info = i_info
        self.node.save()
        self._test_build_pxe_config_options_ipxe(whle_dsk_img=False)

    def test_build_pxe_config_options_ipxe_swift_wdi(self):
        self._test_build_pxe_config_options_ipxe(whle_dsk_img=True,
                                                 ipxe_use_swift=True)

    def test_build_pxe_config_options_ipxe_swift_partition(self):
        self._test_build_pxe_config_options_ipxe(whle_dsk_img=False,
                                                 ipxe_use_swift=True)

    def test_build_pxe_config_options_ipxe_and_ipxe_timeout(self):
        self._test_build_pxe_config_options_ipxe(whle_dsk_img=True,
                                                 ipxe_timeout=120)

    def test_build_pxe_config_options_ipxe_and_iscsi_boot(self):
        vol_id = uuidutils.generate_uuid()
        vol_id2 = uuidutils.generate_uuid()
        object_utils.create_test_volume_connector(
            self.context,
            uuid=uuidutils.generate_uuid(),
            type='iqn',
            node_id=self.node.id,
            connector_id='fake_iqn_initiator')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'target_lun': 0,
                        'target_portal': 'fake_host:3260',
                        'target_iqn': 'fake_iqn',
                        'auth_username': 'fake_username',
                        'auth_password': 'fake_password'})
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='1235', uuid=vol_id2,
            properties={'target_lun': 1,
                        'target_portal': 'fake_host:3260',
                        'target_iqn': 'fake_iqn',
                        'auth_username': 'fake_username_1',
                        'auth_password': 'fake_password_1'})
        self.node.driver_internal_info.update({'boot_from_volume': vol_id})
        self._test_build_pxe_config_options_ipxe(boot_from_volume=True)

    def test_build_pxe_config_options_ipxe_and_iscsi_boot_from_lists(self):
        vol_id = uuidutils.generate_uuid()
        vol_id2 = uuidutils.generate_uuid()
        object_utils.create_test_volume_connector(
            self.context,
            uuid=uuidutils.generate_uuid(),
            type='iqn',
            node_id=self.node.id,
            connector_id='fake_iqn_initiator')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'target_luns': [0, 2],
                        'target_portals': ['fake_host:3260',
                                           'faker_host:3261'],
                        'target_iqns': ['fake_iqn', 'faker_iqn'],
                        'auth_username': 'fake_username',
                        'auth_password': 'fake_password'})
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='1235', uuid=vol_id2,
            properties={'target_lun': [1, 3],
                        'target_portal': ['fake_host:3260', 'faker_host:3261'],
                        'target_iqn': ['fake_iqn', 'faker_iqn'],
                        'auth_username': 'fake_username_1',
                        'auth_password': 'fake_password_1'})
        self.node.driver_internal_info.update({'boot_from_volume': vol_id})
        self._test_build_pxe_config_options_ipxe(boot_from_volume=True,
                                                 multipath=True)

    def test_get_volume_pxe_options(self):
        vol_id = uuidutils.generate_uuid()
        vol_id2 = uuidutils.generate_uuid()
        object_utils.create_test_volume_connector(
            self.context,
            uuid=uuidutils.generate_uuid(),
            type='iqn',
            node_id=self.node.id,
            connector_id='fake_iqn_initiator')
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'target_lun': [0, 1, 3],
                        'target_portal': 'fake_host:3260',
                        'target_iqns': 'fake_iqn',
                        'auth_username': 'fake_username',
                        'auth_password': 'fake_password'})
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=1, volume_id='1235', uuid=vol_id2,
            properties={'target_lun': 1,
                        'target_portal': 'fake_host:3260',
                        'target_iqn': 'fake_iqn',
                        'auth_username': 'fake_username_1',
                        'auth_password': 'fake_password_1'})
        self.node.driver_internal_info.update({'boot_from_volume': vol_id})
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['boot_from_volume'] = vol_id
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        expected = {'boot_from_volume': True,
                    'username': 'fake_username', 'password': 'fake_password',
                    'iscsi_boot_url': 'iscsi:fake_host::3260:0:fake_iqn',
                    'iscsi_initiator_iqn': 'fake_iqn_initiator',
                    'iscsi_volumes': [{
                        'url': 'iscsi:fake_host::3260:1:fake_iqn',
                        'username': 'fake_username_1',
                        'password': 'fake_password_1'
                    }]
                    }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.get_volume_pxe_options(task)
        self.assertEqual(expected, options)

    def test_get_volume_pxe_options_unsupported_volume_type(self):
        vol_id = uuidutils.generate_uuid()
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fake_type',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'foo': 'bar'})

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['boot_from_volume'] = vol_id
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.get_volume_pxe_options(task)
        self.assertEqual({}, options)

    def test_get_volume_pxe_options_unsupported_additional_volume_type(self):
        vol_id = uuidutils.generate_uuid()
        vol_id2 = uuidutils.generate_uuid()
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='iscsi',
            boot_index=0, volume_id='1234', uuid=vol_id,
            properties={'target_lun': 0,
                        'target_portal': 'fake_host:3260',
                        'target_iqn': 'fake_iqn',
                        'auth_username': 'fake_username',
                        'auth_password': 'fake_password'})
        object_utils.create_test_volume_target(
            self.context, node_id=self.node.id, volume_type='fake_type',
            boot_index=1, volume_id='1234', uuid=vol_id2,
            properties={'foo': 'bar'})

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['boot_from_volume'] = vol_id
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            options = pxe_utils.get_volume_pxe_options(task)
        self.assertEqual([], options['iscsi_volumes'])

    def test_build_pxe_config_options_ipxe_rescue(self):
        self._test_build_pxe_config_options_ipxe(mode='rescue')

    def test_build_pxe_config_options_ipxe_rescue_swift(self):
        self._test_build_pxe_config_options_ipxe(mode='rescue',
                                                 ipxe_use_swift=True)

    def test_build_pxe_config_options_ipxe_rescue_timeout(self):
        self._test_build_pxe_config_options_ipxe(mode='rescue',
                                                 ipxe_timeout=120)

    def test_build_pxe_config_options_ipxe_boot_iso(self):
        self._test_build_pxe_config_options_ipxe(iso_boot=True)

    @mock.patch('ironic.common.utils.rmtree_without_raise', autospec=True)
    @mock.patch('ironic_lib.utils.unlink_without_raise', autospec=True)
    def test_clean_up_ipxe_config_uefi(self, unlink_mock, rmtree_mock):
        self.config(http_root='/httpboot', group='deploy')
        address = "aa:aa:aa:aa:aa:aa"
        properties = {'capabilities': 'boot_mode:uefi'}
        object_utils.create_test_port(self.context, node_id=self.node.id,
                                      address=address)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.properties = properties
            pxe_utils.clean_up_pxe_config(task, ipxe_enabled=True)

            ensure_calls = [
                mock.call("/httpboot/pxelinux.cfg/%s"
                          % address.replace(':', '-')),
                mock.call("/httpboot/grub.cfg-01-aa-aa-aa-aa-aa-aa"),
                mock.call("/httpboot/%s.conf" % address)
            ]

            unlink_mock.assert_has_calls(ensure_calls)
            rmtree_mock.assert_called_once_with(
                os.path.join(CONF.deploy.http_root, self.node.uuid))


@mock.patch.object(ipxe.iPXEBoot, '__init__', lambda self: None)
class iPXEBuildServicePXEConfigTestCase(db_base.DbTestCase):
    def setUp(self):
        super(iPXEBuildServicePXEConfigTestCase, self).setUp()
        n = {
            'driver': 'fake-hardware',
            'boot_interface': 'ipxe',
            'instance_info': INST_INFO_DICT,
            'driver_info': DRV_INFO_DICT,
            'driver_internal_info': DRV_INTERNAL_INFO_DICT,
        }
        self.config(enabled_boot_interfaces=['ipxe'])
        self.node = object_utils.create_test_node(self.context, **n)

    @mock.patch.object(pxe_utils, 'create_pxe_config', autospec=True)
    @mock.patch.object(deploy_utils, 'switch_pxe_config', autospec=True)
    def test_build_service_pxe_config_adopt(self, mock_switch, mock_pxe_utils):
        self.node.provision_state = states.ADOPTING

        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['is_whole_disk_image'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        image_info = {}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.build_service_pxe_config(task, image_info, 'id',
                                               is_whole_disk_image=True)

        mock_pxe_utils.assert_called()
        mock_switch.assert_called()


@mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
@mock.patch.object(pxe_utils, 'clean_up_pxe_config', autospec=True)
@mock.patch.object(pxe_utils, 'TFTPImageCache', autospec=True)
class CleanUpPxeEnvTestCase(db_base.DbTestCase):
    def setUp(self):
        super(CleanUpPxeEnvTestCase, self).setUp()
        instance_info = INST_INFO_DICT
        instance_info['deploy_key'] = 'fake-56789'
        self.node = object_utils.create_test_node(
            self.context, boot_interface='pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )

    def test__clean_up_pxe_env(self, mock_cache, mock_pxe_clean,
                               mock_unlink):
        image_info = {'label': ['', 'deploy_kernel']}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_utils.clean_up_pxe_env(task, image_info)
            mock_pxe_clean.assert_called_once_with(task, ipxe_enabled=False)
            mock_unlink.assert_any_call('deploy_kernel')
        mock_cache.return_value.clean_up.assert_called_once_with()


class TFTPImageCacheTestCase(db_base.DbTestCase):
    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    def test_with_master_path(self, mock_ensure_tree):
        self.config(tftp_master_path='/fake/path', group='pxe')
        self.config(image_cache_size=500, group='pxe')
        self.config(image_cache_ttl=30, group='pxe')

        cache = pxe_utils.TFTPImageCache()

        mock_ensure_tree.assert_called_once_with('/fake/path')
        self.assertEqual(500 * 1024 * 1024, cache._cache_size)
        self.assertEqual(30 * 60, cache._cache_ttl)

    @mock.patch.object(fileutils, 'ensure_tree', autospec=True)
    def test_without_master_path(self, mock_ensure_tree):
        self.config(tftp_master_path='', group='pxe')
        self.config(image_cache_size=500, group='pxe')
        self.config(image_cache_ttl=30, group='pxe')

        cache = pxe_utils.TFTPImageCache()

        mock_ensure_tree.assert_not_called()
        self.assertEqual(500 * 1024 * 1024, cache._cache_size)
        self.assertEqual(30 * 60, cache._cache_ttl)


@mock.patch.object(os, 'makedirs', autospec=True)
@mock.patch.object(os, 'chmod', autospec=True)
@mock.patch.object(shutil, 'copy2', autospec=True)
class TestPXEUtilsBootloader(db_base.DbTestCase):

    def setUp(self):
        super(TestPXEUtilsBootloader, self).setUp()

    def test_place_loaders_for_boot_default_noop(self, mock_copy2,
                                                 mock_chmod, mock_makedirs):
        res = pxe_utils.place_loaders_for_boot('/httpboot')
        self.assertIsNone(res)
        self.assertFalse(mock_copy2.called)
        self.assertFalse(mock_chmod.called)
        self.assertFalse(mock_makedirs.called)
        self.assertFalse(mock_makedirs.called)

    def test_place_loaders_for_boot_no_source(self, mock_copy2,
                                              mock_chmod, mock_makedirs):
        self.config(loader_file_paths='grubaa64.efi:/path/to/file',
                    group='pxe')
        mock_copy2.side_effect = FileNotFoundError('No such file or directory')
        self.assertRaises(exception.IncorrectConfiguration,
                          pxe_utils.place_loaders_for_boot,
                          '/tftpboot')
        self.assertTrue(mock_copy2.called)
        self.assertFalse(mock_chmod.called)
        self.assertFalse(mock_makedirs.called)

    def test_place_loaders_for_boot_two_files(self, mock_copy2,
                                              mock_chmod, mock_makedirs):
        self.config(loader_file_paths='bootx64.efi:/path/to/shimx64.efi,'
                                      'grubx64.efi:/path/to/grubx64.efi',
                    group='pxe')
        self.config(file_permission=420, group='pxe')
        res = pxe_utils.place_loaders_for_boot('/tftpboot')
        self.assertIsNone(res)
        mock_copy2.assert_has_calls([
            mock.call('/path/to/shimx64.efi', '/tftpboot/bootx64.efi'),
            mock.call('/path/to/grubx64.efi', '/tftpboot/grubx64.efi')
        ])
        mock_chmod.assert_has_calls([
            mock.call('/tftpboot/bootx64.efi', CONF.pxe.file_permission),
            mock.call('/tftpboot/grubx64.efi', CONF.pxe.file_permission)
        ])
        self.assertFalse(mock_makedirs.called)

    def test_place_loaders_for_boot_two_files_exception_on_copy(
            self, mock_copy2, mock_chmod, mock_makedirs):
        self.config(loader_file_paths='bootx64.efi:/path/to/shimx64.efi,'
                                      'grubx64.efi:/path/to/grubx64.efi',
                    group='pxe')
        self.config(file_permission=420, group='pxe')
        mock_copy2.side_effect = PermissionError('Permission denied')
        self.assertRaises(exception.IncorrectConfiguration,
                          pxe_utils.place_loaders_for_boot,
                          '/tftpboot')
        mock_copy2.assert_has_calls([
            mock.call('/path/to/shimx64.efi', '/tftpboot/bootx64.efi'),
        ])
        mock_chmod.assert_not_called()
        self.assertFalse(mock_makedirs.called)

    def test_place_loaders_for_boot_two_files_exception_on_chmod(
            self, mock_copy2, mock_chmod, mock_makedirs):
        self.config(loader_file_paths='bootx64.efi:/path/to/shimx64.efi,'
                                      'grubx64.efi:/path/to/grubx64.efi',
                    group='pxe')
        self.config(file_permission=420, group='pxe')
        mock_chmod.side_effect = OSError('Chmod not permitted')
        self.assertRaises(exception.IncorrectConfiguration,
                          pxe_utils.place_loaders_for_boot,
                          '/tftpboot')
        mock_copy2.assert_has_calls([
            mock.call('/path/to/shimx64.efi', '/tftpboot/bootx64.efi'),
        ])
        mock_chmod.assert_has_calls([
            mock.call('/tftpboot/bootx64.efi', CONF.pxe.file_permission),
        ])
        self.assertFalse(mock_makedirs.called)

    def test_place_loaders_for_boot_raises_exception_with_absolute_path(
            self, mock_copy2, mock_chmod, mock_makedirs):
        self.config(
            loader_file_paths='/tftpboot/bootx64.efi:/path/to/shimx64.efi',
            group='pxe')
        exc = self.assertRaises(exception.IncorrectConfiguration,
                                pxe_utils.place_loaders_for_boot,
                                '/tftpboot')
        self.assertEqual('File paths configured for [pxe]loader_file_paths '
                         'must be relative paths. Entry: '
                         '/tftpboot/bootx64.efi', str(exc))

    def test_place_loaders_for_boot_two_files_relative_path(
            self, mock_copy2, mock_chmod, mock_makedirs):
        self.config(loader_file_paths='grub/bootx64.efi:/path/to/shimx64.efi,'
                                      'grub/grubx64.efi:/path/to/grubx64.efi',
                    group='pxe')
        self.config(dir_permission=484, group='pxe')
        self.config(file_permission=420, group='pxe')
        res = pxe_utils.place_loaders_for_boot('/tftpboot')
        self.assertIsNone(res)
        mock_copy2.assert_has_calls([
            mock.call('/path/to/shimx64.efi', '/tftpboot/grub/bootx64.efi'),
            mock.call('/path/to/grubx64.efi', '/tftpboot/grub/grubx64.efi')
        ])
        mock_chmod.assert_has_calls([
            mock.call('/tftpboot/grub/bootx64.efi', CONF.pxe.file_permission),
            mock.call('/tftpboot/grub/grubx64.efi', CONF.pxe.file_permission)
        ])
        mock_makedirs.assert_has_calls([
            mock.call('/tftpboot/grub', mode=CONF.pxe.dir_permission,
                      exist_ok=True),
            mock.call('/tftpboot/grub', mode=CONF.pxe.dir_permission,
                      exist_ok=True),
        ])
