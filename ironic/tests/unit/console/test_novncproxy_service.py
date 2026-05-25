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

from oslo_config import cfg

from ironic.console import novncproxy_service
from ironic.tests import base as tests_base

CONF = cfg.CONF


class TestNoVNCProxyService(tests_base.TestCase):

    @mock.patch.object(novncproxy_service, 'websocketproxy',
                       autospec=True)
    def test_real_start_no_ssl(self, mock_wsproxy):
        CONF.set_override('novnc_web', '/tmp/novnc',
                          group='vnc')
        with mock.patch('os.path.exists', return_value=True,
                        autospec=True):
            svc = novncproxy_service.NoVNCProxyService()
            svc._real_start()

        mock_wsproxy.IronicWebSocketProxy.assert_called_once()
        kwargs = (
            mock_wsproxy.IronicWebSocketProxy.call_args[1]
        )
        self.assertNotIn('cert', kwargs)
        self.assertNotIn('key', kwargs)
        self.assertNotIn('ssl_only', kwargs)
        self.assertNotIn('ssl_ciphers', kwargs)
        self.assertNotIn('ssl_minimum_version', kwargs)

    @mock.patch.object(novncproxy_service, 'websocketproxy',
                       autospec=True)
    def test_real_start_with_ssl(self, mock_wsproxy):
        CONF.set_override('enable_ssl', True, group='vnc')
        CONF.set_override('cert_file', '/path/to/cert.pem',
                          group='vnc')
        CONF.set_override('key_file', '/path/to/key.pem',
                          group='vnc')
        CONF.set_override('tls_minimum_version', '1.3',
                          group='vnc')
        CONF.set_override('tls_ciphers', 'HIGH:!aNULL',
                          group='vnc')
        CONF.set_override('novnc_web', '/tmp/novnc',
                          group='vnc')
        with mock.patch('os.path.exists', return_value=True,
                        autospec=True):
            svc = novncproxy_service.NoVNCProxyService()
            svc._real_start()

        mock_wsproxy.IronicWebSocketProxy.assert_called_once()
        kwargs = (
            mock_wsproxy.IronicWebSocketProxy.call_args[1]
        )
        self.assertEqual('/path/to/cert.pem', kwargs['cert'])
        self.assertEqual('/path/to/key.pem', kwargs['key'])
        self.assertTrue(kwargs['ssl_only'])
        self.assertEqual('HIGH:!aNULL',
                         kwargs['ssl_ciphers'])
        self.assertEqual('1.3',
                         kwargs['ssl_minimum_version'])

    @mock.patch.object(novncproxy_service, 'websocketproxy',
                       autospec=True)
    def test_real_start_ssl_default_tls_version(self,
                                                mock_wsproxy):
        CONF.set_override('enable_ssl', True, group='vnc')
        CONF.set_override('cert_file', '/path/to/cert.pem',
                          group='vnc')
        CONF.set_override('key_file', '/path/to/key.pem',
                          group='vnc')
        CONF.set_override('novnc_web', '/tmp/novnc',
                          group='vnc')
        with mock.patch('os.path.exists', return_value=True,
                        autospec=True):
            svc = novncproxy_service.NoVNCProxyService()
            svc._real_start()

        kwargs = (
            mock_wsproxy.IronicWebSocketProxy.call_args[1]
        )
        self.assertEqual('1.2',
                         kwargs['ssl_minimum_version'])
