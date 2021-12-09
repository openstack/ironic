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
Tests for the API /allocations/ methods.
"""

import datetime
from http import client as http_client
import json
from unittest import mock
from urllib import parse as urlparse

import fixtures
from keystonemiddleware import auth_token
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.api.controllers.v1 import notification_utils
from ironic.common import exception
from ironic.common import policy
from ironic.conductor import rpcapi
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as apiutils
from ironic.tests.unit.objects import utils as obj_utils


class TestListAllocations(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestListAllocations, self).setUp()
        self.node = obj_utils.create_test_node(self.context, name='node-1')

    def test_empty(self):
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual([], data['allocations'])

    def test_one(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(allocation.uuid, data['allocations'][0]["uuid"])
        self.assertEqual(allocation.name, data['allocations'][0]['name'])
        self.assertEqual({}, data['allocations'][0]["extra"])
        self.assertEqual(self.node.uuid, data['allocations'][0]["node_uuid"])
        self.assertEqual(allocation.owner, data['allocations'][0]["owner"])
        # never expose the node_id
        self.assertNotIn('node_id', data['allocations'][0])

    def test_get_one(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])
        self.assertEqual({}, data["extra"])
        self.assertEqual(self.node.uuid, data["node_uuid"])
        self.assertEqual(allocation.owner, data["owner"])
        # never expose the node_id
        self.assertNotIn('node_id', data)

    def test_get_one_with_json(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s.json' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_with_json_in_name(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      name='pg.json',
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_with_suffix(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      name='pg.1',
                                                      node_id=self.node.id)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])

    def test_get_one_custom_fields(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        fields = 'resource_class,extra'
        data = self.get_json(
            '/allocations/%s?fields=%s' % (allocation.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertCountEqual(['resource_class', 'extra', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,extra'
        for i in range(3):
            obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)

        data = self.get_json(
            '/allocations?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['allocations']))
        for allocation in data['allocations']:
            # We always append "links"
            self.assertCountEqual(['uuid', 'extra', 'links'], allocation)

    def test_get_custom_fields_invalid_fields(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/allocations/%s?fields=%s' % (allocation.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_one_invalid_api_version(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        response = self.get_json(
            '/allocations/%s' % (allocation.uuid),
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_invalid_api_version_without_check(self):
        # Invalid name, but the check happens after the microversion check.
        response = self.get_json(
            '/allocations/ba!na!na!',
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_many(self):
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context, node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(len(allocations), len(data['allocations']))

        uuids = [n['uuid'] for n in data['allocations']]
        self.assertCountEqual(allocations, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_allocation(self.context,
                                         uuid=uuid,
                                         node_id=self.node.id)
        data = self.get_json('/allocations/%s' % uuid, headers=self.headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'], bookmark=bookmark,
                                               headers=self.headers))

    def test_collection_links(self):
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations/?limit=3', headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

        next_marker = data['allocations'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        allocations = []
        for id_ in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations', headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

        next_marker = data['allocations'][-1]['uuid']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_custom_fields(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        fields = 'uuid,extra'
        allocations = []
        for i in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
            allocations.append(allocation.uuid)

        data = self.get_json(
            '/allocations?fields=%s' % fields,
            headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

        next_marker = data['allocations'][-1]['uuid']
        self.assertIn(next_marker, data['next'])
        self.assertIn('fields', data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'node_uuid'
        limit = 2
        allocations = []
        for id_ in range(3):
            allocation = obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation)

        data = self.get_json(
            '/allocations?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['allocations']))
        self.assertIn('marker=%s' % allocations[limit - 1].uuid, data['next'])

    def test_allocation_get_all_invalid_api_version(self):
        obj_utils.create_test_allocation(
            self.context, node_id=self.node.id, uuid=uuidutils.generate_uuid(),
            name='allocation_1')
        response = self.get_json('/allocations',
                                 headers={api_base.Version.string: '1.14'},
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_allocation_get_all_forbidden(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            raise exception.HTTPForbidden(resource='fake')
        mock_authorize.side_effect = mock_authorize_function

        response = self.get_json('/allocations', expect_errors=True,
                                 headers={
                                     api_base.Version.string: '1.60',
                                     'X-Project-Id': '12345'
                                 })
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_allocation_get_all_forbidden_no_project(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        response = self.get_json('/allocations', expect_errors=True,
                                 headers={
                                     api_base.Version.string: '1.59',
                                 })
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_allocation_get_all_forbid_owner_proj_mismatch(
            self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        response = self.get_json('/allocations?owner=54321',
                                 expect_errors=True,
                                 headers={
                                     api_base.Version.string: '1.60',
                                     'X-Project-Id': '12345'
                                 })
        self.assertEqual(http_client.FORBIDDEN, response.status_int)

    @mock.patch.object(policy, 'authorize', spec=True)
    def test_allocation_get_all_non_admin(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:list_all':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        allocations = []
        for id in range(5):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                owner='12345')
            allocations.append(allocation.uuid)
        for id in range(2):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid())

        data = self.get_json('/allocations', headers={
            api_base.Version.string: '1.60',
            'X-Project-Id': '12345'})
        self.assertEqual(len(allocations), len(data['allocations']))

        uuids = [n['uuid'] for n in data['allocations']]
        self.assertEqual(sorted(allocations), sorted(uuids))

    def test_sort_key(self):
        allocations = []
        for id_ in range(3):
            allocation = obj_utils.create_test_allocation(
                self.context,
                node_id=self.node.id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocations.append(allocation.uuid)
        data = self.get_json('/allocations?sort_key=uuid',
                             headers=self.headers)
        uuids = [n['uuid'] for n in data['allocations']]
        self.assertEqual(sorted(allocations), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['foo', 'extra', 'internal_info', 'properties']
        for invalid_key in invalid_keys_list:
            response = self.get_json('/allocations?sort_key=%s' % invalid_key,
                                     expect_errors=True, headers=self.headers)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def test_sort_key_allowed(self):
        allocation_uuids = []
        for id_ in range(3, 0, -1):
            allocation = obj_utils.create_test_allocation(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % id_)
            allocation_uuids.append(allocation.uuid)
        allocation_uuids.reverse()
        data = self.get_json('/allocations?sort_key=name',
                             headers=self.headers)
        data_uuids = [p['uuid'] for p in data['allocations']]
        self.assertEqual(allocation_uuids, data_uuids)

    def test_get_all_by_state(self):
        for i in range(5):
            if i < 3:
                state = 'allocating'
            else:
                state = 'active'
            obj_utils.create_test_allocation(
                self.context,
                state=state,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
        data = self.get_json("/allocations?state=allocating",
                             headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

    def test_get_all_by_owner(self):
        for i in range(5):
            if i < 3:
                owner = '12345'
            else:
                owner = '54321'
            obj_utils.create_test_allocation(
                self.context,
                owner=owner,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
        # NOTE(TheJulia): Force the cast of the action to a system
        # scoped request. System scoped is allowed to view everything,
        # where as project scoped requests are actually filtered with the
        # secure-rbac work. This was done in troubleshooting the code,
        # so may not be necessary, but filtered views are checked in
        # the RBAC testing.
        headers = self.headers
        headers['X-Roles'] = "member,reader"
        headers['OpenStack-System-Scope'] = "all"
        data = self.get_json("/allocations?owner=12345",
                             headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

    def test_get_all_by_owner_not_allowed(self):
        response = self.get_json("/allocations?owner=12345",
                                 headers={api_base.Version.string: '1.59'},
                                 expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_get_all_by_node_name(self):
        for i in range(5):
            if i < 3:
                node_id = self.node.id
            else:
                node_id = 100000 + i
                obj_utils.create_test_node(self.context, id=node_id,
                                           uuid=uuidutils.generate_uuid())
            obj_utils.create_test_allocation(
                self.context,
                node_id=node_id,
                uuid=uuidutils.generate_uuid(),
                name='allocation%s' % i)
        data = self.get_json("/allocations?node=%s" % self.node.name,
                             headers=self.headers)
        self.assertEqual(3, len(data['allocations']))

    def test_get_all_by_node_uuid(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        data = self.get_json('/allocations?node=%s' % (self.node.uuid),
                             headers=self.headers)
        self.assertEqual(1, len(data['allocations']))

    def test_get_all_by_non_existing_node(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.get_json('/allocations?node=banana',
                                 headers=self.headers, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_get_by_node_resource(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json('/nodes/%s/allocation' % self.node.uuid,
                             headers=self.headers)
        self.assertEqual(allocation.uuid, data['uuid'])
        self.assertEqual({}, data["extra"])
        self.assertEqual(self.node.uuid, data["node_uuid"])

    def test_get_by_node_resource_invalid_api_version(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.get_json(
            '/nodes/%s/allocation' % self.node.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_by_node_resource_with_fields(self):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        data = self.get_json('/nodes/%s/allocation?fields=name,extra' %
                             self.node.uuid,
                             headers=self.headers)
        self.assertNotIn('uuid', data)
        self.assertIn('name', data)
        self.assertEqual({}, data["extra"])

    def test_get_by_node_resource_and_id(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        response = self.get_json('/nodes/%s/allocation/%s' % (self.node.uuid,
                                                              allocation.uuid),
                                 headers=self.headers, expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_by_node_resource_not_existed(self):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid())
        res = self.get_json('/node/%s/allocation' % node.uuid,
                            expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_by_node_invalid_node(self):
        res = self.get_json('/node/%s/allocation' % uuidutils.generate_uuid(),
                            expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_allocation_owner_hidden_in_lower_version(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id)
        data = self.get_json(
            '/allocations/%s' % allocation.uuid,
            headers={api_base.Version.string: '1.59'})
        self.assertNotIn('owner', data)
        data = self.get_json(
            '/allocations/%s' % allocation.uuid,
            headers=self.headers)
        self.assertIn('owner', data)

    def test_allocation_owner_null_field(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id,
                                                      owner=None)
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertIsNone(data['owner'])

    def test_allocation_owner_present(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id,
                                                      owner='12345')
        data = self.get_json('/allocations/%s' % allocation.uuid,
                             headers=self.headers)
        self.assertEqual(data['owner'], '12345')

    def test_get_owner_field(self):
        allocation = obj_utils.create_test_allocation(self.context,
                                                      node_id=self.node.id,
                                                      owner='12345')
        fields = 'owner'
        response = self.get_json(
            '/allocations/%s?fields=%s' % (allocation.uuid, fields),
            headers=self.headers)
        self.assertIn('owner', response)


class TestPatch(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPatch, self).setUp()
        self.allocation = obj_utils.create_test_allocation(self.context)

    def test_update_not_allowed(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/extra/foo',
                                     'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers={api_base.Version.string: '1.56'})
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_update_not_found(self):
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/allocations/%s' % uuid,
                                   [{'path': '/name', 'value': 'b',
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_add(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/extra/foo', 'value': 'bar',
                                     'op': 'add'}], headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_int)

    def test_add_non_existent(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/foo', 'value': 'bar',
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_add_multi(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/extra/foo1', 'value': 'bar1',
                                     'op': 'add'},
                                    {'path': '/extra/foo2', 'value': 'bar2',
                                     'op': 'add'}], headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % self.allocation.uuid,
                               headers=self.headers)
        expected = {"foo1": "bar1", "foo2": "bar2"}
        self.assertEqual(expected, result['extra'])

    def test_replace_invalid_name(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/name', 'value': '[test]',
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_replace_singular(self, mock_utcnow, mock_notify):
        test_time = datetime.datetime(2000, 1, 1, 0, 0)

        mock_utcnow.return_value = test_time
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/name',
                                     'value': 'test', 'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % self.allocation.uuid,
                               headers=self.headers)
        self.assertEqual('test', result['name'])
        return_updated_at = timeutils.parse_isotime(
            result['updated_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_updated_at)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    def test_replace_name_with_none(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/name',
                                     'value': None, 'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % self.allocation.uuid,
                               headers=self.headers)
        self.assertIsNone(result['name'])

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(objects.Allocation, 'save', autospec=True)
    def test_update_error(self, mock_save, mock_notify):
        mock_save.side_effect = Exception()
        allocation = obj_utils.create_test_allocation(self.context)
        self.patch_json('/allocations/%s' % allocation.uuid, [{'path': '/name',
                        'value': 'new', 'op': 'replace'}],
                        expect_errors=True, headers=self.headers)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def test_replace_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        allocation = obj_utils.create_test_allocation(
            self.context, extra=extra, uuid=uuidutils.generate_uuid())
        new_value = 'new value'
        response = self.patch_json('/allocations/%s' % allocation.uuid,
                                   [{'path': '/extra/foo2',
                                     'value': new_value, 'op': 'replace'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % allocation.uuid,
                               headers=self.headers)

        extra["foo2"] = new_value
        self.assertEqual(extra, result['extra'])

    def test_remove_uuid(self):
        response = self.patch_json('/allocations/%s' % self.allocation.uuid,
                                   [{'path': '/uuid', 'op': 'remove'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_remove_singular(self):
        allocation = obj_utils.create_test_allocation(
            self.context, extra={'a': 'b'}, uuid=uuidutils.generate_uuid())
        response = self.patch_json('/allocations/%s' % allocation.uuid,
                                   [{'path': '/extra/a', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % allocation.uuid,
                               headers=self.headers)
        self.assertEqual(result['extra'], {})

        # Assert nothing else was changed
        self.assertEqual(allocation.uuid, result['uuid'])

    def test_remove_multi(self):
        extra = {"foo1": "bar1", "foo2": "bar2", "foo3": "bar3"}
        allocation = obj_utils.create_test_allocation(
            self.context, extra=extra, uuid=uuidutils.generate_uuid())

        # Removing one item from the collection
        response = self.patch_json('/allocations/%s' % allocation.uuid,
                                   [{'path': '/extra/foo2', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % allocation.uuid,
                               headers=self.headers)
        extra.pop("foo2")
        self.assertEqual(extra, result['extra'])

        # Removing the collection
        response = self.patch_json('/allocations/%s' % allocation.uuid,
                                   [{'path': '/extra', 'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        result = self.get_json('/allocations/%s' % allocation.uuid,
                               headers=self.headers)
        self.assertEqual({}, result['extra'])

        # Assert nothing else was changed
        self.assertEqual(allocation.uuid, result['uuid'])

    def test_remove_non_existent_property_fail(self):
        response = self.patch_json(
            '/allocations/%s' % self.allocation.uuid,
            [{'path': '/extra/non-existent', 'op': 'remove'}],
            expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])

    def test_update_owner_not_acceptable(self):
        allocation = obj_utils.create_test_allocation(
            self.context, owner='12345', uuid=uuidutils.generate_uuid())
        new_owner = '54321'
        response = self.patch_json('/allocations/%s' % allocation.uuid,
                                   [{'path': '/owner',
                                     'value': new_owner,
                                     'op': 'replace'}],
                                   expect_errors=True, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)


def _create_locally(_api, _ctx, allocation, topic):
    if 'node_id' in allocation and allocation.node_id:
        assert topic == 'node-topic', topic
    else:
        assert topic == 'some-topic', topic
    allocation.create()
    return allocation


@mock.patch.object(rpcapi.ConductorAPI, 'create_allocation', _create_locally)
class TestPost(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestPost, self).setUp()
        self.mock_get_topic = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_random_topic')
        ).mock
        self.mock_get_topic.return_value = 'some-topic'
        self.mock_get_topic_for_node = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_topic_for')
        ).mock
        self.mock_get_topic_for_node.return_value = 'node-topic'

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_create_allocation(self, mock_utcnow, mock_notify):
        adict = apiutils.allocation_post_data()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(adict['uuid'], response.json['uuid'])
        self.assertEqual('allocating', response.json['state'])
        self.assertIsNone(response.json['node_uuid'])
        self.assertEqual([], response.json['candidate_nodes'])
        self.assertEqual([], response.json['traits'])
        self.assertNotIn('node', response.json)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        self.assertIsNone(result['node_uuid'])
        self.assertEqual([], result['candidate_nodes'])
        self.assertEqual([], result['traits'])
        self.assertIsNone(result['owner'])
        self.assertNotIn('node', result)
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/allocations/%s' % adict['uuid']
        self.assertEqual(urlparse.urlparse(response.location).path,
                         expected_location)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START),
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END),
        ])

    def test_create_allocation_invalid_api_version(self):
        adict = apiutils.allocation_post_data()
        response = self.post_json(
            '/allocations', adict, headers={api_base.Version.string: '1.50'},
            expect_errors=True)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_create_allocation_doesnt_contain_id(self):
        with mock.patch.object(self.dbapi, 'create_allocation',
                               wraps=self.dbapi.create_allocation) as cp_mock:
            adict = apiutils.allocation_post_data(extra={'foo': 123})
            self.post_json('/allocations', adict, headers=self.headers)
            result = self.get_json('/allocations/%s' % adict['uuid'],
                                   headers=self.headers)
            self.assertEqual(adict['extra'], result['extra'])
            cp_mock.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', cp_mock.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_allocation_generate_uuid(self, mock_warn, mock_except):
        adict = apiutils.allocation_post_data()
        del adict['uuid']
        response = self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warn.called)
        self.assertFalse(mock_except.called)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(objects.Allocation, 'create', autospec=True)
    def test_create_allocation_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        adict = apiutils.allocation_post_data()
        self.post_json('/allocations', adict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START),
            mock.call(mock.ANY, mock.ANY, 'create',
                      obj_fields.NotificationLevel.ERROR,
                      obj_fields.NotificationStatus.ERROR),
        ])

    def test_create_allocation_with_candidate_nodes(self):
        node1 = obj_utils.create_test_node(self.context,
                                           name='node-1')
        node2 = obj_utils.create_test_node(self.context,
                                           uuid=uuidutils.generate_uuid())
        adict = apiutils.allocation_post_data(
            candidate_nodes=[node1.name, node2.uuid])
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual([node1.uuid, node2.uuid], result['candidate_nodes'])

    def test_create_allocation_valid_extra(self):
        adict = apiutils.allocation_post_data(
            extra={'str': 'foo', 'int': 123, 'float': 0.1, 'bool': True,
                   'list': [1, 2], 'none': None, 'dict': {'cat': 'meow'}})
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['extra'], result['extra'])

    def test_create_allocation_with_no_extra(self):
        adict = apiutils.allocation_post_data()
        del adict['extra']
        response = self.post_json('/allocations', adict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)

    def test_create_allocation_no_mandatory_field_resource_class(self):
        adict = apiutils.allocation_post_data()
        del adict['resource_class']
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('resource_class', response.json['error_message'])

    def test_create_allocation_resource_class_too_long(self):
        adict = apiutils.allocation_post_data()
        adict['resource_class'] = 'f' * 81
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_with_traits(self):
        adict = apiutils.allocation_post_data()
        adict['traits'] = ['CUSTOM_GPU', 'CUSTOM_FOO_BAR']
        response = self.post_json('/allocations', adict, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(['CUSTOM_GPU', 'CUSTOM_FOO_BAR'],
                         response.json['traits'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(['CUSTOM_GPU', 'CUSTOM_FOO_BAR'],
                         result['traits'])

    def test_create_allocation_invalid_trait(self):
        adict = apiutils.allocation_post_data()
        adict['traits'] = ['CUSTOM_GPU', 'FOO_BAR']
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_invalid_candidate_node_format(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['invalid-format'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_candidate_node_not_found(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['1a1a1a1a-2b2b-3c3c-4d4d-5e5e5e5e5e5e'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_candidate_node_invalid(self):
        adict = apiutils.allocation_post_data(
            candidate_nodes=['this/is/not a/node/name'])
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_name_ok(self):
        name = 'foo'
        adict = apiutils.allocation_post_data(name=name)
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(name, result['name'])

    def test_create_allocation_name_invalid(self):
        name = 'aa:bb_cc'
        adict = apiutils.allocation_post_data(name=name)
        response = self.post_json('/allocations', adict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_create_by_node_not_allowed(self):
        node = obj_utils.create_test_node(self.context)
        adict = apiutils.allocation_post_data()
        response = self.post_json('/nodes/%s/allocation' % node.uuid,
                                  adict, headers=self.headers,
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_create_node_uuid_not_allowed(self):
        node = obj_utils.create_test_node(self.context)
        adict = apiutils.allocation_post_data()
        adict['node_uuid'] = node.uuid
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_allocation_owner(self):
        owner = '12345'
        adict = apiutils.allocation_post_data(owner=owner)
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(owner, result['owner'])

    def test_create_allocation_owner_not_allowed(self):
        owner = '12345'
        adict = apiutils.allocation_post_data(owner=owner)
        response = self.post_json('/allocations', adict,
                                  headers={api_base.Version.string: '1.59'},
                                  expect_errors=True)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_ACCEPTABLE, response.status_int)

    @mock.patch.object(auth_token.AuthProtocol, 'process_request',
                       autospec=True)
    def test_create_allocation_owner_not_my_projet_id(self, mock_auth_req):
        # This is only enforced, test wise with the new oslo policy rbac
        # model and enforcement. Likely can be cleaned up past the Xena cycle.
        cfg.CONF.set_override('enforce_scope', True, group='oslo_policy')
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        # Tests normally run in noauth, but we need policy
        # enforcement to run completely here to ensure the logic is followed.
        cfg.CONF.set_override('auth_strategy', 'keystone')
        self.headers['X-Project-ID'] = '0987'
        self.headers['X-Roles'] = 'admin,member,reader'
        owner = '12345'
        adict = apiutils.allocation_post_data(owner=owner)
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        expected_faultstring = ('Cannot create allocation with an owner '
                                'Project ID value 12345 not matching the '
                                'requestor Project ID 0987. Policy '
                                'baremetal:allocation:create_restricted '
                                'is required for this capability.')
        error_body = json.loads(response.json['error_message'])
        self.assertEqual(expected_faultstring,
                         error_body.get('faultstring'))

    def test_create_allocation_owner_auto_filled(self):
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        self.headers['X-Project-ID'] = '123456'
        adict = apiutils.allocation_post_data()
        self.post_json('/allocations', adict, headers=self.headers)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual('123456', result['owner'])

    def test_backfill(self):
        node = obj_utils.create_test_node(self.context)
        adict = apiutils.allocation_post_data(node=node.uuid)
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertNotIn('node', response.json)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(node.uuid, result['node_uuid'])
        self.assertNotIn('node', result)

    def test_backfill_with_name(self):
        node = obj_utils.create_test_node(self.context, name='backfill-me')
        adict = apiutils.allocation_post_data(node=node.name)
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertNotIn('node', response.json)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=self.headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(node.uuid, result['node_uuid'])
        self.assertNotIn('node', result)

    def test_backfill_without_resource_class(self):
        node = obj_utils.create_test_node(self.context,
                                          resource_class='bm-super')
        adict = {'node': node.uuid}
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/allocations/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(node.uuid, result['node_uuid'])
        self.assertEqual('bm-super', result['resource_class'])

    def test_backfill_copy_instance_uuid(self):
        uuid = uuidutils.generate_uuid()
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid=uuid,
                                          resource_class='bm-super')
        adict = {'node': node.uuid}
        response = self.post_json('/allocations', adict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/allocations/%s' % response.json['uuid'],
                               headers=self.headers)
        self.assertEqual(uuid, result['uuid'])
        self.assertEqual(node.uuid, result['node_uuid'])
        self.assertEqual('bm-super', result['resource_class'])

    def test_backfill_node_not_found(self):
        adict = apiutils.allocation_post_data(node=uuidutils.generate_uuid())
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_backfill_not_allowed(self):
        node = obj_utils.create_test_node(self.context)
        headers = {api_base.Version.string: '1.57'}
        adict = {'node': node.uuid}
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    def test_create_restricted_allocation_normal(self):
        cfg.CONF.set_override('enforce_new_defaults', True,
                              group='oslo_policy')
        owner = '12345'
        adict = apiutils.allocation_post_data()
        headers = {api_base.Version.string: '1.60',
                   'X-Roles': 'member,reader',
                   'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(owner, response.json['owner'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(owner, result['owner'])

    def test_create_restricted_allocation_older_version(self):
        owner = '12345'
        adict = apiutils.allocation_post_data()
        del adict['owner']
        headers = {api_base.Version.string: '1.59', 'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=headers)
        self.assertEqual(adict['uuid'], result['uuid'])

    @mock.patch.object(policy, 'authorize', autospec=True)
    def test_create_restricted_allocation_forbidden(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            raise exception.HTTPForbidden(resource='fake')
        mock_authorize.side_effect = mock_authorize_function

        owner = '12345'
        adict = apiutils.allocation_post_data()
        headers = {api_base.Version.string: '1.60', 'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=headers)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])

    @mock.patch.object(policy, 'authorize', autospec=True)
    def test_create_restricted_allocation_deprecated_without_owner(
            self, mock_authorize):
        cfg.CONF.set_override('enforce_new_defaults', False,
                              group='oslo_policy')

        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:create':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        owner = '12345'
        adict = apiutils.allocation_post_data()
        headers = {api_base.Version.string: '1.60', 'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(owner, response.json['owner'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(owner, result['owner'])

    @mock.patch.object(policy, 'authorize', autospec=True)
    def test_create_restricted_allocation_with_owner(self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:create':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function
        owner = '12345'
        adict = apiutils.allocation_post_data(owner=owner)
        adict['owner'] = owner
        headers = {api_base.Version.string: '1.60', 'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, headers=headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CREATED, response.status_int)
        self.assertEqual(owner, response.json['owner'])
        result = self.get_json('/allocations/%s' % adict['uuid'],
                               headers=headers)
        self.assertEqual(adict['uuid'], result['uuid'])
        self.assertEqual(owner, result['owner'])

    @mock.patch.object(policy, 'authorize', autospec=True)
    def test_create_restricted_allocation_with_mismatch_owner(
            self, mock_authorize):
        def mock_authorize_function(rule, target, creds):
            if rule == 'baremetal:allocation:create':
                raise exception.HTTPForbidden(resource='fake')
            return True
        mock_authorize.side_effect = mock_authorize_function

        owner = '12345'
        adict = apiutils.allocation_post_data(owner=owner)
        adict['owner'] = '54321'
        headers = {api_base.Version.string: '1.60', 'X-Project-Id': owner}
        response = self.post_json('/allocations', adict, expect_errors=True,
                                  headers=headers)
        self.assertEqual(http_client.FORBIDDEN, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])


@mock.patch.object(rpcapi.ConductorAPI, 'destroy_allocation', autospec=True)
class TestDelete(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def setUp(self):
        super(TestDelete, self).setUp()
        self.node = obj_utils.create_test_node(self.context)
        self.allocation = obj_utils.create_test_allocation(
            self.context, node_id=self.node.id, name='alloc1')

        self.mock_get_topic = self.useFixture(
            fixtures.MockPatchObject(rpcapi.ConductorAPI, 'get_random_topic')
        ).mock

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_allocation_by_id(self, mock_notify, mock_destroy):
        self.delete('/allocations/%s' % self.allocation.uuid,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END,
                      node_uuid=self.node.uuid),
        ])

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_allocation_node_locked(self, mock_notify, mock_destroy):
        self.node.reserve(self.context, 'fake', self.node.uuid)
        mock_destroy.side_effect = exception.NodeLocked(node='fake-node',
                                                        host='fake-host')
        ret = self.delete('/allocations/%s' % self.allocation.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.CONFLICT, ret.status_code)
        self.assertTrue(ret.json['error_message'])
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.ERROR,
                      obj_fields.NotificationStatus.ERROR,
                      node_uuid=self.node.uuid),
        ])

    def test_delete_allocation_invalid_api_version(self, mock_destroy):
        response = self.delete('/allocations/%s' % self.allocation.uuid,
                               expect_errors=True,
                               headers={api_base.Version.string: '1.14'})
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_delete_allocation_invalid_api_version_without_check(self,
                                                                 mock_destroy):
        # Invalid name, but the check happens after the microversion check.
        response = self.delete('/allocations/ba!na!na1',
                               expect_errors=True,
                               headers={api_base.Version.string: '1.14'})
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_delete_allocation_by_name(self, mock_destroy):
        self.delete('/allocations/%s' % self.allocation.name,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)

    def test_delete_allocation_by_name_with_json(self, mock_destroy):
        self.delete('/allocations/%s.json' % self.allocation.name,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)

    def test_delete_allocation_by_name_not_existed(self, mock_destroy):
        res = self.delete('/allocations/%s' % 'blah', expect_errors=True,
                          headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_allocation_by_node(self, mock_notify, mock_destroy):
        self.delete('/nodes/%s/allocation' % self.node.uuid,
                    headers=self.headers)
        self.assertTrue(mock_destroy.called)
        mock_notify.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.START,
                      node_uuid=self.node.uuid),
            mock.call(mock.ANY, mock.ANY, 'delete',
                      obj_fields.NotificationLevel.INFO,
                      obj_fields.NotificationStatus.END,
                      node_uuid=self.node.uuid),
        ])

    def test_delete_allocation_by_node_not_existed(self, mock_destroy):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid())
        res = self.delete('/nodes/%s/allocation' % node.uuid,
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_delete_allocation_invalid_node(self, mock_destroy):
        res = self.delete('/nodes/%s/allocation' % uuidutils.generate_uuid(),
                          expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)

    def test_delete_allocation_by_node_invalid_api_version(self, mock_destroy):
        obj_utils.create_test_allocation(self.context, node_id=self.node.id)
        response = self.delete(
            '/nodes/%s/allocation' % self.node.uuid,
            headers={api_base.Version.string: str(api_v1.min_version())},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertFalse(mock_destroy.called)
