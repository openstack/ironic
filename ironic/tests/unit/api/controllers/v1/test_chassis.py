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
from ironic.api.controllers.v1 import chassis as api_chassis
from ironic.api.controllers.v1 import notification_utils
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.objects import utils as obj_utils


class TestChassisObject(base.TestCase):

    def test_chassis_init(self):
        chassis_dict = apiutils.chassis_post_data()
        del chassis_dict['description']
        chassis = api_chassis.Chassis(**chassis_dict)
        self.assertEqual(wtypes.Unset, chassis.description)

    def test_chassis_sample(self):
        expected_description = 'Sample chassis'
        sample = api_chassis.Chassis.sample(expand=False)
        self.assertEqual(expected_description, sample.as_dict()['description'])


class TestListChassis(test_api_base.BaseApiTest):

    def test_empty(self):
        data = self.get_json('/chassis')
        self.assertEqual([], data['chassis'])

    def test_one(self):
        chassis = obj_utils.create_test_chassis(self.context)
        data = self.get_json('/chassis')
        self.assertEqual(chassis.uuid, data['chassis'][0]["uuid"])
        self.assertNotIn('extra', data['chassis'][0])
        self.assertNotIn('nodes', data['chassis'][0])

    def test_get_one(self):
        chassis = obj_utils.create_test_chassis(self.context)
        data = self.get_json('/chassis/%s' % chassis['uuid'])
        self.assertEqual(chassis.uuid, data['uuid'])
        self.assertIn('extra', data)
        self.assertIn('nodes', data)

    def test_get_one_custom_fields(self):
        chassis = obj_utils.create_test_chassis(self.context)
        fields = 'extra,description'
        data = self.get_json(
            '/chassis/%s?fields=%s' % (chassis.uuid, fields),
            headers={api_base.Version.string: str(api_v1.max_version())})
        # We always append "links"
        self.assertItemsEqual(['description', 'extra', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_chassis(
                self.context, uuid=uuidutils.generate_uuid())

        data = self.get_json(
            '/chassis?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(3, len(data['chassis']))
        for ch in data['chassis']:
            # We always append "links"
            self.assertItemsEqual(['uuid', 'extra', 'links'], ch)

    def test_get_custom_fields_invalid_fields(self):
        chassis = obj_utils.create_test_chassis(self.context)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/chassis/%s?fields=%s' % (chassis.uuid, fields),
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_custom_fields_invalid_api_version(self):
        chassis = obj_utils.create_test_chassis(self.context)
        fields = 'uuid,extra'
        response = self.get_json(
            '/chassis/%s?fields=%s' % (chassis.uuid, fields),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

    def test_detail(self):
        chassis = obj_utils.create_test_chassis(self.context)
        data = self.get_json('/chassis/detail')
        self.assertEqual(chassis.uuid, data['chassis'][0]["uuid"])
        self.assertIn('extra', data['chassis'][0])
        self.assertIn('nodes', data['chassis'][0])

    def test_detail_query(self):
        chassis = obj_utils.create_test_chassis(self.context)
        data = self.get_json(
            '/chassis?detail=True',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(chassis.uuid, data['chassis'][0]["uuid"])
        self.assertIn('extra', data['chassis'][0])
        self.assertIn('nodes', data['chassis'][0])

    def test_detail_query_false(self):
        obj_utils.create_test_chassis(self.context)
        data1 = self.get_json(
            '/chassis',
            headers={api_base.Version.string: str(api_v1.max_version())})
        data2 = self.get_json(
            '/chassis?detail=False',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(data1['chassis'], data2['chassis'])

    def test_detail_using_query_and_fields(self):
        obj_utils.create_test_chassis(self.context)
        response = self.get_json(
            '/chassis?detail=True&fields=description',
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_using_query_false_and_fields(self):
        obj_utils.create_test_chassis(self.context)
        data = self.get_json(
            '/chassis?detail=False&fields=description',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertIn('description', data['chassis'][0])
        self.assertNotIn('uuid', data['chassis'][0])

    def test_detail_using_query_old_version(self):
        obj_utils.create_test_chassis(self.context)
        response = self.get_json(
            '/chassis?detail=True',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_detail_against_single(self):
        chassis = obj_utils.create_test_chassis(self.context)
        response = self.get_json('/chassis/%s/detail' % chassis['uuid'],
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_many(self):
        ch_list = []
        for id_ in range(5):
            chassis = obj_utils.create_test_chassis(
                self.context, uuid=uuidutils.generate_uuid())
            ch_list.append(chassis.uuid)
        data = self.get_json('/chassis')
        self.assertEqual(len(ch_list), len(data['chassis']))
        uuids = [n['uuid'] for n in data['chassis']]
        six.assertCountEqual(self, ch_list, uuids)

    def _test_links(self, public_url=None):
        cfg.CONF.set_override('public_endpoint', public_url, 'api')
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_chassis(self.context, uuid=uuid)
        data = self.get_json('/chassis/%s' % uuid)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for l in data['links']:
            bookmark = l['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(l['href'], bookmark=bookmark))

        if public_url is not None:
            expected = [{'href': '%s/v1/chassis/%s' % (public_url, uuid),
                         'rel': 'self'},
                        {'href': '%s/chassis/%s' % (public_url, uuid),
                         'rel': 'bookmark'}]
            for i in expected:
                self.assertIn(i, data['links'])

    def test_links(self):
        self._test_links()

    def test_links_public_url(self):
        self._test_links(public_url='http://foo')

    def test_collection_links(self):
        for id in range(5):
            obj_utils.create_test_chassis(self.context,
                                          uuid=uuidutils.generate_uuid())
        data = self.get_json('/chassis/?limit=3')
        self.assertEqual(3, len(data['chassis']))

        next_marker = data['chassis'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        for id_ in range(5):
            obj_utils.create_test_chassis(self.context,
                                          uuid=uuidutils.generate_uuid())
        data = self.get_json('/chassis')
        self.assertEqual(3, len(data['chassis']))

        next_marker = data['chassis'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'extra'
        limit = 2
        chassis_list = []
        for id_ in range(3):
            chassis = obj_utils.create_test_chassis(
                self.context,
                uuid=uuidutils.generate_uuid())
            chassis_list.append(chassis)

        data = self.get_json(
            '/chassis?fields=%s&limit=%s' % (fields, limit),
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(limit, len(data['chassis']))
        self.assertIn('marker=%s' % chassis_list[limit - 1].uuid, data['next'])

    def test_sort_key(self):
        ch_list = []
        for id_ in range(3):
            chassis = obj_utils.create_test_chassis(
                self.context, uuid=uuidutils.generate_uuid())
            ch_list.append(chassis.uuid)
        data = self.get_json('/chassis?sort_key=uuid')
        uuids = [n['uuid'] for n in data['chassis']]
        self.assertEqual(sorted(ch_list), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/chassis?sort_key=%s' % invalid_key,
                                     expect_errors=True)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def test_nodes_subresource_link(self):
        chassis = obj_utils.create_test_chassis(self.context)
        data = self.get_json('/chassis/%s' % chassis.uuid)
        self.assertIn('nodes', data)

    def test_nodes_subresource(self):
        chassis = obj_utils.create_test_chassis(self.context)

        for id_ in range(2):
            obj_utils.create_test_node(self.context,
                                       chassis_id=chassis.id,
                                       uuid=uuidutils.generate_uuid())

        data = self.get_json('/chassis/%s/nodes' % chassis.uuid)
        self.assertEqual(2, len(data['nodes']))
        self.assertNotIn('next', data)

        # Test collection pagination
        data = self.get_json('/chassis/%s/nodes?limit=1' % chassis.uuid)
        self.assertEqual(1, len(data['nodes']))
        self.assertIn('next', data)

    def test_nodes_subresource_no_uuid(self):
        response = self.get_json('/chassis/nodes', expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_nodes_subresource_chassis_not_found(self):
        non_existent_uuid = 'eeeeeeee-cccc-aaaa-bbbb-cccccccccccc'
        response = self.get_json('/chassis/%s/nodes' % non_existent_uuid,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)


class TestPatch(test_api_base.BaseApiTest):

    def setUp(self):
        super(TestPatch, self).setUp()
        obj_utils.create_test_chassis(self.context)

    def test_update_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/chassis/%s' % uuid,
                                   [{'path': '/extra/a', 'value': 'b',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(timeutils, 'utcnow')
    def test_replace_singular(self, mock_utcnow, mock_notify):
        chassis = obj_utils.get_test_chassis(self.context)
        description = 'chassis-new-description'
        test_time = datetime.datetime(2000, 1, 1, 0, 0)

        mock_utcnow.return_value = test_time
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/description',
                                     'value': description, 'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)
        self.assertEqual(description, result['description'])
        return_updated_at = timeutils.parse_isotime(
            result['updated_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_updated_at)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(objects.Chassis, 'save')
    def test_update_error(self, mock_save, mock_notify):
        mock_save.side_effect = Exception()
        chassis = obj_utils.get_test_chassis(self.context)
        self.patch_json('/chassis/%s' % chassis.uuid, [{'path': '/description',
                        'value': 'new', 'op': 'replace'}],
                        expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def test_replace_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        chassis = obj_utils.create_test_chassis(self.context, extra=extra,
                                                uuid=uuidutils.generate_uuid())
        new_value = 'new value'
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/extra/foo2',
                                     'value': new_value, 'op': 'replace'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)

        extra["foo2"] = new_value
        self.assertEqual(extra, result['extra'])

    def test_remove_singular(self):
        chassis = obj_utils.create_test_chassis(self.context, extra={'a': 'b'},
                                                uuid=uuidutils.generate_uuid())
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/description', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)
        self.assertIsNone(result['description'])

        # Assert nothing else was changed
        self.assertEqual(chassis.uuid, result['uuid'])
        self.assertEqual(chassis.extra, result['extra'])

    def test_remove_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        chassis = obj_utils.create_test_chassis(self.context, extra=extra,
                                                description="foobar",
                                                uuid=uuidutils.generate_uuid())

        # Removing one item from the collection
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/extra/foo2', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)
        extra.pop("foo2")
        self.assertEqual(extra, result['extra'])

        # Removing the collection
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/extra', 'op': 'remove'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)
        self.assertEqual({}, result['extra'])

        # Assert nothing else was changed
        self.assertEqual(chassis.uuid, result['uuid'])
        self.assertEqual(chassis.description, result['description'])

    def test_remove_non_existent_property_fail(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json(
            '/chassis/%s' % chassis.uuid,
            [{'path': '/extra/non-existent', 'op': 'remove'}],
            expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_add_root(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/description', 'value': 'test',
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_int)

    def test_add_root_non_existent(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/foo', 'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_add_multi(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/extra/foo1', 'value': 'bar1',
                                     'op': 'add'},
                                    {'path': '/extra/foo2', 'value': 'bar2',
                                     'op': 'add'}])
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/chassis/%s' % chassis.uuid)
        expected = {"foo1": "bar1", "foo2": "bar2"}
        self.assertEqual(expected, result['extra'])

    def test_patch_nodes_subresource(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json('/chassis/%s/nodes' % chassis.uuid,
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_remove_uuid(self):
        chassis = obj_utils.get_test_chassis(self.context)
        response = self.patch_json('/chassis/%s' % chassis.uuid,
                                   [{'path': '/uuid', 'op': 'remove'}],
                                   expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])


class TestPost(test_api_base.BaseApiTest):

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(timeutils, 'utcnow')
    def test_create_chassis(self, mock_utcnow, mock_notify):
        cdict = apiutils.chassis_post_data()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time

        response = self.post_json('/chassis', cdict)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(cdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/chassis/%s' % cdict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    @mock.patch.object(objects.Chassis, 'create')
    def test_create_chassis_error(self, mock_save, mock_notify):
        mock_save.side_effect = Exception()
        cdict = apiutils.chassis_post_data()
        self.post_json('/chassis', cdict, expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def test_create_chassis_doesnt_contain_id(self):
        with mock.patch.object(self.dbapi, 'create_chassis',
                               wraps=self.dbapi.create_chassis) as cc_mock:
            cdict = apiutils.chassis_post_data(extra={'foo': 123})
            self.post_json('/chassis', cdict)
            result = self.get_json('/chassis/%s' % cdict['uuid'])
            self.assertEqual(cdict['extra'], result['extra'])
            cc_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', cc_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_chassis_generate_uuid(self, mock_warning, mock_exception):
        cdict = apiutils.chassis_post_data()
        del cdict['uuid']
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis')
        self.assertEqual(cdict['description'],
                         result['chassis'][0]['description'])
        self.assertTrue(uuidutils.is_uuid_like(result['chassis'][0]['uuid']))
        self.assertFalse(mock_warning.called)
        self.assertFalse(mock_exception.called)

    def test_post_nodes_subresource(self):
        chassis = obj_utils.create_test_chassis(self.context)
        ndict = apiutils.node_post_data()
        ndict['chassis_uuid'] = chassis.uuid
        response = self.post_json('/chassis/nodes', ndict,
                                  expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    def test_create_chassis_valid_extra(self):
        cdict = apiutils.chassis_post_data(extra={'str': 'foo', 'int': 123,
                                                  'float': 0.1, 'bool': True,
                                                  'list': [1, 2], 'none': None,
                                                  'dict': {'cat': 'meow'}})
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(cdict['extra'], result['extra'])

    def test_create_chassis_unicode_description(self):
        descr = u'\u0430\u043c\u043e'
        cdict = apiutils.chassis_post_data(description=descr)
        self.post_json('/chassis', cdict)
        result = self.get_json('/chassis/%s' % cdict['uuid'])
        self.assertEqual(descr, result['description'])

    def test_create_chassis_toolong_description(self):
        descr = 'a' * 256
        valid_error_message = ('Value should have a maximum character '
                               'requirement of 255')
        cdict = apiutils.chassis_post_data(description=descr)
        response = self.post_json('/chassis', cdict, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(valid_error_message, response.json['error_message'])

    def test_create_chassis_invalid_description(self):
        descr = 1334
        valid_error_message = 'Value should be string'
        cdict = apiutils.chassis_post_data(description=descr)
        response = self.post_json('/chassis', cdict, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn(valid_error_message, response.json['error_message'])


class TestDelete(test_api_base.BaseApiTest):

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_chassis(self, mock_notify):
        chassis = obj_utils.create_test_chassis(self.context)
        self.delete('/chassis/%s' % chassis.uuid)
        response = self.get_json('/chassis/%s' % chassis.uuid,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    @mock.patch.object(notification_utils, '_emit_api_notification')
    def test_delete_chassis_with_node(self, mock_notify):
        chassis = obj_utils.create_test_chassis(self.context)
        obj_utils.create_test_node(self.context, chassis_id=chassis.id)
        response = self.delete('/chassis/%s' % chassis.uuid,
                               expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertIn(chassis.uuid, response.json['error_message'])
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def test_delete_chassis_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.delete('/chassis/%s' % uuid, expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_delete_nodes_subresource(self):
        chassis = obj_utils.create_test_chassis(self.context)
        response = self.delete('/chassis/%s/nodes' % chassis.uuid,
                               expect_errors=True)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
