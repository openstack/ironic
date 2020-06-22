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
Tests for the API /volume targets/ methods.
"""

import datetime
from http import client as http_client
from unittest import mock
from urllib import parse as urlparse

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import notification_utils
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import volume_target as api_volume_target
from ironic.api import types as atypes
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.db import utils as dbutils
from ironic.tests.unit.objects import utils as obj_utils


def post_get_test_volume_target(**kw):
    target = apiutils.volume_target_post_data(**kw)
    node = dbutils.get_test_node()
    target['node_uuid'] = kw.get('node_uuid', node['uuid'])
    return target


class TestVolumeTargetObject(base.TestCase):

    def test_volume_target_init(self):
        target_dict = apiutils.volume_target_post_data(node_id=None)
        del target_dict['extra']
        target = api_volume_target.VolumeTarget(**target_dict)
        self.assertEqual(atypes.Unset, target.extra)


class TestListVolumeTargets(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestListVolumeTargets, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_empty(self):
        data = self.get_json('/volume/targets', headers=self.headers)
        self.assertEqual([], data['targets'])

    def test_one(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/targets', headers=self.headers)
        self.assertEqual(target.uuid, data['targets'][0]["uuid"])
        self.assertNotIn('extra', data['targets'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['targets'][0])

    def test_one_invalid_api_version(self):
        obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        response = self.get_json(
            '/volume/targets',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/targets/%s' % target.uuid,
                             headers=self.headers)
        self.assertEqual(target.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('node_uuid', data)
        # never expose the node_id
        self.assertNotIn('node_id', data)

    def test_get_one_invalid_api_version(self):
        target = obj_utils.create_test_volume_target(self.context,
                                                     node_id=self.node.id)
        response = self.get_json(
            '/volume/targets/%s' % target.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_custom_fields(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        fields = 'boot_index,extra'
        data = self.get_json(
            '/volume/targets/%s?fields=%s' % (target.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertCountEqual(['boot_index', 'extra', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=i)

        data = self.get_json(
            '/volume/targets?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['targets']))
        for target in data['targets']:
            # We always append "links"
            self.assertCountEqual(['uuid', 'extra', 'links'], target)

    def test_get_custom_fields_invalid_fields(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/volume/targets/%s?fields=%s' % (target.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_detail(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/targets?detail=True',
                             headers=self.headers)
        self.assertEqual(target.uuid, data['targets'][0]["uuid"])
        self.assertIn('extra', data['targets'][0])
        self.assertIn('node_uuid', data['targets'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['targets'][0])

    def test_detail_false(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/targets?detail=False',
                             headers=self.headers)
        self.assertEqual(target.uuid, data['targets'][0]["uuid"])
        self.assertNotIn('extra', data['targets'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['targets'][0])

    def test_detail_invalid_api_version(self):
        obj_utils.create_test_volume_target(self.context,
                                            node_id=self.node.id)
        response = self.get_json(
            '/volume/targets?detail=True',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail_sepecified_by_path(self):
        obj_utils.create_test_volume_target(self.context,
                                            node_id=self.node.id)
        response = self.get_json(
            '/volume/targets/detail', headers=self.headers,
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_against_single(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        response = self.get_json('/volume/targets/%s?detail=True'
                                 % target.uuid,
                                 headers=self.headers,
                                 expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_and_fields(self):
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        fields = 'boot_index,extra'
        response = self.get_json('/volume/targets/%s?detail=True&fields=%s'
                                 % (target.uuid, fields),
                                 headers=self.headers,
                                 expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_many(self):
        targets = []
        for id_ in range(5):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets', headers=self.headers)
        self.assertEqual(len(targets), len(data['targets']))

        uuids = [n['uuid'] for n in data['targets']]
        self.assertCountEqual(targets, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_volume_target(self.context,
                                            uuid=uuid,
                                            node_id=self.node.id)
        data = self.get_json('/volume/targets/%s' % uuid,
                             headers=self.headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'], bookmark=bookmark,
                                               headers=self.headers))

    def test_collection_links(self):
        targets = []
        for id_ in range(5):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets/?limit=3', headers=self.headers)
        self.assertEqual(3, len(data['targets']))

        next_marker = data['targets'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/targets', data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        targets = []
        for id_ in range(5):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets', headers=self.headers)
        self.assertEqual(3, len(data['targets']))

        next_marker = data['targets'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/targets', data['next'])

    def test_collection_links_custom_fields(self):
        fields = 'uuid,extra'
        cfg.CONF.set_override('max_limit', 3, 'api')
        targets = []
        for id_ in range(5):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets?fields=%s' % fields,
                             headers=self.headers)
        self.assertEqual(3, len(data['targets']))

        next_marker = data['targets'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/targets', data['next'])
        self.assertIn('fields', data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'boot_index'
        limit = 2
        targets = []
        for id_ in range(3):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target)

        data = self.get_json(
            '/volume/targets?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['targets']))
        self.assertIn('marker=%s' % targets[limit - 1].uuid, data['next'])

    def test_collection_links_detail(self):
        targets = []
        for id_ in range(5):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets?detail=True&limit=3',
                             headers=self.headers)
        self.assertEqual(3, len(data['targets']))

        next_marker = data['targets'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/targets', data['next'])
        self.assertIn('detail=True', data['next'])

    def test_sort_key(self):
        targets = []
        for id_ in range(3):
            target = obj_utils.create_test_volume_target(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(), boot_index=id_)
            targets.append(target.uuid)
        data = self.get_json('/volume/targets?sort_key=uuid',
                             headers=self.headers)
        uuids = [n['uuid'] for n in data['targets']]
        self.assertEqual(sorted(targets), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra', 'properties']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/volume/targets?sort_key=%s'
                                     % invalid_key,
                                     headers=self.headers,
                                     expect_errors=True)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/volume/targets specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_volume_target(
                self.context, node_id=node_id,
                uuid=uuidutils.generate_uuid(), boot_index=i)
        data = self.get_json("/volume/targets?node=%s" % 'test-node',
                             headers=self.headers)
        self.assertEqual(3, len(data['targets']))

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_detail_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/volume/targets/?detail=True specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/targets?detail=True&node=%s' %
                             'test-node',
                             headers=self.headers)
        self.assertEqual(target.uuid, data['targets'][0]['uuid'])
        self.assertEqual(self.node.uuid, data['targets'][0]['node_uuid'])


@mock.patch.object(rpcapi.ConductorAPI, 'update_volume_target')
class TestPatch(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPatch, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)

        p = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = p.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(p.stop)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_update_byid(self, mock_notify, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.target
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    def test_update_byid_invalid_api_version(self, mock_upd):
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=headers,
                                   expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_update_not_found(self, mock_upd):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/volume/targets/%s' % uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_singular(self, mock_upd):
        boot_index = 100
        mock_upd.return_value = self.target
        mock_upd.return_value.boot_index = boot_index
        response = self.patch_json('/volume/targets/%s' % self.target.uuid,
                                   [{'path': '/boot_index',
                                     'value': boot_index,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(boot_index, response.json['boot_index'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(boot_index, kargs.boot_index)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_replace_boot_index_already_exist(self, mock_notify, mock_upd):
        boot_index = 100
        mock_upd.side_effect = \
            exception.VolumeTargetBootIndexAlreadyExists(boot_index=boot_index)
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/boot_index',
                                     'value': boot_index,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(boot_index, kargs.boot_index)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_replace_invalid_power_state(self, mock_upd):
        mock_upd.side_effect = \
            exception.InvalidStateRequested(
                action='volume target update', node=self.node.uuid,
                state='power on')
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/boot_index',
                                     'value': 0,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(0, kargs.boot_index)

    def test_replace_node_uuid(self, mock_upd):
        mock_upd.return_value = self.target
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_replace_node_uuid_inalid_type(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_uuid',
                                     'value': 123,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(b'Expected a UUID for node_uuid, but received 123.',
                      response.body)
        self.assertFalse(mock_upd.called)

    def test_add_node_uuid(self, mock_upd):
        mock_upd.return_value = self.target
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_add_node_uuid_invalid_type(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_uuid',
                                     'value': 123,
                                     'op': 'add'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(b'Expected a UUID for node_uuid, but received 123.',
                      response.body)
        self.assertFalse(mock_upd.called)

    def test_add_node_id(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'add'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_node_id(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'replace'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_remove_node_id(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_id',
                                     'op': 'remove'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_non_existent_node_uuid(self, mock_upd):
        node_uuid = '12506333-a81c-4d59-9987-889ed5f8687b'
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/node_uuid',
                                     'value': node_uuid,
                                     'op': 'replace'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(node_uuid, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.target.extra = extra
        self.target.save()

        # mutate extra so we replace all of them
        extra = dict((k, extra[k] + 'x') for k in extra)

        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'replace'})
        mock_upd.return_value = self.target
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   patch,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

    def test_remove_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.target.extra = extra
        self.target.save()

        # Remove one item from the collection.
        extra.pop('foo1')
        mock_upd.return_value = self.target
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/extra/foo1',
                                     'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

        # Remove the collection.
        extra = {}
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/extra', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({}, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

        # Assert nothing else was changed.
        self.assertEqual(self.target.uuid, response.json['uuid'])
        self.assertEqual(self.target.volume_type,
                         response.json['volume_type'])
        self.assertEqual(self.target.boot_index, response.json['boot_index'])

    def test_remove_non_existent_property_fail(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/extra/non-existent',
                                     'op': 'remove'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_remove_mandatory_field(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/boot_index',
                                     'op': 'remove'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_add_root(self, mock_upd):
        boot_index = 100
        mock_upd.return_value = self.target
        mock_upd.return_value.boot_index = boot_index
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/boot_index',
                                     'value': boot_index,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(boot_index, response.json['boot_index'])
        self.assertTrue(mock_upd.called)
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(boot_index, kargs.boot_index)

    def test_add_root_non_existent(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_add_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'add'})
        mock_upd.return_value = self.target
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   patch,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

    def test_remove_uuid(self, mock_upd):
        response = self.patch_json('/volume/targets/%s'
                                   % self.target.uuid,
                                   [{'path': '/uuid',
                                     'op': 'remove'}],
                                   headers=self.headers,
                                   expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)


class TestPost(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPost, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(timeutils, 'utcnow')
    def test_create_volume_target(self, mock_utcnow, mock_notify):
        pdict = post_get_test_volume_target()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/volume/targets/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header.
        self.assertIsNotNone(response.location)
        expected_location = '/v1/volume/targets/%s' % pdict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    def test_create_volume_target_invalid_api_version(self):
        pdict = post_get_test_volume_target()
        response = self.post_json(
            '/volume/targets', pdict,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_create_volume_target_doesnt_contain_id(self):
        with mock.patch.object(
                self.dbapi, 'create_volume_target',
                wraps=self.dbapi.create_volume_target) as cp_mock:
            pdict = post_get_test_volume_target(extra={'foo': 123})
            self.post_json('/volume/targets', pdict,
                           headers=self.headers)
            result = self.get_json('/volume/targets/%s' % pdict['uuid'],
                                   headers=self.headers)
            self.assertEqual(pdict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args.
            self.assertNotIn('id', cp_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_volume_target_generate_uuid(self, mock_warning,
                                                mock_exception):
        pdict = post_get_test_volume_target()
        del pdict['uuid']
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers)
        result = self.get_json('/volume/targets/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['boot_index'], result['boot_index'])
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warning.called)
        self.assertFalse(mock_exception.called)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(objects.VolumeTarget, 'create')
    def test_create_volume_target_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        tdict = post_get_test_volume_target()
        self.post_json('/volume/targets', tdict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_create_volume_target_valid_extra(self):
        pdict = post_get_test_volume_target(
            extra={'str': 'foo', 'int': 123, 'float': 0.1, 'bool': True,
                   'list': [1, 2], 'none': None, 'dict': {'cat': 'meow'}})
        self.post_json('/volume/targets', pdict, headers=self.headers)
        result = self.get_json('/volume/targets/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['extra'], result['extra'])

    def test_create_volume_target_no_mandatory_field_type(self):
        pdict = post_get_test_volume_target()
        del pdict['volume_type']
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_target_no_mandatory_field_value(self):
        pdict = post_get_test_volume_target()
        del pdict['boot_index']
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_target_no_mandatory_field_node_uuid(self):
        pdict = post_get_test_volume_target()
        del pdict['node_uuid']
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_target_invalid_node_uuid_format(self):
        pdict = post_get_test_volume_target(node_uuid=123)
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertIn(b'Expected a UUID but received 123.', response.body)

    def test_node_uuid_to_node_id_mapping(self):
        pdict = post_get_test_volume_target(node_uuid=self.node['uuid'])
        self.post_json('/volume/targets', pdict, headers=self.headers)
        # GET doesn't return the node_id it's an internal value
        target = self.dbapi.get_volume_target_by_uuid(pdict['uuid'])
        self.assertEqual(self.node['id'], target.node_id)

    def test_create_volume_target_node_uuid_not_found(self):
        pdict = post_get_test_volume_target(
            node_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/volume/targets', pdict,
                                  headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_volume_target')
class TestDelete(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.target = obj_utils.create_test_volume_target(
            self.context, node_id=self.node.id)

        gtf = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = gtf.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(gtf.stop)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_volume_target_byid(self, mock_notify, mock_dvc):
        self.delete('/volume/targets/%s' % self.target.uuid,
                    headers=self.headers,
                    expect_errors=True)
        self.assertTrue(mock_dvc.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    def test_delete_volume_target_byid_invalid_api_version(self, mock_dvc):
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.delete('/volume/targets/%s' % self.target.uuid,
                               headers=headers,
                               expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_volume_target_node_locked(self, mock_notify, mock_dvc):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_dvc.side_effect = exception.NodeLocked(node='fake-node',
                                                    host='fake-host')
        ret = self.delete('/volume/targets/%s' % self.target.uuid,
                          headers=self.headers,
                          expect_errors=True)
        self.assertEqual(http_client.CONFLICT, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_dvc.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_delete_volume_target_invalid_power_state(self, mock_dvc):
        mock_dvc.side_effect = exception.InvalidStateRequested(
            action='volume target deletion', node=self.node.uuid,
            state='power on')
        ret = self.delete('/volume/targets/%s' % self.target.uuid,
                          headers=self.headers,
                          expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_dvc.called)
