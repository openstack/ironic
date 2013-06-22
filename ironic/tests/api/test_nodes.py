# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import mox

from ironic.common import context
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListNodes(base.FunctionalTest):

    def test_empty(self):
        data = self.get_json('/nodes')
        self.assertEqual([], data)

    def test_one(self):
        ndict = dbutils.get_test_node()
        node = self.dbapi.create_node(ndict)
        data = self.get_json('/nodes')
        self.assertEqual([node['uuid']], data)

    def test_many(self):
        nodes = []
        for id in xrange(5):
            ndict = dbutils.get_test_node(id=id)
            node = self.dbapi.create_node(ndict)
            nodes.append(node['uuid'])
        data = self.get_json('/nodes')
        self.assertEqual(nodes.sort(), data.sort())


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        ndict = dbutils.get_test_node()
        self.context = context.get_admin_context()
        self.node = self.dbapi.create_node(ndict)
        self.mox.StubOutWithMock(rpcapi.ConductorAPI, 'update_node')
        self.mox.StubOutWithMock(rpcapi.ConductorAPI, 'start_state_change')

    def test_update_ok(self):
        rpcapi.ConductorAPI.update_node(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndReturn(self.node)
        self.mox.ReplayAll()

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                {'instance_uuid': 'fake instance uuid'})
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        self.mox.VerifyAll()

    def test_update_state(self):
        rpcapi.ConductorAPI.update_node(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndReturn(self.node)
        rpcapi.ConductorAPI.start_state_change(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                {'task_state': 'new state'})
        self.assertEqual(response.content_type, 'application/json')
        # TODO(deva): change to 202 when wsme 0.5b3 is released
        self.assertEqual(response.status_code, 200)
        self.mox.VerifyAll()

    def test_update_fails_bad_driver_info(self):
        fake_err = 'Fake Error Message'
        rpcapi.ConductorAPI.update_node(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndRaise(exception.InvalidParameterValue(fake_err))
        self.mox.ReplayAll()

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                {'driver_info': {'this': 'foo', 'that': 'bar'}},
                expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 400)
        self.mox.VerifyAll()

    def test_update_fails_bad_state(self):
        fake_err = 'Fake Power State'
        rpcapi.ConductorAPI.update_node(mox.IgnoreArg(), mox.IgnoreArg()).\
                AndRaise(exception.NodeInWrongPowerState(
                    node=self.node['uuid'], pstate=fake_err))
        self.mox.ReplayAll()

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                {'instance_uuid': 'fake instance uuid'},
                expect_errors=True)
        print "======================"
        print response
        self.assertEqual(response.content_type, 'application/json')
        # TODO(deva): change to 409 when wsme 0.5b3 released
        self.assertEqual(response.status_code, 400)
        self.mox.VerifyAll()
