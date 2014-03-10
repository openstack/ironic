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

import datetime

import mock
from oslo.config import cfg

from ironic.common import utils
from ironic.openstack.common import timeutils
from ironic.tests.api import base
from ironic.tests.api import utils as apiutils
from ironic.tests.db import utils as dbutils


# NOTE(lucasagomes): When creating a port via API (POST)
#                    we have to use node_uuid
def post_get_test_port(**kw):
    port = apiutils.port_post_data(**kw)
    node = dbutils.get_test_node()
    del port['node_id']
    port['node_uuid'] = kw.get('node_uuid', node['uuid'])
    return port


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
        self.assertNotIn('node_uuid', data['ports'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['ports'][0])

    def test_detail(self):
        pdict = dbutils.get_test_port()
        port = self.dbapi.create_port(pdict)
        data = self.get_json('/ports/detail')
        self.assertEqual(port['uuid'], data['ports'][0]["uuid"])
        self.assertIn('extra', data['ports'][0])
        self.assertIn('node_uuid', data['ports'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['ports'][0])

    def test_detail_against_single(self):
        pdict = dbutils.get_test_port()
        port = self.dbapi.create_port(pdict)
        response = self.get_json('/ports/%s/detail' % port['uuid'],
                                 expect_errors=True)
        self.assertEqual(404, response.status_int)

    def test_many(self):
        ports = []
        for id in range(5):
            ndict = dbutils.get_test_port(id=id,
                                          uuid=utils.generate_uuid(),
                                          address='52:54:00:cf:2d:3%s' % id)
            port = self.dbapi.create_port(ndict)
            ports.append(port['uuid'])
        data = self.get_json('/ports')
        self.assertEqual(len(ports), len(data['ports']))

        uuids = [n['uuid'] for n in data['ports']]
        self.assertEqual(ports.sort(), uuids.sort())

    def test_links(self):
        uuid = utils.generate_uuid()
        ndict = dbutils.get_test_port(id=1, uuid=uuid)
        self.dbapi.create_port(ndict)
        data = self.get_json('/ports/%s' % uuid)
        self.assertIn('links', data.keys())
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        self.assertTrue(self.validate_link(data['links'][0]['href']))
        self.assertTrue(self.validate_link(data['links'][1]['href']))

    def test_collection_links(self):
        ports = []
        for id in range(5):
            ndict = dbutils.get_test_port(id=id,
                                          uuid=utils.generate_uuid(),
                                          address='52:54:00:cf:2d:3%s' % id)
            port = self.dbapi.create_port(ndict)
            ports.append(port['uuid'])
        data = self.get_json('/ports/?limit=3')
        self.assertEqual(3, len(data['ports']))

        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        ports = []
        for id in range(5):
            ndict = dbutils.get_test_port(id=id,
                                          uuid=utils.generate_uuid(),
                                          address='52:54:00:cf:2d:3%s' % id)
            port = self.dbapi.create_port(ndict)
            ports.append(port['uuid'])
        data = self.get_json('/ports')
        self.assertEqual(3, len(data['ports']))

        next_marker = data['ports'][-1]['uuid']
        self.assertIn(next_marker, data['next'])


class TestPatch(base.FunctionalTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        self.pdict = dbutils.get_test_port(id=None)
        self.dbapi.create_port(self.pdict)

    @mock.patch.object(timeutils, 'utcnow')
    def test_update_byid(self, mock_utcnow):
        extra = {'foo': 'bar'}
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % self.pdict['uuid'])
        self.assertEqual(extra, result['extra'])
        return_updated_at = timeutils.parse_isotime(
                            result['updated_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_updated_at)

    def test_update_byaddress(self):
        response = self.patch_json('/ports/%s' % self.pdict['address'],
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(self.pdict['address'], response.json['error_message'])

    def test_update_not_found(self):
        uuid = utils.generate_uuid()
        response = self.patch_json('/ports/%s' % uuid,
                                   [{'path': '/extra/a',
                                     'value': 'b',
                                     'op': 'add'}],
                             expect_errors=True)
        self.assertEqual(404, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_replace_singular(self):
        address = 'aa:bb:cc:dd:ee:ff'
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/address',
                                     'value': address, 'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % self.pdict['uuid'])
        self.assertEqual(address, result['address'])

    def test_replace_address_already_exist(self):
        pdict1 = dbutils.get_test_port(address='aa:aa:aa:aa:aa:aa',
                                       uuid=utils.generate_uuid(),
                                       id=None)
        self.dbapi.create_port(pdict1)

        pdict2 = dbutils.get_test_port(address='bb:bb:bb:bb:bb:bb',
                                       uuid=utils.generate_uuid(),
                                       id=None)
        self.dbapi.create_port(pdict2)

        response = self.patch_json('/ports/%s' % pdict1['uuid'],
                                   [{'path': '/address',
                                     'value': pdict2['address'],
                                     'op': 'replace'}],
                                     expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(409, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_replace_nodeid_dont_exist(self):
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                             [{'path': '/node_uuid',
                               'value': '12506333-a81c-4d59-9987-889ed5f8687b',
                               'op': 'replace'}],
                             expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_replace_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        pdict = dbutils.get_test_port(extra=extra,
                                   address="AA:BB:CC:DD:EE:FF",
                                   uuid=utils.generate_uuid())
        self.dbapi.create_port(pdict)

        new_value = 'new value'
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo2',
                                     'value': new_value, 'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % pdict['uuid'])

        extra["foo2"] = new_value
        self.assertEqual(extra, result['extra'])

    def test_remove_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        pdict = dbutils.get_test_port(extra=extra,
                                   address="aa:bb:cc:dd:ee:ff",
                                   uuid=utils.generate_uuid())
        self.dbapi.create_port(pdict)

        # Removing one item from the collection
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra/foo2', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        extra.pop("foo2")
        self.assertEqual(extra, result['extra'])

        # Removing the collection
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/extra', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual({}, result['extra'])

        # Assert nothing else was changed
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertEqual(pdict['address'], result['address'])

    def test_remove_non_existent_property_fail(self):
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                             [{'path': '/extra/non-existent', 'op': 'remove'}],
                             expect_errors=True)
        self.assertEqual('application/json', response.content_type, )
        self.assertEqual(400, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_remove_mandatory_field(self):
        pdict = dbutils.get_test_port(address="AA:BB:CC:DD:EE:FF",
                                   uuid=utils.generate_uuid())
        self.dbapi.create_port(pdict)

        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/address', 'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_add_singular(self):
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/foo', 'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_add_multi(self):
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/extra/foo1', 'value': 'bar1',
                                     'op': 'add'},
                                    {'path': '/extra/foo2', 'value': 'bar2',
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % self.pdict['uuid'])
        expected = {"foo1": "bar1", "foo2": "bar2"}
        self.assertEqual(expected, result['extra'])

    def test_remove_uuid(self):
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/uuid', 'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_update_address_invalid_format(self):
        pdict = dbutils.get_test_port(address="AA:BB:CC:DD:EE:FF",
                                   uuid=utils.generate_uuid())
        self.dbapi.create_port(pdict)
        response = self.patch_json('/ports/%s' % pdict['uuid'],
                                   [{'path': '/address',
                                     'value': 'invalid-format',
                                     'op': 'replace'}],
                                   expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_update_port_address_normalized(self):
        new_address = 'AA:BB:CC:DD:EE:FF'
        response = self.patch_json('/ports/%s' % self.pdict['uuid'],
                                   [{'path': '/address', 'value': new_address,
                                     'op': 'replace'}])
        self.assertEqual(200, response.status_code)
        result = self.get_json('/ports/%s' % self.pdict['uuid'])
        self.assertEqual(new_address.lower(), result['address'])


class TestPost(base.FunctionalTest):

    def setUp(self):
        super(TestPost, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)

    @mock.patch.object(timeutils, 'utcnow')
    def test_create_port(self, mock_utcnow):
        pdict = post_get_test_port()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/ports', pdict)
        self.assertEqual(201, response.status_int)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
                            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)

    def test_create_port_generate_uuid(self):
        pdict = post_get_test_port()
        del pdict['uuid']
        response = self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % response.json['uuid'])
        self.assertEqual(pdict['address'], result['address'])
        self.assertTrue(utils.is_uuid_like(result['uuid']))

    def test_create_port_valid_extra(self):
        pdict = post_get_test_port(extra={'foo': 123})
        self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(pdict['extra'], result['extra'])

    def test_create_port_invalid_extra(self):
        pdict = post_get_test_port(extra={'foo': 0.123})
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_port_no_mandatory_field_address(self):
        pdict = post_get_test_port()
        del pdict['address']
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_port_no_mandatory_field_node_uuid(self):
        pdict = post_get_test_port()
        del pdict['node_uuid']
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_port_invalid_addr_format(self):
        pdict = post_get_test_port(address='invalid-format')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_port_address_normalized(self):
        address = 'AA:BB:CC:DD:EE:FF'
        pdict = post_get_test_port(address=address)
        self.post_json('/ports', pdict)
        result = self.get_json('/ports/%s' % pdict['uuid'])
        self.assertEqual(address.lower(), result['address'])

    def test_create_port_with_hyphens_delimiter(self):
        pdict = post_get_test_port()
        colonsMAC = pdict['address']
        hyphensMAC = colonsMAC.replace(':', '-')
        pdict['address'] = hyphensMAC
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_port_invalid_node_uuid_format(self):
        pdict = post_get_test_port(node_uuid='invalid-format')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_node_uuid_to_node_id_mapping(self):
        pdict = post_get_test_port(node_uuid=self.node['uuid'])
        self.post_json('/ports', pdict)
        # GET doesn't return the node_id it's an internal value
        port = self.dbapi.get_port(pdict['uuid'])
        self.assertEqual(self.node['id'], port.node_id)

    def test_create_port_node_uuid_not_found(self):
        pdict = post_get_test_port(
                              node_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(400, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_port_address_already_exist(self):
        address = 'AA:AA:AA:11:22:33'
        pdict = post_get_test_port(address=address)
        self.post_json('/ports', pdict)
        pdict['uuid'] = utils.generate_uuid()
        response = self.post_json('/ports', pdict, expect_errors=True)
        self.assertEqual(409, response.status_int)
        self.assertEqual('application/json', response.content_type)
        error_msg = response.json['error_message']
        self.assertTrue(error_msg)
        self.assertIn(address, error_msg.upper())


class TestDelete(base.FunctionalTest):

    def setUp(self):
        super(TestDelete, self).setUp()
        ndict = dbutils.get_test_node()
        self.node = self.dbapi.create_node(ndict)
        pdict = dbutils.get_test_port()
        self.dbapi.create_port(pdict)

    def test_delete_port_byid(self):
        pdict = dbutils.get_test_port()
        self.delete('/ports/%s' % pdict['uuid'])
        response = self.get_json('/ports/%s' % pdict['uuid'],
                                 expect_errors=True)
        self.assertEqual(404, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_delete_port_byaddress(self):
        pdict = dbutils.get_test_port()
        response = self.delete('/ports/%s' % pdict['address'],
                               expect_errors=True)
        self.assertEqual(400, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(pdict['address'], response.json['error_message'])
