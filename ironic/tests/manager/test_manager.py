# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Test class for Ironic ManagerService."""

import mox

from ironic.common import states
from ironic.db import api as dbapi
from ironic.manager import manager
from ironic.openstack.common import context
from ironic.tests.db import base
from ironic.tests.db import utils
from ironic.tests.manager import utils as mgr_utils


class ManagerTestCase(base.DbTestCase):

    def setUp(self):
        super(ManagerTestCase, self).setUp()
        self.service = manager.ManagerService('test-host', 'test-topic')
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager()

    def test_get_power_state(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)

        # FakeControlDriver.get_power_state will "pass"
        # and states.NOSTATE is None, so this test should pass.
        state = self.service.get_node_power_state(self.context, n['uuid'])
        self.assertEqual(state, states.NOSTATE)

    def test_get_power_state_with_mock(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)

        self.mox.StubOutWithMock(self.driver.power, 'get_power_state')

        self.driver.power.get_power_state(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndReturn(states.POWER_OFF)
        self.driver.power.get_power_state(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndReturn(states.POWER_ON)
        self.mox.ReplayAll()

        state = self.service.get_node_power_state(self.context, n['uuid'])
        self.assertEqual(state, states.POWER_OFF)
        state = self.service.get_node_power_state(self.context, n['uuid'])
        self.assertEqual(state, states.POWER_ON)

        self.mox.VerifyAll()
