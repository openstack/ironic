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

import datetime

import mock
from testtools.matchers import HasLength
import webtest.app

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import rpcapi
from ironic import objects
from ironic.openstack.common import timeutils
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListNodes(base.FunctionalTest):

    def setUp(self):
        super(TestListNodes, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.chassis = self.dbapi.create_chassis(cdict)

    def _create_association_test_nodes(self):
        #create some unassociated nodes
        unassociated_nodes = []
        for id in range(3):
            ndict = dbutils.get_test_node(id=id,
                                          uuid=utils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            unassociated_nodes.append(node['uuid'])

        #created some associated nodes
        associated_nodes = []
        for id in range(3, 7):
            ndict = dbutils.get_test_node(
                        id=id,
                        uuid=utils.generate_uuid(),
                        instance_uuid=utils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            associated_nodes.append(node['uuid'])
        return {'associated': associated_nodes,
                'unassociated': unassociated_nodes}

    def test_empty(self):
        data = self.get_json('/nodes')
        self.assertEqual([], data['nodes'])

    def test_one(self):
        ndict = dbutils.get_test_node()
        node = self.dbapi.create_node(ndict)
        data = self.get_json('/nodes')
        self.assertEqual(node['uuid'], data['nodes'][0]["uuid"])
        self.assertNotIn('driver', data['nodes'][0])
        self.assertNotIn('driver_info', data['nodes'][0])
        self.assertNotIn('extra', data['nodes'][0])
        self.assertNotIn('properties', data['nodes'][0])
        self.assertNotIn('chassis_id', data['nodes'][0])

    def test_detail(self):
        ndict = dbutils.get_test_node()
        node = self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/detail')
        self.assertEqual(node['uuid'], data['nodes'][0]["uuid"])
        self.assertIn('driver', data['nodes'][0])
        self.assertIn('driver_info', data['nodes'][0])
        self.assertIn('extra', data['nodes'][0])
        self.assertIn('properties', data['nodes'][0])
        self.assertIn('chassis_id', data['nodes'][0])

    def test_detail_against_single(self):
        ndict = dbutils.get_test_node()
        node = self.dbapi.create_node(ndict)
        response = self.get_json('/nodes/%s/detail' % node['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)

    def test_many(self):
        nodes = []
        for id in range(5):
            ndict = dbutils.get_test_node(id=id,
                                          uuid=utils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            nodes.append(node['uuid'])
        data = self.get_json('/nodes')
        self.assertEqual(len(nodes), len(data['nodes']))

        uuids = [n['uuid'] for n in data['nodes']]
        self.assertEqual(sorted(nodes), sorted(uuids))

    def test_links(self):
        uuid = utils.generate_uuid()
        ndict = dbutils.get_test_node(id=1, uuid=uuid)
        self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/1')
        self.assertIn('links', data.keys())
        self.assertEqual(len(data['links']), 2)
        self.assertIn(uuid, data['links'][0]['href'])
        self.assertTrue(self.validate_link(data['links'][0]['href']))
        self.assertTrue(self.validate_link(data['links'][1]['href']))

    def test_collection_links(self):
        nodes = []
        for id in range(5):
            ndict = dbutils.get_test_node(id=id,
                                          uuid=utils.generate_uuid())
            node = self.dbapi.create_node(ndict)
            nodes.append(node['uuid'])
        data = self.get_json('/nodes/?limit=3')
        self.assertEqual(len(data['nodes']), 3)

        next_marker = data['nodes'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_ports_subresource_link(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)

        data = self.get_json('/nodes/%s' % ndict['uuid'])
        self.assertIn('ports', data.keys())

    def test_ports_subresource(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)

        for id in range(2):
            pdict = dbutils.get_test_port(id=id, node_id=ndict['id'],
                                          uuid=utils.generate_uuid(),
                                          address='52:54:00:cf:2d:3%s' % id)
            self.dbapi.create_port(pdict)

        data = self.get_json('/nodes/%s/ports' % ndict['uuid'])
        self.assertEqual(len(data['ports']), 2)
        self.assertNotIn('next', data.keys())

        # Test collection pagination
        data = self.get_json('/nodes/%s/ports?limit=1' % ndict['uuid'])
        self.assertEqual(len(data['ports']), 1)
        self.assertIn('next', data.keys())

    def test_ports_subresource_noid(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)
        pdict = dbutils.get_test_port(node_id=ndict['id'])
        self.dbapi.create_port(pdict)
        # No node id specified
        response = self.get_json('/nodes/ports', expect_errors=True)
        self.assertEqual(response.status_int, 400)

    def test_ports_subresource_node_not_found(self):
        non_existent_uuid = 'eeeeeeee-cccc-aaaa-bbbb-cccccccccccc'
        response = self.get_json('/nodes/%s/ports' % non_existent_uuid,
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)

    def test_state(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/%s/state' % ndict['uuid'])
        [self.assertIn(key, data) for key in ['power', 'provision']]

        # Check if it only returns a sub-set of the attributes
        [self.assertIn(key, ['current', 'links'])
                       for key in data['power'].keys()]
        [self.assertIn(key, ['current', 'links'])
                       for key in data['provision'].keys()]

    def test_power_state(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/%s/state/power' % ndict['uuid'])
        [self.assertIn(key, data) for key in
                       ['available', 'current', 'target', 'links']]
        #TODO(lucasagomes): Add more tests to check to which states it can
        # transition to from the current one, and check if they are present
        # in the available list.

    def test_provision_state(self):
        ndict = dbutils.get_test_node()
        self.dbapi.create_node(ndict)
        data = self.get_json('/nodes/%s/state/provision' % ndict['uuid'])
        [self.assertIn(key, data) for key in
                       ['available', 'current', 'target', 'links']]
        #TODO(lucasagomes): Add more tests to check to which states it can
        # transition to from the current one, and check if they are present
        # in the available list.

    def test_node_by_instance_uuid(self):
        ndict = dbutils.get_test_node(uuid=utils.generate_uuid(),
                                      instance_uuid=utils.generate_uuid())
        node = self.dbapi.create_node(ndict)
        instance_uuid = node['instance_uuid']

        data = self.get_json('/nodes?instance_uuid=%s' % instance_uuid)

        self.assertThat(data['nodes'], HasLength(1))
        self.assertEqual(node['instance_uuid'],
                         data['nodes'][0]["instance_uuid"])

    def test_node_by_instance_uuid_wrong_uuid(self):
        ndict = dbutils.get_test_node(uuid=utils.generate_uuid(),
                                      instance_uuid=utils.generate_uuid())
        self.dbapi.create_node(ndict)
        wrong_uuid = utils.generate_uuid()

        data = self.get_json('/nodes?instance_uuid=%s' % wrong_uuid)

        self.assertThat(data['nodes'], HasLength(0))

    def test_node_by_instance_uuid_invalid_uuid(self):
        response = self.get_json('/nodes?instance_uuid=fake',
                                 expect_errors=True)

        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_code)

    def test_associated_nodes_insensitive(self):
        associated_nodes = self._create_association_test_nodes().\
                get('associated')

        data = self.get_json('/nodes?associated=true')
        data1 = self.get_json('/nodes?associated=True')

        uuids = [n['uuid'] for n in data['nodes']]
        uuids1 = [n['uuid'] for n in data1['nodes']]
        self.assertEqual(sorted(associated_nodes), sorted(uuids1))
        self.assertEqual(sorted(associated_nodes), sorted(uuids))

    def test_associated_nodes_error(self):
        self._create_association_test_nodes()

        self.assertRaises(webtest.app.AppError, self.get_json,
                          '/nodes?associated=blah')

    def test_unassociated_nodes_insensitive(self):
        unassociated_nodes = self._create_association_test_nodes().\
                get('unassociated')

        data = self.get_json('/nodes?associated=false')
        data1 = self.get_json('/nodes?associated=FALSE')

        uuids = [n['uuid'] for n in data['nodes']]
        uuids1 = [n['uuid'] for n in data1['nodes']]
        self.assertEqual(sorted(unassociated_nodes), sorted(uuids1))
        self.assertEqual(sorted(unassociated_nodes), sorted(uuids))

    def test_unassociated_nodes_with_limit(self):
        unassociated_nodes = self._create_association_test_nodes().\
                get('unassociated')

        data = self.get_json('/nodes?associated=False&limit=2')

        self.assertThat(data['nodes'], HasLength(2))
        self.assertTrue(data['nodes'][0]['uuid'] in unassociated_nodes)

    def test_next_link_with_association(self):
        self._create_association_test_nodes()
        data = self.get_json('/nodes/?limit=3&associated=True')
        self.assertThat(data['nodes'], HasLength(3))
        self.assertIn('associated=true', data['next'])

    def test_detail_with_association_filter(self):
        associated_nodes = self._create_association_test_nodes().\
                get('associated')
        data = self.get_json('/nodes/detail?associated=true')
        self.assertIn('driver', data['nodes'][0])
        self.assertEqual(len(associated_nodes), len(data['nodes']))

    def test_next_link_with_association_with_detail(self):
        self._create_association_test_nodes()
        data = self.get_json('/nodes/detail?limit=3&associated=true')
        self.assertThat(data['nodes'], HasLength(3))
        self.assertIn('driver', data['nodes'][0])
        self.assertIn('associated=true', data['next'])

    def test_detail_with_instance_uuid(self):
        ndict = dbutils.get_test_node(uuid=utils.generate_uuid(),
                                      instance_uuid=utils.generate_uuid())
        node = self.dbapi.create_node(ndict)
        instance_uuid = node['instance_uuid']

        data = self.get_json('/nodes/detail?instance_uuid=%s' % instance_uuid)

        self.assertEqual(node['instance_uuid'],
                         data['nodes'][0]["instance_uuid"])
        self.assertIn('driver', data['nodes'][0])
        self.assertIn('driver_info', data['nodes'][0])
        self.assertIn('extra', data['nodes'][0])
        self.assertIn('properties', data['nodes'][0])
        self.assertIn('chassis_id', data['nodes'][0])


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.chassis = self.dbapi.create_chassis(cdict)
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        p = mock.patch.object(rpcapi.ConductorAPI, 'update_node')
        self.mock_update_node = p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(rpcapi.ConductorAPI, 'change_node_power_state')
        self.mock_cnps = p.start()
        self.addCleanup(p.stop)

    def test_update_ok(self):
        self.mock_update_node.return_value = self.node
        self.mock_update_node.return_value.updated_at = \
                                   "2013-12-03T06:20:41.184720+00:00"
        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                                   [{'path': '/instance_uuid',
                                     'value': 'fake instance uuid',
                                     'op': 'replace'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_update_node.return_value.updated_at,
                         timeutils.parse_isotime(response.json['updated_at']))
        self.mock_update_node.assert_called_once_with(mock.ANY, mock.ANY)

    def test_update_state(self):
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/nodes/%s' % self.node['uuid'],
                          {'power_state': 'new state'})

    def test_update_fails_bad_driver_info(self):
        fake_err = 'Fake Error Message'
        self.mock_update_node.side_effect = exception.InvalidParameterValue(
                                                fake_err)

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                                   [{'path': '/driver_info/this',
                                     'value': 'foo',
                                     'op': 'add'},
                                    {'path': '/driver_info/that',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 400)

        self.mock_update_node.assert_called_once_with(mock.ANY, mock.ANY)

    def test_update_fails_bad_state(self):
        fake_err = 'Fake Power State'
        self.mock_update_node.side_effect = exception.NodeInWrongPowerState(
                    node=self.node['uuid'], pstate=fake_err)

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                                   [{'path': '/instance_uuid',
                                     'value': 'fake instance uuid',
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 409)

        self.mock_update_node.assert_called_once_with(mock.ANY, mock.ANY)

    def test_add_ok(self):
        self.mock_update_node.return_value = self.node

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)

        self.mock_update_node.assert_called_once_with(mock.ANY, mock.ANY)

    def test_add_fail(self):
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/nodes/%s' % self.node['uuid'],
                          [{'path': '/foo', 'value': 'bar', 'op': 'add'}])

    def test_remove_ok(self):
        self.mock_update_node.return_value = self.node

        response = self.patch_json('/nodes/%s' % self.node['uuid'],
                                   [{'path': '/extra',
                                     'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)

        self.mock_update_node.assert_called_once_with(mock.ANY, mock.ANY)

    def test_remove_fail(self):
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/nodes/%s' % self.node['uuid'],
                          [{'path': '/extra/non-existent', 'op': 'remove'}])

    def test_update_state_in_progress(self):
        ndict = dbutils.get_test_node(id=99, uuid=utils.generate_uuid(),
                                      target_power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/nodes/%s' % node['uuid'],
                          [{'path': '/extra/foo', 'value': 'bar',
                            'op': 'add'}])
        response = self.patch_json('/nodes/%s' % node['uuid'],
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], expect_errors=True)
        self.assertEqual(response.status_code, 409)

    def test_patch_ports_subresource(self):
        response = self.patch_json('/nodes/%s/ports' % self.node['uuid'],
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], expect_errors=True)
        self.assertEqual(response.status_int, 403)

    def test_remove_uuid(self):
        ndict = dbutils.get_test_node()
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/nodes/%s' % ndict['uuid'],
                          [{'path': '/uuid', 'op': 'remove'}])


class TestPost(base.FunctionalTest):

    def setUp(self):
        super(TestPost, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.chassis = self.dbapi.create_chassis(cdict)
        self.addCleanup(timeutils.clear_time_override)

    def test_create_node(self):
        ndict = dbutils.get_test_node()
        t1 = datetime.datetime(2000, 1, 1, 0, 0)
        timeutils.set_time_override(t1)
        self.post_json('/nodes', ndict)
        result = self.get_json('/nodes/%s' % ndict['uuid'])
        self.assertEqual(ndict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
                result['created_at']).replace(tzinfo=None)
        self.assertEqual(t1, return_created_at)

    def test_create_node_valid_extra(self):
        ndict = dbutils.get_test_node(extra={'foo': 123})
        self.post_json('/nodes', ndict)
        result = self.get_json('/nodes/%s' % ndict['uuid'])
        self.assertEqual(ndict['extra'], result['extra'])

    def test_create_node_invalid_extra(self):
        ndict = dbutils.get_test_node(extra={'foo': 0.123})
        self.assertRaises(webtest.app.AppError, self.post_json, '/nodes',
                          ndict)

    def test_vendor_passthru_ok(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        uuid = ndict['uuid']
        info = {'foo': 'bar'}

        with mock.patch.object(
                rpcapi.ConductorAPI, 'vendor_passthru') as mock_vendor:
            mock_vendor.return_value = 'OK'
            response = self.post_json('/nodes/%s/vendor_passthru/test' % uuid,
                                      info, expect_errors=False)
            mock_vendor.assert_called_once_with(mock.ANY, uuid, 'test', info)
            self.assertEqual(response.body, '"OK"')
            self.assertEqual(response.status_code, 202)

    def test_vendor_passthru_no_such_method(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        uuid = ndict['uuid']
        info = {'foo': 'bar'}

        with mock.patch.object(
                rpcapi.ConductorAPI, 'vendor_passthru') as mock_vendor:
            mock_vendor.side_effect = exception.UnsupportedDriverExtension(
                                        {'driver': ndict['driver'],
                                         'node': uuid,
                                         'extension': 'test'})
            response = self.post_json('/nodes/%s/vendor_passthru/test' % uuid,
                                      info, expect_errors=True)
            mock_vendor.assert_called_once_with(mock.ANY, uuid, 'test', info)
            self.assertEqual(response.status_code, 400)

    def test_vendor_passthru_without_method(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        self.assertRaises(webtest.app.AppError, self.post_json,
                          '/nodes/%s/vendor_passthru' % ndict['uuid'],
                          {'foo': 'bar'})

    def test_post_ports_subresource(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        pdict = dbutils.get_test_port(node_id=None)
        pdict['node_uuid'] = ndict['uuid']
        response = self.post_json('/nodes/ports', pdict,
                                  expect_errors=True)
        self.assertEqual(response.status_int, 403)


class TestDelete(base.FunctionalTest):

    def setUp(self):
        super(TestDelete, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.chassis = self.dbapi.create_chassis(cdict)

    def test_delete_node(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        self.delete('/nodes/%s' % ndict['uuid'])
        response = self.get_json('/nodes/%s' % ndict['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_ports_subresource(self):
        ndict = dbutils.get_test_node()
        self.post_json('/nodes', ndict)
        response = self.delete('/nodes/%s/ports' % ndict['uuid'],
                               expect_errors=True)
        self.assertEqual(response.status_int, 403)

    def test_delete_associated(self):
        ndict = dbutils.get_test_node(instance_uuid='fake-uuid-1234')
        self.post_json('/nodes', ndict)
        response = self.delete('/nodes/%s' % ndict['uuid'], expect_errors=True)
        self.assertEqual(response.status_int, 409)


class TestPut(base.FunctionalTest):

    def setUp(self):
        super(TestPut, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.chassis = self.dbapi.create_chassis(cdict)
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        p = mock.patch.object(rpcapi.ConductorAPI, 'change_node_power_state')
        self.mock_cnps = p.start()
        self.addCleanup(p.stop)

    def test_power_state(self):
        response = self.put_json('/nodes/%s/state/power' % self.node['uuid'],
                                 {'target': states.POWER_ON})
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 202)

        self.mock_cnps.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_power_state_in_progress(self):
        manager = mock.MagicMock()
        with mock.patch.object(objects.Node, 'get_by_uuid') as mock_get_node:
            mock_get_node.return_value = self.node
            manager.attach_mock(mock_get_node, 'get_by_uuid')
            manager.attach_mock(self.mock_cnps, 'change_node_power_state')
            expected = [mock.call.get_by_uuid(mock.ANY, self.node['uuid']),
                        mock.call.change_node_power_state(mock.ANY, mock.ANY,
                                                          mock.ANY)]

            self.put_json('/nodes/%s/state/power' % self.node['uuid'],
                          {'target': states.POWER_ON})
            self.assertEqual(manager.mock_calls, expected)

        self.dbapi.update_node(self.node['uuid'],
                               {'target_power_state': 'fake'})
        self.assertRaises(webtest.app.AppError, self.put_json,
                          '/nodes/%s/state/power' % self.node['uuid'],
                          {'target': states.POWER_ON})
        response = self.put_json('/nodes/%s/state/power' % self.node['uuid'],
                                 {'target': states.POWER_ON},
                                 expect_errors=True)
        self.assertEqual(response.status_code, 409)
