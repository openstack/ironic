# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

        dev = '/dev/fake'
        root_part = '/dev/fake-part1'
        swap_part = '/dev/fake-part2'
        root_uuid = '12345678-1234-1234-12345678-12345678abcdef'

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'make_partitions', 'is_block_device',
                     'dd', 'mkswap', 'block_uuid', 'switch_pxe_config',
                     'notify']
        patch_list = [mock.patch.object(utils, name) for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]

        parent_mock = mock.MagicMock()
        for mocker, name in zip(mock_list, name_list):
            parent_mock.attach_mock(mocker, name)

        parent_mock.get_dev.return_value = dev
        parent_mock.get_image_mb.return_value = 1
        parent_mock.is_block_device.return_value = True
        parent_mock.block_uuid.return_value = root_uuid
        calls_expected = [mock.call.get_dev(address, port, iqn, lun),
                          mock.call.get_image_mb(image_path),
                          mock.call.discovery(address, port),
                          mock.call.login_iscsi(address, port, iqn),
                          mock.call.is_block_device(dev),
                          mock.call.make_partitions(dev, root_mb, swap_mb),
                          mock.call.is_block_device(root_part),
                          mock.call.is_block_device(swap_part),
                          mock.call.dd(image_path, root_part),
                          mock.call.mkswap(swap_part),
                          mock.call.block_uuid(root_part),
                          mock.call.logout_iscsi(address, port, iqn),
                          mock.call.switch_pxe_config(pxe_config_path,
                                                      root_uuid),
                          mock.call.notify(address, 10000)]

        utils.deploy(address, port, iqn, lun, image_path, pxe_config_path,
                     root_mb, swap_mb)

        self.assertEqual(calls_expected, parent_mock.mock_calls)

        for patcher in patch_list:
            patcher.stop()

    def test_always_logout_iscsi(self):
        """logout_iscsi() must be called once login_iscsi() is called."""
        address = '127.0.0.1'
        port = 3306
        iqn = 'iqn.xyz'
        lun = 1
        image_path = '/tmp/xyz/image'
        pxe_config_path = '/tmp/abc/pxeconfig'
        root_mb = 128
        swap_mb = 64

        dev = '/dev/fake'

        class TestException(Exception):
            pass

        name_list = ['get_dev', 'get_image_mb', 'discovery', 'login_iscsi',
                     'logout_iscsi', 'work_on_disk']
        patch_list = [mock.patch.object(utils, name) for name in name_list]
        mock_list = [patcher.start() for patcher in patch_list]

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
                                                 image_path),
                          mock.call.logout_iscsi(address, port, iqn)]

        self.assertRaises(TestException,
                         utils.deploy,
                         address, port, iqn, lun, image_path,
                         pxe_config_path, root_mb, swap_mb)

        self.assertEqual(calls_expected, parent_mock.mock_calls)

        for patcher in patch_list:
            patcher.stop()


class SwitchPxeConfigTestCase(tests_base.TestCase):
    def setUp(self):
        super(SwitchPxeConfigTestCase, self).setUp()
        (fd, self.fname) = tempfile.mkstemp()
        os.write(fd, _PXECONF_DEPLOY)
        os.close(fd)

        def cleanup():
            os.unlink(self.fname)

        self.addCleanup(cleanup)

    def test_switch_pxe_config(self):
        utils.switch_pxe_config(self.fname,
                               '12345678-1234-1234-1234-1234567890abcdef')
        with open(self.fname, 'r') as f:
            pxeconf = f.read()
        self.assertEqual(pxeconf, _PXECONF_BOOT)


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
        self.assertEqual(utils.get_image_mb('x'), 0)
        size = 1
        self.assertEqual(utils.get_image_mb('x'), 1)
        size = mb
        self.assertEqual(utils.get_image_mb('x'), 1)
        size = mb + 1
        self.assertEqual(utils.get_image_mb('x'), 2)
