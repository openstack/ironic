# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 International Business Machines Corporation
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

"""
Test class for Native IPMI power driver module.
"""

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as db_api
from ironic.drivers.modules import ipminative
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from oslo.config import cfg
from pyghmi.ipmi import command as ipmi_command


CONF = cfg.CONF


class IPMINativePrivateMethodTestCase(base.TestCase):
    """Test cases for ipminative private methods."""

    def setUp(self):
        super(IPMINativePrivateMethodTestCase, self).setUp()
        n = db_utils.get_test_node(
                driver='fake_ipminative',
                driver_info=db_utils.ipmi_info)
        self.dbapi = db_api.get_instance()
        self.node = self.dbapi.create_node(n)
        self.info = ipminative._parse_driver_info(self.node)
        self.mox.StubOutWithMock(ipmi_command.Command, '__init__')
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                 userid=self.info.get('username'),
                 password=self.info.get('password')).AndReturn(None)

    def test__parse_driver_info(self):
        # make sure we get back the expected things
        self.assertIsNotNone(self.info.get('address'))
        self.assertIsNotNone(self.info.get('username'))
        self.assertIsNotNone(self.info.get('password'))
        self.assertIsNotNone(self.info.get('uuid'))

        self.mox.ReplayAll()
        ipmi_command.Command(bmc=self.info.get('address'),
                             userid=self.info.get('username'),
                             password=self.info.get('password'))
        self.mox.VerifyAll()

        # make sure error is raised when info, eg. username, is missing
        _driver_info = {
                         'ipmi': {
                                   "address": "2.2.3.4",
                                   "password": "fake",
                                 }
                       }
        node = db_utils.get_test_node(driver_info=_driver_info)
        self.assertRaises(exception.InvalidParameterValue,
                ipminative._parse_driver_info,
                node)

    def test__power_status_on(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'get_power')
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'on'})
        self.mox.ReplayAll()

        state = ipminative._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_ON)

    def test__power_status_off(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'get_power')
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'off'})
        self.mox.ReplayAll()

        state = ipminative._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_OFF)

    def test__power_status_error(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'get_power')
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'Error'})
        self.mox.ReplayAll()

        state = ipminative._power_status(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.ERROR)

    def test__power_on(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_power')
        ipmi_command.Command.set_power('on', 300).AndReturn(
                   {'powerstate': 'on'})
        self.mox.ReplayAll()

        state = ipminative._power_on(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_ON)

    def test__power_off(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_power')
        ipmi_command.Command.set_power('off', 300).AndReturn(
                 {'powerstate': 'off'})
        self.mox.ReplayAll()

        state = ipminative._power_off(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_OFF)

    def test__reboot(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_power')
        ipmi_command.Command.set_power('boot', 300).AndReturn(
                 {'powerstate': 'on'})
        self.mox.ReplayAll()

        state = ipminative._reboot(self.info)
        self.mox.VerifyAll()
        self.assertEqual(state, states.POWER_ON)


class IPMINativeDriverTestCase(db_base.DbTestCase):
    """Test cases for ipminative.NativeIPMIPower class functions.
    """

    def setUp(self):
        super(IPMINativeDriverTestCase, self).setUp()
        self.dbapi = db_api.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager(
                      driver='fake_ipminative')

        n = db_utils.get_test_node(
                driver='fake_ipminative',
                driver_info=db_utils.ipmi_info)
        self.dbapi = db_api.get_instance()
        self.node = self.dbapi.create_node(n)
        self.info = ipminative._parse_driver_info(self.node)

    def test_get_power_state(self):

        self.mox.StubOutWithMock(ipmi_command.Command, 'get_power')
        self.mox.StubOutWithMock(ipmi_command.Command, '__init__')
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                 userid=self.info.get('username'),
                 password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'off'})
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                 userid=self.info.get('username'),
                 password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'on'})
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                 userid=self.info.get('username'),
                 password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.get_power().AndReturn({'powerstate': 'error'})
        self.mox.ReplayAll()

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_OFF)

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.POWER_ON)

        pstate = self.driver.power.get_power_state(None, self.node)
        self.assertEqual(pstate, states.ERROR)

        self.mox.VerifyAll()

    def test_set_power_on_ok(self):
        self.mox.StubOutWithMock(ipminative, '_power_on')
        self.mox.StubOutWithMock(ipminative, '_power_off')

        ipminative._power_on(self.info).AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.set_power_state(
                    task, self.node, states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_power_off_ok(self):
        self.mox.StubOutWithMock(ipminative, '_power_on')
        self.mox.StubOutWithMock(ipminative, '_power_off')

        ipminative._power_off(self.info).AndReturn(states.POWER_OFF)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.set_power_state(
                    task, self.node, states.POWER_OFF)
        self.mox.VerifyAll()

    def test_set_power_on_fail(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_power')
        self.mox.StubOutWithMock(ipmi_command.Command, '__init__')
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                   userid=self.info.get('username'),
                   password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.set_power('on', 300).AndReturn(
                   {'powerstate': 'error'})
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.PowerStateFailure,
                    self.driver.power.set_power_state,
                    task,
                    self.node,
                    states.POWER_ON)
        self.mox.VerifyAll()

    def test_set_boot_device_ok(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_bootdev')
        self.mox.StubOutWithMock(ipmi_command.Command, '__init__')
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                 userid=self.info.get('username'),
                 password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.set_bootdev('pxe').AndReturn(None)
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
        self.mox.StubOutWithMock(ipminative, '_reboot')

        ipminative._reboot(self.info).AndReturn(None)
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.driver.power.reboot(task, self.node)

        self.mox.VerifyAll()

    def test_reboot_fail(self):
        self.mox.StubOutWithMock(ipmi_command.Command, 'set_power')
        self.mox.StubOutWithMock(ipmi_command.Command, '__init__')
        ipmi_command.Command.__init__(bmc=self.info.get('address'),
                   userid=self.info.get('username'),
                   password=self.info.get('password')).AndReturn(None)
        ipmi_command.Command.set_power('boot', 300).AndReturn(
                   {'powerstate': 'error'})
        self.mox.ReplayAll()

        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.PowerStateFailure,
                    self.driver.power.reboot,
                    task,
                    self.node)

        self.mox.VerifyAll()
