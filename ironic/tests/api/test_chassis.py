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

from ironic.openstack.common import uuidutils
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListChassis(base.FunctionalTest):

    def test_empty(self):
        data = self.get_json('/chassis')
        self.assertEqual([], data['items'])

    def test_one(self):
        ndict = dbutils.get_test_chassis()
        chassis = self.dbapi.create_chassis(ndict)
        data = self.get_json('/chassis')
        self.assertEqual(chassis['uuid'], data['items'][0]["uuid"])

    def test_many(self):
        ch_list = []
        for id in xrange(5):
            ndict = dbutils.get_test_chassis(id=id,
                                             uuid=uuidutils.generate_uuid())
            chassis = self.dbapi.create_chassis(ndict)
            ch_list.append(chassis['uuid'])
        data = self.get_json('/chassis')
        self.assertEqual(len(ch_list), len(data['items']))

        uuids = [n['uuid'] for n in data['items']]
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
        self.assertEqual(data['type'], 'chassis')
        self.assertEqual(len(data['items']), 3)

        next_marker = data['items'][-1]['uuid']
        next_link = [l['href'] for l in data['links'] if l['rel'] == 'next'][0]
        self.assertIn(next_marker, next_link)


class TestPatch(base.FunctionalTest):

    def test_update_chassis(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        description = 'chassis-new-description'
        response = self.patch_json('/chassis/%s' % cdict['uuid'],
                                   {'description': description})
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(result['description'], description)

    def test_update_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/chassis/%s' % uuid, {'extra': {'a': 'b'}},
                                   expect_errors=True)
        # TODO(yuriyz): change to 404 (bug 1200517)
        self.assertEqual(response.status_int, 500)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])


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
                         result['items'][0]['description'])
        self.assertTrue(uuidutils.is_uuid_like(result['items'][0]['uuid']))


class TestDelete(base.FunctionalTest):

    def test_delete_chassis(self):
        cdict = dbutils.get_test_chassis()
        self.post_json('/chassis', cdict)
        self.delete('/chassis/%s' % cdict['uuid'])
        response = self.get_json('/chassis/%s' % cdict['uuid'],
                                 expect_errors=True)
        # TODO(yuriyz): change to 404 (bug 1200517)
        self.assertEqual(response.status_int, 500)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_chassis_with_node(self):
        cdict = dbutils.get_test_chassis()
        self.dbapi.create_chassis(cdict)
        ndict = dbutils.get_test_node(chassis_id=cdict['id'])
        self.dbapi.create_node(ndict)
        response = self.delete('/chassis/%s' % cdict['uuid'],
                               expect_errors=True)
        self.assertEqual(response.status_int, 500)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_chassis_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.delete('/chassis/%s' % uuid, expect_errors=True)
        # TODO(yuriyz): change to 404 (bug 1200517)
        self.assertEqual(response.status_int, 500)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])
