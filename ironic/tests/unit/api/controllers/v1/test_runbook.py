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
Tests for the API /runbooks/ methods.
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
from ironic.common import exception
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.api import utils as test_api_utils
from ironic.tests.unit.objects import utils as obj_utils


def _obj_to_api_step(obj_step):
    """Convert a runbook step in 'object' form to one in 'API' form."""
    return {
        'interface': obj_step['interface'],
        'step': obj_step['step'],
        'args': obj_step['args'],
        'order': obj_step['order'],
    }


class BaseRunbooksAPITest(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}
    invalid_version_headers = {api_base.Version.string: '1.91'}


class TestListRunbooks(BaseRunbooksAPITest):

    def test_empty(self):
        data = self.get_json('/runbooks', headers=self.headers)
        self.assertEqual([], data['runbooks'])

    def test_one(self):
        runbook = obj_utils.create_test_runbook(self.context)
        data = self.get_json('/runbooks', headers=self.headers)
        self.assertEqual(1, len(data['runbooks']))
        self.assertEqual(runbook.uuid, data['runbooks'][0]['uuid'])
        self.assertEqual(runbook.name, data['runbooks'][0]['name'])
        self.assertNotIn('steps', data['runbooks'][0])
        self.assertNotIn('extra', data['runbooks'][0])

    def test_get_one(self):
        runbook = obj_utils.create_test_runbook(self.context)
        data = self.get_json('/runbooks/%s' % runbook.uuid,
                             headers=self.headers)
        self.assertEqual(runbook.uuid, data['uuid'])
        self.assertEqual(runbook.name, data['name'])
        self.assertEqual(runbook.extra, data['extra'])
        for t_dict_step, t_step in zip(data['steps'], runbook.steps):
            self.assertEqual(t_dict_step['interface'], t_step['interface'])
            self.assertEqual(t_dict_step['step'], t_step['step'])
            self.assertEqual(t_dict_step['args'], t_step['args'])
            self.assertEqual(t_dict_step['order'], t_step['order'])

    def test_get_one_custom_fields(self):
        runbook = obj_utils.create_test_runbook(self.context)
        fields = 'name,steps'
        data = self.get_json(
            '/runbooks/%s?fields=%s' % (runbook.uuid, fields),
            headers=self.headers)
        # We always append "links"
        self.assertCountEqual(['name', 'steps', 'links'], data)

    def test_get_collection_custom_fields(self):
        fields = 'uuid,steps'
        for i in range(3):
            obj_utils.create_test_runbook(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % i)

        data = self.get_json(
            '/runbooks?fields=%s' % fields,
            headers=self.headers)

        self.assertEqual(3, len(data['runbooks']))
        for runbook in data['runbooks']:
            # We always append "links"
            self.assertCountEqual(['uuid', 'steps', 'links'], runbook)

    def test_get_custom_fields_invalid_fields(self):
        runbook = obj_utils.create_test_runbook(self.context)
        fields = 'uuid,spongebob'
        response = self.get_json(
            '/runbooks/%s?fields=%s' % (runbook.uuid, fields),
            headers=self.headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def test_get_all_invalid_api_version(self):
        obj_utils.create_test_runbook(self.context)
        response = self.get_json('/runbooks',
                                 headers=self.invalid_version_headers,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_invalid_api_version(self):
        runbook = obj_utils.create_test_runbook(self.context)
        response = self.get_json(
            '/runbooks/%s' % (runbook.uuid),
            headers=self.invalid_version_headers,
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_detail_query(self):
        runbook = obj_utils.create_test_runbook(self.context)
        data = self.get_json('/runbooks?detail=True',
                             headers=self.headers)
        self.assertEqual(runbook.uuid, data['runbooks'][0]['uuid'])
        self.assertIn('name', data['runbooks'][0])
        self.assertIn('steps', data['runbooks'][0])
        self.assertIn('extra', data['runbooks'][0])

    def test_detail_query_false(self):
        obj_utils.create_test_runbook(self.context)
        data1 = self.get_json('/runbooks', headers=self.headers)
        data2 = self.get_json(
            '/runbooks?detail=False', headers=self.headers)
        self.assertEqual(data1['runbooks'], data2['runbooks'])

    def test_detail_using_query_false_and_fields(self):
        obj_utils.create_test_runbook(self.context)
        data = self.get_json(
            '/runbooks?detail=False&fields=steps',
            headers=self.headers)
        self.assertIn('steps', data['runbooks'][0])
        self.assertNotIn('uuid', data['runbooks'][0])
        self.assertNotIn('extra', data['runbooks'][0])

    def test_detail_using_query_and_fields(self):
        obj_utils.create_test_runbook(self.context)
        response = self.get_json(
            '/runbooks?detail=True&fields=name', headers=self.headers,
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_many(self):
        templates = []
        for id_ in range(5):
            runbook = obj_utils.create_test_runbook(
                self.context, uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            templates.append(runbook.uuid)
        data = self.get_json('/runbooks', headers=self.headers)
        self.assertEqual(len(templates), len(data['runbooks']))

        uuids = [n['uuid'] for n in data['runbooks']]
        self.assertCountEqual(templates, uuids)

    def test_links(self):
        uuid = uuidutils.generate_uuid()
        obj_utils.create_test_runbook(self.context, uuid=uuid)
        data = self.get_json('/runbooks/%s' % uuid,
                             headers=self.headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn(uuid, data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'], bookmark=bookmark,
                            headers=self.headers))

    def test_collection_links(self):
        templates = []
        for id_ in range(5):
            runbook = obj_utils.create_test_runbook(
                self.context, uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            templates.append(runbook.uuid)
        data = self.get_json('/runbooks/?limit=3',
                             headers=self.headers)
        self.assertEqual(3, len(data['runbooks']))

        next_marker = data['runbooks'][-1]['uuid']
        self.assertIn('/runbooks', data['next'])
        self.assertIn('limit=3', data['next'])
        self.assertIn(f'marker={next_marker}', data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        templates = []
        for id_ in range(5):
            runbook = obj_utils.create_test_runbook(
                self.context, uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            templates.append(runbook.uuid)
        data = self.get_json('/runbooks', headers=self.headers)
        self.assertEqual(3, len(data['runbooks']))

        next_marker = data['runbooks'][-1]['uuid']
        self.assertIn('/runbooks', data['next'])
        self.assertIn(f'marker={next_marker}', data['next'])

    def test_collection_links_custom_fields(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        templates = []
        fields = 'uuid,steps'
        for i in range(5):
            runbook = obj_utils.create_test_runbook(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % i)
            templates.append(runbook.uuid)
        data = self.get_json('/runbooks?fields=%s' % fields,
                             headers=self.headers)
        self.assertEqual(3, len(data['runbooks']))
        next_marker = data['runbooks'][-1]['uuid']
        self.assertIn('/runbooks', data['next'])
        self.assertIn(f'marker={next_marker}', data['next'])
        self.assertIn(f'fields={fields}', data['next'])

    def test_get_collection_pagination_no_uuid(self):
        fields = 'name'
        limit = 2
        templates = []
        for id_ in range(3):
            runbook = obj_utils.create_test_runbook(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            templates.append(runbook)

        data = self.get_json(
            '/runbooks?fields=%s&limit=%s' % (fields, limit),
            headers=self.headers)

        self.assertEqual(limit, len(data['runbooks']))
        self.assertIn('/runbooks', data['next'])
        self.assertIn('marker=%s' % templates[limit - 1].uuid, data['next'])

    def test_sort_key(self):
        templates = []
        for id_ in range(3):
            runbook = obj_utils.create_test_runbook(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            templates.append(runbook.uuid)
        data = self.get_json('/runbooks?sort_key=uuid',
                             headers=self.headers)
        uuids = [n['uuid'] for n in data['runbooks']]
        self.assertEqual(sorted(templates), uuids)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['extra', 'foo', 'steps']
        for invalid_key in invalid_keys_list:
            path = '/runbooks?sort_key=%s' % invalid_key
            response = self.get_json(path, expect_errors=True,
                                     headers=self.headers)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])

    def _test_sort_key_allowed(self, detail=False):
        template_uuids = []
        for id_ in range(3, 0, -1):
            runbook = obj_utils.create_test_runbook(
                self.context,
                uuid=uuidutils.generate_uuid(),
                name='CUSTOM_DT%s' % id_)
            template_uuids.append(runbook.uuid)
        template_uuids.reverse()
        url = '/runbooks?sort_key=name&detail=%s' % str(detail)
        data = self.get_json(url, headers=self.headers)
        data_uuids = [p['uuid'] for p in data['runbooks']]
        self.assertEqual(template_uuids, data_uuids)

    def test_sort_key_allowed(self):
        self._test_sort_key_allowed()

    def test_detail_sort_key_allowed(self):
        self._test_sort_key_allowed(detail=True)

    def test_sensitive_data_masked(self):
        runbook = obj_utils.get_test_runbook(self.context)
        runbook.steps[0]['args']['password'] = 'correcthorsebatterystaple'
        runbook.create()
        data = self.get_json('/runbooks/%s' % runbook.uuid,
                             headers=self.headers)

        self.assertEqual("******", data['steps'][0]['args']['password'])


@mock.patch.object(objects.Runbook, 'save', autospec=True)
class TestPatch(BaseRunbooksAPITest):

    def setUp(self):
        super(TestPatch, self).setUp()
        self.runbook = obj_utils.create_test_runbook(
            self.context, name='CUSTOM_DT1')

    def _test_update_ok(self, mock_save, patch):
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        mock_save.assert_called_once_with(mock.ANY)
        return response

    def _test_update_bad_request(self, mock_save, patch, error_msg=None):
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch, expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.BAD_REQUEST, response.status_code)
        self.assertTrue(response.json['error_message'])
        if error_msg:
            self.assertIn(error_msg, response.json['error_message'])
        self.assertFalse(mock_save.called)
        return response

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_update_by_id(self, mock_notify, mock_save):
        name = 'CUSTOM_DT2'
        patch = [{'path': '/name', 'value': name, 'op': 'add'}]
        response = self._test_update_ok(mock_save, patch)
        self.assertEqual(name, response.json['name'])

        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    def test_update_by_name(self, mock_save):
        steps = [{
            'interface': 'bios',
            'step': 'apply_configuration',
            'args': {'foo': 'bar'},
            'order': 1
        }]
        patch = [{'path': '/steps', 'value': steps, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % self.runbook.name,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        mock_save.assert_called_once_with(mock.ANY)
        self.assertEqual(steps, response.json['steps'])

    def test_update_name_standard_trait(self, mock_save):
        name = 'HW_CPU_X86_VMX'
        patch = [{'path': '/name', 'value': name, 'op': 'replace'}]
        response = self._test_update_ok(mock_save, patch)
        self.assertEqual(name, response.json['name'])

    def test_update_by_id_invalid_api_version(self, mock_save):
        name = 'CUSTOM_DT2'
        headers = self.invalid_version_headers
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   [{'path': '/name',
                                     'value': name,
                                     'op': 'add'}],
                                   headers=headers,
                                   expect_errors=True)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)
        self.assertFalse(mock_save.called)

    def test_update_by_name_old_api_version(self, mock_save):
        name = 'CUSTOM_DT2'
        response = self.patch_json('/runbooks/%s' % self.runbook.name,
                                   [{'path': '/name',
                                     'value': name,
                                     'op': 'add'}],
                                   expect_errors=True)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)
        self.assertFalse(mock_save.called)

    def test_update_not_found(self, mock_save):
        name = 'CUSTOM_DT2'
        uuid = uuidutils.generate_uuid()
        response = self.patch_json('/runbooks/%s' % uuid,
                                   [{'path': '/name',
                                     'value': name,
                                     'op': 'add'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
        self.assertTrue(response.json['error_message'])
        self.assertFalse(mock_save.called)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_replace_name_already_exist(self, mock_notify, mock_save):
        name = 'CUSTOM_DT2'
        obj_utils.create_test_runbook(self.context,
                                      uuid=uuidutils.generate_uuid(),
                                      name=name)
        mock_save.side_effect = exception.RunbookAlreadyExists(
            uuid=self.runbook.uuid)
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   [{'path': '/name',
                                     'value': name,
                                     'op': 'replace'}],
                                   expect_errors=True,
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.CONFLICT, response.status_code)
        self.assertTrue(response.json['error_message'])
        mock_save.assert_called_once_with(mock.ANY)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'update',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def test_replace_invalid_name_too_long(self, mock_save):
        name = 'CUSTOM_' + 'X' * 249
        patch = [{'path': '/name', 'op': 'replace', 'value': name}]
        self._test_update_bad_request(
            mock_save, patch, "'%s' is too long" % name)

    def test_replace_invalid_name_none(self, mock_save):
        patch = [{'path': '/name', 'op': 'replace', 'value': None}]
        self._test_update_bad_request(
            mock_save, patch, "None is not of type 'string'")

    def test_replace_duplicate_step(self, mock_save):
        # interface & step combination must be unique.
        steps = [
            {
                'interface': 'raid',
                'step': 'create_configuration',
                'args': {'foo': '%d' % i},
                'order': i,
            }
            for i in range(2)
        ]
        patch = [{'path': '/steps', 'op': 'replace', 'value': steps}]
        self._test_update_bad_request(
            mock_save, patch, "Duplicate deploy steps")

    def test_replace_invalid_step_interface_fail(self, mock_save):
        step = {
            'interface': 'foo',
            'step': 'apply_configuration',
            'args': {'foo': 'bar'},
            'order': 1
        }
        patch = [{'path': '/steps/0', 'op': 'replace', 'value': step}]
        self._test_update_bad_request(
            mock_save, patch, "'foo' is not one of")

    def test_replace_non_existent_step_fail(self, mock_save):
        step = {
            'interface': 'bios',
            'step': 'apply_configuration',
            'args': {'foo': 'bar'},
            'order': 1
        }
        patch = [{'path': '/steps/1', 'op': 'replace', 'value': step}]
        self._test_update_bad_request(mock_save, patch)

    def test_replace_empty_step_list_fail(self, mock_save):
        patch = [{'path': '/steps', 'op': 'replace', 'value': []}]
        try:
            self._test_update_bad_request(
                mock_save, patch, "[] is too short")
        except Exception:
            self._test_update_bad_request(
                mock_save, patch, "[] should be non-empty")

    def _test_remove_not_allowed(self, mock_save, field, error_msg=None):
        patch = [{'path': '/%s' % field, 'op': 'remove'}]
        self._test_update_bad_request(mock_save, patch, error_msg)

    def test_remove_uuid(self, mock_save):
        self._test_remove_not_allowed(
            mock_save, 'uuid',
            "Cannot patch /uuid")

    def test_remove_name(self, mock_save):
        self._test_remove_not_allowed(
            mock_save, 'name',
            "'name' is a required property")

    def test_remove_steps(self, mock_save):
        self._test_remove_not_allowed(
            mock_save, 'steps',
            "'steps' is a required property")

    def test_remove_foo(self, mock_save):
        self._test_remove_not_allowed(mock_save, 'foo')

    def test_replace_step_invalid_interface(self, mock_save):
        patch = [{'path': '/steps/0/interface', 'op': 'replace',
                  'value': 'foo'}]
        self._test_update_bad_request(
            mock_save, patch, "'foo' is not one of")

    def test_replace_multi(self, mock_save):
        steps = [
            {
                'interface': 'raid',
                'step': 'create_configuration%d' % i,
                'args': {},
                'order': 2,
            }
            for i in range(3)
        ]
        runbook = obj_utils.create_test_runbook(
            self.context, uuid=uuidutils.generate_uuid(), name='CUSTOM_DT2',
            steps=steps)

        # mutate steps so we replace all of them
        for step in steps:
            step['order'] = step['order'] + 1

        patch = []
        for i, step in enumerate(steps):
            patch.append({'path': '/steps/%s' % i,
                          'value': step,
                          'op': 'replace'})
        response = self.patch_json('/runbooks/%s' % runbook.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(steps, response.json['steps'])
        mock_save.assert_called_once_with(mock.ANY)

    def test_remove_multi(self, mock_save):
        steps = [
            {
                'interface': 'raid',
                'step': 'create_configuration%d' % i,
                'args': {},
                'order': 2,
            }
            for i in range(3)
        ]
        runbook = obj_utils.create_test_runbook(
            self.context, uuid=uuidutils.generate_uuid(), name='CUSTOM_DT2',
            steps=steps)

        # Removing one step from the collection
        steps.pop(1)
        response = self.patch_json('/runbooks/%s' % runbook.uuid,
                                   [{'path': '/steps/1',
                                     'op': 'remove'}],
                                   headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(steps, response.json['steps'])
        mock_save.assert_called_once_with(mock.ANY)

    def test_remove_non_existent_property_fail(self, mock_save):
        patch = [{'path': '/non-existent', 'op': 'remove'}]
        self._test_update_bad_request(mock_save, patch)

    def test_remove_non_existent_step_fail(self, mock_save):
        patch = [{'path': '/steps/1', 'op': 'remove'}]
        self._test_update_bad_request(mock_save, patch)

    def test_remove_only_step_fail(self, mock_save):
        patch = [{'path': '/steps/0', 'op': 'remove'}]
        try:
            self._test_update_bad_request(
                mock_save, patch, "[] is too short")
        except Exception:
            self._test_update_bad_request(
                mock_save, patch, "[] should be non-empty")

    def test_remove_non_existent_step_property_fail(self, mock_save):
        patch = [{'path': '/steps/0/non-existent', 'op': 'remove'}]
        self._test_update_bad_request(mock_save, patch)

    def test_add_root_non_existent(self, mock_save):
        patch = [{'path': '/foo', 'value': 'bar', 'op': 'add'}]
        self._test_update_bad_request(
            mock_save, patch,
            "Cannot patch /foo")

    def test_add_too_high_index_step_fail(self, mock_save):
        step = {
            'interface': 'bios',
            'step': 'apply_configuration',
            'args': {'foo': 'bar'},
            'order': 1
        }
        patch = [{'path': '/steps/2', 'op': 'add', 'value': step}]
        self._test_update_bad_request(mock_save, patch)

    def test_add_multi(self, mock_save):
        steps = [
            {
                'interface': 'raid',
                'step': 'create_configuration%d' % i,
                'args': {},
                'order': 2,
            }
            for i in range(3)
        ]
        patch = []
        for i, step in enumerate(steps):
            patch.append({'path': '/steps/%d' % i,
                          'value': step,
                          'op': 'add'})
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch, headers=self.headers)
        self.assertEqual('application/json', response.content_type)
        self.assertEqual(http_client.OK, response.status_code)
        self.assertEqual(steps, response.json['steps'][:-1])
        self.assertEqual(_obj_to_api_step(self.runbook.steps[0]),
                         response.json['steps'][-1])
        mock_save.assert_called_once_with(mock.ANY)

    def test_update_project_scope(self, mock_save):
        patch = [{'path': '/name', 'value': 'CUSTOM_NAME', 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch,
                                   headers={api_base.Version.string:
                                            str(api_v1.max_version()),
                                            'X-Project-Id': 'projectX'})

        self.assertEqual(http_client.OK, response.status_code)

    def test_update_system_scope(self, mock_save):
        patch = [{'path': '/name', 'value': 'CUSTOM_NAME', 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch,
                                   headers={api_base.Version.string:
                                            str(api_v1.max_version()),
                                            'OpenStack-System-Scope': 'all',
                                            'X-Roles': 'admin'})

        self.assertEqual(http_client.OK, response.status_code)

    def test_set_public_system_scope(self, mock_save):
        patch = [{'path': '/public', 'value': True, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % self.runbook.uuid,
                                   patch,
                                   headers={api_base.Version.string:
                                            str(api_v1.max_version()),
                                            'OpenStack-System-Scope': 'all',
                                            'X-Roles': 'admin'})

        self.assertTrue(response.json['public'])
        self.assertIsNone(response.json['owner'])

    def test_set_project_owned_runbook_public(self, mock_save):
        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        runbook = self.post_json('/runbooks', tdict,
                                 headers={api_base.Version.string:
                                          str(api_v1.max_version()),
                                          'X-Project-Id': 'projectX'})
        self.assertEqual(http_client.CREATED, runbook.status_int)
        self.assertEqual('projectX', runbook.json['owner'])

        patch = [{'path': '/public', 'value': True, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch,
                                   headers={api_base.Version.string:
                                            str(api_v1.max_version()),
                                            'OpenStack-System-Scope': 'all',
                                            'X-Roles': 'admin'})

        self.assertTrue(response.json['public'])
        self.assertIsNone(response.json['owner'])

    def test_unset_public_system_scope(self, mock_save):
        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}

        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE2')
        tdict['public'] = True
        runbook = self.post_json('/runbooks', tdict, headers=headers)
        self.assertEqual(http_client.CREATED, runbook.status_int)

        patch = [{'path': '/public', 'value': False, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers)
        self.assertFalse(response.json['public'])
        self.assertIsNone(response.json['owner'])

    def test_set_owner_system_scope(self, mock_save):
        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}

        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        runbook = self.post_json('/runbooks', tdict, headers=self.headers)
        self.assertEqual(http_client.CREATED, runbook.status_int)

        new_owner = 'projectX'
        patch = [{'path': '/owner', 'value': new_owner, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers)
        self.assertEqual(new_owner, response.json['owner'])

    def test_set_new_owner_for_project_owned_runbook(self, mock_save):
        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        runbook = self.post_json('/runbooks', tdict,
                                 headers={api_base.Version.string:
                                          str(api_v1.max_version()),
                                          'X-Project-Id': 'projectX'})
        self.assertEqual(http_client.CREATED, runbook.status_int)
        self.assertEqual('projectX', runbook.json['owner'])

        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}
        new_owner = 'projectY'
        patch = [{'path': '/owner', 'value': new_owner, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers)
        self.assertEqual(new_owner, response.json['owner'])

    def test_set_owner_system_scope_fails_if_public(self, mock_save):
        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}

        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        tdict['public'] = True
        runbook = self.post_json('/runbooks', tdict, headers=headers)
        self.assertEqual(http_client.CREATED, runbook.status_int)

        new_owner = 'projectX'
        patch = [{'path': '/owner', 'value': new_owner, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_runbook_set_owner_public_system_scope(self, mock_save):
        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}

        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        tdict['public'] = True
        runbook = self.post_json('/runbooks', tdict, headers=headers)
        self.assertEqual(http_client.CREATED, runbook.status_int)
        self.assertTrue(runbook.json['public'])

        new_owner = 'projectX'
        patch = [{'path': '/owner', 'value': new_owner, 'op': 'replace'},
                 {'path': '/public', 'value': False, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers)

        self.assertFalse(response.json['public'])
        self.assertEqual(new_owner, response.json['owner'])

    def test_runbook_set_owner_public_system_scope_fails(self, mock_save):
        headers = {api_base.Version.string: str(api_v1.max_version()),
                   'OpenStack-System-Scope': 'all',
                   'X-Roles': 'admin'}

        tdict = test_api_utils.post_get_test_runbook(name='CUSTOM_UNIQUE1')
        tdict['public'] = True
        runbook = self.post_json('/runbooks', tdict, headers=headers)
        self.assertEqual(http_client.CREATED, runbook.status_int)
        self.assertTrue(runbook.json['public'])

        new_owner = 'projectX'
        patch = [{'path': '/owner', 'value': new_owner, 'op': 'replace'},
                 {'path': '/public', 'value': True, 'op': 'replace'}]
        response = self.patch_json('/runbooks/%s' % runbook.json['uuid'],
                                   patch, headers=headers, expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)


class TestPost(BaseRunbooksAPITest):

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_create(self, mock_utcnow, mock_notify):
        tdict = test_api_utils.post_get_test_runbook()
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        response = self.post_json('/runbooks', tdict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/runbooks/%s' % tdict['uuid'],
                               headers=self.headers)
        self.assertEqual(tdict['uuid'], result['uuid'])
        self.assertFalse(result['updated_at'])
        return_created_at = timeutils.parse_isotime(
            result['created_at']).replace(tzinfo=None)
        self.assertEqual(test_time, return_created_at)
        # Check location header
        self.assertIsNotNone(response.location)
        expected_location = '/v1/runbooks/%s' % tdict['uuid']
        self.assertEqual(expected_location,
                         urlparse.urlparse(response.location).path)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    def test_create_invalid_api_version(self):
        tdict = test_api_utils.post_get_test_runbook()
        response = self.post_json(
            '/runbooks', tdict, headers=self.invalid_version_headers,
            expect_errors=True)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_create_doesnt_contain_id(self):
        with mock.patch.object(
                self.dbapi, 'create_runbook',
                wraps=self.dbapi.create_runbook) as mock_create:
            tdict = test_api_utils.post_get_test_runbook()
            self.post_json('/runbooks', tdict, headers=self.headers)
            self.get_json('/runbooks/%s' % tdict['uuid'],
                          headers=self.headers)
            mock_create.assert_called_once_with(mock.ANY)
            # Check that 'id' is not in first arg of positional args
            self.assertNotIn('id', mock_create.call_args[0][0])

    @mock.patch.object(notification_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(notification_utils.LOG, 'warning', autospec=True)
    def test_create_generate_uuid(self, mock_warn, mock_except):
        tdict = test_api_utils.post_get_test_runbook()
        del tdict['uuid']
        response = self.post_json('/runbooks', tdict,
                                  headers=self.headers)
        result = self.get_json('/runbooks/%s' % response.json['uuid'],
                               headers=self.headers)
        print(mock_warn.call_args)
        self.assertTrue(uuidutils.is_uuid_like(result['uuid']))
        self.assertFalse(mock_warn.called)
        self.assertFalse(mock_except.called)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    @mock.patch.object(objects.Runbook, 'create', autospec=True)
    def test_create_error(self, mock_create, mock_notify):
        mock_create.side_effect = Exception()
        tdict = test_api_utils.post_get_test_runbook()
        self.post_json('/runbooks', tdict, headers=self.headers,
                       expect_errors=True)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'create',
                                      obj_fields.NotificationLevel.ERROR,
                                      obj_fields.NotificationStatus.ERROR)])

    def _test_create_ok(self, tdict):
        response = self.post_json('/runbooks', tdict,
                                  headers=self.headers)
        self.assertEqual(http_client.CREATED, response.status_int)

    def _test_create_bad_request(self, tdict, error_msg):
        response = self.post_json('/runbooks', tdict,
                                  expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertTrue(response.json['error_message'])
        self.assertIn(error_msg, response.json['error_message'])

    def test_create_long_name(self):
        name = 'CUSTOM_' + 'X' * 248
        tdict = test_api_utils.post_get_test_runbook(name=name)
        self._test_create_ok(tdict)

    def test_create_standard_trait_name(self):
        name = 'HW_CPU_X86_VMX'
        tdict = test_api_utils.post_get_test_runbook(name=name)
        self._test_create_ok(tdict)

    def test_create_name_invalid_too_long(self):
        name = 'CUSTOM_' + 'X' * 249
        tdict = test_api_utils.post_get_test_runbook(name=name)
        self._test_create_bad_request(
            tdict, "'%s' is too long" % name)

    def test_create_steps_invalid_duplicate(self):
        steps = [
            {
                'interface': 'raid',
                'step': 'create_configuration',
                'args': {'foo': '%d' % i},
                'order': i,
            }
            for i in range(2)
        ]
        tdict = test_api_utils.post_get_test_runbook(steps=steps)
        self._test_create_bad_request(tdict, "Duplicate deploy steps")

    def _test_create_no_mandatory_field(self, field):
        tdict = test_api_utils.post_get_test_runbook()
        del tdict[field]
        self._test_create_bad_request(tdict, "is a required property")

    def test_create_no_mandatory_field_name(self):
        self._test_create_no_mandatory_field('name')

    def test_create_no_mandatory_field_steps(self):
        self._test_create_no_mandatory_field('steps')

    def _test_create_no_mandatory_step_field(self, field):
        tdict = test_api_utils.post_get_test_runbook()
        del tdict['steps'][0][field]
        self._test_create_bad_request(tdict, "is a required property")

    def test_create_no_mandatory_step_field_interface(self):
        self._test_create_no_mandatory_step_field('interface')

    def test_create_no_mandatory_step_field_step(self):
        self._test_create_no_mandatory_step_field('step')

    def test_create_no_mandatory_step_field_order(self):
        self._test_create_no_mandatory_step_field('order')

    def _test_create_invalid_field(self, field, value, error_msg):
        tdict = test_api_utils.post_get_test_runbook()
        tdict[field] = value
        self._test_create_bad_request(tdict, error_msg)

    def test_create_invalid_field_name(self):
        self._test_create_invalid_field(
            'name', 1, "1 is not of type 'string'")

    def test_create_invalid_field_name_none(self):
        self._test_create_invalid_field(
            'name', None, "None is not of type 'string'")

    def test_create_invalid_field_steps(self):
        self._test_create_invalid_field(
            'steps', {}, "{} is not of type 'array'")

    def test_create_invalid_field_empty_steps(self):
        try:
            self._test_create_invalid_field(
                'steps', [], "[] is too short")
        except Exception:
            self._test_create_invalid_field(
                'steps', [], "[] should be non-empty")

    def test_create_invalid_field_extra(self):
        self._test_create_invalid_field(
            'extra', 1, "1 is not of type 'object'")

    def test_create_invalid_field_foo(self):
        self._test_create_invalid_field(
            'foo', 'bar',
            "Additional properties are not allowed ('foo' was unexpected)")

    def _test_create_invalid_step_field(self, field, value, error_msg=None):
        tdict = test_api_utils.post_get_test_runbook()
        tdict['steps'][0][field] = value
        if error_msg is None:
            error_msg = "Deploy runbook invalid: "
        self._test_create_bad_request(tdict, error_msg)

    def test_create_invalid_step_field_interface1(self):
        self._test_create_invalid_step_field(
            'interface', [3], "[3] is not of type 'string'")

    def test_create_invalid_step_field_interface2(self):
        self._test_create_invalid_step_field(
            'interface', 'foo', "'foo' is not one of")

    def test_create_invalid_step_field_step(self):
        self._test_create_invalid_step_field(
            'step', 1, "1 is not of type 'string'")

    def test_create_invalid_step_field_args1(self):
        self._test_create_invalid_step_field(
            'args', 'not a dict', "'not a dict' is not of type 'object'")

    def test_create_invalid_step_field_args2(self):
        self._test_create_invalid_step_field(
            'args', [], "[] is not of type 'object'")

    def test_create_invalid_step_field_order(self):
        self._test_create_invalid_step_field(
            'order', 'not a number',
            "'not a number'")  # differs between jsonschema versions

    def test_create_invalid_step_field_negative_order(self):
        self._test_create_invalid_step_field(
            'order', -1, "-1 is less than the minimum of 0")

    def test_create_invalid_step_field_foo(self):
        self._test_create_invalid_step_field(
            'foo', 'bar',
            "Additional properties are not allowed ('foo' was unexpected)")

    def test_create_step_string_order(self):
        tdict = test_api_utils.post_get_test_runbook()
        tdict['steps'][0]['order'] = '1'
        self._test_create_ok(tdict)

    def test_create_complex_step_args(self):
        tdict = test_api_utils.post_get_test_runbook()
        tdict['steps'][0]['args'] = {'foo': [{'bar': 'baz'}]}
        self._test_create_ok(tdict)

    def test_create_runbook_system_scope(self):
        tdict = test_api_utils.post_get_test_runbook()
        response = self.post_json('/runbooks', tdict,
                                  headers={api_base.Version.string:
                                           str(api_v1.max_version()),
                                           'OpenStack-System-Scope': 'all',
                                           'X-Roles': 'admin'})
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/runbooks/%s' % tdict['uuid'],
                               headers={api_base.Version.string:
                                        str(api_v1.max_version())})
        self.assertIsNone(result['owner'])
        self.assertFalse(result['public'])

    def test_create_runbook_owner_system_scope(self):
        ndict = test_api_utils.post_get_test_runbook(owner='catsay')
        response = self.post_json('/runbooks', ndict,
                                  headers={api_base.Version.string:
                                           str(api_v1.max_version()),
                                           'OpenStack-System-Scope': 'all',
                                           'X-Roles': 'admin'})
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/runbooks/%s' % ndict['uuid'],
                               headers={api_base.Version.string:
                                        str(api_v1.max_version())})
        self.assertEqual('catsay', result['owner'])

    def test_create_runbook_project_scope(self):
        tdict = test_api_utils.post_get_test_runbook()
        response = self.post_json('/runbooks', tdict,
                                  headers={api_base.Version.string:
                                           str(api_v1.max_version()),
                                           'X-Project-Id': 'projectX'})
        self.assertEqual(http_client.CREATED, response.status_int)
        result = self.get_json('/runbooks/%s' % tdict['uuid'],
                               headers={api_base.Version.string:
                                        str(api_v1.max_version())})
        self.assertEqual(result['owner'], 'projectX')
        self.assertFalse(result['public'])

    def test_create_runbook_owner_project_scope_fails(self):
        """In project scope, owner has to match the requester's project."""
        ndict = test_api_utils.post_get_test_runbook(owner='catsay')
        response = self.post_json('/runbooks', ndict,
                                  headers={api_base.Version.string:
                                           str(api_v1.max_version()),
                                           'X-Project-Id': 'projectX'},
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)

    def test_create_public_runbook_project_scope_fails(self):
        """A runbook cannot be public in project scope."""
        ndict = test_api_utils.post_get_test_runbook(owner='catsay',
                                                     public=True)
        response = self.post_json('/runbooks', ndict,
                                  headers={api_base.Version.string:
                                           str(api_v1.max_version()),
                                           'X-Project-Id': 'projectX'},
                                  expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)


@mock.patch.object(objects.Runbook, 'destroy', autospec=True)
class TestDelete(BaseRunbooksAPITest):

    def setUp(self):
        super(TestDelete, self).setUp()
        self.runbook = obj_utils.create_test_runbook(self.context)

    @mock.patch.object(notification_utils, '_emit_api_notification',
                       autospec=True)
    def test_delete_by_uuid(self, mock_notify, mock_destroy):
        self.delete('/runbooks/%s' % self.runbook.uuid,
                    headers=self.headers)
        mock_destroy.assert_called_once_with(mock.ANY)
        mock_notify.assert_has_calls([mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.START),
                                      mock.call(mock.ANY, mock.ANY, 'delete',
                                      obj_fields.NotificationLevel.INFO,
                                      obj_fields.NotificationStatus.END)])

    def test_delete_by_name(self, mock_destroy):
        self.delete('/runbooks/%s' % self.runbook.name,
                    headers=self.headers)
        mock_destroy.assert_called_once_with(mock.ANY)

    def test_delete_invalid_api_version(self, mock_dpt):
        response = self.delete('/runbooks/%s' % self.runbook.uuid,
                               expect_errors=True,
                               headers=self.invalid_version_headers)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_delete_old_api_version(self, mock_dpt):
        # Names like CUSTOM_1 were not valid in API 1.1, but the check should
        # go after the microversion check.
        response = self.delete('/runbooks/%s' % self.runbook.name,
                               expect_errors=True)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, response.status_int)

    def test_delete_by_name_non_existent(self, mock_dpt):
        res = self.delete('/runbooks/%s' % 'blah', expect_errors=True,
                          headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, res.status_code)
