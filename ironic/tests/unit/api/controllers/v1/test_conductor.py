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
Tests for the API /conductors/ methods.
"""

import datetime
from http import client as http_client

import mock
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.objects import utils as obj_utils


class TestListConductors(test_api_base.BaseApiTest):

    def test_empty(self):
        data = self.get_json(
            '/conductors',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual([], data['conductors'])

    def test_list(self):
        obj_utils.create_test_conductor(self.context, hostname='why care')
        obj_utils.create_test_conductor(self.context, hostname='why not')
        data = self.get_json(
            '/conductors',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(2, len(data['conductors']))
        for c in data['conductors']:
            self.assertIn('hostname', c)
            self.assertIn('conductor_group', c)
            self.assertIn('alive', c)
            self.assertNotIn('drivers', c)
        self.assertEqual(data['conductors'][0]['hostname'], 'why care')
        self.assertEqual(data['conductors'][1]['hostname'], 'why not')

    def test_list_with_detail(self):
        obj_utils.create_test_conductor(self.context, hostname='why care')
        obj_utils.create_test_conductor(self.context, hostname='why not')
        data = self.get_json(
            '/conductors?detail=true',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(2, len(data['conductors']))
        for c in data['conductors']:
            self.assertIn('hostname', c)
            self.assertIn('drivers', c)
            self.assertIn('conductor_group', c)
            self.assertIn('alive', c)
            self.assertIn('drivers', c)
        self.assertEqual(data['conductors'][0]['hostname'], 'why care')
        self.assertEqual(data['conductors'][1]['hostname'], 'why not')

    def test_list_with_invalid_api(self):
        response = self.get_json(
            '/conductors', headers={api_base.Version.string: '1.48'},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one(self):
        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')
        data = self.get_json(
            '/conductors/rocky.rocks',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertIn('hostname', data)
        self.assertIn('drivers', data)
        self.assertIn('conductor_group', data)
        self.assertIn('alive', data)
        self.assertIn('drivers', data)
        self.assertEqual(data['hostname'], 'rocky.rocks')
        self.assertTrue(data['alive'])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_one_conductor_offline(self, mock_utcnow):
        self.config(heartbeat_timeout=10, group='conductor')

        _time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = _time

        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')

        mock_utcnow.return_value = _time + datetime.timedelta(seconds=30)

        data = self.get_json(
            '/conductors/rocky.rocks',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertIn('hostname', data)
        self.assertIn('drivers', data)
        self.assertIn('conductor_group', data)
        self.assertIn('alive', data)
        self.assertIn('drivers', data)
        self.assertEqual(data['hostname'], 'rocky.rocks')
        self.assertFalse(data['alive'])

    def test_get_one_with_invalid_api(self):
        response = self.get_json(
            '/conductors/rocky.rocks',
            headers={api_base.Version.string: '1.48'},
            expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)

    def test_get_one_custom_fields(self):
        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')
        fields = 'hostname,alive'
        data = self.get_json(
            '/conductors/rocky.rocks?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertItemsEqual(['hostname', 'alive', 'links'], data)

    def test_get_collection_custom_fields(self):
        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')
        obj_utils.create_test_conductor(self.context, hostname='stein.rocks')
        fields = 'hostname,alive'

        data = self.get_json(
            '/conductors?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})

        self.assertEqual(2, len(data['conductors']))
        for c in data['conductors']:
            self.assertItemsEqual(['hostname', 'alive', 'links'], c)

    def test_get_custom_fields_invalid_fields(self):
        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')
        fields = 'hostname,spongebob'
        response = self.get_json(
            '/conductors/rocky.rocks?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())},
            expect_errors=True)
        self.assertEqual(http_client.BAD_REQUEST, response.status_int)
        self.assertEqual('application/json', response.content_type)
        self.assertIn('spongebob', response.json['error_message'])

    def _test_links(self, public_url=None):
        cfg.CONF.set_override('public_endpoint', public_url, 'api')
        obj_utils.create_test_conductor(self.context, hostname='rocky.rocks')
        headers = {api_base.Version.string: str(api_v1.max_version())}
        data = self.get_json(
            '/conductors/rocky.rocks',
            headers=headers)
        self.assertIn('links', data)
        self.assertEqual(2, len(data['links']))
        self.assertIn('rocky.rocks', data['links'][0]['href'])
        for link in data['links']:
            bookmark = link['rel'] == 'bookmark'
            self.assertTrue(self.validate_link(link['href'], bookmark=bookmark,
                                               headers=headers))

        if public_url is not None:
            expected = [{'href': '%s/v1/conductors/rocky.rocks' % public_url,
                         'rel': 'self'},
                        {'href': '%s/conductors/rocky.rocks' % public_url,
                         'rel': 'bookmark'}]
            for i in expected:
                self.assertIn(i, data['links'])

    def test_links(self):
        self._test_links()

    def test_links_public_url(self):
        self._test_links(public_url='http://foo')

    def test_collection_links(self):
        conductors = []
        for id in range(5):
            hostname = uuidutils.generate_uuid()
            conductor = obj_utils.create_test_conductor(self.context,
                                                        hostname=hostname)
            conductors.append(conductor.hostname)
        data = self.get_json(
            '/conductors/?limit=3',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(3, len(data['conductors']))

        next_marker = data['conductors'][-1]['hostname']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_default_limit(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        conductors = []
        for id in range(5):
            hostname = uuidutils.generate_uuid()
            conductor = obj_utils.create_test_conductor(self.context,
                                                        hostname=hostname)
            conductors.append(conductor.hostname)
        data = self.get_json(
            '/conductors',
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(3, len(data['conductors']))

        next_marker = data['conductors'][-1]['hostname']
        self.assertIn(next_marker, data['next'])

    def test_collection_links_custom_fields(self):
        cfg.CONF.set_override('max_limit', 3, 'api')
        conductors = []
        fields = 'hostname,alive'
        for id in range(5):
            hostname = uuidutils.generate_uuid()
            conductor = obj_utils.create_test_conductor(self.context,
                                                        hostname=hostname)
            conductors.append(conductor.hostname)
        data = self.get_json(
            '/conductors?fields=%s' % fields,
            headers={api_base.Version.string: str(api_v1.max_version())})
        self.assertEqual(3, len(data['conductors']))

        next_marker = data['conductors'][-1]['hostname']
        self.assertIn(next_marker, data['next'])
        self.assertIn('fields', data['next'])

    def test_sort_key(self):
        conductors = []
        for id in range(5):
            hostname = uuidutils.generate_uuid()
            conductor = obj_utils.create_test_conductor(self.context,
                                                        hostname=hostname)
            conductors.append(conductor.hostname)
        data = self.get_json(
            '/conductors?sort_key=hostname',
            headers={api_base.Version.string: str(api_v1.max_version())})
        hosts = [n['hostname'] for n in data['conductors']]
        self.assertEqual(sorted(conductors), hosts)

    def test_sort_key_invalid(self):
        invalid_keys_list = ['alive', 'drivers']
        headers = {api_base.Version.string: str(api_v1.max_version())}
        for invalid_key in invalid_keys_list:
            response = self.get_json('/conductors?sort_key=%s' % invalid_key,
                                     headers=headers,
                                     expect_errors=True)
            self.assertEqual(http_client.BAD_REQUEST, response.status_int)
            self.assertEqual('application/json', response.content_type)
            self.assertIn(invalid_key, response.json['error_message'])
