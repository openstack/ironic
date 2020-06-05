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
Tests to assert that various incorporated middleware works as expected.
"""

from http import client as http_client
import os
import tempfile

from oslo_config import cfg
import oslo_middleware.cors as cors_middleware

from ironic.tests.unit.api import base
from ironic.tests.unit.api import utils
from ironic.tests.unit.db import utils as db_utils


class TestCORSMiddleware(base.BaseApiTest):
    '''Provide a basic smoke test to ensure CORS middleware is active.

    The tests below provide minimal confirmation that the CORS middleware
    is active, and may be configured. For comprehensive tests, please consult
    the test suite in oslo_middleware.
    '''
    def setUp(self):
        # Make sure the CORS options are registered
        cfg.CONF.register_opts(cors_middleware.CORS_OPTS, 'cors')

        # Load up our valid domain values before the application is created.
        cfg.CONF.set_override("allowed_origin",
                              "http://valid.example.com",
                              group='cors')

        # Create the application.
        super(TestCORSMiddleware, self).setUp()

    @staticmethod
    def _response_string(status_code):
        """Helper function to return string in form of 'CODE DESCRIPTION'.

        For example: '200 OK'
        """
        return '{} {}'.format(status_code, http_client.responses[status_code])

    def test_valid_cors_options_request(self):
        req_headers = ['content-type',
                       'x-auth-token',
                       'x-openstack-ironic-api-version']
        headers = {
            'Origin': 'http://valid.example.com',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': ','.join(req_headers),
            'X-OpenStack-Ironic-API-Version': '1.14'
        }
        response = self.app.options('/', headers=headers, xhr=True)

        # Assert response status.
        self.assertEqual(
            self._response_string(http_client.OK), response.status)
        self.assertIn('Access-Control-Allow-Origin', response.headers)
        self.assertEqual('http://valid.example.com',
                         response.headers['Access-Control-Allow-Origin'])

    def test_invalid_cors_options_request(self):
        req_headers = ['content-type',
                       'x-auth-token',
                       'x-openstack-ironic-api-version']
        headers = {
            'Origin': 'http://invalid.example.com',
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': ','.join(req_headers),
            'X-OpenStack-Ironic-API-Version': '1.14'
        }
        response = self.app.options('/', headers=headers, xhr=True)

        # Assert response status.
        self.assertEqual(
            self._response_string(http_client.OK), response.status)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)

    def test_valid_cors_get_request(self):
        response = self.app \
            .get('/nodes/detail',
                 headers={
                     'Origin': 'http://valid.example.com'
                 })

        # Assert response status.
        self.assertEqual(
            self._response_string(http_client.OK), response.status)
        self.assertIn('Access-Control-Allow-Origin', response.headers)
        self.assertIn('X-OpenStack-Ironic-API-Version', response.headers)
        self.assertEqual('http://valid.example.com',
                         response.headers['Access-Control-Allow-Origin'])

    def test_invalid_cors_get_request(self):
        response = self.app \
            .get('/',
                 headers={
                     'Origin': 'http://invalid.example.com'
                 })

        # Assert response status.
        self.assertEqual(
            self._response_string(http_client.OK), response.status)
        self.assertNotIn('Access-Control-Allow-Origin', response.headers)


class TestBasicAuthMiddleware(base.BaseApiTest):

    def _make_app(self):
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write('myName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
                    'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
            cfg.CONF.set_override('http_basic_auth_user_file', f.name)
        self.addCleanup(os.remove, cfg.CONF.http_basic_auth_user_file)

        cfg.CONF.set_override('auth_strategy', 'http_basic')
        return super(TestBasicAuthMiddleware, self)._make_app()

    def setUp(self):
        super(TestBasicAuthMiddleware, self).setUp()
        self.environ = {'fake.cache': utils.FakeMemcache()}
        self.fake_db_node = db_utils.get_test_node(chassis_id=None)

    def test_not_authenticated(self):
        response = self.get_json('/chassis', expect_errors=True)
        self.assertEqual(http_client.UNAUTHORIZED, response.status_int)
        self.assertEqual(
            'Basic realm="Baremetal API"',
            response.headers['WWW-Authenticate']
        )

    def test_authenticated(self):
        auth_header = {'Authorization': 'Basic bXlOYW1lOm15UGFzc3dvcmQ='}
        response = self.get_json('/chassis', headers=auth_header)
        self.assertEqual({'chassis': []}, response)

    def test_public_unauthenticated(self):
        response = self.get_json('/')
        self.assertEqual('v1', response['id'])
