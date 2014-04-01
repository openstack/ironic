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

from ironic.common import exception
from ironic.common import utils as common_utils
from ironic.drivers.modules import deploy_utils as utils
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
        pxe_config_path = '/tmp/abc/pxeconfig'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 0
        ephemeral_format = None

        dev = '/dev/fake'
        root_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'switch_pxe_config', 'notify']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn),
                          mock.call.switch_pxe_config(pxe_config_path,
                                                      root_uuid),
                          mock.call.notify(address, 10000)]

        utils.deploy(address, port, iqn, lun, image_path, pxe_config_path,
                     root_mb, swap_mb, ephemeral_mb, ephemeral_format)

        self.assertEqual(calls_expected, parent_mock.mock_calls)

    def test_deploy_with_ephemeral(self):
        """Check loosely all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        pxe_config_path = '/tmp/abc/pxeconfig'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        dev = '/dev/fake'
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'switch_pxe_config', 'notify', 'mkfs_ephemeral']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.mkfs_ephemeral(ephemeral_part,
                                                   ephemeral_format),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn),
                          mock.call.switch_pxe_config(pxe_config_path,
                                                      root_uuid),
                          mock.call.notify(address, 10000)]

        utils.deploy(address, port, iqn, lun, image_path, pxe_config_path,
                     root_mb, swap_mb, ephemeral_mb, ephemeral_format)

        self.assertEqual(calls_expected, parent_mock.mock_calls)

    def test_deploy_preserve_ephemeral(self):
        """Check if all functions are called with right args."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        pxe_config_path = '/tmp/abc/pxeconfig'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

        dev = '/dev/fake'
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        mock_mkfs_eph = mock.patch.object(utils, 'mkfs_ephemeral').start()
        self.addCleanup(mock_mkfs_eph.stop)

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'delete_iscsi', 'make_partitions',
                     'is_block_device', 'dd', 'mkswap', 'block_uuid',
                     'switch_pxe_config', 'notify']
        parent_mock = self._mock_calls(name_list)
        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb,
                                                    ephemeral_mb),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.is_block_device(ephemeral_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn),
                          mock.call.switch_pxe_config(pxe_config_path,
                                                      root_uuid),
                          mock.call.notify(address, 10000)]

        utils.deploy(address, port, iqn, lun, image_path, pxe_config_path,
                     root_mb, swap_mb, ephemeral_mb, ephemeral_format,
                     preserve_ephemeral=True)
        self.assertEqual(calls_expected, parent_mock.mock_calls)
        # mkfs_ephemeral should not be called
        self.assertFalse(mock_mkfs_eph.called)

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
        pxe_config_path = '/tmp/abc/pxeconfig'
        root_mb = 128
        swap_mb = 64
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

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
                                                 False),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.delete_iscsi(address, port, iqn)]

        self.assertRaises(TestException, utils.deploy,
                          address, port, iqn, lun, image_path,
                          pxe_config_path, root_mb, swap_mb, ephemeral_mb,
                          ephemeral_format)

        self.assertEqual(calls_expected, parent_mock.mock_calls)


class SwitchPxeConfigTestCase(tests_base.TestCase):
    def setUp(self):
        super(SwitchPxeConfigTestCase, self).setUp()
        (fd, self.fname) = tempfile.mkstemp()
        os.write(fd, _PXECONF_DEPLOY)
        os.close(fd)
        self.addCleanup(os.unlink, self.fname)

    def test_switch_pxe_config(self):
        utils.switch_pxe_config(self.fname,
                               '12345678-1234-1234-1234-1234567890abcdef')
        with open(self.fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(_PXECONF_BOOT, pxeconf)


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


class WorkOnDiskTestCase(tests_base.TestCase):

    def setUp(self):
        super(WorkOnDiskTestCase, self).setUp()
        self.image_path = '/tmp/xyz/image'
        self.root_mb = 128
        self.swap_mb = 64
        self.ephemeral_mb = 0
        self.ephemeral_format = None
        self.dev = '/dev/fake'
        self.root_part = '/dev/fake-part1'
        self.swap_part = '/dev/fake-part2'

        self.mock_ibd = mock.patch.object(utils, 'is_block_device').start()
        self.mock_mp = mock.patch.object(utils, 'make_partitions').start()
        self.addCleanup(self.mock_ibd.stop)
        self.addCleanup(self.mock_mp.stop)

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
                                             self.swap_mb, self.ephemeral_mb)

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
                                             self.swap_mb, self.ephemeral_mb)

    def test_no_ephemeral_partition(self):
        ephemeral_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_part = '/dev/fake-part3'
        ephemeral_mb = 256
        ephemeral_format = 'exttest'

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
                                             self.swap_mb, ephemeral_mb)


@mock.patch.object(common_utils, 'execute')
class MakePartitionsTestCase(tests_base.TestCase):

    def setUp(self):
        super(MakePartitionsTestCase, self).setUp()
        self.dev = 'fake-dev'
        self.root_mb = 1024
        self.swap_mb = 512
        self.ephemeral_mb = 0
        self.parted_static_cmd = ['parted', '-a', 'optimal', '-s', self.dev,
                                  '--', 'mklabel', 'msdos', 'unit', 'MiB']

    def test_make_partitions(self, mock_exc):
        expected_mkpart = ['mkpart', 'primary', '', '1', '1025',
                           'mkpart', 'primary', 'linux-swap', '1025', '1537']
        cmd = self.parted_static_cmd + expected_mkpart
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb)
        mock_exc.assert_called_once_with(*cmd,
                                         run_as_root=True, attempts=3,
                                         check_exit_code=[0])

    def test_make_partitions_with_ephemeral(self, mock_exc):
        self.ephemeral_mb = 2048
        expected_mkpart = ['mkpart', 'primary', '', '1', '2049',
                           'mkpart', 'primary', 'linux-swap', '2049', '2561',
                           'mkpart', 'primary', '', '2561', '3585']
        cmd = self.parted_static_cmd + expected_mkpart
        utils.make_partitions(self.dev, self.root_mb, self.swap_mb,
                              self.ephemeral_mb)
        mock_exc.assert_called_once_with(*cmd,
                                         run_as_root=True, attempts=3,
                                         check_exit_code=[0])
