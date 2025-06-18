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

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_service import sslutils

from ironic.common import exception
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

        service_name = 'ironic_api'
        srv = wsgi_service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
        mock_server.assert_called_once_with(server_name=service_name,
                                            wsgi_app=srv.app,
                                            bind_addr=('0.0.0.0', 6385))

        mock_ssl_adapter.assert_called_once_with(
            certificate='/path/to/cert',
            private_key='/path/to/key'
        )
        self.assertIsNotNone(self.server.ssl_adapter)
