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


class KeystoneTestCase(base.TestCase):

    def setUp(self):
        super(KeystoneTestCase, self).setUp()
        self.config(group='keystone_authtoken',
                    auth_uri='http://127.0.0.1:9898/',
                    admin_user='fake', admin_password='fake',
                    admin_tenant_name='fake')
        self.config(group='keystone', region_name='fake')

    def test_failure_authorization(self):
        self.assertRaises(exception.KeystoneFailure, keystone.get_service_url)

    @mock.patch.object(FakeCatalog, 'url_for')
    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_url(self, mock_ks, mock_uf):
        fake_url = 'http://127.0.0.1:6385'
        mock_uf.return_value = fake_url
        mock_ks.return_value = FakeClient()
        res = keystone.get_service_url()
        self.assertEqual(fake_url, res)

    @mock.patch.object(FakeCatalog, 'url_for')
    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_url_not_found(self, mock_ks, mock_uf):
        mock_uf.side_effect = ksexception.EndpointNotFound
        mock_ks.return_value = FakeClient()
        self.assertRaises(exception.CatalogNotFound, keystone.get_service_url)

    @mock.patch.object(FakeClient, 'has_service_catalog')
    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_no_catalog(self, mock_ks, mock_hsc):
        mock_hsc.return_value = False
        mock_ks.return_value = FakeClient()
        self.assertRaises(exception.KeystoneFailure, keystone.get_service_url)

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_unauthorized(self, mock_ks):
        mock_ks.side_effect = ksexception.Unauthorized
        self.assertRaises(exception.KeystoneUnauthorized,
                          keystone.get_service_url)

    def test_get_service_url_fail_missing_auth_uri(self):
        self.config(group='keystone_authtoken', auth_uri=None)
        self.assertRaises(exception.KeystoneFailure,
                          keystone.get_service_url)

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_service_url_versionless_v2(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone_authtoken', auth_uri='http://127.0.0.1')
        expected_url = 'http://127.0.0.1/v2.0'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        region_name='fake',
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
                                        region_name='fake',
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
                                        region_name='fake',
                                        auth_url=expected_url)

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_admin_auth_token(self, mock_ks):
        fake_client = FakeClient()
        fake_client.auth_token = '123456'
        mock_ks.return_value = fake_client
        self.assertEqual('123456', keystone.get_admin_auth_token())

    @mock.patch('keystoneclient.v2_0.client.Client')
    def test_get_region_name_v2(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone', region_name='fake_region')
        expected_url = 'http://127.0.0.1:9898/v2.0'
        expected_region = 'fake_region'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        region_name=expected_region,
                                        auth_url=expected_url)

    @mock.patch('keystoneclient.v3.client.Client')
    def test_get_region_name_v3(self, mock_ks):
        mock_ks.return_value = FakeClient()
        self.config(group='keystone', region_name='fake_region')
        self.config(group='keystone_authtoken', auth_version='v3.0')
        expected_url = 'http://127.0.0.1:9898/v3'
        expected_region = 'fake_region'
        keystone.get_service_url()
        mock_ks.assert_called_once_with(username='fake', password='fake',
                                        tenant_name='fake',
                                        region_name=expected_region,
                                        auth_url=expected_url)
