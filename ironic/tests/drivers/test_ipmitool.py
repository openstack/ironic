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

"""Test class for IPMITool driver module."""

import os
import stat

from oslo.config import cfg

from ironic.openstack.common import jsonutils as json

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as db_api
from ironic.drivers.modules import ipmitool as ipmi
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils

CONF = cfg.CONF


class IPMIToolPrivateMethodTestCase(base.TestCase):

    def setUp(self):
        super(IPMIToolPrivateMethodTestCase, self).setUp()
        self.node = db_utils.get_test_node(
                driver='fake_ipmitool',
                driver_info=db_utils.ipmi_info)
        self.info = ipmi._parse_driver_info(self.node)

    def test__make_password_file(self):
        with ipmi._make_password_file(self.info.get('password')) as pw_file:
            del_chk_pw_file = pw_file
            self.assertTrue(os.path.isfile(pw_file))
            self.assertEqual(os.stat(pw_file)[stat.ST_MODE] & 0o777, 0o600)
            with open(pw_file, "r") as f:
                password = f.read()
            self.assertEqual(password, self.info.get('password'))
        self.assertFalse(os.path.isfile(del_chk_pw_file))

    def test__parse_driver_info(self):
        # make sure we get back the expected things
        self.assertIsNotNone(self.info.get('address'))
        self.assertIsNotNone(self.info.get('username'))
        self.assertIsNotNone(self.info.get('password'))
        self.assertIsNotNone(self.info.get('uuid'))

        # make sure error is raised when info, eg. username, is missing
        _driver_info = json.dumps(
            {
                'ipmi': {
                    "address": "1.2.3.4",
                    "password": "fake",
                }
             })
        node = db_utils.get_test_node(driver_info=_driver_info)
        self.assertRaises(exception.InvalidParameterValue,
                ipmi._parse_driver_info,
                node)

    def test__exec_ipmitool(self):
        pw_file = '/tmp/password_file'
        file_handle = open(pw_file, "w")

        self.mox.StubOutWithMock(ipmi, '_make_password_file')
        self.mox.StubOutWithMock(utils, 'execute')
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-U', self.info['username'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]
        ipmi._make_password_file(self.info['password']).AndReturn(file_handle)
        utils.execute(*args, attempts=3).AndReturn((None, None))
        self.mox.ReplayAll()

        ipmi._exec_ipmitool(self.info, 'A B C')
        self.mox.VerifyAll()

    def test__power_status_on(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is on\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_ON)

    def test__power_status_off(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_OFF)

    def test__power_status_error(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is badstate\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.ERROR)

    def test__power_on_max_retries(self):
        self.config(ipmi_power_retry=2)
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')

        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(self.info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(self.info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(self.info, "power on").AndReturn([None, None])
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        self.mox.ReplayAll()

        state = ipmi._power_on(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.ERROR)


class IPMIToolDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIToolDriverTestCase, self).setUp()
        self.dbapi = db_api.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager(driver='fake_ipmitool')

        self.node = db_utils.get_test_node(
                driver='fake_ipmitool',
                driver_info=db_utils.ipmi_info)
        self.info = ipmi._parse_driver_info(self.node)
        self.dbapi.create_node(self.node)

    def test_get_power_state(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is off\n", None])
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["Chassis Power is on\n", None])
        ipmi._exec_ipmitool(self.info, "power status").AndReturn(
                ["\n", None])
        self.mox.ReplayAll()

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_OFF)

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_ON)

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.ERROR)

        self.mox.VerifyAll()

    def test_set_power_on_ok(self):
        self.config(ipmi_power_retry=0)
        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_on(self.info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.set_power_state(
                    task, self.node, states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_off_ok(self):
        self.config(ipmi_power_retry=0)
        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_off(self.info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.set_power_state(
                    task, self.node, states.POWER_OFF)
        self.mox.VerifyAll()

    def test_set_power_on_fail(self):
        self.config(ipmi_power_retry=0)

        self.mox.StubOutWithMock(ipmi, '_power_on')
        self.mox.StubOutWithMock(ipmi, '_power_off')

        ipmi._power_on(self.info).AndReturn(states.ERROR)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.PowerStateFailure,
                    self.driver.power.set_power_state,
                    task,
                    self.node,
                    states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_invalid_state(self):
        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.IronicException,
                    self.driver.power.set_power_state,
                    task,
                    self.node,
                    "fake state")

    def test_set_boot_device_ok(self):
        self.mox.StubOutWithMock(ipmi, '_exec_ipmitool')

        ipmi._exec_ipmitool(self.info, "chassis bootdev pxe").\
                AndReturn([None, None])
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power._set_boot_device(task, self.node, 'pxe')
        self.mox.VerifyAll()

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.power._set_boot_device,
                    task,
                    self.node,
                    'fake-device')

    def test_reboot_ok(self):
        self.mox.StubOutWithMock(ipmi, '_power_off')
        self.mox.StubOutWithMock(ipmi, '_power_on')

        ipmi._power_off(self.info)
        ipmi._power_on(self.info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.reboot(task, self.node)

        self.mox.VerifyAll()

    def test_reboot_fail(self):
        self.mox.StubOutWithMock(ipmi, '_power_off')
        self.mox.StubOutWithMock(ipmi, '_power_on')

        ipmi._power_off(self.info)
        ipmi._power_on(self.info).AndReturn(states.ERROR)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.PowerStateFailure,
                    self.driver.power.reboot,
                    task,
                    self.node)

        self.mox.VerifyAll()
