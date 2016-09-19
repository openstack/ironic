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

import os
import tempfile
import time
import types

from ironic_lib import disk_utils
from ironic_lib import utils as ironic_utils
import mock
from oslo_config import cfg
from oslo_utils import uuidutils
import testtools
from testtools import matchers

from ironic.common import boot_devices
from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import image_service
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils as utils
from ironic.drivers.modules import image_cache
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
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

    def _mock_calls(self, name_list, module):
        patch_list = [mock.patch.object(module, name,
                                        spec_set=types.FunctionType)
                      for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock(spec=[])
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)
        return parent_mock

    def _test_deploy_partition_image(self, boot_option=None,
                                     boot_mode=None, disk_label=None):
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['is_block_device', 'get_image_mb',
                                'make_partitions', 'populate_image', 'mkfs',
                                'block_uuid', 'destroy_disk_metadata']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True
        disk_utils_mock.block_uuid.return_value = root_uuid
        disk_utils_mock.make_partitions.return_value = {'root': root_part,
                                                        'swap': swap_part}

        make_partitions_expected_args = [dev, root_mb, swap_mb, ephemeral_mb,
                                         configdrive_mb, node_uuid]
        make_partitions_expected_kwargs = {'commit': True,
                                           'disk_label': disk_label}
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

        if disk_label:
            deploy_kwargs['disk_label'] = disk_label

        # If no boot_option, then it should default to netboot.
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.destroy_disk_metadata(
                                         dev, node_uuid),
                                     mock.call.make_partitions(
                                         *make_partitions_expected_args,
                                         **make_partitions_expected_kwargs),
                                     mock.call.is_block_device(root_part),
                                     mock.call.is_block_device(swap_part),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.mkfs(
                                         dev=swap_part, fs='swap',
                                         label='swap1'),
                                     mock.call.block_uuid(root_part)]

        uuids_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid, **deploy_kwargs)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        expected_uuid_dict = {
            'root uuid': root_uuid,
            'efi system partition uuid': None}
        self.assertEqual(expected_uuid_dict, uuids_dict_returned)

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

    def test_deploy_partition_image_disk_label(self):
        self._test_deploy_partition_image(disk_label='gpt')

    @mock.patch.object(disk_utils, 'get_image_mb', return_value=129,
                       autospec=True)
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
    @mock.patch.object(disk_utils, 'block_uuid', autospec=True)
    def test_deploy_partition_image_localboot_uefi(self, block_uuid_mock):
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['get_image_mb', 'make_partitions',
                                'is_block_device', 'populate_image', 'mkfs',
                                'destroy_disk_metadata']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True

        def block_uuid_side_effect(device):
            if device == root_part:
                return root_uuid
            if device == efi_system_part:
                return efi_system_part_uuid

        block_uuid_mock.side_effect = block_uuid_side_effect
        disk_utils_mock.make_partitions.return_value = {
            'root': root_part, 'swap': swap_part,
            'efi system partition': efi_system_part}

        # If no boot_option, then it should default to netboot.
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]

        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.destroy_disk_metadata(
                                         dev, node_uuid),
                                     mock.call.make_partitions(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         configdrive_mb,
                                         node_uuid,
                                         commit=True,
                                         boot_option="local",
                                         boot_mode="uefi",
                                         disk_label=None),
                                     mock.call.is_block_device(root_part),
                                     mock.call.is_block_device(swap_part),
                                     mock.call.is_block_device(
                                         efi_system_part),
                                     mock.call.mkfs(
                                         dev=efi_system_part, fs='vfat',
                                         label='efi-part'),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.mkfs(
                                         dev=swap_part, fs='swap',
                                         label='swap1')]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid, boot_option="local",
            boot_mode="uefi")

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)

        block_uuid_mock.assert_any_call('/dev/fake-part1')
        block_uuid_mock.assert_any_call('/dev/fake-part3')
        expected_uuid_dict = {
            'root uuid': root_uuid,
            'efi system partition uuid': efi_system_part_uuid}
        self.assertEqual(expected_uuid_dict, uuid_dict_returned)

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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['make_partitions', 'get_image_mb',
                                'is_block_device', 'populate_image',
                                'block_uuid', 'destroy_disk_metadata']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True
        disk_utils_mock.block_uuid.return_value = root_uuid
        disk_utils_mock.make_partitions.return_value = {'root': root_part}
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.destroy_disk_metadata(
                                         dev, node_uuid),
                                     mock.call.make_partitions(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         configdrive_mb,
                                         node_uuid,
                                         commit=True,
                                         boot_option="netboot",
                                         boot_mode="bios",
                                         disk_label=None),
                                     mock.call.is_block_device(root_part),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.block_uuid(root_part)]

        uuid_dict_returned = utils.deploy_partition_image(address, port, iqn,
                                                          lun, image_path,
                                                          root_mb, swap_mb,
                                                          ephemeral_mb,
                                                          ephemeral_format,
                                                          node_uuid)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])

    def test_deploy_partition_image_with_ephemeral(self):
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['get_image_mb', 'make_partitions',
                                'is_block_device', 'populate_image', 'mkfs',
                                'block_uuid', 'destroy_disk_metadata']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True
        disk_utils_mock.block_uuid.return_value = root_uuid
        disk_utils_mock.make_partitions.return_value = {
            'swap': swap_part,
            'ephemeral': ephemeral_part,
            'root': root_part}
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.destroy_disk_metadata(
                                         dev, node_uuid),
                                     mock.call.make_partitions(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         configdrive_mb,
                                         node_uuid,
                                         commit=True,
                                         boot_option="netboot",
                                         boot_mode="bios",
                                         disk_label=None),
                                     mock.call.is_block_device(root_part),
                                     mock.call.is_block_device(swap_part),
                                     mock.call.is_block_device(ephemeral_part),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.mkfs(
                                         dev=swap_part, fs='swap',
                                         label='swap1'),
                                     mock.call.mkfs(
                                         dev=ephemeral_part,
                                         fs=ephemeral_format,
                                         label='ephemeral0'),
                                     mock.call.block_uuid(root_part)]

        uuid_dict_returned = utils.deploy_partition_image(address, port, iqn,
                                                          lun, image_path,
                                                          root_mb, swap_mb,
                                                          ephemeral_mb,
                                                          ephemeral_format,
                                                          node_uuid)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])

    def test_deploy_partition_image_preserve_ephemeral(self):
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'delete_iscsi', 'logout_iscsi']
        disk_utils_name_list = ['make_partitions', 'get_image_mb',
                                'is_block_device', 'populate_image', 'mkfs',
                                'block_uuid', 'get_dev_block_size']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True
        disk_utils_mock.block_uuid.return_value = root_uuid
        disk_utils_mock.make_partitions.return_value = {
            'swap': swap_part,
            'ephemeral': ephemeral_part,
            'root': root_part}
        disk_utils_mock.block_uuid.return_value = root_uuid

        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.make_partitions(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         configdrive_mb,
                                         node_uuid,
                                         commit=False,
                                         boot_option="netboot",
                                         boot_mode="bios",
                                         disk_label=None),
                                     mock.call.is_block_device(root_part),
                                     mock.call.is_block_device(swap_part),
                                     mock.call.is_block_device(ephemeral_part),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.mkfs(
                                         dev=swap_part, fs='swap',
                                         label='swap1'),
                                     mock.call.block_uuid(root_part)]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid,
            preserve_ephemeral=True, boot_option="netboot")
        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertFalse(disk_utils_mock.get_dev_block_size.called)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])

    @mock.patch.object(ironic_utils, 'unlink_without_raise', autospec=True)
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']
        disk_utils_name_list = ['is_block_device', 'populate_image',
                                'get_image_mb', 'destroy_disk_metadata', 'dd',
                                'block_uuid', 'make_partitions',
                                '_get_configdrive']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.is_block_device.return_value = True
        disk_utils_mock.block_uuid.return_value = root_uuid
        disk_utils_mock.make_partitions.return_value = {
            'root': root_part,
            'configdrive': configdrive_part}
        disk_utils_mock._get_configdrive.return_value = (10,
                                                         'configdrive-path')
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.is_block_device(dev),
                                     mock.call.destroy_disk_metadata(
                                         dev, node_uuid),
                                     mock.call._get_configdrive(
                                         configdrive_url, node_uuid,
                                         tempdir=None),
                                     mock.call.make_partitions(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         configdrive_mb,
                                         node_uuid,
                                         commit=True,
                                         boot_option="netboot",
                                         boot_mode="bios",
                                         disk_label=None),
                                     mock.call.is_block_device(root_part),
                                     mock.call.is_block_device(
                                         configdrive_part),
                                     mock.call.dd(mock.ANY, configdrive_part),
                                     mock.call.populate_image(
                                         image_path, root_part),
                                     mock.call.block_uuid(root_part)]

        uuid_dict_returned = utils.deploy_partition_image(
            address, port, iqn, lun, image_path, root_mb, swap_mb,
            ephemeral_mb, ephemeral_format, node_uuid,
            configdrive=configdrive_url)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertEqual(root_uuid, uuid_dict_returned['root uuid'])
        mock_unlink.assert_called_once_with('configdrive-path')

    @mock.patch.object(disk_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image(self, mock_gdi, create_config_drive_mock):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']
        disk_utils_name_list = ['is_block_device', 'populate_image']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.is_block_device(dev),
                                     mock.call.populate_image(image_path, dev)]

        uuid_dict_returned = utils.deploy_disk_image(address, port, iqn, lun,
                                                     image_path, node_uuid,
                                                     configdrive=None)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)
        self.assertFalse(create_config_drive_mock.called)
        self.assertEqual('0x12345678', uuid_dict_returned['disk identifier'])

    @mock.patch.object(disk_utils, 'create_config_drive_partition',
                       autospec=True)
    @mock.patch.object(disk_utils, 'get_disk_identifier', autospec=True)
    def test_deploy_whole_disk_image_with_config_drive(self, mock_gdi,
                                                       create_partition_mock):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"
        config_url = 'http://1.2.3.4/cd'

        dev = '/dev/fake'
        utils_list = ['get_dev', 'discovery', 'login_iscsi', 'logout_iscsi',
                      'delete_iscsi']

        disk_utils_list = ['is_block_device', 'populate_image']
        utils_mock = self._mock_calls(utils_list, utils)
        disk_utils_mock = self._mock_calls(disk_utils_list, disk_utils)
        utils_mock.get_dev.return_value = dev
        disk_utils_mock.is_block_device.return_value = True
        mock_gdi.return_value = '0x12345678'
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]

        disk_utils_calls_expected = [mock.call.is_block_device(dev),
                                     mock.call.populate_image(image_path, dev)]

        uuid_dict_returned = utils.deploy_disk_image(address, port, iqn, lun,
                                                     image_path, node_uuid,
                                                     configdrive=config_url)

        utils_mock.assert_has_calls(utils_calls_expected)
        disk_utils_mock.assert_has_calls(disk_utils_calls_expected)
        create_partition_mock.assert_called_once_with(node_uuid, dev,
                                                      config_url)
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

    @mock.patch.object(disk_utils, 'is_block_device', lambda d: True)
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

        utils_name_list = ['get_dev', 'discovery', 'login_iscsi',
                           'logout_iscsi', 'delete_iscsi']

        disk_utils_name_list = ['get_image_mb', 'work_on_disk']

        utils_mock = self._mock_calls(utils_name_list, utils)
        utils_mock.get_dev.return_value = dev

        disk_utils_mock = self._mock_calls(disk_utils_name_list, disk_utils)
        disk_utils_mock.get_image_mb.return_value = 1
        disk_utils_mock.work_on_disk.side_effect = TestException
        utils_calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                                mock.call.discovery(address, port),
                                mock.call.login_iscsi(address, port, iqn),
                                mock.call.logout_iscsi(address, port, iqn),
                                mock.call.delete_iscsi(address, port, iqn)]
        disk_utils_calls_expected = [mock.call.get_image_mb(image_path),
                                     mock.call.work_on_disk(
                                         dev, root_mb, swap_mb,
                                         ephemeral_mb,
                                         ephemeral_format, image_path,
                                         node_uuid, configdrive=None,
                                         preserve_ephemeral=False,
                                         boot_option="netboot",
                                         boot_mode="bios",
                                         disk_label=None)]

        self.assertRaises(TestException, utils.deploy_partition_image,
                          address, port, iqn, lun, image_path,
                          root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                          node_uuid)

        self.assertEqual(utils_calls_expected, utils_mock.mock_calls)
        self.assertEqual(disk_utils_calls_expected, disk_utils_mock.mock_calls)


class SwitchPxeConfigTestCase(tests_base.TestCase):

    def _create_config(self, ipxe=False, boot_mode=None, boot_loader='elilo'):
        (fd, fname) = tempfile.mkstemp()
        if boot_mode == 'uefi' and not ipxe:
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

    def test_switch_uefi_ipxe_config_partition_image(self):
        boot_mode = 'uefi'
        cfg.CONF.set_override('ipxe_enabled', True, 'pxe')
        fname = self._create_config(boot_mode=boot_mode, ipxe=True)
        utils.switch_pxe_config(fname,
                                '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode,
                                False)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_PARTITION, pxeconf)

    def test_switch_uefi_ipxe_config_whole_disk_image(self):
        boot_mode = 'uefi'
        cfg.CONF.set_override('ipxe_enabled', True, 'pxe')
        fname = self._create_config(boot_mode=boot_mode, ipxe=True)
        utils.switch_pxe_config(fname,
                                '0x12345678',
                                boot_mode,
                                True)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT_WHOLE_DISK, pxeconf)


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

    def test_parse_root_device_hints(self):
        self.node.properties['root_device'] = {
            'wwn': '123456', 'model': 'foo-model', 'size': 123,
            'serial': 'foo-serial', 'vendor': 'foo-vendor', 'name': '/dev/sda',
            'wwn_with_extension': '123456111', 'wwn_vendor_extension': '111',
            'rotational': True,
        }
        expected = ('model=foo-model,name=/dev/sda,rotational=True,'
                    'serial=foo-serial,size=123,vendor=foo-vendor,wwn=123456,'
                    'wwn_vendor_extension=111,wwn_with_extension=123456111')
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

    def test_parse_root_device_hints_invalid_rotational(self):
        self.node.properties['root_device'] = {'rotational': 'not-boolean'}
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_root_device_hints, self.node)

    @mock.patch.object(utils, 'LOG', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(task_manager.TaskManager, 'process_event',
                       autospec=True)
    def _test_set_failed_state(self, mock_event, mock_power, mock_log,
                               event_value=None, power_value=None,
                               log_calls=None, poweroff=True,
                               collect_logs=True):
        err_msg = 'some failure'
        mock_event.side_effect = event_value
        mock_power.side_effect = power_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            if collect_logs:
                utils.set_failed_state(task, err_msg)
            else:
                utils.set_failed_state(task, err_msg,
                                       collect_logs=collect_logs)
            mock_event.assert_called_once_with(task, 'fail')
            if poweroff:
                mock_power.assert_called_once_with(task, states.POWER_OFF)
            else:
                self.assertFalse(mock_power.called)
            self.assertEqual(err_msg, task.node.last_error)
            if (log_calls and poweroff):
                mock_log.exception.assert_has_calls(log_calls)
            else:
                self.assertFalse(mock_log.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state(self, mock_collect):
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
        self.assertEqual(4, mock_collect.call_count)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_no_poweroff(self, mock_collect):
        cfg.CONF.set_override('power_off_after_deploy_failure', False,
                              'deploy')
        exc_state = exception.InvalidState('invalid state')
        exc_param = exception.InvalidParameterValue('invalid parameter')
        mock_call = mock.call(mock.ANY)
        self._test_set_failed_state(poweroff=False)
        calls = [mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    log_calls=calls, poweroff=False)
        calls = [mock_call]
        self._test_set_failed_state(power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls, poweroff=False)
        calls = [mock_call, mock_call]
        self._test_set_failed_state(event_value=iter([exc_state] * len(calls)),
                                    power_value=iter([exc_param] * len(calls)),
                                    log_calls=calls, poweroff=False)
        self.assertEqual(4, mock_collect.call_count)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs(self, mock_collect):
        for opt in ('always', 'on_failure'):
            cfg.CONF.set_override('deploy_logs_collect', opt, 'agent')
            self._test_set_failed_state()
            mock_collect.assert_called_once_with(mock.ANY)
            mock_collect.reset_mock()

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs_never(self, mock_collect):
        cfg.CONF.set_override('deploy_logs_collect', 'never', 'agent')
        self._test_set_failed_state()
        self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    def test_set_failed_state_collect_deploy_logs_overide(self, mock_collect):
        cfg.CONF.set_override('deploy_logs_collect', 'always', 'agent')
        self._test_set_failed_state(collect_logs=False)
        self.assertFalse(mock_collect.called)

    def test_get_boot_option(self):
        self.node.instance_info = {'capabilities': '{"boot_option": "local"}'}
        result = utils.get_boot_option(self.node)
        self.assertEqual("local", result)

    def test_get_boot_option_default_value(self):
        self.node.instance_info = {}
        result = utils.get_boot_option(self.node)
        self.assertEqual("netboot", result)

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
        mock_clean_up_caches.side_effect = [exc]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.fetch_images,
                          None,
                          mock_cache,
                          [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])

    @mock.patch.object(utils, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_defaults(self, log_mock):
        utils.warn_about_unsafe_shred_parameters()
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(utils, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_zeros(self, log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 0, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', True,
                              'deploy')
        utils.warn_about_unsafe_shred_parameters()
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(utils, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_random_no_zeros(self,
                                                                log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 1, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        utils.warn_about_unsafe_shred_parameters()
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(utils, 'LOG', autospec=True)
    def test_warn_about_unsafe_shred_parameters_produces_a_warning(self,
                                                                   log_mock):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 0, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        utils.warn_about_unsafe_shred_parameters()
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(utils, '_get_ironic_session')
    @mock.patch('ironic.common.keystone.get_service_url')
    def test_get_ironic_api_url_from_config(self, mock_get_url, mock_ks):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        fake_api_url = 'http://foo/'
        mock_get_url.side_effect = exception.KeystoneFailure
        self.config(api_url=fake_api_url, group='conductor')
        url = utils.get_ironic_api_url()
        # also checking for stripped trailing slash
        self.assertEqual(fake_api_url[:-1], url)
        self.assertFalse(mock_get_url.called)

    @mock.patch.object(utils, '_get_ironic_session')
    @mock.patch('ironic.common.keystone.get_service_url')
    def test_get_ironic_api_url_from_keystone(self, mock_get_url, mock_ks):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        fake_api_url = 'http://foo/'
        mock_get_url.return_value = fake_api_url
        self.config(api_url=None, group='conductor')
        url = utils.get_ironic_api_url()
        # also checking for stripped trailing slash
        self.assertEqual(fake_api_url[:-1], url)
        mock_get_url.assert_called_with(mock_sess)

    @mock.patch.object(utils, '_get_ironic_session')
    @mock.patch('ironic.common.keystone.get_service_url')
    def test_get_ironic_api_url_fail(self, mock_get_url, mock_ks):
        mock_sess = mock.Mock()
        mock_ks.return_value = mock_sess
        mock_get_url.side_effect = exception.KeystoneFailure()
        self.config(api_url=None, group='conductor')
        self.assertRaises(exception.InvalidParameterValue,
                          utils.get_ironic_api_url)


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
            extra={'vif_port_id': 'test-vif-A'})
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)

    def test_get_single_nic_with_cleaning_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            internal_info={'cleaning_vif_port_id': 'test-vif-A'})
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            address = utils.get_single_nic_with_vif_port_id(task)
            self.assertEqual('aa:bb:cc:dd:ee:ff', address)

    def test_get_single_nic_with_provisioning_vif_port_id(self):
        obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='aa:bb:cc:dd:ee:ff',
            uuid=uuidutils.generate_uuid(),
            internal_info={'provisioning_vif_port_id': 'test-vif-A'})
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

    def test_get_disk_label(self):
        inst_info = {'capabilities': {'disk_label': 'gpt', 'foo': 'bar'}}
        self.node.instance_info = inst_info
        result = utils.get_disk_label(self.node)
        self.assertEqual('gpt', result)


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
        node_set_boot_device_mock.side_effect = exception.IPMIFailure(cmd='a')
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
        node_set_boot_device_mock.side_effect = exception.IPMIFailure(cmd='a')
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
        node_set_boot_device_mock.side_effect = exc
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

        self.clean_steps = {
            'deploy': [
                {'interface': 'deploy',
                 'step': 'erase_devices',
                 'priority': 20},
                {'interface': 'deploy',
                 'step': 'update_firmware',
                 'priority': 30}
            ],
            'raid': [
                {'interface': 'raid',
                 'step': 'create_configuration',
                 'priority': 10}
            ]
        }
        n = {'driver': 'fake_agent',
             'driver_internal_info': {
                 'agent_cached_clean_steps': self.clean_steps}}
        self.node = obj_utils.create_test_node(self.context, **n)
        self.ports = [obj_utils.create_test_port(self.context,
                                                 node_id=self.node.id)]

    def test_agent_get_clean_steps(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_get_clean_steps(task)

            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertThat(response, matchers.HasLength(3))
            self.assertIn(self.clean_steps['deploy'][0], response)
            self.assertIn(self.clean_steps['deploy'][1], response)
            self.assertIn(self.clean_steps['raid'][0], response)

    def test_get_clean_steps_custom_interface(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_get_clean_steps(task, interface='raid')
            self.assertThat(response, matchers.HasLength(1))
            self.assertEqual(self.clean_steps['raid'], response)

    def test_get_clean_steps_override_priorities(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            new_priorities = {'create_configuration': 42}
            response = utils.agent_get_clean_steps(
                task, interface='raid', override_priorities=new_priorities)
            self.assertEqual(42, response[0]['priority'])

    def test_get_clean_steps_override_priorities_none(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            # this is simulating the default value of a configuration option
            new_priorities = {'create_configuration': None}
            response = utils.agent_get_clean_steps(
                task, interface='raid', override_priorities=new_priorities)
            self.assertEqual(10, response[0]['priority'])

    def test_get_clean_steps_missing_steps(self):
        info = self.node.driver_internal_info
        del info['agent_cached_clean_steps']
        self.node.driver_internal_info = info
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaises(exception.NodeCleaningFailure,
                              utils.agent_get_clean_steps,
                              task)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'SUCCEEDED'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['deploy'][0])
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
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['deploy'][0])
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
                self.context, self.node.uuid, shared=False) as task:
            response = utils.agent_execute_clean_step(
                task,
                self.clean_steps['deploy'][0])
            self.assertEqual(states.CLEANWAIT, response)

    def test_agent_add_clean_params(self):
        cfg.CONF.set_override('shred_random_overwrite_iterations', 2, 'deploy')
        cfg.CONF.set_override('shred_final_overwrite_with_zeros', False,
                              'deploy')
        cfg.CONF.set_override('continue_if_disk_secure_erase_fails', True,
                              'deploy')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.agent_add_clean_params(task)
            self.assertEqual(2, task.node.driver_internal_info[
                'agent_erase_devices_iterations'])
            self.assertEqual(False, task.node.driver_internal_info[
                'agent_erase_devices_zeroize'])
            self.assertEqual(True, task.node.driver_internal_info[
                'agent_continue_if_ata_erase_failed'])

    @mock.patch.object(utils.LOG, 'warning', autospec=True)
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    def _test_prepare_inband_cleaning_ports_out_of_tree(
            self, dhcp_factory_mock, log_mock, return_vif_port_id=True):
        self.config(group='dhcp', dhcp_provider='my_shiny_dhcp_provider')
        dhcp_provider = dhcp_factory_mock.return_value.provider
        create = dhcp_provider.create_cleaning_ports
        delete = dhcp_provider.delete_cleaning_ports
        if return_vif_port_id:
            create.return_value = {self.ports[0].uuid: 'vif-port-id'}
        else:
            create.return_value = {}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.prepare_cleaning_ports(task)
            create.assert_called_once_with(task)
            delete.assert_called_once_with(task)
            self.assertTrue(log_mock.called)

        self.ports[0].refresh()
        self.assertEqual('vif-port-id',
                         self.ports[0].internal_info['cleaning_vif_port_id'])

    def test_prepare_inband_cleaning_ports_out_of_tree(self):
        self._test_prepare_inband_cleaning_ports_out_of_tree()

    def test_prepare_inband_cleaning_ports_out_of_tree_no_vif_port_id(self):
        self.assertRaises(
            exception.NodeCleaningFailure,
            self._test_prepare_inband_cleaning_ports_out_of_tree,
            return_vif_port_id=False)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_cleaning_network')
    def test_prepare_inband_cleaning_ports_neutron(self, add_clean_net_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.prepare_cleaning_ports(task)
            add_clean_net_mock.assert_called_once_with(task)

    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'add_cleaning_network')
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    def test_prepare_inband_cleaning_ports_provider_does_not_create(
            self, dhcp_factory_mock, add_clean_net_mock):
        self.config(group='dhcp', dhcp_provider='my_shiny_dhcp_provider')
        self.node.network_interface = 'noop'
        self.node.save()
        dhcp_provider = dhcp_factory_mock.return_value.provider
        del dhcp_provider.delete_cleaning_ports
        del dhcp_provider.create_cleaning_ports
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.prepare_cleaning_ports(task)
            add_clean_net_mock.assert_called_once_with(task)

    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    def test_tear_down_inband_cleaning_ports_out_of_tree(self,
                                                         dhcp_factory_mock):
        self.config(group='dhcp', dhcp_provider='my_shiny_dhcp_provider')
        dhcp_provider = dhcp_factory_mock.return_value.provider
        delete = dhcp_provider.delete_cleaning_ports
        internal_info = self.ports[0].internal_info
        internal_info['cleaning_vif_port_id'] = 'vif-port-id-1'
        self.ports[0].internal_info = internal_info
        self.ports[0].save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_cleaning_ports(task)
            delete.assert_called_once_with(task)

        self.ports[0].refresh()
        self.assertNotIn('cleaning_vif_port_id', self.ports[0].internal_info)
        self.assertNotIn('vif_port_id', self.ports[0].extra)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'remove_cleaning_network')
    def test_tear_down_inband_cleaning_ports_neutron(self, rm_clean_net_mock):
        extra_port = obj_utils.create_test_port(
            self.context, node_id=self.node.id, address='10:00:00:00:00:01',
            extra={'vif_port_id': 'vif-port'}, uuid=uuidutils.generate_uuid()
        )
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_cleaning_ports(task)
            rm_clean_net_mock.assert_called_once_with(task)
        extra_port.refresh()
        self.assertNotIn('vif_port_id', extra_port.extra)

    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'remove_cleaning_network')
    @mock.patch.object(dhcp_factory, 'DHCPFactory', autospec=True)
    def test_tear_down_inband_cleaning_ports_provider_does_not_delete(
            self, dhcp_factory_mock, rm_clean_net_mock):
        self.config(group='dhcp', dhcp_provider='my_shiny_dhcp_provider')
        self.node.network_interface = 'noop'
        self.node.save()
        dhcp_provider = dhcp_factory_mock.return_value.provider
        del dhcp_provider.delete_cleaning_ports
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_cleaning_ports(task)
            rm_clean_net_mock.assert_called_once_with(task)

    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', autospec=True)
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    @mock.patch.object(utils, 'build_agent_options', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'add_cleaning_network')
    def _test_prepare_inband_cleaning(
            self, add_cleaning_network_mock,
            build_options_mock, power_mock, prepare_ramdisk_mock,
            manage_boot=True):
        build_options_mock.return_value = {'a': 'b'}
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual(
                states.CLEANWAIT,
                utils.prepare_inband_cleaning(task, manage_boot=manage_boot))
            add_cleaning_network_mock.assert_called_once_with(task)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(1, task.node.driver_internal_info[
                             'agent_erase_devices_iterations'])
            self.assertEqual(True, task.node.driver_internal_info[
                             'agent_erase_devices_zeroize'])
            if manage_boot:
                prepare_ramdisk_mock.assert_called_once_with(
                    mock.ANY, mock.ANY, {'a': 'b'})
                build_options_mock.assert_called_once_with(task.node)
            else:
                self.assertFalse(prepare_ramdisk_mock.called)
                self.assertFalse(build_options_mock.called)

    def test_prepare_inband_cleaning(self):
        self._test_prepare_inband_cleaning()

    def test_prepare_inband_cleaning_manage_boot_false(self):
        self._test_prepare_inband_cleaning(manage_boot=False)

    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.'
                'remove_cleaning_network')
    @mock.patch('ironic.conductor.utils.node_power_action', autospec=True)
    def _test_tear_down_inband_cleaning(
            self, power_mock, remove_cleaning_network_mock,
            clean_up_ramdisk_mock, manage_boot=True):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            utils.tear_down_inband_cleaning(task, manage_boot=manage_boot)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            remove_cleaning_network_mock.assert_called_once_with(task)
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

    @mock.patch.object(utils, '_get_ironic_session')
    def test_build_agent_options_keystone(self, session_mock):
        self.config(api_url=None, group='conductor')
        sess = mock.Mock()
        sess.get_endpoint.return_value = 'api-url'
        session_mock.return_value = sess
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


@mock.patch.object(disk_utils, 'is_block_device', autospec=True)
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
        img_service_show_mock.side_effect = exception.ImageRefValidationFailed(
            image_href='http://ubuntu', reason='HTTPError')
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
        self.assertIsNotNone(info['image_source'])
        return info

    def test__get_img_instance_info_good(self):
        self._test__get_img_instance_info()

    def test__get_img_instance_info_good_non_glance_image(self):
        instance_info = INST_INFO_DICT.copy()
        instance_info['image_source'] = 'http://image'
        instance_info['kernel'] = 'http://kernel'
        instance_info['ramdisk'] = 'http://ramdisk'

        info = self._test__get_img_instance_info(instance_info=instance_info)

        self.assertIsNotNone(info['ramdisk'])
        self.assertIsNotNone(info['kernel'])

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


class InstanceInfoTestCase(db_base.DbTestCase):

    def test_parse_instance_info_good(self):
        # make sure we get back the expected things
        node = obj_utils.create_test_node(
            self.context, driver='fake_pxe',
            instance_info=INST_INFO_DICT,
            driver_internal_info=DRV_INTERNAL_INFO_DICT
        )
        info = utils.parse_instance_info(node)
        self.assertIsNotNone(info['image_source'])
        self.assertIsNotNone(info['root_gb'])
        self.assertEqual(0, info['ephemeral_gb'])
        self.assertIsNone(info['configdrive'])

    def test_parse_instance_info_missing_instance_source(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['image_source']
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_missing_root_gb(self):
        # make sure error is raised when info is missing
        info = dict(INST_INFO_DICT)
        del info['root_gb']

        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_root_gb(self):
        info = dict(INST_INFO_DICT)
        info['root_gb'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_valid_ephemeral_gb(self):
        ephemeral_gb = 10
        ephemeral_mb = 1024 * ephemeral_gb
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = ephemeral_fmt
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        data = utils.parse_instance_info(node)
        self.assertEqual(ephemeral_mb, data['ephemeral_mb'])
        self.assertEqual(ephemeral_fmt, data['ephemeral_format'])

    def test_parse_instance_info_unicode_swap_mb(self):
        swap_mb = u'10'
        swap_mb_int = 10
        info = dict(INST_INFO_DICT)
        info['swap_mb'] = swap_mb
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        data = utils.parse_instance_info(node)
        self.assertEqual(swap_mb_int, data['swap_mb'])

    def test_parse_instance_info_invalid_ephemeral_gb(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 'foobar'
        info['ephemeral_format'] = 'exttest'

        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_valid_ephemeral_missing_format(self):
        ephemeral_gb = 10
        ephemeral_fmt = 'test-fmt'
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = ephemeral_gb
        info['ephemeral_format'] = None
        self.config(default_ephemeral_format=ephemeral_fmt, group='pxe')
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertEqual(ephemeral_fmt, instance_info['ephemeral_format'])

    def test_parse_instance_info_valid_preserve_ephemeral_true(self):
        info = dict(INST_INFO_DICT)
        for opt in ['true', 'TRUE', 'True', 't',
                    'on', 'yes', 'y', '1']:
            info['preserve_ephemeral'] = opt

            node = obj_utils.create_test_node(
                self.context, uuid=uuidutils.generate_uuid(),
                instance_info=info,
                driver_internal_info=DRV_INTERNAL_INFO_DICT,
            )
            data = utils.parse_instance_info(node)
            self.assertTrue(data['preserve_ephemeral'])

    def test_parse_instance_info_valid_preserve_ephemeral_false(self):
        info = dict(INST_INFO_DICT)
        for opt in ['false', 'FALSE', 'False', 'f',
                    'off', 'no', 'n', '0']:
            info['preserve_ephemeral'] = opt
            node = obj_utils.create_test_node(
                self.context, uuid=uuidutils.generate_uuid(),
                instance_info=info,
                driver_internal_info=DRV_INTERNAL_INFO_DICT,
            )
            data = utils.parse_instance_info(node)
            self.assertFalse(data['preserve_ephemeral'])

    def test_parse_instance_info_invalid_preserve_ephemeral(self):
        info = dict(INST_INFO_DICT)
        info['preserve_ephemeral'] = 'foobar'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test_parse_instance_info_invalid_ephemeral_disk(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 9,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info,
                          node)

    def test__check_disk_layout_unchanged_fails(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 20,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertRaises(exception.InvalidParameterValue,
                          utils._check_disk_layout_unchanged,
                          node, info)

    def test__check_disk_layout_unchanged(self):
        info = dict(INST_INFO_DICT)
        info['ephemeral_gb'] = 10
        info['swap_mb'] = 0
        info['root_gb'] = 20
        info['preserve_ephemeral'] = True
        drv_internal_dict = {'instance': {'ephemeral_gb': 10,
                                          'swap_mb': 0,
                                          'root_gb': 20}}
        drv_internal_dict.update(DRV_INTERNAL_INFO_DICT)
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=drv_internal_dict,
        )
        self.assertIsNone(utils._check_disk_layout_unchanged(node,
                                                             info))

    def test_parse_instance_info_configdrive(self):
        info = dict(INST_INFO_DICT)
        info['configdrive'] = 'http://1.2.3.4/cd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertEqual('http://1.2.3.4/cd', instance_info['configdrive'])

    def test_parse_instance_info_nonglance_image(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['kernel'] = 'file:///image.vmlinuz'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        utils.parse_instance_info(node)

    def test_parse_instance_info_nonglance_image_no_kernel(self):
        info = INST_INFO_DICT.copy()
        info['image_source'] = 'file:///image.qcow2'
        info['ramdisk'] = 'file:///image.initrd'
        node = obj_utils.create_test_node(
            self.context, instance_info=info,
            driver_internal_info=DRV_INTERNAL_INFO_DICT,
        )
        self.assertRaises(exception.MissingParameterValue,
                          utils.parse_instance_info, node)

    def test_parse_instance_info_whole_disk_image(self):
        driver_internal_info = dict(DRV_INTERNAL_INFO_DICT)
        driver_internal_info['is_whole_disk_image'] = True
        node = obj_utils.create_test_node(
            self.context, instance_info=INST_INFO_DICT,
            driver_internal_info=driver_internal_info,
        )
        instance_info = utils.parse_instance_info(node)
        self.assertIsNotNone(instance_info['image_source'])
        self.assertIsNotNone(instance_info['root_mb'])
        self.assertEqual(0, instance_info['swap_mb'])
        self.assertEqual(0, instance_info['ephemeral_mb'])
        self.assertIsNone(instance_info['configdrive'])

    def test_parse_instance_info_whole_disk_image_missing_root(self):
        info = dict(INST_INFO_DICT)
        del info['root_gb']
        node = obj_utils.create_test_node(self.context, instance_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          utils.parse_instance_info, node)
