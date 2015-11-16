#    Copyright (c) 2012 NTT DOCOMO, INC.
#    Copyright 2011 OpenStack Foundation
#    Copyright 2011 Ilya Alekseyev
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

import base64
import gzip
import os
import shutil
import stat
import tempfile
import time
import types

import mock
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import uuidutils
import requests
import testtools
from testtools import matchers

from ironic.common import boot_devices
from ironic.common import disk_partitioner
from ironic.common import exception
from ironic.common import image_service
from ironic.common import images
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils as utils
from ironic.drivers.modules import image_cache
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers.modules import pxe
from ironic.tests import base as tests_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INST_INFO_DICT = db_utils.get_test_pxe_instance_info()
DRV_INFO_DICT = db_utils.get_test_pxe_driver_info()
DRV_INTERNAL_INFO_DICT = db_utils.get_test_pxe_driver_internal_info()

_PXECONF_DEPLOY = b"""
default deploy

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root={{ ROOT }} --- ramdisk
"""

_PXECONF_BOOT_PARTITION = """
default boot_partition

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root=UUID=12345678-1234-1234-1234-1234567890abcdef \
--- ramdisk
"""

_PXECONF_BOOT_WHOLE_DISK = """
default boot_whole_disk

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}

label boot_whole_disk
COM32 chain.c32
append mbr:0x12345678

label trusted_boot
kernel mboot
append tboot.gz --- kernel root={{ ROOT }} --- ramdisk
"""

_PXECONF_TRUSTED_BOOT = """
default trusted_boot

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef

label boot_whole_disk
COM32 chain.c32
append mbr:{{ DISK_IDENTIFIER }}

label trusted_boot
kernel mboot
append tboot.gz --- kernel root=UUID=12345678-1234-1234-1234-1234567890abcdef \
--- ramdisk
"""

_IPXECONF_DEPLOY = b"""
#!ipxe

dhcp

goto deploy

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}
boot

:boot_whole_disk
kernel chain.c32
append mbr:{{ DISK_IDENTIFIER }}
boot
"""

_IPXECONF_BOOT_PARTITION = """
#!ipxe

dhcp

goto boot_partition

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef
boot

:boot_whole_disk
kernel chain.c32
append mbr:{{ DISK_IDENTIFIER }}
boot
"""

_IPXECONF_BOOT_WHOLE_DISK = """
#!ipxe

dhcp

goto boot_whole_disk

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot_partition
kernel kernel
append initrd=ramdisk root={{ ROOT }}
boot

:boot_whole_disk
kernel chain.c32
append mbr:0x12345678
boot
"""

_UEFI_PXECONF_DEPLOY = b"""
default=deploy

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root={{ ROOT }}"

image=chain.c32
        label=boot_whole_disk
        append="mbr:{{ DISK_IDENTIFIER }}"
"""

_UEFI_PXECONF_BOOT_PARTITION = """
default=boot_partition

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root=UUID=12345678-1234-1234-1234-1234567890abcdef"

image=chain.c32
        label=boot_whole_disk
        append="mbr:{{ DISK_IDENTIFIER }}"
"""

_UEFI_PXECONF_BOOT_WHOLE_DISK = """
default=boot_whole_disk

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot_partition
        initrd=ramdisk
        append="root={{ ROOT }}"

image=chain.c32
        label=boot_whole_disk
        append="mbr:0x12345678"
"""

_UEFI_PXECONF_DEPLOY_GRUB = b"""
set default=deploy
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=(( ROOT ))"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:(( DISK_IDENTIFIER ))
}
"""

_UEFI_PXECONF_BOOT_PARTITION_GRUB = """
set default=boot_partition
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=UUID=12345678-1234-1234-1234-1234567890abcdef"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:(( DISK_IDENTIFIER ))
}
"""

_UEFI_PXECONF_BOOT_WHOLE_DISK_GRUB = """
set default=boot_whole_disk
set timeout=5
set hidden_timeout_quiet=false

menuentry "deploy"  {
    linuxefi deploy_kernel "ro text"
    initrdefi deploy_ramdisk
}

menuentry "boot_partition"  {
    linuxefi kernel "root=(( ROOT ))"
    initrdefi ramdisk
}

menuentry "boot_whole_disk"  {
    linuxefi chain.c32 mbr:0x12345678
}
"""


@mock.patch.object(time, 'sleep', lambda seconds: None)
class PhysicalWorkTestCase(tests_base.TestCase):

    def _mock_calls(self, name_list):
        patch_list = [mock.patch.object(utils, name,
                                        spec_set=types.FunctionType)
                      for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock(spec=[])
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)
        return parent_mock

    @mock.patch.object(common_utils, 'mkfs', autospec=True)
    def _test_deploy_partition_image(self, mock_mkfs, boot_option=None,
                                     boot_mode=None):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 0
        ephemeral_format = None
        configdrive_mb = 0
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        swap_part = '/dev/fake-part1'
        root_part = '/dev/fake-part2'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'block_uuid',
                     'notify', 'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'root': root_part,
                                                    'swap': swap_part}

        make_partitions_expected_args = [dev, root_mb, swap_mb, ephemeral_mb,
                                         configdrive_mb, node_uuid]
        make_partitions_expected_kwargs = {'commit': True}
        deploy_kwargs = {}

        if boot_option:
            make_partitions_expected_kwargs['boot_option'] = boot_option
            deploy_kwargs['boot_option'] = boot_option
        else:
            make_partitions_expected_kwargs['boot_option'] = 'netboot'

        if boot_mode:
            make_partitions_expected_kwargs['boot_mode'] = boot_mode
            deploy_kwargs['boot_mode'] = boot_mode
        else:
            make_partitions_expected_kwargs['boot_mode'] = 'bios'

        # If no boot_option, then it should default to netboot.
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(
                              *make_partitions_expected_args,
                              **make_partitions_expected_kwargs),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuids_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid, **deploy_kwargs)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        expected_uuid_dict = {
            'root uuid': root_uuid,
            'efi system partition uuid': None}
        self.assertEqual(expected_uuid_dict, uuids_dict_returned)
        mock_mkfs.assert_called_once_with('swap', swap_part, 'swap1')

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

    @mock.patch.object(utils, 'get_image_mb', return_value=129, autospec=True)
    def test_deploy_partition_image_image_exceeds_root_partition(self,
                                                                 gim_mock):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 0
        ephemeral_format = None
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        self.assertRaises(exception.InstanceDeployFailure,
                          utils.deploy_partition_image, address, port, iqn,
                          lun, image_path, root_mb, swap_mb, ephemeral_mb,
                          ephemeral_format, node_uuid)

        gim_mock.assert_called_once_with(image_path)

    # We mock utils.block_uuid separately here because we can't predict
    # the order in which it will be called.
    @mock.patch.object(utils, 'block_uuid', autospec=True)
    @mock.patch.object(common_utils, 'mkfs', autospec=True)
    def test_deploy_partition_image_localboot_uefi(self, mock_mkfs,
                                                   block_uuid_mock):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 0
        ephemeral_format = None
        configdrive_mb = 0
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        efi_system_part = '/dev/fake-part1'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'
        efi_system_part_uuid = '9036-482'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'notify',
                     'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True

        def block_uuid_side_effect(device):
            if device == root_part:
                return root_uuid
            if device == efi_system_part:
                return efi_system_part_uuid

        block_uuid_mock.side_effect = block_uuid_side_effect
        parent_mock.make_partitions.return_value = {
            'root': root_part, 'swap': swap_part,
            'efi system partition': efi_system_part}

        # If no boot_option, then it should default to netboot.
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    configdrive_mb,
                                                    node_uuid,
                                                    commit=True,
                                                    boot_option="local",
                                                    boot_mode="uefi"),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(efi_system_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid, boot_option="local",
            boot_mode="uefi")

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        block_uuid_mock.assert_any_call('/dev/fake-part1')
        block_uuid_mock.assert_any_call('/dev/fake-part3')
        expected_uuid_dict = {
            'root uuid': root_uuid,
            'efi system partition uuid': efi_system_part_uuid}
        self.assertEqual(expected_uuid_dict, uuid_dict_returned)
        expected_calls = [mock.call('vfat', efi_system_part, 'efi-part'),
                          mock.call('swap', swap_part, 'swap1')]
        mock_mkfs.assert_has_calls(expected_calls)

    def test_deploy_partition_image_without_swap(self):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 0
        ephemeral_mb = 0
        ephemeral_format = None
        configdrive_mb = 0
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        root_part = '/dev/fake-part1'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'block_uuid',
                     'notify', 'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'root': root_part}
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    configdrive_mb,
                                                    node_uuid,
                                                    commit=True,
                                                    boot_option="netboot",
                                                    boot_mode="bios"),
                          mock.call.is_block_device(root_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_partition_image(address, port, iqn,
                                                          lun, image_path,
                                                          root_mb, swap_mb,
                                                          ephemeral_mb,
                                                          ephemeral_format,
                                                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])

    @mock.patch.object(common_utils, 'mkfs', autospec=True)
    def test_deploy_partition_image_with_ephemeral(self, mock_mkfs):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        configdrive_mb = 0
        ephemeral_format = 'exttest'
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'block_uuid',
                     'notify', 'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {
            'swap': swap_part, 'ephemeral': ephemeral_part, 'root': root_part}
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    configdrive_mb,
                                                    node_uuid,
                                                    commit=True,
                                                    boot_option="netboot",
                                                    boot_mode="bios"),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_partition_image(address, port, iqn,
                                                          lun, image_path,
                                                          root_mb, swap_mb,
                                                          ephemeral_mb,
                                                          ephemeral_format,
                                                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])
        expected_calls = [mock.call('swap', swap_part, 'swap1'),
                          mock.call(ephemeral_format, ephemeral_part,
                                    'ephemeral0')]
        mock_mkfs.assert_has_calls(expected_calls)

    @mock.patch.object(common_utils, 'mkfs', autospec=True)
    def test_deploy_partition_image_preserve_ephemeral(self, mock_mkfs):
        """Check if all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        ephemeral_format = 'exttest'
        configdrive_mb = 0
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'block_uuid',
                     'notify', 'get_dev_block_size']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {
            'swap': swap_part, 'ephemeral': ephemeral_part, 'root': root_part}
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    configdrive_mb,
                                                    node_uuid,
                                                    commit=False,
                                                    boot_option="netboot",
                                                    boot_mode="bios"),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid,
            preserve_ephemeral=True, boot_option="netboot")
        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertFalse(parent_mock.get_dev_block_size.called)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])
        mock_mkfs.assert_called_once_with('swap', swap_part, 'swap1')

    @mock.patch.object(common_utils, 'unlink_without_raise', autospec=True)
    def test_deploy_partition_image_with_configdrive(self, mock_unlink):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        root_mb = 128
        swap_mb = 0
        ephemeral_mb = 0
        configdrive_mb = 10
        ephemeral_format = None
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        configdrive_url = 'http://1.2.3.4/cd'

        dev = '/dev/fake'
        configdrive_part = '/dev/fake-part1'
        root_part = '/dev/fake-part2'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'populate_image', 'block_uuid',
                     'notify', 'destroy_disk_metadata', 'dd',
                     '_get_configdrive']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'root': root_part,
                                                    'configdrive':
                                                        configdrive_part}
        parent_mock._get_configdrive.return_value = (10, 'configdrive-path')
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call._get_configdrive(configdrive_url,
                                                     node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    configdrive_mb,
                                                    node_uuid,
                                                    commit=True,
                                                    boot_option="netboot",
                                                    boot_mode="bios"),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(configdrive_part),
                          mock.call.dd(mock.ANY, configdrive_part),
                          mock.call.populate_image(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid,
            configdrive=configdrive_url)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])
        mock_unlink.assert_called_once_with('configdrive-path')

    @mock.patch.object(utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image(self, mock_gdi):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        name_list = ['get_dev', 'discovery', 'login_iscsi', 'logout_iscsi',
                     'delete_iscsi', 'is_block_device', 'populate_image',
                     'notify']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.populate_image(image_path, dev),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        uuid_dict_returned = utils.deploy_disk_image(address, port, iqn, lun,
                                                     image_path, node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual('0x12345678', uuid_dict_returned['disk identifier'])

    @mock.patch.object(common_utils, 'execute', autospec=True)
    def test_verify_iscsi_connection_raises(self, mock_exec):
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.abc', '']
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.verify_iscsi_connection, iqn)
        self.assertEqual(3, mock_exec.call_count)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_check_file_system_for_iscsi_device_raises(self, mock_os):
        iqn = 'iqn.xyz'
        ip = "127.0.0.1"
        port = "22"
        mock_os.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.check_file_system_for_iscsi_device,
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
        utils.check_file_system_for_iscsi_device(ip, port, iqn)
        mock_os.assert_called_once_with(check_dir)

    @mock.patch.object(common_utils, 'execute', autospec=True)
    def test_verify_iscsi_connection(self, mock_exec):
        iqn = 'iqn.xyz'
        mock_exec.return_value = ['iqn.xyz', '']
        utils.verify_iscsi_connection(iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-S',
            run_as_root=True,
            check_exit_code=[0])

    @mock.patch.object(common_utils, 'execute', autospec=True)
    def test_force_iscsi_lun_update(self, mock_exec):
        iqn = 'iqn.xyz'
        utils.force_iscsi_lun_update(iqn)
        mock_exec.assert_called_once_with(
            'iscsiadm',
            '-m', 'node',
            '-T', iqn,
            '-R',
            run_as_root=True,
            check_exit_code=[0])

    @mock.patch.object(common_utils, 'execute', autospec=True)
    @mock.patch.object(utils, 'verify_iscsi_connection', autospec=True)
    @mock.patch.object(utils, 'force_iscsi_lun_update', autospec=True)
    @mock.patch.object(utils, 'check_file_system_for_iscsi_device',
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
        utils.login_iscsi(address, port, iqn)
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

    @mock.patch.object(utils, 'is_block_device', lambda d: True)
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

        dev = '/dev/fake'

        class TestException(Exception):
            pass

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'work_on_disk']
        patch_list = [mock.patch.object(utils, name,
                                        spec_set=types.FunctionType)
                      for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock(spec=[])
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)

        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.work_on_disk.side_effect = TestException
        calls_expected = [mock.call.get_image_mb(image_path),
                          mock.call.get_dev(address, port, iqn, lun),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.work_on_disk(dev, root_mb, swap_mb,
                                                 ephemeral_mb,
                                                 ephemeral_format, image_path,
                                                 node_uuid, configdrive=None,
                                                 preserve_ephemeral=False,
                                                 boot_option="netboot",
                                                 boot_mode="bios"),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        self.assertRaises(TestException, utils.deploy_partition_image,
                          address, port, iqn, lun, image_path,
                          root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)


class SwitchPxeConfigTestCase(tests_base.TestCase):

    def _create_config(self, ipxe=False, boot_mode=None, boot_loader='elilo'):
        (fd, fname) = tempfile.mkstemp()
        if boot_mode == 'uefi':
            if boot_loader == 'grub':
                pxe_cfg = _UEFI_PXECONF_DEPLOY_GRUB
            else:
                pxe_cfg = _UEFI_PXECONF_DEPLOY
        else:
            pxe_cfg = _IPXECONF_DEPLOY if ipxe else _PXECONF_DEPLOY
        os.write(fd, pxe_cfg)
        os.close(fd)
        self.addCleanup(os.unlink, fname)
        return fname

    def test_switch_pxe_config_partition_image(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_pxe_config_whole_disk_image(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_pxe_config_trusted_boot(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False, True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_TRUSTED_BOOT, pxeconf)

    def test_switch_ipxe_config_partition_image(self):
        boot_mode = 'bios'
        cfg.CONF.set_override('ipxe_enabled', True, 'pxe')
        fname = self._create_config(ipxe=True)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_ipxe_config_whole_disk_image(self):
        boot_mode = 'bios'
        cfg.CONF.set_override('ipxe_enabled', True, 'pxe')
        fname = self._create_config(ipxe=True)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_uefi_elilo_pxe_config_partition_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_uefi_elilo_config_whole_disk_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_WHOLE_DISK, pxeconf)

    def test_switch_uefi_grub_pxe_config_partition_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, boot_loader='grub')
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_PARTITION_GRUB, pxeconf)

    def test_switch_uefi_grub_config_whole_disk_image(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode, boot_loader='grub')
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT_WHOLE_DISK_GRUB, pxeconf)


@mock.patch('time.sleep', lambda sec: None)
class OtherFunctionTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OtherFunctionTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.node = obj_utils.create_test_node(self.context, driver='fake_pxe')

    def test_get_dev(self):
        expected = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        actual = utils.get_dev('1.2.3.4', 5678, 'iqn.fake', 9)
        self.assertEqual(expected, actual)

    @mock.patch.object(os, 'stat', autospec=True)
    @mock.patch.object(stat, 'S_ISBLK', autospec=True)
    def test_is_block_device_works(self, mock_is_blk, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_is_blk.return_value = True
        mock_os().st_mode = 10000
        self.assertTrue(utils.is_block_device(device))
        mock_is_blk.assert_called_once_with(mock_os().st_mode)

    @mock.patch.object(os, 'stat', autospec=True)
    def test_is_block_device_raises(self, mock_os):
        device = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        mock_os.side_effect = OSError
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.is_block_device, device)
        mock_os.assert_has_calls([mock.call(device)] * 3)

    @mock.patch.object(os.path, 'getsize', autospec=True)
    @mock.patch.object(images, 'converted_size', autospec=True)
    def test_get_image_mb(self, mock_csize, mock_getsize):
        mb = 1024 * 1024

        mock_getsize.return_value = 0
        mock_csize.return_value = 0
        self.assertEqual(0, utils.get_image_mb('x', False))
        self.assertEqual(0, utils.get_image_mb('x', True))
        mock_getsize.return_value = 1
        mock_csize.return_value = 1
        self.assertEqual(1, utils.get_image_mb('x', False))
        self.assertEqual(1, utils.get_image_mb('x', True))
        mock_getsize.return_value = mb
        mock_csize.return_value = mb
        self.assertEqual(1, utils.get_image_mb('x', False))
        self.assertEqual(1, utils.get_image_mb('x', True))
        mock_getsize.return_value = mb + 1
        mock_csize.return_value = mb + 1
        self.assertEqual(2, utils.get_image_mb('x', False))
        self.assertEqual(2, utils.get_image_mb('x', True))

    def test_parse_root_device_hints(self):
        self.node.properties['root_device'] = {
            'wwn': 123456, 'model': 'foo-model', 'size': 123,
            'serial': 'foo-serial', 'vendor': 'foo-vendor',
            'wwn_with_extension': 123456111, 'wwn_vendor_extension': 111,
        }
        expected = ('model=foo-model,serial=foo-serial,size=123,'
                    'vendor=foo-vendor,wwn=123456,wwn_vendor_extension=111,'
                    'wwn_with_extension=123456111')
        result = utils.parse_root_device_hints(self.node)
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_string_space(self):
        self.node.properties['root_device'] = {'model': 'fake model'}
        expected = 'model=fake%20model'
        result = utils.parse_root_device_hints(self.node)
        self.assertEqual(expected, result)

    def test_parse_root_device_hints_no_hints(self):
        self.node.properties = {}
        result = utils.parse_root_device_hints(self.node)
        self.assertIsNone(result)

    def test_parse_root_device_hints_invalid_hints(self):
        self.node.properties['root_device'] = {'vehicle': 'Owlship'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_root_device_hints, self.node)

    def test_parse_root_device_hints_invalid_size(self):
        self.node.properties['root_device'] = {'size': 'not-int'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_root_device_hints, self.node)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(task_manager.TaskManager, 'process_event',
                       autospec=True)
    def _test_set_failed_state(self, mock_event, mock_power, mock_log,
                               event_value=None, power_value=None,
                               log_calls=None):
        err_msg = 'some failure'
        mock_event.side_effect = event_value
        mock_power.side_effect = power_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.set_failed_state(task, err_msg)
            mock_event.assert_called_once_with(task, 'fail')
            mock_power.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(err_msg, task.node.last_error)
            if log_calls:
                mock_log.exception.assert_has_calls(log_calls)
            else:
                self.assertFalse(mock_log.called)

    def test_set_failed_state(self):
        exc_state = exception.InvalidState('invalid state')
        exc_param = exception.InvalidParameterValue('invalid parameter')
        mock_call = mock.call(mock.ANY)
        self._test_set_failed_state()
        calls = [mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    log_calls=calls)
        calls = [mock_call]
        self._test_set_failed_state(power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls)
        calls = [mock_call, mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls)

    def test_get_boot_option(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_default_value(self):
        self.node.instance_info = {}
        result = utils.get_boot_option(self.node)
        self.assertEqual("netboot", result)


@mock.patch.object(disk_partitioner.DiskPartitioner, 'commit', lambda _: None)
class WorkOnDiskTestCase(tests_base.TestCase):

    def setUp(self):
        super(WorkOnDiskTestCase, self).setUp()
        self.image_path = '/tmp/xyz/image'
        self.root_mb = 128
        self.swap_mb = 64
        self.ephemeral_mb = 0
        self.ephemeral_format = None
        self.configdrive_mb = 0
        self.dev = '/dev/fake'
        self.swap_part = '/dev/fake-part1'
        self.root_part = '/dev/fake-part2'

        self.mock_ibd_obj = mock.patch.object(
            utils, 'is_block_device', autospec=True)
        self.mock_ibd = self.mock_ibd_obj.start()
        self.addCleanup(self.mock_ibd_obj.stop)
        self.mock_mp_obj = mock.patch.object(
            utils, 'make_partitions', autospec=True)
        self.mock_mp = self.mock_mp_obj.start()
        self.addCleanup(self.mock_mp_obj.stop)
        self.mock_remlbl_obj = mock.patch.object(
            utils, 'destroy_disk_metadata', autospec=True)
        self.mock_remlbl = self.mock_remlbl_obj.start()
        self.addCleanup(self.mock_remlbl_obj.stop)
        self.mock_mp.return_value = {'swap': self.swap_part,
                                     'root': self.root_part}

    def test_no_root_partition(self):
        self.mock_ibd.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid')
        self.mock_ibd.assert_called_once_with(self.root_part)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             'fake-uuid',
                                             commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    def test_no_swap_partition(self):
        self.mock_ibd.side_effect = iter([True, False])
        calls = [mock.call(self.root_part),
                 mock.call(self.swap_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid')
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             self.configdrive_mb,
                                             'fake-uuid',
                                             commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    def test_no_ephemeral_partition(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, ephemeral_mb, ephemeral_format,
                          self.image_path, 'fake-uuid')
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             self.configdrive_mb,
                                             'fake-uuid',
                                             commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")

    @mock.patch.object(common_utils, 'unlink_without_raise', autospec=True)
    @mock.patch.object(utils, '_get_configdrive', autospec=True)
    def test_no_configdrive_partition(self, mock_configdrive, mock_unlink):
        mock_configdrive.return_value = (10, 'fake-path')
        swap_part = '/dev/fake-part1'
        configdrive_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        configdrive_url = 'http://1.2.3.4/cd'
        configdrive_mb = 10

        self.mock_mp.return_value = {'swap': swap_part,
                                     'configdrive': configdrive_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = iter([True, True, False])
        calls = [mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(configdrive_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, 'fake-uuid',
                          preserve_ephemeral=False,
                          configdrive=configdrive_url,
                          boot_option="netboot")
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             configdrive_mb,
                                             'fake-uuid',
                                             commit=True,
                                             boot_option="netboot",
                                             boot_mode="bios")
        mock_unlink.assert_called_once_with('fake-path')


@mock.patch.object(common_utils, 'execute', autospec=True)
class MakePartitionsTestCase(tests_base.TestCase):

    def setUp(self):
        super(MakePartitionsTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.root_mb = 1024
        self.swap_mb = 512
        self.ephemeral_mb = 0
        self.configdrive_mb = 0
        self.parted_static_cmd = ['parted', '-a', 'optimal', '-s', self.dev,
                                  '--', 'unit', 'MiB', 'mklabel', 'msdos']

    def _test_make_partitions(self, mock_exc, boot_option):
        mock_exc.return_value = (None, None)
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb, self.configdrive_mb,
                              '12345678-1234-1234-1234-1234567890abcxyz',
                              boot_option=boot_option)

        expected_mkpart = ['mkpart', 'primary', 'linux-swap', '1', '513',
                           'mkpart', 'primary', '', '513', '1537']
        if boot_option == "local":
            expected_mkpart.extend(['set', '2', 'boot', 'on'])
        parted_cmd = self.parted_static_cmd + expected_mkpart
        parted_call = mock.call(*parted_cmd, use_standard_locale=True,
                                run_as_root=True, check_exit_code=[0])
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, run_as_root=True,
                               check_exit_code=[0, 1])
        mock_exc.assert_has_calls([parted_call, fuser_call])

    def test_make_partitions(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="netboot")

    def test_make_partitions_local_boot(self, mock_exc):
        self._test_make_partitions(mock_exc, boot_option="local")

    def test_make_partitions_with_ephemeral(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        cmd = self.parted_static_cmd + expected_mkpart
        mock_exc.return_value = (None, None)
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb, self.configdrive_mb,
                              '12345678-1234-1234-1234-1234567890abcxyz')

        parted_call = mock.call(*cmd, use_standard_locale=True,
                                run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls([parted_call])


@mock.patch.object(utils, 'get_dev_block_size', autospec=True)
@mock.patch.object(common_utils, 'execute', autospec=True)
class DestroyMetaDataTestCase(tests_base.TestCase):

    def setUp(self):
        super(DestroyMetaDataTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_destroy_disk_metadata(self, mock_exec, mock_gz):
        mock_gz.return_value = 64
        expected_calls = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', run_as_root=True,
                                    check_exit_code=[0],
                                    use_standard_locale=True),
                          mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', 'seek=28',
                                    run_as_root=True,
                                    check_exit_code=[0],
                                    use_standard_locale=True)]
        utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)
        self.assertTrue(mock_gz.called)

    def test_destroy_disk_metadata_get_dev_size_fail(self, mock_exec, mock_gz):
        mock_gz.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                   'bs=512', 'count=36', run_as_root=True,
                                   check_exit_code=[0],
                                   use_standard_locale=True)]
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)

    def test_destroy_disk_metadata_dd_fail(self, mock_exec, mock_gz):
        mock_exec.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                   'bs=512', 'count=36', run_as_root=True,
                                   check_exit_code=[0],
                                   use_standard_locale=True)]
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)
        self.assertFalse(mock_gz.called)


@mock.patch.object(common_utils, 'execute', autospec=True)
class GetDeviceBlockSizeTestCase(tests_base.TestCase):

    def setUp(self):
        super(GetDeviceBlockSizeTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_get_dev_block_size(self, mock_exec):
        mock_exec.return_value = ("64", "")
        expected_call = [mock.call('blockdev', '--getsz', self.dev,
                                   run_as_root=True, check_exit_code=[0])]
        utils.get_dev_block_size(self.dev)
        mock_exec.assert_has_calls(expected_call)


@mock.patch.object(utils, 'dd', autospec=True)
@mock.patch.object(images, 'qemu_img_info', autospec=True)
@mock.patch.object(images, 'convert_image', autospec=True)
class PopulateImageTestCase(tests_base.TestCase):

    def setUp(self):
        super(PopulateImageTestCase, self).setUp()

    def test_populate_raw_image(self, mock_cg, mock_qinfo, mock_dd):
        type(mock_qinfo.return_value).file_format = mock.PropertyMock(
            return_value='raw')
        utils.populate_image('src', 'dst')
        mock_dd.assert_called_once_with('src', 'dst')
        self.assertFalse(mock_cg.called)

    def test_populate_qcow2_image(self, mock_cg, mock_qinfo, mock_dd):
        type(mock_qinfo.return_value).file_format = mock.PropertyMock(
            return_value='qcow2')
        utils.populate_image('src', 'dst')
        mock_cg.assert_called_once_with('src', 'dst', 'raw', True)
        self.assertFalse(mock_dd.called)


@mock.patch.object(utils, 'is_block_device', lambda d: True)
@mock.patch.object(utils, 'block_uuid', lambda p: 'uuid')
@mock.patch.object(utils, 'dd', lambda *_: None)
@mock.patch.object(images, 'convert_image', lambda *_: None)
@mock.patch.object(common_utils, 'mkfs', lambda *_: None)
# NOTE(dtantsur): destroy_disk_metadata resets file size, disabling it
@mock.patch.object(utils, 'destroy_disk_metadata', lambda *_: None)
class RealFilePartitioningTestCase(tests_base.TestCase):
    """This test applies some real-world partitioning scenario to a file.

    This test covers the whole partitioning, mocking everything not possible
    on a file. That helps us assure, that we do all partitioning math properly
    and also conducts integration testing of DiskPartitioner.
    """

    def setUp(self):
        super(RealFilePartitioningTestCase, self).setUp()
        # NOTE(dtantsur): no parted utility on gate-ironic-python26
        try:
            common_utils.execute('parted', '--version')
        except OSError as exc:
            self.skipTest('parted utility was not found: %s' % exc)
        self.file = tempfile.NamedTemporaryFile(delete=False)
        # NOTE(ifarkas): the file needs to be closed, so fuser won't report
        #                any usage
        self.file.close()
        # NOTE(dtantsur): 20 MiB file with zeros
        common_utils.execute('dd', 'if=/dev/zero', 'of=%s' % self.file.name,
                             'bs=1', 'count=0', 'seek=20MiB')

    @staticmethod
    def _run_without_root(func, *args, **kwargs):
        """Make sure root is not required when using utils.execute."""
        real_execute = common_utils.execute

        def fake_execute(*cmd, **kwargs):
            kwargs['run_as_root'] = False
            return real_execute(*cmd, **kwargs)

        with mock.patch.object(common_utils, 'execute', fake_execute):
            return func(*args, **kwargs)

    def test_different_sizes(self):
        # NOTE(dtantsur): Keep this list in order with expected partitioning
        fields = ['ephemeral_mb', 'swap_mb', 'root_mb']
        variants = ((0, 0, 12), (4, 2, 8), (0, 4, 10), (5, 0, 10))
        for variant in variants:
            kwargs = dict(zip(fields, variant))
            self._run_without_root(utils.work_on_disk, self.file.name,
                                   ephemeral_format='ext4', node_uuid='',
                                   image_path='path', **kwargs)
            part_table = self._run_without_root(
                disk_partitioner.list_partitions, self.file.name)
            for part, expected_size in zip(part_table, filter(None, variant)):
                self.assertEqual(expected_size, part['size'],
                                 "comparison failed for %s" % list(variant))

    def test_whole_disk(self):
        # 6 MiB ephemeral + 3 MiB swap + 9 MiB root + 1 MiB for MBR
        # + 1 MiB MAGIC == 20 MiB whole disk
        # TODO(dtantsur): figure out why we need 'magic' 1 more MiB
        # and why the is different on Ubuntu and Fedora (see below)
        self._run_without_root(utils.work_on_disk, self.file.name,
                               root_mb=9, ephemeral_mb=6, swap_mb=3,
                               ephemeral_format='ext4', node_uuid='',
                               image_path='path')
        part_table = self._run_without_root(
            disk_partitioner.list_partitions, self.file.name)
        sizes = [part['size'] for part in part_table]
        # NOTE(dtantsur): parted in Ubuntu 12.04 will occupy the last MiB,
        # parted in Fedora 20 won't - thus two possible variants for last part
        self.assertEqual([6, 3], sizes[:2],
                         "unexpected partitioning %s" % part_table)
        self.assertIn(sizes[2], (9, 10))

    @mock.patch.object(image_cache, 'clean_up_caches', autospec=True)
    def test_fetch_images(self, mock_clean_up_caches):

        mock_cache = mock.MagicMock(
            spec_set=['fetch_image', 'master_dir'], master_dir='master_dir')
        utils.fetch_images(None, mock_cache, [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])
        mock_cache.fetch_image.assert_called_once_with('uuid', 'path',
                                                       ctx=None,
                                                       force_raw=True)

    @mock.patch.object(image_cache, 'clean_up_caches', autospec=True)
    def test_fetch_images_fail(self, mock_clean_up_caches):

        exc = exception.InsufficientDiskSpace(path='a',
                                              required=2,
                                              actual=1)

        mock_cache = mock.MagicMock(
            spec_set=['master_dir'], master_dir='master_dir')
        mock_clean_up_caches.side_effect = iter([exc])
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.fetch_images,
                          None,
                          mock_cache,
                          [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])


@mock.patch.object(tempfile, 'NamedTemporaryFile', autospec=True)
@mock.patch.object(shutil, 'copyfileobj', autospec=True)
@mock.patch.object(requests, 'get', autospec=True)
class GetConfigdriveTestCase(tests_base.TestCase):

    def setUp(self):
        super(GetConfigdriveTestCase, self).setUp()
        # NOTE(lucasagomes): "name" can't be passed to Mock() when
        # instantiating the object because it's an expected parameter.
        # https://docs.python.org/3/library/unittest.mock.html
        self.fake_configdrive_file = mock.Mock(tell=lambda *_: 123)
        self.fake_configdrive_file.name = '/tmp/foo'

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive(self, mock_gzip, mock_requests, mock_copy,
                             mock_file):
        mock_file.return_value = self.fake_configdrive_file
        mock_requests.return_value = mock.MagicMock(
            spec_set=['content'], content='Zm9vYmFy')
        utils._get_configdrive('http://1.2.3.4/cd', 'fake-node-uuid')
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)
        mock_file.assert_called_once_with(prefix='configdrive',
                                          dir=cfg.CONF.tempdir, delete=False)

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive_base64_string(self, mock_gzip, mock_requests,
                                           mock_copy, mock_file):
        mock_file.return_value = self.fake_configdrive_file
        utils._get_configdrive('Zm9vYmFy', 'fake-node-uuid')
        self.assertFalse(mock_requests.called)
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)
        mock_file.assert_called_once_with(prefix='configdrive',
                                          dir=cfg.CONF.tempdir, delete=False)

    def test_get_configdrive_bad_url(self, mock_requests, mock_copy,
                                     mock_file):
        mock_requests.side_effect = requests.exceptions.RequestException
        self.assertRaises(exception.InstanceDeployFailure,
                          utils._get_configdrive, 'http://1.2.3.4/cd',
                          'fake-node-uuid')
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_file.called)

    @mock.patch.object(base64, 'b64decode', autospec=True)
    def test_get_configdrive_base64_error(self, mock_b64, mock_requests,
                                          mock_copy, mock_file):
        mock_b64.side_effect = TypeError
        self.assertRaises(exception.InstanceDeployFailure,
                          utils._get_configdrive,
                          'malformed', 'fake-node-uuid')
        mock_b64.assert_called_once_with('malformed')
        self.assertFalse(mock_copy.called)
        self.assertFalse(mock_file.called)

    @mock.patch.object(gzip, 'GzipFile', autospec=True)
    def test_get_configdrive_gzip_error(self, mock_gzip, mock_requests,
                                        mock_copy, mock_file):
        mock_file.return_value = self.fake_configdrive_file
        mock_requests.return_value = mock.MagicMock(
            spec_set=['content'], content='Zm9vYmFy')
        mock_copy.side_effect = IOError
        self.assertRaises(exception.InstanceDeployFailure,
                          utils._get_configdrive, 'http://1.2.3.4/cd',
                          'fake-node-uuid')
        mock_requests.assert_called_once_with('http://1.2.3.4/cd')
        mock_gzip.assert_called_once_with('configdrive', 'rb',
                                          fileobj=mock.ANY)
        mock_copy.assert_called_once_with(mock.ANY, mock.ANY)
        mock_file.assert_called_once_with(prefix='configdrive',
                                          dir=cfg.CONF.tempdir, delete=False)


class VirtualMediaDeployUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(VirtualMediaDeployUtilsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        info_dict = db_utils.get_test_ilo_info()
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_ilo', driver_info=info_dict)

    def test_get_single_nic_with_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            extra={'vif_port_id': 'test-vif-A'}, driver='iscsi_ilo')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)


class ParseInstanceInfoCapabilitiesTestCase(tests_base.TestCase):

    def setUp(self):
        super(ParseInstanceInfoCapabilitiesTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context, driver='fake')

    def test_parse_instance_info_capabilities_string(self):
        self.node.instance_info = {'capabilities': '{"cat": "meow"}'}
        expected_result = {"cat": "meow"}
        result = utils.parse_instance_info_capabilities(self.node)
        self.assertEqual(expected_result, result)

    def test_parse_instance_info_capabilities(self):
        self.node.instance_info = {'capabilities': {"dog": "wuff"}}
        expected_result = {"dog": "wuff"}
        result = utils.parse_instance_info_capabilities(self.node)
        self.assertEqual(expected_result, result)

    def test_parse_instance_info_invalid_type(self):
        self.node.instance_info = {'capabilities': 'not-a-dict'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info_capabilities, self.node)

    def test_is_secure_boot_requested_true(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "tRue"}}
        self.assertTrue(utils.is_secure_boot_requested(self.node))

    def test_is_secure_boot_requested_false(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "false"}}
        self.assertFalse(utils.is_secure_boot_requested(self.node))

    def test_is_secure_boot_requested_invalid(self):
        self.node.instance_info = {'capabilities': {"secure_boot": "invalid"}}
        self.assertFalse(utils.is_secure_boot_requested(self.node))

    def test_is_trusted_boot_requested_true(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "true"}}
        self.assertTrue(utils.is_trusted_boot_requested(self.node))

    def test_is_trusted_boot_requested_false(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "false"}}
        self.assertFalse(utils.is_trusted_boot_requested(self.node))

    def test_is_trusted_boot_requested_invalid(self):
        self.node.instance_info = {'capabilities': {"trusted_boot": "invalid"}}
        self.assertFalse(utils.is_trusted_boot_requested(self.node))

    def test_get_boot_mode_for_deploy_using_capabilities(self):
        properties = {'capabilities': 'boot_mode:uefi,cap2:value2'}
        self.node.properties = properties

        result = utils.get_boot_mode_for_deploy(self.node)
        self.assertEqual('uefi', result)

    def test_get_boot_mode_for_deploy_using_instance_info_cap(self):
        instance_info = {'capabilities': {'secure_boot': 'True'}}
        self.node.instance_info = instance_info

        result = utils.get_boot_mode_for_deploy(self.node)
        self.assertEqual('uefi', result)

        instance_info = {'capabilities': {'trusted_boot': 'True'}}
        self.node.instance_info = instance_info

        result = utils.get_boot_mode_for_deploy(self.node)
        self.assertEqual('bios', result)

        instance_info = {'capabilities': {'trusted_boot': 'True'},
                         'capabilities': {'secure_boot': 'True'}}
        self.node.instance_info = instance_info

        result = utils.get_boot_mode_for_deploy(self.node)
        self.assertEqual('uefi', result)

    def test_get_boot_mode_for_deploy_using_instance_info(self):
        instance_info = {'deploy_boot_mode': 'bios'}
        self.node.instance_info = instance_info

        result = utils.get_boot_mode_for_deploy(self.node)
        self.assertEqual('bios', result)

    def test_validate_boot_mode_capability(self):
        prop = {'capabilities': 'boot_mode:uefi,cap2:value2'}
        self.node.properties = prop

        result = utils.validate_capabilities(self.node)
        self.assertIsNone(result)

    def test_validate_boot_mode_capability_with_exc(self):
        prop = {'capabilities': 'boot_mode:UEFI,cap2:value2'}
        self.node.properties = prop

        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_validate_boot_mode_capability_instance_info(self):
        inst_info = {'capabilities': {"boot_mode": "uefi", "cap2": "value2"}}
        self.node.instance_info = inst_info

        result = utils.validate_capabilities(self.node)
        self.assertIsNone(result)

    def test_validate_boot_mode_capability_instance_info_with_exc(self):
        inst_info = {'capabilities': {"boot_mode": "UEFI", "cap2": "value2"}}
        self.node.instance_info = inst_info

        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_validate_trusted_boot_capability(self):
        properties = {'capabilities': 'trusted_boot:value'}
        self.node.properties = properties
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_capabilities, self.node)

    def test_all_supported_capabilities(self):
        self.assertEqual(('local', 'netboot'),
                         utils.SUPPORTED_CAPABILITIES['boot_option'])
        self.assertEqual(('bios', 'uefi'),
                         utils.SUPPORTED_CAPABILITIES['boot_mode'])
        self.assertEqual(('true', 'false'),
                         utils.SUPPORTED_CAPABILITIES['secure_boot'])
        self.assertEqual(('true', 'false'),
                         utils.SUPPORTED_CAPABILITIES['trusted_boot'])


class TrySetBootDeviceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(TrySetBootDeviceTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake")
        self.node = obj_utils.create_test_node(self.context, driver="fake")

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_okay(self, node_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.try_set_boot_device(task, boot_devices.DISK,
                                      persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_ipmifailure_uefi(
            self, node_set_boot_device_mock, log_mock):
        self.node.properties = {'capabilities': 'boot_mode:uefi'}
        self.node.save()
        node_set_boot_device_mock.side_effect = iter(
            [exception.IPMIFailure(cmd='a')])
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            utils.try_set_boot_device(task, boot_devices.DISK,
                                      persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            log_mock.warning.assert_called_once_with(mock.ANY)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_ipmifailure_bios(
            self, node_set_boot_device_mock):
        node_set_boot_device_mock.side_effect = iter(
            [exception.IPMIFailure(cmd='a')])
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IPMIFailure,
                              utils.try_set_boot_device,
                              task, boot_devices.DISK, persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(manager_utils, 'node_set_boot_device', autospec=True)
    def test_try_set_boot_device_some_other_exception(
            self, node_set_boot_device_mock):
        exc = exception.IloOperationError(operation="qwe", error="error")
        node_set_boot_device_mock.side_effect = iter([exc])
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.IloOperationError,
                              utils.try_set_boot_device,
                              task, boot_devices.DISK, persistent=True)
            node_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)


class AgentMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AgentMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        n = {'driver': 'fake_agent',
             'driver_internal_info': {'agent_url': 'http://127.0.0.1:9999'}}

        self.node = obj_utils.create_test_node(self.context, **n)
        self.ports = [obj_utils.create_test_port(self.context,
                                                 node_id=self.node.id)]

        self.clean_steps = {
            'hardware_manager_version': '1',
            'clean_steps': {
                'GenericHardwareManager': [
                    {'interface': 'deploy',
                     'step': 'erase_devices',
                     'priority': 20},
                ],
                'SpecificHardwareManager': [
                    {'interface': 'deploy',
                     'step': 'update_firmware',
                     'priority': 30},
                    {'interface': 'raid',
                     'step': 'create_configuration',
                     'priority': 10},
                ]
            }
        }

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_get_clean_steps(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_result': self.clean_steps}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            response = utils.agent_get_clean_steps(task)
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                self.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])

            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertThat(response, matchers.HasLength(3))
            self.assertIn(self.clean_steps['clean_steps'][
                'GenericHardwareManager'][0], response)
            self.assertIn(self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][0], response)
            self.assertIn(self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][1], response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_get_clean_steps_custom_interface(
            self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_result': self.clean_steps}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_get_clean_steps(task, interface='raid')
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                self.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])

            self.assertThat(response, matchers.HasLength(1))
            self.assertIn(self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][1], response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_get_clean_steps_override_priorities(
            self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_result': self.clean_steps}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            new_priorities = {'create_configuration': 42}
            response = utils.agent_get_clean_steps(
                task, interface='raid', override_priorities=new_priorities)
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                self.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])
            self.assertEqual(42, response[0]['priority'])

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_get_clean_steps_override_priorities_none(
            self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_result': self.clean_steps}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            # this is simulating the default value of a configuration option
            new_priorities = {'create_configuration': None}
            response = utils.agent_get_clean_steps(
                task, interface='raid', override_priorities=new_priorities)
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                self.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])
            self.assertEqual(10, response[0]['priority'])

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_get_clean_steps_missing_steps(self, client_mock,
                                           list_ports_mock):
        del self.clean_steps['clean_steps']
        client_mock.return_value = {
            'command_result': self.clean_steps}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.NodeCleaningFailure,
                              utils.agent_get_clean_steps,
                              task)
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                self.ports)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'SUCCEEDED'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['clean_steps']['GenericHardwareManager'][0])
            self.assertEqual(states.CLEANWAIT, response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step_running(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'RUNNING'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['clean_steps']['GenericHardwareManager'][0])
            self.assertEqual(states.CLEANWAIT, response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step_version_mismatch(
            self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'RUNNING'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['clean_steps']['GenericHardwareManager'][0])
            self.assertEqual(states.CLEANWAIT, response)

    def test_agent_add_clean_params(self):
        cfg.CONF.deploy.erase_devices_iterations = 2
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            utils.agent_add_clean_params(task)
            self.assertEqual(task.node.driver_internal_info.get(
                'agent_erase_devices_iterations'), 2)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports',
                autospec=True)
    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.create_cleaning_ports',
                autospec=True)
    def _test_prepare_inband_cleaning_ports(
            self, create_mock, delete_mock, return_vif_port_id=True):
        if return_vif_port_id:
            create_mock.return_value = {self.ports[0].uuid: 'vif-port-id'}
        else:
            create_mock.return_value = {}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.prepare_cleaning_ports(task)
            create_mock.assert_called_once_with(mock.ANY, task)
            delete_mock.assert_called_once_with(mock.ANY, task)

        self.ports[0].refresh()
        self.assertEqual('vif-port-id', self.ports[0].extra['vif_port_id'])

    def test_prepare_inband_cleaning_ports(self):
        self._test_prepare_inband_cleaning_ports()

    def test_prepare_inband_cleaning_ports_no_vif_port_id(self):
        self.assertRaises(
            exception.NodeCleaningFailure,
            self._test_prepare_inband_cleaning_ports,
            return_vif_port_id=False)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.delete_cleaning_ports',
                autospec=True)
    def test_tear_down_inband_cleaning_ports(self, neutron_mock):
        extra_dict = self.ports[0].extra
        extra_dict['vif_port_id'] = 'vif-port-id'
        self.ports[0].extra = extra_dict
        self.ports[0].save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_cleaning_ports(task)
            neutron_mock.assert_called_once_with(mock.ANY, task)

        self.ports[0].refresh()
        self.assertNotIn('vif_port_id', self.ports[0].extra)

    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    @mock.patch.object(iscsi_deploy, 'build_deploy_ramdisk_options',
                       autospec=True)
    @mock.patch.object(utils, 'build_agent_options', autospec=True)
    @mock.patch.object(utils, 'prepare_cleaning_ports', autospec=True)
    def _test_prepare_inband_cleaning(
            self, prepare_cleaning_ports_mock, iscsi_build_options_mock,
            build_options_mock, power_mock, prepare_ramdisk_mock,
            manage_boot=True):
        build_options_mock.return_value = {'a': 'b'}
        iscsi_build_options_mock.return_value = {'c': 'd'}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual(
                states.CLEANWAIT,
                utils.prepare_inband_cleaning(task, manage_boot=manage_boot))
            prepare_cleaning_ports_mock.assert_called_once_with(task)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(task.node.driver_internal_info.get(
                             'agent_erase_devices_iterations'), 1)
            if manage_boot:
                prepare_ramdisk_mock.assert_called_once_with(
                    mock.ANY, mock.ANY, {'a': 'b', 'c': 'd'})
                build_options_mock.assert_called_once_with(task.node)
            else:
                self.assertFalse(prepare_ramdisk_mock.called)
                self.assertFalse(build_options_mock.called)

    def test_prepare_inband_cleaning(self):
        self._test_prepare_inband_cleaning()

    def test_prepare_inband_cleaning_manage_boot_false(self):
        self._test_prepare_inband_cleaning(manage_boot=False)

    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch.object(utils, 'tear_down_cleaning_ports', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def _test_tear_down_inband_cleaning(
            self, power_mock, tear_down_ports_mock,
            clean_up_ramdisk_mock, manage_boot=True):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_inband_cleaning(task, manage_boot=manage_boot)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            tear_down_ports_mock.assert_called_once_with(task)
            if manage_boot:
                clean_up_ramdisk_mock.assert_called_once_with(
                    task.driver.boot, task)
            else:
                self.assertFalse(clean_up_ramdisk_mock.called)

    def test_tear_down_inband_cleaning(self):
        self._test_tear_down_inband_cleaning(manage_boot=True)

    def test_tear_down_inband_cleaning_manage_boot_false(self):
        self._test_tear_down_inband_cleaning(manage_boot=False)

    def test_build_agent_options_conf(self):
        self.config(api_url='api-url', group='conductor')
        options = utils.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual(0, options['coreos.configdrive'])

    @mock.patch.object(keystone, 'get_service_url', autospec=True)
    def test_build_agent_options_keystone(self, get_url_mock):

        self.config(api_url=None, group='conductor')
        get_url_mock.return_value = 'api-url'
        options = utils.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual(0, options['coreos.configdrive'])

    def test_build_agent_options_root_device_hints(self):
        self.config(api_url='api-url', group='conductor')
        self.node.properties['root_device'] = {'model': 'fake_model'}
        options = utils.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])
        self.assertEqual('model=fake_model', options['root_device'])


@mock.patch.object(utils, 'is_block_device', autospec=True)
@mock.patch.object(utils, 'login_iscsi', lambda *_: None)
@mock.patch.object(utils, 'discovery', lambda *_: None)
@mock.patch.object(utils, 'logout_iscsi', lambda *_: None)
@mock.patch.object(utils, 'delete_iscsi', lambda *_: None)
@mock.patch.object(utils, 'get_dev', lambda *_: '/dev/fake')
class ISCSISetupAndHandleErrorsTestCase(tests_base.TestCase):

    def test_no_parent_device(self, mock_ibd):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        mock_ibd.return_value = False
        expected_dev = '/dev/fake'
        with testtools.ExpectedException(exception.InstanceDeployFailure):
            with utils._iscsi_setup_and_handle_errors(
                    address, port, iqn, lun) as dev:
                self.assertEqual(expected_dev, dev)

        mock_ibd.assert_called_once_with(expected_dev)

    def test_parent_device_yield(self, mock_ibd):
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        expected_dev = '/dev/fake'
        mock_ibd.return_value = True
        with utils._iscsi_setup_and_handle_errors(
                address, port, iqn, lun) as dev:
            self.assertEqual(expected_dev, dev)

        mock_ibd.assert_called_once_with(expected_dev)


class ValidateImagePropertiesTestCase(db_base.DbTestCase):

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image(self, image_service_mock):
        node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111', 'ramdisk_id': '2222'},
        }

        utils.validate_image_properties(self.context, inst_info,
                                        ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_missing_prop(
            self, image_service_mock):
        node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        image_service_mock.return_value.show.return_value = {
            'properties': {'kernel_id': '1111'},
        }

        self.assertRaises(exception.MissingParameterValue,
                          utils.validate_image_properties,
                          self.context, inst_info, ['kernel_id', 'ramdisk_id'])
        image_service_mock.assert_called_once_with(
            node.instance_info['image_source'], context=self.context
        )

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_not_authorized(
            self, image_service_mock):
        inst_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotAuthorized(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    @mock.patch.object(image_service, 'get_image_service', autospec=True)
    def test_validate_image_properties_glance_image_not_found(
            self, image_service_mock):
        inst_info = {'image_source': 'uuid'}
        show_mock = image_service_mock.return_value.show
        show_mock.side_effect = exception.ImageNotFound(image_id='uuid')
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    def test_validate_image_properties_invalid_image_href(self):
        inst_info = {'image_source': 'emule://uuid'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, [])

    @mock.patch.object(image_service.HttpImageService, 'show', autospec=True)
    def test_validate_image_properties_nonglance_image(
            self, image_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        image_service_show_mock.return_value = {'size': 1, 'properties': {}}
        node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        utils.validate_image_properties(self.context, inst_info,
                                        ['kernel', 'ramdisk'])
        image_service_show_mock.assert_called_once_with(
            mock.ANY, instance_info['image_source'])

    @mock.patch.object(image_service.HttpImageService, 'show', autospec=True)
    def test_validate_image_properties_nonglance_image_validation_fail(
            self, img_service_show_mock):
        instance_info = {
            'image_source': 'http://ubuntu',
            'kernel': 'kernel_uuid',
            'ramdisk': 'file://initrd',
            'root_gb': 100,
        }
        img_service_show_mock.side_effect = iter(
            [exception.ImageRefValidationFailed(
                image_href='http://ubuntu', reason='HTTPError')])
        node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=instance_info,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        inst_info = utils.get_image_instance_info(node)
        self.assertRaises(exception.InvalidParameterValue,
                          utils.validate_image_properties, self.context,
                          inst_info, ['kernel', 'ramdisk'])


class ValidateParametersTestCase(db_base.DbTestCase):

    def _test__get_img_instance_info(
            self, instance_info=INST_INFO_DICT,
            driver_info=DRV_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(
            self.context,
            driver='fake_pxe',
            instance_info=instance_info,
            driver_info=driver_info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )

        info = utils.get_image_instance_info(node)
        self.assertIsNotNone(info.get('image_source'))
        return info

    def test__get_img_instance_info_good(self):
        self._test__get_img_instance_info()

    def test__get_img_instance_info_good_non_glance_image(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['kernel'] = 'http://kernel'
        instance_info['ramdisk'] = 'http://ramdisk'

        info = self._test__get_img_instance_info(instance_info=instance_info)

        self.assertIsNotNone(info.get('ramdisk'))
        self.assertIsNotNone(info.get('kernel'))

    def test__get_img_instance_info_non_glance_image_missing_kernel(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['ramdisk'] = 'http://ramdisk'

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_non_glance_image_missing_ramdisk(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['kernel'] = 'http://kernel'

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_missing_image_source(self):
        instance_info = INST_INFO_DICT.copy()
        del instance_info['image_source']

        self.assertRaises(
            exception.MissingParameterValue,
            self._test__get_img_instance_info,
            instance_info=instance_info)

    def test__get_img_instance_info_whole_disk_image(self):
        driver_internal_info = DRV_INTERNAL_INFO_DICT.copy()
        driver_internal_info['is_whole_disk_image'] = True

        self._test__get_img_instance_info(
            driver_internal_info=driver_internal_info)
