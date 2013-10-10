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
Tests for the API /chassis/ methods.
"""

import webtest.app

from ironic.openstack.common import uuidutils
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListChassis(base.FunctionalTest):

    def test_empty(self):
        data = self.get_json('/chassis')
        self.assertEqual([], data['chassis'])

    def test_one(self):
        ndict = dbutils.get_test_chassis()
        chassis = self.dbapi.create_chassis(ndict)
        data = self.get_json('/chassis')
        self.assertEqual(chassis['uuid'], data['chassis'][0]["uuid"])
        self.assertNotIn('extra', data['chassis'][0])
        self.assertNotIn('nodes', data['chassis'][0])

    def test_detail(self):
        cdict = dbutils.get_test_chassis()
        chassis = self.dbapi.create_chassis(cdict)
        data = self.get_json('/chassis/detail')
        self.assertEqual(chassis['uuid'], data['chassis'][0]["uuid"])
        self.assertIn('extra', data['chassis'][0])
        self.assertIn('nodes', data['chassis'][0])

    def test_detail_against_single(self):
        cdict = dbutils.get_test_chassis()
        chassis = self.dbapi.create_chassis(cdict)
        response = self.get_json('/chassis/%s/detail' % chassis['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)

    def test_many(self):
        ch_list = []
        for id in xrange(5):
            ndict = dbutils.get_test_chassis(id=id,
                                             uuid=uuidutils.generate_uuid())
            chassis = self.dbapi.create_chassis(ndict)
            ch_list.append(chassis['uuid'])
        data = self.get_json('/chassis')
        self.assertEqual(len(ch_list), len(data['chassis']))

        uuids = [n['uuid'] for n in data['chassis']]
        self.assertEqual(ch_list.sort(), uuids.sort())

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        ndict = dbutils.get_test_chassis(id=1, uuid=uuid)
        self.dbapi.create_chassis(ndict)
        data = self.get_json('/chassis/1')
        self.assertIn('links', data.keys())
        self.assertEqual(len(data['links']), 2)
        self.assertIn(uuid, data['links'][0]['href'])

    def test_collection_links(self):
        chassis = []
        for id in xrange(5):
            ndict = dbutils.get_test_chassis(id=id,
                                             uuid=uuidutils.generate_uuid())
            ch = self.dbapi.create_chassis(ndict)
            chassis.append(ch['uuid'])
        data = self.get_json('/chassis/?limit=3')
        self.assertEqual(len(data['chassis']), 3)

        next_marker = data['chassis'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_nodes_subresource_link(self):
        ndict = dbutils.get_test_chassis()
        self.dbapi.create_chassis(ndict)

        data = self.get_json('/chassis/%s' % ndict['uuid'])
        self.assertIn('nodes', data.keys())

    def test_nodes_subresource(self):
        cdict = dbutils.get_test_chassis()
        self.dbapi.create_chassis(cdict)

        for id in xrange(2):
            ndict = dbutils.get_test_node(id=id, chassis_id=cdict['id'],
                                          uuid=uuidutils.generate_uuid())
            self.dbapi.create_node(ndict)

        data = self.get_json('/chassis/%s/nodes' % cdict['uuid'])
        self.assertEqual(len(data['nodes']), 2)
        self.assertNotIn('next', data.keys())

        # Test collection pagination
        data = self.get_json('/chassis/%s/nodes?limit=1' % cdict['uuid'])
        self.assertEqual(len(data['nodes']), 1)
        self.assertIn('next', data.keys())

    def test_nodes_subresource_noid(self):
        cdict = dbutils.get_test_chassis()
        self.dbapi.create_chassis(cdict)
        ndict = dbutils.get_test_node(chassis_id=cdict['id'])
        self.dbapi.create_node(ndict)
        # No chassis id specified
        response = self.get_json('/chassis/nodes', expect_errors=True)
        self.assertEqual(response.status_int, 400)


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)

    def test_update_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/chassis/%s' % uuid,
                                   [{'path': '/extra/a', 'value': 'b',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_replace_singular(self):
        cdict = dbutils.get_test_chassis()
        description = 'chassis-new-description'
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/description',
                                     'value': description, 'op': 'replace'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(result['description'], description)

    def test_replace_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        cdict = dbutils.get_test_chassis(extra=extra,
                                         uuid=uuidutils.generate_uuid())
        self.post_json('/chassis', cdict)
        new_value = 'new value'
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/extra/foo2',
                                     'value': new_value, 'op': 'replace'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])

        extra["foo2"] = new_value
        self.assertEqual(result['extra'], extra)

    def test_remove_singular(self):
        cdict = dbutils.get_test_chassis(extra={'a': 'b'},
                                         uuid=uuidutils.generate_uuid())
        self.post_json('/chassis', cdict)
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/description', 'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(result['description'], None)

        # Assert nothing else was changed
        self.assertEqual(result['uuid'], cdict['uuid'])
        self.assertEqual(result['extra'], cdict['extra'])

    def test_remove_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        cdict = dbutils.get_test_chassis(extra=extra, description="foobar",
                                         uuid=uuidutils.generate_uuid())
        self.post_json('/chassis', cdict)

        # Removing one item from the collection
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/extra/foo2', 'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        extra.pop("foo2")
        self.assertEqual(result['extra'], extra)

        # Removing the collection
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/extra', 'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(result['extra'], {})

        # Assert nothing else was changed
        self.assertEqual(result['uuid'], cdict['uuid'])
        self.assertEqual(result['description'], cdict['description'])

    def test_add_singular(self):
        cdict = dbutils.get_test_chassis()
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/foo', 'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_int, 400)
        self.assertTrue(response.json['error_message'])

    def test_add_multi(self):
        cdict = dbutils.get_test_chassis()
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   [{'path': '/extra/foo1', 'value': 'bar1',
                                     'op': 'add'},
                                    {'path': '/extra/foo2', 'value': 'bar2',
                                     'op': 'add'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        expected = {"foo1": "bar1", "foo2": "bar2"}
        self.assertEqual(result['extra'], expected)

    def test_patch_nodes_subresource(self):
        cdict = dbutils.get_test_chassis()
        response = self.patch_json('/chassis/%s/nodes' % cdict['uuid'],
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], expect_errors=True)
        self.assertEqual(response.status_int, 403)

    def test_remove_uuid(self):
        cdict = dbutils.get_test_chassis()
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/chassis/%s' % cdict['uuid'],
                          [{'path': '/uuid', 'op': 'remove'}])


class TestPost(base.FunctionalTest):

    def test_create_chassis(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(cdict['uuid'], result['uuid'])

    def test_create_chassis_generate_uuid(self):
        cdict = dbutils.get_test_chassis()
        del cdict['uuid']
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis')
        self.assertEqual(cdict['description'],
                         result['chassis'][0]['description'])
        self.assertTrue(uuidutils.is_uuid_like(result['chassis'][0]['uuid']))

    def test_post_nodes_subresource(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        ndict = dbutils.get_test_node(chassis_id=cdict['id'])
        response = self.post_json('/chassis/nodes', ndict,
                                   expect_errors=True)
        self.assertEqual(response.status_int, 403)

    def test_create_chassis_valid_extra(self):
        cdict = dbutils.get_test_chassis(extra={'foo': 123})
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(cdict['extra'], result['extra'])

    def test_create_chassis_invalid_extra(self):
        cdict = dbutils.get_test_chassis(extra={'foo': 0.123})
        self.assertRaises(webtest.app.AppError, self.post_json, '/chassis',
                          cdict)


class TestDelete(base.FunctionalTest):

    def test_delete_chassis(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        self.delete('/chassis/%s' % cdict['uuid'])
        response = self.get_json('/chassis/%s' % cdict['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_chassis_with_node(self):
        cdict = dbutils.get_test_chassis()
        self.dbapi.create_chassis(cdict)
        ndict = dbutils.get_test_node(chassis_id=cdict['id'])
        self.dbapi.create_node(ndict)
        response = self.delete('/chassis/%s' % cdict['uuid'],
                               expect_errors=True)
        self.assertEqual(response.status_int, 400)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_chassis_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.delete('/chassis/%s' % uuid, expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_nodes_subresource(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        response = self.delete('/chassis/%s/nodes' % cdict['uuid'],
                               expect_errors=True)
        self.assertEqual(response.status_int, 403)
