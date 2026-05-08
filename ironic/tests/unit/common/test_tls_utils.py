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

import ssl
from unittest import mock

from ironic.common import tls_utils
from ironic.tests import base


class TLSVersionMapTestCase(base.TestCase):

    def test_contains_tls_1_2(self):
        self.assertEqual(ssl.TLSVersion.TLSv1_2,
                         tls_utils.TLS_VERSION_MAP['1.2'])

    def test_contains_tls_1_3(self):
        self.assertEqual(ssl.TLSVersion.TLSv1_3,
                         tls_utils.TLS_VERSION_MAP['1.3'])

    def test_only_expected_entries(self):
        self.assertEqual({'1.2', '1.3'},
                         set(tls_utils.TLS_VERSION_MAP))


class TLSHTTPAdapterTestCase(base.TestCase):

    @mock.patch('requests.adapters.HTTPAdapter.init_poolmanager',
                autospec=True)
    def test_init_poolmanager_passes_ssl_context(self, mock_init):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        adapter = tls_utils.TLSHTTPAdapter(ssl_context=ctx)
        # Reset because __init__ calls init_poolmanager internally
        mock_init.reset_mock()
        adapter.init_poolmanager(1, 2, block=False)
        mock_init.assert_called_once_with(
            adapter, 1, 2, block=False, ssl_context=ctx)

    @mock.patch('requests.adapters.HTTPAdapter.init_poolmanager',
                autospec=True)
    def test_init_poolmanager_no_context(self, mock_init):
        adapter = tls_utils.TLSHTTPAdapter()
        # Reset because __init__ calls init_poolmanager internally
        mock_init.reset_mock()
        adapter.init_poolmanager(1, 2, block=False)
        mock_init.assert_called_once_with(
            adapter, 1, 2, block=False)


class BuildSSLContextTestCase(base.TestCase):

    def test_returns_none_when_no_options(self):
        self.assertIsNone(tls_utils.build_ssl_context())

    def test_returns_none_with_empty_strings(self):
        self.assertIsNone(
            tls_utils.build_ssl_context(
                tls_minimum_version='', tls_ciphers=''))

    def test_sets_minimum_version_1_2(self):
        ctx = tls_utils.build_ssl_context(tls_minimum_version='1.2')
        self.assertIsNotNone(ctx)
        self.assertEqual(ssl.TLSVersion.TLSv1_2,
                         ctx.minimum_version)

    def test_sets_minimum_version_1_3(self):
        ctx = tls_utils.build_ssl_context(tls_minimum_version='1.3')
        self.assertIsNotNone(ctx)
        self.assertEqual(ssl.TLSVersion.TLSv1_3,
                         ctx.minimum_version)

    @mock.patch.object(ssl.SSLContext, 'set_ciphers',
                       autospec=True)
    def test_sets_ciphers(self, mock_set):
        ctx = tls_utils.build_ssl_context(
            tls_ciphers='ECDHE+AESGCM')
        self.assertIsNotNone(ctx)
        mock_set.assert_called_once_with('ECDHE+AESGCM')

    @mock.patch.object(ssl.SSLContext, 'set_ciphers',
                       autospec=True)
    def test_sets_both(self, mock_set):
        ctx = tls_utils.build_ssl_context(
            tls_minimum_version='1.2',
            tls_ciphers='ECDHE+AESGCM')
        self.assertIsNotNone(ctx)
        self.assertEqual(ssl.TLSVersion.TLSv1_2,
                         ctx.minimum_version)
        mock_set.assert_called_once_with('ECDHE+AESGCM')

    def test_check_hostname_false(self):
        ctx = tls_utils.build_ssl_context(
            tls_minimum_version='1.2')
        self.assertFalse(ctx.check_hostname)

    def test_verify_mode_cert_none(self):
        ctx = tls_utils.build_ssl_context(
            tls_minimum_version='1.2')
        self.assertEqual(ssl.CERT_NONE, ctx.verify_mode)
