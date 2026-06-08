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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_service import sslutils

from ironic.common import exception
from ironic.common import tls_utils
from ironic.common import wsgi_service
from ironic.tests import base

CONF = cfg.CONF


class TestWSGIService(base.TestCase):
    def setUp(self):
        super().setUp()

        sslutils.register_opts(CONF)
        self.server = mock.Mock()
        self.server.requests = mock.Mock(min=0, max=0)

    @mock.patch.object(processutils, 'get_worker_count', lambda: 2)
    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_default(self, mock_server):
        service_name = "ironic_api"
        mock_server.return_value = self.server
        test_service = wsgi_service.WSGIService(service_name)
        self.assertEqual(2, test_service.workers)
        mock_server.assert_called_once_with(server_name=service_name,
                                            wsgi_app=test_service.app,
                                            bind_addr=('0.0.0.0', 6385))

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_correct_setting(self, mock_server):
        self.config(api_workers=8, group='api')
        mock_server.return_value = self.server
        test_service = wsgi_service.WSGIService("ironic_api")
        self.assertEqual(8, test_service.workers)

    @mock.patch.object(processutils, 'get_worker_count', lambda: 3)
    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_zero_setting(self, mock_server):
        self.config(api_workers=0, group='api')
        mock_server.return_value = self.server
        test_service = wsgi_service.WSGIService("ironic_api")
        self.assertEqual(3, test_service.workers)

    @mock.patch.object(processutils, 'get_worker_count', lambda: 42)
    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_default_limit(self, mock_server):
        self.config(api_workers=0, group='api')
        mock_server.return_value = self.server
        test_service = wsgi_service.WSGIService("ironic_api")
        self.assertEqual(4, test_service.workers)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_workers_set_negative_setting(self, mock_server):
        self.config(api_workers=-2, group='api')
        mock_server.return_value = self.server
        self.assertRaises(exception.ConfigInvalid,
                          wsgi_service.WSGIService,
                          'ironic_api')
        self.assertFalse(mock_server.called)

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    @mock.patch('oslo_service.sslutils.is_enabled', return_value=True,
                autospec=True)
    def test_wsgi_service_with_ssl_enabled(self, mock_is_enabled,
                                           mock_validate_tls,
                                           mock_ssl_adapter,
                                           mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='ssl')
        self.config(key_file='/path/to/key', group='ssl')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        service_name = 'ironic_api'
        srv = wsgi_service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
        mock_server.assert_called_once_with(server_name=service_name,
                                            wsgi_app=srv.app,
                                            bind_addr=('0.0.0.0', 6385))

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers=None
        )
        self.assertIsNotNone(self.server.ssl_adapter)
        # Default TLS minimum version of 1.2 is applied
        self.assertEqual(
            ssl.TLSVersion.TLSv1_2,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_with_tls_minimum_version(self, mock_validate_tls,
                                          mock_ssl_adapter,
                                          mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.3', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers=None
        )
        self.assertEqual(
            ssl.TLSVersion.TLSv1_3,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_with_tls_ciphers(self, mock_validate_tls,
                                  mock_ssl_adapter,
                                  mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_ciphers='ECDHE+AESGCM', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers='ECDHE+AESGCM'
        )
        # Default TLS 1.2 minimum is still applied
        self.assertEqual(
            ssl.TLSVersion.TLSv1_2,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_with_tls_minimum_version_1_2(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.2', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        self.assertEqual(
            ssl.TLSVersion.TLSv1_2,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_with_all_tls_options(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.3', group='api')
        self.config(tls_ciphers='ECDHE+AESGCM', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers='ECDHE+AESGCM'
        )
        self.assertEqual(
            ssl.TLSVersion.TLSv1_3,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_no_tls_options_uses_defaults(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers=None
        )
        # Default TLS 1.2 minimum is always applied
        self.assertEqual(
            ssl.TLSVersion.TLSv1_2,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    def test_tls_options_ignored_when_ssl_disabled(
            self, mock_server):
        """TLS hardening options have no effect with SSL off."""
        self.config(enable_ssl_api=False, group='api')
        self.config(tls_minimum_version='1.3', group='api')
        self.config(tls_ciphers='ECDHE+AESGCM', group='api')

        mock_server.return_value = self.server

        svc = wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        # ssl_adapter should never be set
        self.assertFalse(
            hasattr(svc.server, 'ssl_adapter')
            and svc.server.ssl_adapter is not None
            and not isinstance(
                svc.server.ssl_adapter, mock.Mock
            )
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    @mock.patch('oslo_service.sslutils.is_enabled',
                return_value=True, autospec=True)
    def test_ssl_legacy_group_with_tls_options(
            self, mock_is_enabled, mock_validate_tls,
            mock_ssl_adapter, mock_server):
        """TLS options work with legacy [ssl] cert path."""
        self.config(enable_ssl_api=True, group='api')
        self.config(tls_minimum_version='1.3', group='api')
        self.config(tls_ciphers='ECDHE+AESGCM', group='api')
        self.config(cert_file='/path/to/cert', group='ssl')
        self.config(key_file='/path/to/key', group='ssl')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        wsgi_service.WSGIService(
            'ironic_api', CONF.api.enable_ssl_api
        )

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key',
            ciphers='ECDHE+AESGCM'
        )
        self.assertEqual(
            ssl.TLSVersion.TLSv1_3,
            mock_context.minimum_version
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_tls_min_version_logged(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        """LOG.info is emitted when TLS min version is set."""
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.3', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        with mock.patch.object(
            wsgi_service.LOG, 'info', autospec=True
        ) as mock_log:
            wsgi_service.WSGIService(
                'ironic_api', CONF.api.enable_ssl_api
            )
            mock_log.assert_any_call(
                "TLS minimum version set to %s for %s",
                '1.3', 'ironic_api'
            )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    @mock.patch.object(ssl, 'HAS_TLSv1_3', False)
    def test_ssl_tls_version_unsupported_compile_time(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        """Startup fails if TLS version lacks compile-time support."""
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.3', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        self.assertRaisesRegex(
            RuntimeError,
            'TLS 1.3 is not supported',
            wsgi_service.WSGIService,
            'ironic_api', CONF.api.enable_ssl_api
        )

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_tls_version_exceeds_crypto_policy(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        """Startup fails if TLS version exceeds crypto policy."""
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_minimum_version='1.3', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        fake_ctx = mock.Mock()
        fake_ctx.maximum_version = ssl.TLSVersion.TLSv1_2

        with mock.patch.object(
            ssl, 'SSLContext', autospec=True,
            return_value=fake_ctx
        ):
            self.assertRaisesRegex(
                RuntimeError,
                'exceeds the maximum TLS version',
                wsgi_service.WSGIService,
                'ironic_api', CONF.api.enable_ssl_api
            )

    def test_check_tls_version_supported_ok(self):
        """Supported TLS version passes validation."""
        tls_utils.check_tls_version_supported('1.2')

    @mock.patch.object(wsgi_service.wsgi, 'Server', autospec=True)
    @mock.patch('ironic.common.wsgi_service.cheroot_ssl.BuiltinSSLAdapter',
                autospec=True)
    @mock.patch('ironic.common.wsgi_service.validate_cert_paths',
                autospec=True)
    def test_ssl_tls_ciphers_logged(
            self, mock_validate_tls, mock_ssl_adapter,
            mock_server):
        """LOG.info is emitted when TLS ciphers are set."""
        self.config(enable_ssl_api=True, group='api')
        self.config(cert_file='/path/to/cert', group='api')
        self.config(key_file='/path/to/key', group='api')
        self.config(tls_ciphers='ECDHE+AESGCM', group='api')

        mock_server.return_value = self.server
        mock_context = mock.Mock()
        mock_ssl_adapter.return_value.context = mock_context

        with mock.patch.object(
            wsgi_service.LOG, 'info', autospec=True
        ) as mock_log:
            wsgi_service.WSGIService(
                'ironic_api', CONF.api.enable_ssl_api
            )
            mock_log.assert_any_call(
                "TLS ciphers configured for %s",
                'ironic_api'
            )
