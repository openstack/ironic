# All Rights Reserved.
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

from unittest import mock

from webob import exc as webob_exc

from ironic.api.controllers import v1 as v1_api
from ironic.api.controllers.v1 import versions
from ironic.tests import base as test_base
from ironic.tests.unit.api import base as api_base


class TestV1Routing(api_base.BaseApiTest):
    def test_route_checks_version(self):
        self.get_json('/')
        self._check_version.assert_called_once_with(mock.ANY,
                                                    mock.ANY,
                                                    mock.ANY)

    def test_min_version(self):
        response = self.get_json(
            '/',
            headers={
                'Accept': 'application/json',
                'X-OpenStack-Ironic-API-Version':
                versions.min_version_string()
            })
        self.assertEqual({
            'id': 'v1',
            'links': [
                {'href': 'http://localhost/v1/', 'rel': 'self'},
                {'href': 'https://docs.openstack.org//ironic/latest'
                         '/contributor//webapi.html',
                 'rel': 'describedby', 'type': 'text/html'}
            ],
            'media_types': {
                'base': 'application/json',
                'type': 'application/vnd.openstack.ironic.v1+json'
            },
            'version': {
                'id': 'v1',
                'links': [{'href': 'http://localhost/v1/', 'rel': 'self'}],
                'status': 'CURRENT',
                'min_version': versions.min_version_string(),
                'version': versions.max_version_string()
            },
            'chassis': [
                {'href': 'http://localhost/v1/chassis/', 'rel': 'self'},
                {'href': 'http://localhost/chassis/', 'rel': 'bookmark'}
            ],
            'nodes': [
                {'href': 'http://localhost/v1/nodes/', 'rel': 'self'},
                {'href': 'http://localhost/nodes/', 'rel': 'bookmark'}
            ],
            'ports': [
                {'href': 'http://localhost/v1/ports/', 'rel': 'self'},
                {'href': 'http://localhost/ports/', 'rel': 'bookmark'}
            ],
            'drivers': [
                {'href': 'http://localhost/v1/drivers/', 'rel': 'self'},
                {'href': 'http://localhost/drivers/', 'rel': 'bookmark'}
            ],
        }, response)

    def test_max_version(self):
        response = self.get_json(
            '/',
            headers={
                'Accept': 'application/json',
                'X-OpenStack-Ironic-API-Version':
                versions.max_version_string()
            })
        self.assertEqual({
            'id': 'v1',
            'links': [
                {'href': 'http://localhost/v1/', 'rel': 'self'},
                {'href': 'https://docs.openstack.org//ironic/latest'
                         '/contributor//webapi.html',
                 'rel': 'describedby', 'type': 'text/html'}
            ],
            'media_types': {
                'base': 'application/json',
                'type': 'application/vnd.openstack.ironic.v1+json'
            },
            'version': {
                'id': 'v1',
                'links': [{'href': 'http://localhost/v1/', 'rel': 'self'}],
                'status': 'CURRENT',
                'min_version': versions.min_version_string(),
                'version': versions.max_version_string()
            },
            'allocations': [
                {'href': 'http://localhost/v1/allocations/', 'rel': 'self'},
                {'href': 'http://localhost/allocations/', 'rel': 'bookmark'}
            ],
            'chassis': [
                {'href': 'http://localhost/v1/chassis/', 'rel': 'self'},
                {'href': 'http://localhost/chassis/', 'rel': 'bookmark'}
            ],
            'conductors': [
                {'href': 'http://localhost/v1/conductors/', 'rel': 'self'},
                {'href': 'http://localhost/conductors/', 'rel': 'bookmark'}
            ],
            'continue_inspection': [
                {'href': 'http://localhost/v1/continue_inspection/',
                 'rel': 'self'},
                {'href': 'http://localhost/continue_inspection/',
                 'rel': 'bookmark'}
            ],
            'deploy_templates': [
                {'href': 'http://localhost/v1/deploy_templates/',
                 'rel': 'self'},
                {'href': 'http://localhost/deploy_templates/',
                 'rel': 'bookmark'}
            ],
            'drivers': [
                {'href': 'http://localhost/v1/drivers/', 'rel': 'self'},
                {'href': 'http://localhost/drivers/', 'rel': 'bookmark'}
            ],
            'events': [
                {'href': 'http://localhost/v1/events/', 'rel': 'self'},
                {'href': 'http://localhost/events/', 'rel': 'bookmark'}
            ],
            'heartbeat': [
                {'href': 'http://localhost/v1/heartbeat/', 'rel': 'self'},
                {'href': 'http://localhost/heartbeat/', 'rel': 'bookmark'}
            ],
            'lookup': [
                {'href': 'http://localhost/v1/lookup/', 'rel': 'self'},
                {'href': 'http://localhost/lookup/', 'rel': 'bookmark'}
            ],
            'nodes': [
                {'href': 'http://localhost/v1/nodes/', 'rel': 'self'},
                {'href': 'http://localhost/nodes/', 'rel': 'bookmark'}
            ],
            'portgroups': [
                {'href': 'http://localhost/v1/portgroups/', 'rel': 'self'},
                {'href': 'http://localhost/portgroups/', 'rel': 'bookmark'}
            ],
            'ports': [
                {'href': 'http://localhost/v1/ports/', 'rel': 'self'},
                {'href': 'http://localhost/ports/', 'rel': 'bookmark'}
            ],
            'shards': [
                {'href': 'http://localhost/v1/shards/', 'rel': 'self'},
                {'href': 'http://localhost/shards/', 'rel': 'bookmark'}
            ],
            'volume': [
                {'href': 'http://localhost/v1/volume/', 'rel': 'self'},
                {'href': 'http://localhost/volume/', 'rel': 'bookmark'}
            ]
        }, response)


class TestCheckVersions(test_base.TestCase):

    def setUp(self):
        super(TestCheckVersions, self).setUp()

        class ver(object):
            major = None
            minor = None

        self.version = ver()

    def test_check_version_invalid_major_version(self):
        self.version.major = v1_api.BASE_VERSION + 1
        self.version.minor = v1_api.min_version().minor
        self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version)

    def test_check_version_too_low(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.min_version().minor - 1
        self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version)

    def test_check_version_too_high(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.max_version().minor + 1
        e = self.assertRaises(
            webob_exc.HTTPNotAcceptable,
            v1_api.Controller()._check_version,
            self.version, {'fake-headers': v1_api.max_version().minor})
        self.assertEqual(v1_api.max_version().minor, e.headers['fake-headers'])

    def test_check_version_ok(self):
        self.version.major = v1_api.BASE_VERSION
        self.version.minor = v1_api.min_version().minor
        v1_api.Controller()._check_version(self.version)
