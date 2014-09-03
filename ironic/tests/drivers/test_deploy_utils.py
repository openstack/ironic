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

import fixtures
import mock
import os
import tempfile

from oslo.config import cfg

from ironic.common import disk_partitioner
from ironic.common import exception
from ironic.common import utils as common_utils
from ironic.drivers.modules import deploy_utils as utils
from ironic.drivers.modules import image_cache
from ironic.openstack.common import processutils
from ironic.tests import base as tests_base

_PXECONF_DEPLOY = """
default deploy

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot
kernel kernel
append initrd=ramdisk root={{ ROOT }}
"""

_PXECONF_BOOT = """
default boot

label deploy
kernel deploy_kernel
append initrd=deploy_ramdisk
ipappend 3

label boot
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef
"""

_IPXECONF_DEPLOY = """
#!ipxe

dhcp

goto deploy

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot
kernel kernel
append initrd=ramdisk root={{ ROOT }}
boot
"""

_IPXECONF_BOOT = """
#!ipxe

dhcp

goto boot

:deploy
kernel deploy_kernel
initrd deploy_ramdisk
boot

:boot
kernel kernel
append initrd=ramdisk root=UUID=12345678-1234-1234-1234-1234567890abcdef
boot
"""

_UEFI_PXECONF_DEPLOY = """
default=deploy

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot
        initrd=ramdisk
        append="root={{ ROOT }}"
"""

_UEFI_PXECONF_BOOT = """
default=boot

image=deploy_kernel
        label=deploy
        initrd=deploy_ramdisk
        append="ro text"

image=kernel
        label=boot
        initrd=ramdisk
        append="root=UUID=12345678-1234-1234-1234-1234567890abcdef"
"""


class PhysicalWorkTestCase(tests_base.TestCase):
    def setUp(self):
        super(PhysicalWorkTestCase, self).setUp()

        def noop(*args, **kwargs):
            pass

        self.useFixture(fixtures.MonkeyPatch('time.sleep', noop))

    def _mock_calls(self, name_list):
        patch_list = [mock.patch.object(utils, name) for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock()
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)
        return parent_mock

    def test_deploy(self):
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
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        swap_part = '/dev/fake-part1'
        root_part = '/dev/fake-part2'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'notify', 'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'root': root_part,
                                                    'swap': swap_part}
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    commit=True),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        returned_root_uuid = utils.deploy(address, port, iqn, lun,
                                          image_path, root_mb, swap_mb,
                                          ephemeral_mb, ephemeral_format,
                                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, returned_root_uuid)

    def test_deploy_without_swap(self):
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
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        root_part = '/dev/fake-part1'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'block_uuid',
                     'notify', 'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'root': root_part}
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    commit=True),
                          mock.call.is_block_device(root_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        returned_root_uuid = utils.deploy(address, port, iqn, lun,
                                          image_path, root_mb, swap_mb,
                                          ephemeral_mb, ephemeral_format,
                                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, returned_root_uuid)

    def test_deploy_with_ephemeral(self):
        """Check loosely all functions are called with right args."""
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
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'notify', 'mkfs_ephemeral',
                     'destroy_disk_metadata']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'swap': swap_part,
                                                   'ephemeral': ephemeral_part,
                                                   'root': root_part}
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.destroy_disk_metadata(dev, node_uuid),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    commit=True),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.mkfs_ephemeral(ephemeral_part,
                                                   ephemeral_format),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        returned_root_uuid = utils.deploy(address, port, iqn, lun,
                                          image_path, root_mb, swap_mb,
                                          ephemeral_mb, ephemeral_format,
                                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertEqual(root_uuid, returned_root_uuid)

    def test_deploy_preserve_ephemeral(self):
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
        node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

        dev = '/dev/fake'
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'notify', 'mkfs_ephemeral', 'get_dev_block_size']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        parent_mock.make_partitions.return_value = {'swap': swap_part,
                                                   'ephemeral': ephemeral_part,
                                                   'root': root_part}
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb,
                                                    commit=False),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        returned_root_uuid = utils.deploy(address, port, iqn, lun,
                                          image_path, root_mb, swap_mb,
                                          ephemeral_mb, ephemeral_format,
                                          node_uuid, preserve_ephemeral=True)
        self.assertEqual(calls_expected, parent_mock.mock_calls)
        self.assertFalse(parent_mock.mkfs_ephemeral.called)
        self.assertFalse(parent_mock.get_dev_block_size.called)
        self.assertEqual(root_uuid, returned_root_uuid)

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
        patch_list = [mock.patch.object(utils, name) for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for patcher in patch_list:
            self.addCleanup(patcher.stop)

        parent_mock = mock.MagicMock()
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)

        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.work_on_disk.side_effect = TestException
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.work_on_disk(dev, root_mb, swap_mb,
                                                 ephemeral_mb,
                                                 ephemeral_format, image_path,
                                                 node_uuid, False),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        self.assertRaises(TestException, utils.deploy,
                          address, port, iqn, lun, image_path,
                          root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                          node_uuid)

        self.assertEqual(calls_expected, parent_mock.mock_calls)


class SwitchPxeConfigTestCase(tests_base.TestCase):

    def _create_config(self, ipxe=False, boot_mode=None):
        (fd, fname) = tempfile.mkstemp()
        if boot_mode == 'uefi':
            pxe_cfg = _UEFI_PXECONF_DEPLOY
        else:
            pxe_cfg = _IPXECONF_DEPLOY if ipxe else _PXECONF_DEPLOY
        os.write(fd, pxe_cfg)
        os.close(fd)
        self.addCleanup(os.unlink, fname)
        return fname

    def test_switch_pxe_config(self):
        boot_mode = 'bios'
        fname = self._create_config()
        utils.switch_pxe_config(fname,
                               '12345678-1234-1234-1234-1234567890abcdef',
                                boot_mode)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT, pxeconf)

    def test_switch_ipxe_config(self):
        boot_mode = 'bios'
        cfg.CONF.set_override('ipxe_enabled', True, 'pxe')
        fname = self._create_config(ipxe=True)
        utils.switch_pxe_config(fname,
                               '12345678-1234-1234-1234-1234567890abcdef',
                               boot_mode)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_IPXECONF_BOOT, pxeconf)

    def test_switch_uefi_pxe_config(self):
        boot_mode = 'uefi'
        fname = self._create_config(boot_mode=boot_mode)
        utils.switch_pxe_config(fname,
                               '12345678-1234-1234-1234-1234567890abcdef',
                               boot_mode)
        with open(fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_UEFI_PXECONF_BOOT, pxeconf)


class OtherFunctionTestCase(tests_base.TestCase):
    def test_get_dev(self):
        expected = '/dev/disk/by-path/ip-1.2.3.4:5678-iscsi-iqn.fake-lun-9'
        actual = utils.get_dev('1.2.3.4', 5678, 'iqn.fake', 9)
        self.assertEqual(expected, actual)

    def test_get_image_mb(self):
        mb = 1024 * 1024
        size = None

        def fake_getsize(path):
            return size

        self.useFixture(fixtures.MonkeyPatch('os.path.getsize', fake_getsize))
        size = 0
        self.assertEqual(0, utils.get_image_mb('x'))
        size = 1
        self.assertEqual(1, utils.get_image_mb('x'))
        size = mb
        self.assertEqual(1, utils.get_image_mb('x'))
        size = mb + 1
        self.assertEqual(2, utils.get_image_mb('x'))


@mock.patch.object(disk_partitioner.DiskPartitioner, 'commit', lambda _: None)
class WorkOnDiskTestCase(tests_base.TestCase):

    def setUp(self):
        super(WorkOnDiskTestCase, self).setUp()
        self.image_path = '/tmp/xyz/image'
        self.root_mb = 128
        self.swap_mb = 64
        self.ephemeral_mb = 0
        self.ephemeral_format = None
        self.dev = '/dev/fake'
        self.swap_part = '/dev/fake-part1'
        self.root_part = '/dev/fake-part2'

        self.mock_ibd = mock.patch.object(utils, 'is_block_device').start()
        self.mock_mp = mock.patch.object(utils, 'make_partitions').start()
        self.addCleanup(self.mock_ibd.stop)
        self.addCleanup(self.mock_mp.stop)
        self.mock_remlbl = mock.patch.object(utils,
                                             'destroy_disk_metadata').start()
        self.addCleanup(self.mock_remlbl.stop)
        self.mock_mp.return_value = {'swap': self.swap_part,
                                     'root': self.root_part}

    def test_no_parent_device(self):
        self.mock_ibd.return_value = False
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, False)
        self.mock_ibd.assert_called_once_with(self.dev)
        self.assertFalse(self.mock_mp.called,
                         "make_partitions mock was unexpectedly called.")

    def test_no_root_partition(self):
        self.mock_ibd.side_effect = [True, False]
        calls = [mock.call(self.dev),
                 mock.call(self.root_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, False)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             commit=True)

    def test_no_swap_partition(self):
        self.mock_ibd.side_effect = [True, True, False]
        calls = [mock.call(self.dev),
                 mock.call(self.root_part),
                 mock.call(self.swap_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, self.ephemeral_mb,
                          self.ephemeral_format, self.image_path, False)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, self.ephemeral_mb,
                                             commit=True)

    def test_no_ephemeral_partition(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        self.mock_mp.return_value = {'ephemeral': ephemeral_part,
                                     'swap': swap_part,
                                     'root': root_part}
        self.mock_ibd.side_effect = [True, True, True, False]
        calls = [mock.call(self.dev),
                 mock.call(root_part),
                 mock.call(swap_part),
                 mock.call(ephemeral_part)]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.work_on_disk, self.dev, self.root_mb,
                          self.swap_mb, ephemeral_mb, ephemeral_format,
                          self.image_path, False)
        self.assertEqual(self.mock_ibd.call_args_list, calls)
        self.mock_mp.assert_called_once_with(self.dev, self.root_mb,
                                             self.swap_mb, ephemeral_mb,
                                             commit=True)


@mock.patch.object(common_utils, 'execute')
class MakePartitionsTestCase(tests_base.TestCase):

    def setUp(self):
        super(MakePartitionsTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.root_mb = 1024
        self.swap_mb = 512
        self.ephemeral_mb = 0
        self.parted_static_cmd = ['parted', '-a', 'optimal', '-s', self.dev,
                                  '--', 'unit', 'MiB', 'mklabel', 'msdos']

    def test_make_partitions(self, mock_exc):
        mock_exc.return_value = (None, None)
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb)

        expected_mkpart = ['mkpart', 'primary', 'linux-swap', '1', '513',
                           'mkpart', 'primary', '', '513', '1537']
        parted_cmd = self.parted_static_cmd + expected_mkpart
        parted_call = mock.call(*parted_cmd, run_as_root=True,
                                check_exit_code=[0])
        fuser_cmd = ['fuser', 'fake-dev']
        fuser_call = mock.call(*fuser_cmd, run_as_root=True,
                               check_exit_code=[0, 1])
        mock_exc.assert_has_calls([parted_call, fuser_call])

    def test_make_partitions_with_ephemeral(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        cmd = self.parted_static_cmd + expected_mkpart
        mock_exc.return_value = (None, None)
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb)

        parted_call = mock.call(*cmd, run_as_root=True, check_exit_code=[0])
        mock_exc.assert_has_calls(parted_call)


@mock.patch.object(utils, 'get_dev_block_size')
@mock.patch.object(common_utils, 'execute')
class DestroyMetaDataTestCase(tests_base.TestCase):

    def setUp(self):
        super(DestroyMetaDataTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.node_uuid = "12345678-1234-1234-1234-1234567890abcxyz"

    def test_destroy_disk_metadata(self, mock_exec, mock_gz):
        mock_gz.return_value = 64
        expected_calls = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', run_as_root=True,
                                    check_exit_code=[0]),
                          mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                                    'bs=512', 'count=36', 'seek=28',
                                    run_as_root=True,
                                    check_exit_code=[0])]
        utils.destroy_disk_metadata(self.dev, self.node_uuid)
        mock_exec.assert_has_calls(expected_calls)
        self.assertTrue(mock_gz.called)

    def test_destroy_disk_metadata_get_dev_size_fail(self, mock_exec, mock_gz):
        mock_gz.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                            'bs=512', 'count=36', run_as_root=True,
                            check_exit_code=[0])]
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)

    def test_destroy_disk_metadata_dd_fail(self, mock_exec, mock_gz):
        mock_exec.side_effect = processutils.ProcessExecutionError

        expected_call = [mock.call('dd', 'if=/dev/zero', 'of=fake-dev',
                            'bs=512', 'count=36', run_as_root=True,
                            check_exit_code=[0])]
        self.assertRaises(processutils.ProcessExecutionError,
                          utils.destroy_disk_metadata,
                          self.dev,
                          self.node_uuid)
        mock_exec.assert_has_calls(expected_call)
        self.assertFalse(mock_gz.called)


@mock.patch.object(common_utils, 'execute')
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


@mock.patch.object(utils, 'is_block_device', lambda d: True)
@mock.patch.object(utils, 'block_uuid', lambda p: 'uuid')
@mock.patch.object(utils, 'dd', lambda *_: None)
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

    @mock.patch.object(image_cache, 'clean_up_caches')
    def test_fetch_images(self, mock_clean_up_caches):

        mock_cache = mock.MagicMock(master_dir='master_dir')
        utils.fetch_images(None, mock_cache, [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])
        mock_cache.fetch_image.assert_called_once_with('uuid', 'path',
                                                       ctx=None)

    @mock.patch.object(image_cache, 'clean_up_caches')
    def test_fetch_images_fail(self, mock_clean_up_caches):

        exc = exception.InsufficientDiskSpace(path='a',
                                              required=2,
                                              actual=1)

        mock_cache = mock.MagicMock(master_dir='master_dir')
        mock_clean_up_caches.side_effect = [exc]
        self.assertRaises(exception.InstanceDeployFailure,
                          utils.fetch_images,
                          None,
                          mock_cache,
                          [('uuid', 'path')])
        mock_clean_up_caches.assert_called_once_with(None, 'master_dir',
                                                     [('uuid', 'path')])
