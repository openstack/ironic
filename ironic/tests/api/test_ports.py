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
Tests for the API /ports/ methods.
"""

import webtest.app

from ironic.openstack.common import uuidutils
from ironic.tests.api import base
from ironic.tests.db import utils as dbutils


class TestListPorts(base.FunctionalTest):

    def setUp(self):
        super(TestListPorts, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)

    def test_empty(self):
        data = self.get_json('/ports')
        self.assertEqual([], data['ports'])

    def test_one(self):
        ndict = dbutils.get_test_port()
        port = self.dbapi.create_port(ndict)
        data = self.get_json('/ports')
        self.assertEqual(port['uuid'], data['ports'][0]["uuid"])
        self.assertNotIn('extra', data['ports'][0])

    def test_detail(self):
        pdict = dbutils.get_test_port()
        port = self.dbapi.create_port(pdict)
        data = self.get_json('/ports/detail')
        self.assertEqual(port['uuid'], data['ports'][0]["uuid"])
        self.assertIn('extra', data['ports'][0])

    def test_detail_against_single(self):
        pdict = dbutils.get_test_port()
        port = self.dbapi.create_port(pdict)
        response = self.get_json('/ports/%s/detail' % port['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)

    def test_many(self):
        ports = []
        for id in xrange(5):
            ndict = dbutils.get_test_port(id=id,
                                          uuid=uuidutils.generate_uuid())
            port = self.dbapi.create_port(ndict)
            ports.append(port['uuid'])
        data = self.get_json('/ports')
        self.assertEqual(len(ports), len(data['ports']))

        uuids = [n['uuid'] for n in data['ports']]
        self.assertEqual(ports.sort(), uuids.sort())

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        ndict = dbutils.get_test_port(id=1, uuid=uuid)
        self.dbapi.create_port(ndict)
        data = self.get_json('/ports/1')
        self.assertIn('links', data.keys())
        self.assertEqual(len(data['links']), 2)
        self.assertIn(uuid, data['links'][0]['href'])

    def test_collection_links(self):
        ports = []
        for id in xrange(5):
            ndict = dbutils.get_test_port(id=id,
                                          uuid=uuidutils.generate_uuid())
            port = self.dbapi.create_port(ndict)
            ports.append(port['uuid'])
        data = self.get_json('/ports/?limit=3')
        self.assertEqual(len(data['ports']), 3)

        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        pdict = dbutils.get_test_port()
        self.post_json('/ports', pdict)

    def test_update_byid(self):
        pdict = dbutils.get_test_port()
        extra = {'foo': 'bar'}
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(result['extra'], extra)

    def test_update_byaddress(self):
        pdict = dbutils.get_test_port()
        extra = {'foo': 'bar'}
        response = self.patch_json('/ports/%s' % pdict['address'],
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(result['extra'], extra)

    def test_update_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/ports/%s' % uuid,
                                   [{'path': '/extra/a',
                                     'value': 'b',
                                     'op': 'add'}],
                             expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_replace_singular(self):
        pdict = dbutils.get_test_port()
        address = 'AA:BB:CC:DD:EE:FF'
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/address',
                                     'value': address, 'op': 'replace'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(result['address'], address)

    def test_replace_address_already_exist(self):
        address = '11:22:33:AA:BB:CC'
        pdict = dbutils.get_test_port(address=address,
                                      uuid=uuidutils.generate_uuid())
        self.post_json('/ports', pdict)

        pdict = dbutils.get_test_port()
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/address',
                                     'value': address, 'op': 'replace'}],
                                     expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json['error_message'])

    def test_replace_nodeid_dont_exist(self):
        pdict = dbutils.get_test_port()
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                             [{'path': '/node_id',
                               'value': '12506333-a81c-4d59-9987-889ed5f8687b',
                               'op': 'replace'}],
                             expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json['error_message'])

    def test_replace_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        pdict = dbutils.get_test_port(extra=extra,
                                      address="AA:BB:CC:DD:EE:FF",
                                      uuid=uuidutils.generate_uuid())
        self.post_json('/ports', pdict)
        new_value = 'new value'
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo2',
                                     'value': new_value, 'op': 'replace'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])

        extra["foo2"] = new_value
        self.assertEqual(result['extra'], extra)

    def test_remove_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        pdict = dbutils.get_test_port(extra=extra,
                                      address="AA:BB:CC:DD:EE:FF",
                                      uuid=uuidutils.generate_uuid())
        self.post_json('/ports', pdict)

        # Removing one item from the collection
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo2', 'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        extra.pop("foo2")
        self.assertEqual(result['extra'], extra)

        # Removing the collection
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra', 'op': 'remove'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(result['extra'], {})

        # Assert nothing else was changed
        self.assertEqual(result['uuid'], pdict['uuid'])
        self.assertEqual(result['address'], pdict['address'])

    def test_remove_mandatory_field(self):
        pdict = dbutils.get_test_port(address="AA:BB:CC:DD:EE:FF",
                                      uuid=uuidutils.generate_uuid())
        self.post_json('/ports', pdict)
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/address', 'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json['error_message'])

    def test_add_singular(self):
        pdict = dbutils.get_test_port()
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/foo', 'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_int, 400)
        self.assertTrue(response.json['error_message'])

    def test_add_multi(self):
        pdict = dbutils.get_test_port()
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo1', 'value': 'bar1',
                                     'op': 'add'},
                                    {'path': '/extra/foo2', 'value': 'bar2',
                                     'op': 'add'}])
        self.assertEqual(response.content_type, 'application/json')
        self.assertEqual(response.status_code, 200)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        expected = {"foo1": "bar1", "foo2": "bar2"}
        self.assertEqual(result['extra'], expected)

    def test_remove_uuid(self):
        pdict = dbutils.get_test_port()
        self.assertRaises(webtest.app.AppError, self.patch_json,
                          '/ports/%s' % pdict['uuid'],
                          [{'path': '/uuid', 'op': 'remove'}])


class TestPost(base.FunctionalTest):

    def setUp(self):
        super(TestPost, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)

    def test_create_port(self):
        pdict = dbutils.get_test_port()
        self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(pdict['uuid'], result['uuid'])

    def test_create_port_generate_uuid(self):
        pdict = dbutils.get_test_port()
        del pdict['uuid']
        self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % pdict['address'])
        self.assertEqual(pdict['address'], result['address'])
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))

    def test_create_port_valid_extra(self):
        pdict = dbutils.get_test_port(extra={'foo': 123})
        self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(pdict['extra'], result['extra'])

    def test_create_port_invalid_extra(self):
        pdict = dbutils.get_test_port(extra={'foo': 0.123})
        self.assertRaises(webtest.app.AppError, self.post_json, '/ports',
                          pdict)

    def test_create_port_no_mandatory_fields(self):
        pdict = dbutils.get_test_port(address=None, node_id=None)
        self.assertRaises(webtest.app.AppError, self.post_json, '/ports',
                          pdict)

    def test_create_port_invalid_addr_format(self):
        pdict = dbutils.get_test_port(address='invalid-format')
        self.assertRaises(webtest.app.AppError, self.post_json, '/ports',
                          pdict)


class TestDelete(base.FunctionalTest):

    def setUp(self):
        super(TestDelete, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        pdict = dbutils.get_test_port()
        self.post_json('/ports', pdict)

    def test_delete_port_byid(self):
        pdict = dbutils.get_test_port()
        self.delete('/ports/%s' % pdict['uuid'])
        response = self.get_json('/ports/%s' % pdict['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])

    def test_delete_port_byaddress(self):
        pdict = dbutils.get_test_port()
        self.delete('/ports/%s' % pdict['address'])
        response = self.get_json('/ports/%s' % pdict['uuid'],
                                 expect_errors=True)
        self.assertEqual(response.status_int, 404)
        self.assertEqual(response.content_type, 'application/json')
        self.assertTrue(response.json['error_message'])
