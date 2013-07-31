# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
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
Tests for the API /nodes/ methods.
"""

import mox

from ironic.common import exception
from ironic.conductor import rpcapi
from ironic.openstack.common import uuidutils
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListNodes(base.FunctionalTest):

    def test_empty(self):
        data = self.get_json('/nodes')
        self.assertEqual([], data['items'])

    def test_one(self):
        ndict = dbutils.get_test_node()
        node = self.dbapi.create_node(ndict)
        data = self.get_json('/nodes')
        self.assertEqual(node['uuid'], data['items'][0]["uuid"])

    def test_many(self):
        nodes = []
        for id in xrange(5):
            ndict = dbutils.get_test_node(id=id,
                                          uuid=uuidutils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            nodes.append(node['uuid'])
        data = self.get_json('/nodes')
        self.assertEqual(len(nodes), len(data['items']))

        uuids = [n['uuid'] for n in data['items']]
        self.assertEqual(nodes.sort(), uuids.sort())

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        ndict = dbutils.get_test_node(id=1, uuid=uuid)
        self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/1')
        self.assertIn('links', data.keys())
        self.assertEqual(len(data['links']), 2)
        self.assertIn(uuid, data['links'][0]['href'])

    def test_collection_links(self):
        nodes = []
        for id in xrange(5):
            ndict = dbutils.get_test_node(id=id,
                                          uuid=uuidutils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            nodes.append(node['uuid'])
        data = self.get_json('/nodes/?limit=3')
        self.assertEqual(data['type'], 'node')
        self.assertEqual(len(data['items']), 3)

        next_marker = data['items'][-1]['uuid']
        next_link = [l['href'] for l in data['links'] if l['rel'] == 'next'][0]
        self.assertIn(next_marker, next_link)

    def test_ports_subresource_link(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)

        data = self.get_json('/nodes/%s' % ndict['uuid'])
        self.assertIn('ports', data.keys())

    def test_ports_subresource(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)

        for id in xrange(2):
            pdict = dbutils.get_test_port(id=id, node_id=ndict['id'],
                                          uuid=uuidutils.generate_uuid())
            self.dbapi.create_port(pdict)

        data = self.get_json('/nodes/%s/ports' % ndict['uuid'])
        self.assertEqual(data['type'], 'port')
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(len(data['links']), 0)

        # Test collection pagination
        data = self.get_json('/nodes/%s/ports?limit=1' % ndict['uuid'])
        self.assertEqual(data['type'], 'port')
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(len(data['links']), 1)


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        ndict = dbutils.get_test_node()
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
        self.assertEqual(response.content_type, 'application/json')
        # TODO(deva): change to 409 when wsme 0.5b3 released
        self.assertEqual(response.status_code, 400)
        self.mox.VerifyAll()


class TestPost(base.FunctionalTest):

    def test_create_node(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        result = self.get_json('/nodes/%s' % ndict['uuid'])
        self.assertEqual(ndict['uuid'], result['uuid'])


class TestDelete(base.FunctionalTest):

    def test_delete_node(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        self.delete('/nodes/%s' % ndict['uuid'])
        response = self.get_json('/nodes/%s' % ndict['uuid'],
                expect_errors=True)
        self.assertEqual(response.status_int, 500)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])
