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

from oslo.config import cfg

from ironic.openstack.common import jsonutils as json

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.drivers import ipmi
from ironic.tests import base
from ironic.tests.db import utils as db_utils

CONF = cfg.CONF


class BareMetalIPMITestCase(base.TestCase):

    def setUp(self):
        super(BareMetalIPMITestCase, self).setUp()
        self.node = db_utils.get_test_node()
        self.ipmi = ipmi.IPMIPowerDriver()

    def test__make_password_file(self):
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

    def test__parse_control_info(self):
        # make sure we get back the expected things
        node = db_utils.get_test_node()
        info = ipmi._parse_control_info(node)
        self.assertIsNotNone(info.get('address'))
        self.assertIsNotNone(info.get('user'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('uuid'))

        # make sure error is raised when info, eg. username, is missing
        _control_info = json.dumps(
            {
                "ipmi_address": "1.2.3.4",
                "ipmi_password": "fake",
             })
        node = db_utils.get_test_node(control_info=_control_info)
        self.assertRaises(exception.InvalidParameterValue,
                ipmi._parse_control_info,
                node)

    def test__exec_ipmitool(self):
        pw_file = '/tmp/password_file'
        info = ipmi._parse_control_info(self.node)

        self.mox.StubOutWithMock(ipmi, '_make_password_file')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(utils, 'delete_if_exists')
        ipmi._make_password_file(info['password']).AndReturn(pw_file)
        args = [
                'ipmitool',
                '-I', 'lanplus',
                '-H', info['address'],
                '-U', info['user'],
                '-f', pw_file,
                'A', 'B', 'C',
                ]
        utils.execute(*args, attempts=3).AndReturn(('', ''))
        utils.delete_if_exists(pw_file).AndReturn(None)
        self.mox.ReplayAll()

        ipmi._exec_ipmitool(info, 'A B C')
        self.mox.VerifyAll()

    def test__power_status_on(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        info = ipmi._parse_control_info(self.node)
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is on\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_ON)

    def test__power_status_off(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        info = ipmi._parse_control_info(self.node)
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_OFF)

    def test__power_status_error(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        info = ipmi._parse_control_info(self.node)
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is badstate\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.ERROR)

    def test__power_on_max_retries(self):
        self.config(ipmi_power_retry=2)
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        info = ipmi._parse_control_info(self.node)

        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_on(info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.ERROR)

    def test_get_power_state(self):
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["Chassis Power is on\n", None])
        ipmi._exec_ipmitool(info, "power status").AndReturn(
                ["\n", None])
        self.mox.ReplayAll()

        pstate = self.ipmi.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_OFF)

        pstate = self.ipmi.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_ON)

        pstate = self.ipmi.get_power_state(None, self.node)
        self.assertEqual(pstate, states.ERROR)

        self.mox.VerifyAll()

    def test_set_power_on_ok(self):
        self.config(ipmi_power_retry=0)
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_on(info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        self.ipmi.set_power_state(None, self.node, states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_off_ok(self):
        self.config(ipmi_power_retry=0)
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_off(info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        self.ipmi.set_power_state(None, self.node, states.POWER_OFF)
        self.mox.VerifyAll()

    def test_set_power_on_fail(self):
        self.config(ipmi_power_retry=0)
        info = ipmi._parse_control_info(self.node)

        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_on(info).AndReturn(states.ERROR)
        self.mox.ReplayAll()

        self.assertRaises(exception.PowerStateFailure,
                self.ipmi.set_power_state,
                None,
                self.node,
                states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_invalid_state(self):
        self.assertRaises(exception.IronicException,
                self.ipmi.set_power_state,
                None,
                self.node,
                "fake state")

    def test_set_boot_device_ok(self):
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')

        ipmi._exec_ipmitool(info, "chassis bootdev pxe").\
                AndReturn([None, None])
        self.mox.ReplayAll()

        self.ipmi.set_boot_device(None, self.node, 'pxe')
        self.mox.VerifyAll()

    def test_set_boot_device_bad_device(self):
        self.assertRaises(exception.InvalidParameterValue,
                self.ipmi.set_boot_device,
                None,
                self.node,
                'fake-device')

    def test_reboot_ok(self):
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_power_off')
        self.mox.StubOutWithMock(ipmi, '_power_on')

        ipmi._power_off(info)
        ipmi._power_on(info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        self.ipmi.reboot(None, self.node)
        self.mox.VerifyAll()

    def test_reboot_fail(self):
        info = ipmi._parse_control_info(self.node)
        self.mox.StubOutWithMock(ipmi, '_power_off')
        self.mox.StubOutWithMock(ipmi, '_power_on')

        ipmi._power_off(info)
        ipmi._power_on(info).AndReturn(states.ERROR)
        self.mox.ReplayAll()

        self.assertRaises(exception.PowerStateFailure,
                self.ipmi.reboot,
                None,
                self.node)
        self.mox.VerifyAll()
