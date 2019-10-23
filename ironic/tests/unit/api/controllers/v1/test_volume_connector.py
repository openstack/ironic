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
Tests for the API /volume connectors/ methods.
"""

import datetime

import mock
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from six.moves import http_client
from six.moves.urllib import parse as urlparse
from wsme import types as wtypes

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import notification_utils
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import volume_connector as api_volume_connector
from ironic.common import exception
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.db import utils as dbutils
from ironic.tests.unit.objects import utils as obj_utils


def post_get_test_volume_connector(**kw):
    connector = apiutils.volume_connector_post_data(**kw)
    node = dbutils.get_test_node()
    connector['node_uuid'] = kw.get('node_uuid', node['uuid'])
    return connector


class TestVolumeConnectorObject(base.TestCase):

    def test_volume_connector_init(self):
        connector_dict = apiutils.volume_connector_post_data(node_id=None)
        del connector_dict['extra']
        connector = api_volume_connector.VolumeConnector(**connector_dict)
        self.assertEqual(wtypes.Unset, connector.extra)


class TestListVolumeConnectors(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestListVolumeConnectors, self).setUp()
        self.node = obj_utils.create_test_node(self.context)

    def test_empty(self):
        data = self.get_json('/volume/connectors', headers=self.headers)
        self.assertEqual([], data['connectors'])

    def test_one(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/connectors', headers=self.headers)
        self.assertEqual(connector.uuid, data['connectors'][0]["uuid"])
        self.assertNotIn('extra', data['connectors'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['connectors'][0])

    def test_one_invalid_api_version(self):
        obj_utils.create_test_volume_connector(self.context,
                                               node_id=self.node.id)
        response = self.get_json(
            '/volume/connectors',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/connectors/%s' % connector.uuid,
                             headers=self.headers)
        self.assertEqual(connector.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('node_uuid', data)
        # never expose the node_id
        self.assertNotIn('node_id', data)

    def test_get_one_invalid_api_version(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        response = self.get_json(
            '/volume/connectors/%s' % connector.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_custom_fields(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        fields = 'connector_id,extra'
        data = self.get_json(
            '/volume/connectors/%s?fields=%s' % (connector.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertItemsEqual(['connector_id', 'extra', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_volume_connector(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % i)

        data = self.get_json(
            '/volume/connectors?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['connectors']))
        for connector in data['connectors']:
            # We always append "links"
            self.assertItemsEqual(['uuid', 'extra', 'links'], connector)

    def test_get_custom_fields_invalid_fields(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/volume/connectors/%s?fields=%s' % (connector.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_custom_fields_invalid_api_version(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        fields = 'uuid,extra'
        response = self.get_json(
            '/volume/connectors/%s?fields=%s' % (connector.uuid, fields),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/connectors?detail=True',
                             headers=self.headers)
        self.assertEqual(connector.uuid, data['connectors'][0]["uuid"])
        self.assertIn('extra', data['connectors'][0])
        self.assertIn('node_uuid', data['connectors'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['connectors'][0])

    def test_detail_false(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/connectors?detail=False',
                             headers=self.headers)
        self.assertEqual(connector.uuid, data['connectors'][0]["uuid"])
        self.assertNotIn('extra', data['connectors'][0])
        # never expose the node_id
        self.assertNotIn('node_id', data['connectors'][0])

    def test_detail_invalid_api_version(self):
        obj_utils.create_test_volume_connector(self.context,
                                               node_id=self.node.id)
        response = self.get_json(
            '/volume/connectors?detail=True',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail_sepecified_by_path(self):
        obj_utils.create_test_volume_connector(self.context,
                                               node_id=self.node.id)
        response = self.get_json(
            '/volume/connectors/detail', headers=self.headers,
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_against_single(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        response = self.get_json('/volume/connectors/%s?detail=True'
                                 % connector.uuid,
                                 expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_and_fields(self):
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        fields = 'connector_id,extra'
        response = self.get_json('/volume/connectors/%s?detail=True&fields=%s'
                                 % (connector.uuid, fields),
                                 expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_many(self):
        connectors = []
        for id_ in range(5):
            connector = obj_utils.create_test_volume_connector(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % id_)
            connectors.append(connector.uuid)
        data = self.get_json('/volume/connectors', headers=self.headers)
        self.assertEqual(len(connectors), len(data['connectors']))

        uuids = [n['uuid'] for n in data['connectors']]
        six.assertCountEqual(self, connectors, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_volume_connector(self.context,
                                               uuid=uuid,
                                               node_id=self.node.id)
        data = self.get_json('/volume/connectors/%s' % uuid,
                             headers=self.headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for l in data['links']:
            bookmark = l['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(l['href'], bookmark=bookmark,
                                               headers=self.headers))

    def test_collection_links(self):
        connectors = []
        for id_ in range(5):
            connector = obj_utils.create_test_volume_connector(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % id_)
            connectors.append(connector.uuid)
        data = self.get_json('/volume/connectors/?limit=3',
                             headers=self.headers)
        self.assertEqual(3, len(data['connectors']))

        next_marker = data['connectors'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/connectors', data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        connectors = []
        for id_ in range(5):
            connector = obj_utils.create_test_volume_connector(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % id_)
            connectors.append(connector.uuid)
        data = self.get_json('/volume/connectors', headers=self.headers)
        self.assertEqual(3, len(data['connectors']))
        self.assertIn('volume/connectors', data['next'])

        next_marker = data['connectors'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'connector_id'
        limit = 2
        connectors = []
        for id_ in range(3):
            volume_connector = obj_utils.create_test_volume_connector(
                self.context,
                node_id=self.node.id,
                connector_id='test-connector_id-%s' % id_,
                uuid=uuidutils.generate_uuid())
            connectors.append(volume_connector)

        data = self.get_json(
            '/volume/connectors?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['connectors']))
        self.assertIn('marker=%s' % connectors[limit - 1].uuid, data['next'])

    def test_collection_links_detail(self):
        connectors = []
        for id_ in range(5):
            connector = obj_utils.create_test_volume_connector(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % id_)
            connectors.append(connector.uuid)
        data = self.get_json('/volume/connectors?detail=True&limit=3',
                             headers=self.headers)
        self.assertEqual(3, len(data['connectors']))

        next_marker = data['connectors'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('volume/connectors', data['next'])
        self.assertIn('detail=True', data['next'])

    def test_sort_key(self):
        connectors = []
        for id_ in range(3):
            connector = obj_utils.create_test_volume_connector(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-connector_id-%s' % id_)
            connectors.append(connector.uuid)
        data = self.get_json('/volume/connectors?sort_key=uuid',
                             headers=self.headers)
        uuids = [n['uuid'] for n in data['connectors']]
        self.assertEqual(sorted(connectors), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/volume/connectors?sort_key=%s'
                                     % invalid_key,
                                     expect_errors=True,
                                     headers=self.headers)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_get_all_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/volume/connectors specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
            obj_utils.create_test_volume_connector(
                self.context, node_id=node_id,
                uuid=uuidutils.generate_uuid(),
                connector_id='test-value-%s' % i)
        data = self.get_json("/volume/connectors?node=%s" % 'test-node',
                             headers=self.headers)
        self.assertEqual(3, len(data['connectors']))

    @mock.patch.object(api_utils, 'get_rpc_node')
    def test_detail_by_node_name_ok(self, mock_get_rpc_node):
        # GET /v1/volume/connectors?detail=True specifying node_name - success
        mock_get_rpc_node.return_value = self.node
        connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)
        data = self.get_json('/volume/connectors?detail=True&node=%s' %
                             'test-node',
                             headers=self.headers)
        self.assertEqual(connector.uuid, data['connectors'][0]['uuid'])
        self.assertEqual(self.node.uuid, data['connectors'][0]['node_uuid'])


@mock.patch.object(rpcapi.ConductorAPI, 'update_volume_connector')
class TestPatch(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPatch, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)

        p = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = p.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(p.stop)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_update_byid(self, mock_notify, mock_upd):
        extra = {'foo': 'bar'}
        mock_upd.return_value = self.connector
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
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

    def test_update_invalid_api_version(self, mock_upd):
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   headers=headers,
                                   expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_update_not_found(self, mock_upd):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/volume/connectors/%s' % uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_singular(self, mock_upd):
        connector_id = 'test-connector-id-999'
        mock_upd.return_value = self.connector
        mock_upd.return_value.connector_id = connector_id
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/connector_id',
                                     'value': connector_id,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(connector_id, response.json['connector_id'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(connector_id, kargs.connector_id)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_replace_connector_id_already_exist(self, mock_notify, mock_upd):
        connector_id = 'test-connector-id-123'
        mock_upd.side_effect = \
            exception.VolumeConnectorTypeAndIdAlreadyExists(
                type=None, connector_id=connector_id)
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/connector_id',
                                     'value': connector_id,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(connector_id, kargs.connector_id)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_replace_invalid_power_state(self, mock_upd):
        connector_id = 'test-connector-id-123'
        mock_upd.side_effect = \
            exception.InvalidStateRequested(
                action='volume connector update', node=self.node.uuid,
                state='power on')
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/connector_id',
                                     'value': connector_id,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertTrue(mock_upd.called)

        kargs = mock_upd.call_args[0][1]
        self.assertEqual(connector_id, kargs.connector_id)

    def test_replace_node_uuid(self, mock_upd):
        mock_upd.return_value = self.connector
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_replace_node_uuid_invalid_type(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
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
        mock_upd.return_value = self.connector
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_uuid',
                                     'value': self.node.uuid,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)

    def test_add_node_uuid_invalid_type(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
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
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'add'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_node_id(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_id',
                                     'value': '1',
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_remove_node_id(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_id',
                                     'op': 'remove'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertFalse(mock_upd.called)

    def test_replace_non_existent_node_uuid(self, mock_upd):
        node_uuid = '12506333-a81c-4d59-9987-889ed5f8687b'
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/node_uuid',
                                     'value': node_uuid,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertIn(node_uuid, response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_replace_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.connector.extra = extra
        self.connector.save()

        # mutate extra so we replace all of them
        extra = dict((k, extra[k] + 'x') for k in extra)

        patch = []
        for k in extra:
            patch.append({'path': '/extra/%s' % k,
                          'value': extra[k],
                          'op': 'replace'})
        mock_upd.return_value = self.connector
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

    def test_remove_multi(self, mock_upd):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        self.connector.extra = extra
        self.connector.save()

        # Remove one item from the collection.
        extra.pop('foo1')
        mock_upd.return_value = self.connector
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
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
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/extra', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual({}, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

        # Assert nothing else was changed.
        self.assertEqual(self.connector.uuid, response.json['uuid'])
        self.assertEqual(self.connector.type, response.json['type'])
        self.assertEqual(self.connector.connector_id,
                         response.json['connector_id'])

    def test_remove_non_existent_property_fail(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/extra/non-existent',
                                     'op': 'remove'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_remove_mandatory_field(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/value',
                                     'op': 'remove'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_upd.called)

    def test_add_root(self, mock_upd):
        connector_id = 'test-connector-id-123'
        mock_upd.return_value = self.connector
        mock_upd.return_value.connector_id = connector_id
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/connector_id',
                                     'value': connector_id,
                                     'op': 'add'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(connector_id, response.json['connector_id'])
        self.assertTrue(mock_upd.called)
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(connector_id, kargs.connector_id)

    def test_add_root_non_existent(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True, headers=self.headers)
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
        mock_upd.return_value = self.connector
        mock_upd.return_value.extra = extra
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(extra, response.json['extra'])
        kargs = mock_upd.call_args[0][1]
        self.assertEqual(extra, kargs.extra)

    def test_remove_uuid(self, mock_upd):
        response = self.patch_json('/volume/connectors/%s'
                                   % self.connector.uuid,
                                   [{'path': '/uuid',
                                     'op': 'remove'}],
                                   expect_errors=True, headers=self.headers)
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
    def test_create_volume_connector(self, mock_utcnow, mock_notify):
        pdict = post_get_test_volume_connector()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/volume/connectors', pdict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/volume/connectors/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header.
        self.assertIsNotNone(response.location)
        expected_location = '/v1/volume/connectors/%s' % pdict['uuid']
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

    def test_create_volume_connector_invalid_api_version(self):
        pdict = post_get_test_volume_connector()
        response = self.post_json(
            '/volume/connectors', pdict,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_create_volume_connector_doesnt_contain_id(self):
        with mock.patch.object(
                self.dbapi, 'create_volume_connector',
                wraps=self.dbapi.create_volume_connector) as cp_mock:
            pdict = post_get_test_volume_connector(extra={'foo': 123})
            self.post_json('/volume/connectors', pdict, headers=self.headers)
            result = self.get_json('/volume/connectors/%s' % pdict['uuid'],
                                   headers=self.headers)
            self.assertEqual(pdict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args.
            self.assertNotIn('id', cp_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_volume_connector_generate_uuid(self, mock_warning,
                                                   mock_exception):
        pdict = post_get_test_volume_connector()
        del pdict['uuid']
        response = self.post_json('/volume/connectors', pdict,
                                  headers=self.headers)
        result = self.get_json('/volume/connectors/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['connector_id'], result['connector_id'])
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warning.called)
        self.assertFalse(mock_exception.called)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(objects.VolumeConnector, 'create')
    def test_create_volume_connector_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        cdict = post_get_test_volume_connector()
        self.post_json('/volume/connectors', cdict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR,
                                      node_uuid=self.node.uuid)])

    def test_create_volume_connector_valid_extra(self):
        pdict = post_get_test_volume_connector(
            extra={'str': 'foo', 'int': 123, 'float': 0.1, 'bool': True,
                   'list': [1, 2], 'none': None, 'dict': {'cat': 'meow'}})
        self.post_json('/volume/connectors', pdict, headers=self.headers)
        result = self.get_json('/volume/connectors/%s' % pdict['uuid'],
                               headers=self.headers)
        self.assertEqual(pdict['extra'], result['extra'])

    def test_create_volume_connector_no_mandatory_field_type(self):
        pdict = post_get_test_volume_connector()
        del pdict['type']
        response = self.post_json('/volume/connectors', pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_connector_no_mandatory_field_connector_id(self):
        pdict = post_get_test_volume_connector()
        del pdict['connector_id']
        response = self.post_json('/volume/connectors', pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_connector_no_mandatory_field_node_uuid(self):
        pdict = post_get_test_volume_connector()
        del pdict['node_uuid']
        response = self.post_json('/volume/connectors', pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_connector_invalid_node_uuid_format(self):
        pdict = post_get_test_volume_connector(node_uuid=123)
        response = self.post_json('/volume/connectors', pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertIn(b'Expected a UUID but received 123.', response.body)

    def test_node_uuid_to_node_id_mapping(self):
        pdict = post_get_test_volume_connector(node_uuid=self.node['uuid'])
        self.post_json('/volume/connectors', pdict, headers=self.headers)
        # GET doesn't return the node_id it's an internal value
        connector = self.dbapi.get_volume_connector_by_uuid(pdict['uuid'])
        self.assertEqual(self.node['id'], connector.node_id)

    def test_create_volume_connector_node_uuid_not_found(self):
        pdict = post_get_test_volume_connector(
            node_uuid='1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e')
        response = self.post_json('/volume/connectors', pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_volume_connector_type_value_already_exist(self):
        connector_id = 'test-connector-id-456'
        pdict = post_get_test_volume_connector(connector_id=connector_id)
        self.post_json('/volume/connectors', pdict, headers=self.headers)
        pdict['uuid'] = uuidutils.generate_uuid()
        response = self.post_json('/volume/connectors',
                                  pdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.CONFLICT, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertIn(connector_id, response.json['error_message'])


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_volume_connector')
class TestDelete(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.connector = obj_utils.create_test_volume_connector(
            self.context, node_id=self.node.id)

        gtf = mock.patch.object(rpcapi.ConductorAPI, 'get_topic_for')
        self.mock_gtf = gtf.start()
        self.mock_gtf.return_value = 'test-topic'
        self.addCleanup(gtf.stop)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_volume_connector_byid(self, mock_notify, mock_dvc):
        self.delete('/volume/connectors/%s' % self.connector.uuid,
                    expect_errors=True, headers=self.headers)
        self.assertTrue(mock_dvc.called)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START,
                                      node_uuid=self.node.uuid),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END,
                                      node_uuid=self.node.uuid)])

    def test_delete_volume_connector_byid_invalid_api_version(self, mock_dvc):
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.delete('/volume/connectors/%s' % self.connector.uuid,
                               expect_errors=True, headers=headers)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_volume_connector_node_locked(self, mock_notify, mock_dvc):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_dvc.side_effect = exception.NodeLocked(node='fake-node',
                                                    host='fake-host')
        ret = self.delete('/volume/connectors/%s' % self.connector.uuid,
                          expect_errors=True, headers=self.headers)
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

    def test_delete_volume_connector_invalid_power_state(self, mock_dvc):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_dvc.side_effect = exception.InvalidStateRequested(
            action='volume connector deletion', node=self.node.uuid,
            state='power on')
        ret = self.delete('/volume/connectors/%s' % self.connector.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_dvc.called)
