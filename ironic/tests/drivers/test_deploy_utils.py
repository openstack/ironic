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

import os
import tempfile
import time


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

        self.stubs.Set(time, 'sleep', noop)

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

        self.mox.StubOutWithMock(utils, 'get_dev')
        self.mox.StubOutWithMock(utils, 'get_image_mb')
        self.mox.StubOutWithMock(utils, 'discovery')
        self.mox.StubOutWithMock(utils, 'login_iscsi')
        self.mox.StubOutWithMock(utils, 'logout_iscsi')
        self.mox.StubOutWithMock(utils, 'make_partitions')
        self.mox.StubOutWithMock(utils, 'is_block_device')
        self.mox.StubOutWithMock(utils, 'dd')
        self.mox.StubOutWithMock(utils, 'mkswap')
        self.mox.StubOutWithMock(utils, 'block_uuid')
        self.mox.StubOutWithMock(utils, 'switch_pxe_config')
        self.mox.StubOutWithMock(utils, 'notify')

        utils.get_dev(address, port, iqn, lun).AndReturn(dev)
        utils.get_image_mb(image_path).AndReturn(1)  # < root_mb
        utils.discovery(address, port)
        utils.login_iscsi(address, port, iqn)
        utils.is_block_device(dev).AndReturn(True)
        utils.make_partitions(dev, root_mb, swap_mb)
        utils.is_block_device(root_part).AndReturn(True)
        utils.is_block_device(swap_part).AndReturn(True)
        utils.dd(image_path, root_part)
        utils.mkswap(swap_part)
        utils.block_uuid(root_part).AndReturn(root_uuid)
        utils.logout_iscsi(address, port, iqn)
        utils.switch_pxe_config(pxe_config_path, root_uuid)
        utils.notify(address, 10000)
        self.mox.ReplayAll()

        utils.deploy(address, port, iqn, lun, image_path, pxe_config_path,
                    root_mb, swap_mb)

        self.mox.VerifyAll()

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

        self.mox.StubOutWithMock(utils, 'get_dev')
        self.mox.StubOutWithMock(utils, 'get_image_mb')
        self.mox.StubOutWithMock(utils, 'discovery')
        self.mox.StubOutWithMock(utils, 'login_iscsi')
        self.mox.StubOutWithMock(utils, 'logout_iscsi')
        self.mox.StubOutWithMock(utils, 'work_on_disk')

        class TestException(Exception):
            pass

        utils.get_dev(address, port, iqn, lun).AndReturn(dev)
        utils.get_image_mb(image_path).AndReturn(1)  # < root_mb
        utils.discovery(address, port)
        utils.login_iscsi(address, port, iqn)
        utils.work_on_disk(dev, root_mb, swap_mb, image_path).\
                AndRaise(TestException)
        utils.logout_iscsi(address, port, iqn)
        self.mox.ReplayAll()

        self.assertRaises(TestException,
                         utils.deploy,
                         address, port, iqn, lun, image_path,
                         pxe_config_path, root_mb, swap_mb)


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

        self.stubs.Set(os.path, 'getsize', fake_getsize)
        size = 0
        self.assertEqual(utils.get_image_mb('x'), 0)
        size = 1
        self.assertEqual(utils.get_image_mb('x'), 1)
        size = mb
        self.assertEqual(utils.get_image_mb('x'), 1)
        size = mb + 1
        self.assertEqual(utils.get_image_mb('x'), 2)
