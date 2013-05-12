# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
# All Rights Reserved.
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

"""Test class for baremetal IPMI power manager."""

import os
import stat
import tempfile

from oslo.config import cfg

from ironic import test
from ironic.common import states
from ironic.common import utils
from ironic.tests.db import utils as db_utils
from ironic.manager import ipmi

CONF = cfg.CONF


class BareMetalIPMITestCase(test.TestCase):

    def setUp(self):
        super(BareMetalIPMITestCase, self).setUp()
        self.node = db_utils.get_test_node()
        self.ipmi = ipmi.IPMI(self.node)

    def test_construct(self):
        self.assertEqual(self.ipmi.node_id, 123)
        self.assertEqual(self.ipmi.address, 'fake-address')
        self.assertEqual(self.ipmi.user, 'fake-user')
        self.assertEqual(self.ipmi.password, 'fake-password')

    def test_make_password_file(self):
        fakepass = 'this is a fake password'
        pw_file = ipmi._make_password_file(fakepass)
        try:
            self.assertTrue(os.path.isfile(pw_file))
            self.assertEqual(os.stat(pw_file)[stat.ST_MODE] & 0777, 0600)
            with open(pw_file, "r") as f:
                password = f.read()
            self.assertEqual(password, fakepass)
        finally:
            os.unlink(pw_file)

    def test_exec_ipmitool(self):
        pw_file = '/tmp/password_file'

        self.mox.StubOutWithMock(ipmi, '_make_password_file')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(utils, 'delete_if_exists')
        ipmi._make_password_file(self.ipmi.password).AndReturn(pw_file)
        args = [
                'ipmitool',
                '-I', 'lanplus',
                '-H', self.ipmi.address,
                '-U', self.ipmi.user,
                '-f', pw_file,
                'A', 'B', 'C',
                ]
        utils.execute(*args, attempts=3).AndReturn(('', ''))
        utils.delete_if_exists(pw_file).AndReturn(None)
        self.mox.ReplayAll()

        self.ipmi._exec_ipmitool('A B C')
        self.mox.VerifyAll()

    def test_is_power(self):
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is on\n"])
        self.mox.ReplayAll()

        self.ipmi._is_power("on")
        self.mox.VerifyAll()

    def test_power_already_on(self):
        self.flags(ipmi_power_retry=0)
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')

        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is on\n"])
        self.mox.ReplayAll()

        self.ipmi.state = states.DELETED
        self.ipmi._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.ipmi.state, states.ACTIVE)

    def test_power_on_ok(self):
        self.flags(ipmi_power_retry=0)
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')

        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.ipmi._exec_ipmitool("power on").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is on\n"])
        self.mox.ReplayAll()

        self.ipmi.state = states.DELETED
        self.ipmi._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.ipmi.state, states.ACTIVE)

    def test_power_on_fail(self):
        self.flags(ipmi_power_retry=0)
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')

        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.ipmi._exec_ipmitool("power on").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.mox.ReplayAll()

        self.ipmi.state = states.DELETED
        self.ipmi._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.ipmi.state, states.ERROR)

    def test_power_on_max_retries(self):
        self.flags(ipmi_power_retry=2)
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')

        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.ipmi._exec_ipmitool("power on").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.ipmi._exec_ipmitool("power on").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.ipmi._exec_ipmitool("power on").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.mox.ReplayAll()

        self.ipmi.state = states.DELETED
        self.ipmi._power_on()
        self.mox.VerifyAll()
        self.assertEqual(self.ipmi.state, states.ERROR)
        self.assertEqual(self.ipmi.retries, 3)

    def test_power_off_ok(self):
        self.flags(ipmi_power_retry=0)
        self.mox.StubOutWithMock(self.ipmi, '_exec_ipmitool')

        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is on\n"])
        self.ipmi._exec_ipmitool("power off").AndReturn([])
        self.ipmi._exec_ipmitool("power status").AndReturn(
                ["Chassis Power is off\n"])
        self.mox.ReplayAll()

        self.ipmi.state = states.ACTIVE
        self.ipmi._power_off()
        self.mox.VerifyAll()
        self.assertEqual(self.ipmi.state, states.DELETED)

    def test_get_console_pid_path(self):
        self.flags(terminal_pid_dir='/tmp')
        path = ipmi._get_console_pid_path(self.ipmi.node_id)
        self.assertEqual(path, '/tmp/%s.pid' % self.ipmi.node_id)

    def test_console_pid(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'w') as f:
            f.write("12345\n")

        self.mox.StubOutWithMock(ipmi, '_get_console_pid_path')
        ipmi._get_console_pid_path(self.ipmi.node_id).AndReturn(path)
        self.mox.ReplayAll()

        pid = ipmi._get_console_pid(self.ipmi.node_id)
        utils.delete_if_exists(path)
        self.mox.VerifyAll()
        self.assertEqual(pid, 12345)

    def test_console_pid_nan(self):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, 'w') as f:
            f.write("hello world\n")

        self.mox.StubOutWithMock(ipmi, '_get_console_pid_path')
        ipmi._get_console_pid_path(self.ipmi.node_id).AndReturn(path)
        self.mox.ReplayAll()

        pid = ipmi._get_console_pid(self.ipmi.node_id)
        utils.delete_if_exists(path)
        self.mox.VerifyAll()
        self.assertTrue(pid is None)

    def test_console_pid_file_not_found(self):
        pid_path = ipmi._get_console_pid_path(self.ipmi.node_id)

        self.mox.StubOutWithMock(os.path, 'exists')
        os.path.exists(pid_path).AndReturn(False)
        self.mox.ReplayAll()

        pid = ipmi._get_console_pid(self.ipmi.node_id)
        self.mox.VerifyAll()
        self.assertTrue(pid is None)
