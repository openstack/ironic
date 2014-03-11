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

import fixtures
from keystoneclient import exceptions as ksexception
import mock

from ironic.common import exception
from ironic.common import keystone
from ironic.tests import base


class FakeCatalog:
    def url_for(self, **kwargs):
        return 'fake-url'


class FakeClient:
    def __init__(self, **kwargs):
        self.service_catalog = FakeCatalog()

    def has_service_catalog(self):
        return True


# TODO(lucasagomes): Replace fixtures with mock for some of the tests in
#                    the KeystoneTestCase class
class KeystoneTestCase(base.TestCase):

    def setUp(self):
        super(KeystoneTestCase, self).setUp()
        self.config(group='keystone_authtoken',
                    auth_uri='http://127.0.0.1:9898/',
                    admin_user='fake', admin_password='fake',
                    admin_tenant_name='fake')

    def test_failure_authorization(self):
        self.assertRaises(exception.CatalogFailure, keystone.get_service_url)

    def test_get_url(self):
        fake_url = 'http://127.0.0.1:6385'

        class _fake_catalog:
            def url_for(self, **kwargs):
                return fake_url

        class _fake_client:
            def __init__(self, **kwargs):
                self.service_catalog = _fake_catalog()

            def has_service_catalog(self):
                return True

        self.useFixture(fixtures.MonkeyPatch(
                        'keystoneclient.v2_0.client.Client',
                        _fake_client))

        res = keystone.get_service_url()
        self.assertEqual(fake_url, res)

    def test_url_not_found(self):

        class _fake_catalog:
            def url_for(self, **kwargs):
                raise ksexception.EndpointNotFound

        class _fake_client:
            def __init__(self, **kwargs):
                self.service_catalog = _fake_catalog()

            def has_service_catalog(self):
                return True

        self.useFixture(fixtures.MonkeyPatch(
                        'keystoneclient.v2_0.client.Client',
                        _fake_client))

        self.assertRaises(exception.CatalogNotFound, keystone.get_service_url)

    def test_no_catalog(self):

        class _fake_client:
            def __init__(self, **kwargs):
                pass

            def has_service_catalog(self):
                return False

        self.useFixture(fixtures.MonkeyPatch(
                        'keystoneclient.v2_0.client.Client',
                        _fake_client))

        self.assertRaises(exception.CatalogFailure, keystone.get_service_url)

    def test_unauthorized(self):

        class _fake_client:
            def __init__(self, **kwargs):
                raise ksexception.Unauthorized

        self.useFixture(fixtures.MonkeyPatch(
                        'keystoneclient.v2_0.client.Client',
                        _fake_client))

        self.assertRaises(exception.CatalogUnauthorized,
                          keystone.get_service_url)

    def test_get_service_url_fail_missing_auth_uri(self):
        self.config(group='keystone_authtoken', auth_uri=None)
        self.assertRaises(exception.CatalogFailure,
                          keystone.get_service_url)

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_service_url_versionless_v2(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone_authtoken', auth_uri='http://127.0.0.1')
        expected_url = 'http://127.0.0.1/v2.0'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        auth_url=expected_url)

    @mock.patch('keystoneclient.v3.client.Client')
    def test_get_service_url_versionless_v3(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone_authtoken', auth_version='v3.0',
                    auth_uri='http://127.0.0.1')
        expected_url = 'http://127.0.0.1/v3'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        auth_url=expected_url)

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_service_url_version_override(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone_authtoken',
                    auth_uri='http://127.0.0.1/v2.0/')
        expected_url = 'http://127.0.0.1/v2.0'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        auth_url=expected_url)
