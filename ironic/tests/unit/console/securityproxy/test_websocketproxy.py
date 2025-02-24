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

"""Tests for nova websocketproxy."""

import fixtures
import io
import socket
from unittest import mock

from oslo_config import cfg
import oslo_middleware.cors as cors_middleware
from oslo_utils import timeutils

from ironic.common import exception
from ironic.common import vnc as vnc_utils

from ironic.console.securityproxy import base
from ironic.console import websocketproxy
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class IronicProxyRequestHandlerDBTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IronicProxyRequestHandlerDBTestCase, self).setUp()

        self.node = obj_utils.create_test_node(
            self.context,
            driver_internal_info={
                'vnc_host': 'node1',
                'vnc_port': 10000,
                'novnc_secret_token': '123-456-789',
                'novnc_secret_token_created': timeutils.utcnow().isoformat()
            }
        )
        self.uuid = self.node.uuid

        with mock.patch('websockify.ProxyRequestHandler', autospec=True):
            self.wh = websocketproxy.IronicProxyRequestHandler()
        self.wh.server = websocketproxy.IronicWebSocketProxy()
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()
        # register [cors] config options
        cors_middleware.CORS(None, CONF)
        CONF.set_override(
            'allowed_origin',
            ['allowed-origin-example-1.net', 'allowed-origin-example-2.net'],
            group='cors')

    fake_header = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    @mock.patch('ironic.objects.Node.get_by_uuid',
                autospec=True)
    def test_new_websocket_client_db(
            self, mock_node_get, mock_validate,
            node_not_found=False):

        if node_not_found:
            mock_node_get.side_effect = exception.NodeNotFound(
                node=self.uuid)
        else:
            mock_node_get.return_value = self.node

        tsock = mock.MagicMock()
        tsock.recv.return_value = "HTTP/1.1 200 OK\r\n\r\n"
        self.wh.socket.return_value = tsock

        self.wh.path = "http://127.0.0.1/?token=123-456-789"
        self.wh.headers = self.fake_header

        if node_not_found:
            self.assertRaises(exception.NotAuthorized,
                              self.wh.new_websocket_client)
        else:
            self.wh.new_websocket_client()
            mock_validate.assert_called_once_with(mock.ANY, '123-456-789')
            self.wh.socket.assert_called_with('node1', 10000, connect=True)
            self.wh.do_proxy.assert_called_with(tsock)

    def test_new_websocket_client_db_instance_not_found(self):
        self.test_new_websocket_client_db(node_not_found=True)


class IronicProxyRequestHandlerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IronicProxyRequestHandlerTestCase, self).setUp()

        self.node = obj_utils.create_test_node(
            self.context,
            driver_internal_info={
                'vnc_host': 'node1',
                'vnc_port': 10000,
                'novnc_secret_token': '123-456-789',
                'novnc_secret_token_created': timeutils.utcnow().isoformat()
            }
        )
        self.uuid = self.node.uuid

        self.server = websocketproxy.IronicWebSocketProxy()
        with mock.patch('websockify.ProxyRequestHandler', autospec=True):
            self.wh = websocketproxy.IronicProxyRequestHandler()
        self.wh.server = self.server
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()
        # register [cors] config options
        cors_middleware.CORS(None, CONF)
        CONF.set_override(
            'allowed_origin',
            ['allowed-origin-example-1.net', 'allowed-origin-example-2.net'],
            group='cors')

        self.threading_timer_mock = self.useFixture(
            fixtures.MockPatch('threading.Timer', mock.DEFAULT)).mock

    fake_header = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_ipv6 = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://[2001:db8::1]:6080',
        'Host': '[2001:db8::1]:6080',
    }

    fake_header_bad_token = {
        'cookie': 'token="XXX"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_bad_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://bad-origin-example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_allowed_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': 'https://allowed-origin-example-2.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_blank_origin = {
        'cookie': 'token="123-456-789"',
        'Origin': '',
        'Host': 'example.net:6080',
    }

    fake_header_no_origin = {
        'cookie': 'token="123-456-789"',
        'Host': 'example.net:6080',
    }

    fake_header_http = {
        'cookie': 'token="123-456-789"',
        'Origin': 'http://example.net:6080',
        'Host': 'example.net:6080',
    }

    fake_header_malformed_cookie = {
        'cookie': '?=!; token="123-456-789"',
        'Origin': 'https://example.net:6080',
        'Host': 'example.net:6080',
    }

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client(self, validate):
        validate.return_value = '123-456-789'

        self.wh.socket.return_value = '<socket>'
        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, '123-456-789')
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_ipv6_url(self, validate):
        validate.return_value = '123-456-789'

        tsock = mock.MagicMock()
        self.wh.socket.return_value = tsock
        ip = '[2001:db8::1]'
        self.wh.path = f"http://{ip}/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header_ipv6

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_token_invalid(self, validate):
        validate.side_effect = exception.NotAuthorized()

        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=XXX"
        self.wh.headers = self.fake_header_bad_token

        self.assertRaises(exception.NotAuthorized,
                          self.wh.new_websocket_client)
        validate.assert_called_with(mock.ANY, "XXX")

    @mock.patch('socket.getfqdn',
                autospec=True)
    def test_address_string_doesnt_do_reverse_dns_lookup(self, getfqdn):
        request_mock = mock.MagicMock()
        request_mock.makefile().readline.side_effect = [
            b'GET /vnc_auth.html?token=123-456-789 HTTP/1.1\r\n',
            b''
        ]
        server_mock = mock.MagicMock()
        client_address = ('8.8.8.8', 54321)

        handler = websocketproxy.IronicProxyRequestHandler(
            request_mock, client_address, server_mock)
        handler.log_message('log message using client address context info')

        self.assertFalse(getfqdn.called)  # no reverse dns look up
        self.assertEqual(handler.address_string(), '8.8.8.8')  # plain address

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_novnc_bad_origin_header(self, validate):
        validate.return_value = '123-456-789'

        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header_bad_origin

        self.assertRaises(exception.NotAuthorized,
                          self.wh.new_websocket_client)

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_novnc_allowed_origin_header(self, validate):
        validate.return_value = '123-456-789'

        tsock = mock.MagicMock()
        self.wh.socket.return_value = tsock
        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header_allowed_origin

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_novnc_blank_origin_header(self, validate):
        validate.return_value = '123-456-789'

        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header_blank_origin

        self.assertRaises(exception.NotAuthorized,
                          self.wh.new_websocket_client)

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_novnc_no_origin_header(self, validate):
        validate.return_value = '123-456-789'

        tsock = mock.MagicMock()
        self.wh.socket.return_value = tsock

        self.wh.path = f"http://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = self.fake_header_no_origin

        self.wh.new_websocket_client()

        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with(tsock)

    @mock.patch('ironic.common.vnc.novnc_validate',
                autospec=True)
    def test_new_websocket_client_http_forwarded_proto_https(self, validate):
        validate.return_value = '123-456-789'

        header = {
            'cookie': 'token="123-456-789"',
            'Origin': 'http://example.net:6080',
            'Host': 'example.net:6080',
            'X-Forwarded-Proto': 'https'
        }
        self.wh.socket.return_value = '<socket>'
        self.wh.path = f"https://127.0.0.1/?node={self.uuid}&token=123-456-789"
        self.wh.headers = header

        self.wh.new_websocket_client()

        validate.assert_called_with(mock.ANY, "123-456-789")
        self.wh.socket.assert_called_with('node1', 10000, connect=True)
        self.wh.do_proxy.assert_called_with('<socket>')

    def test_reject_open_redirect(self, url='//example.com/%2F..'):
        # This will test the behavior when an attempt is made to cause an open
        # redirect. It should be rejected.
        mock_req = mock.MagicMock()
        mock_req.makefile().readline.side_effect = [
            f'GET {url} HTTP/1.1\r\n'.encode('utf-8'),
            b''
        ]

        client_addr = ('8.8.8.8', 54321)
        mock_server = mock.MagicMock()
        # This specifies that the server will be able to handle requests other
        # than only websockets.
        mock_server.only_upgrade = False

        # Constructing a handler will process the mock_req request passed in.
        handler = websocketproxy.IronicProxyRequestHandler(
            mock_req, client_addr, mock_server)

        # Collect the response data to verify at the end. The
        # SimpleHTTPRequestHandler writes the response data to a 'wfile'
        # attribute.
        output = io.BytesIO()
        handler.wfile = output
        # Process the mock_req again to do the capture.
        handler.do_GET()
        output.seek(0)
        result = output.readlines()

        # Verify no redirect happens and instead a 400 Bad Request is returned.
        # NOTE: As of python 3.10.6 there is a fix for this vulnerability,
        # which will cause a 301 Moved Permanently error to be returned
        # instead that redirects to a sanitized version of the URL with extra
        # leading '/' characters removed.
        # See https://github.com/python/cpython/issues/87389 for details.
        # We will consider either response to be valid for this test. This will
        # also help if and when the above fix gets backported to older versions
        # of python.
        errmsg = result[0].decode()
        expected_ironic = '400 URI must not start with //'
        expected_cpython = '301 Moved Permanently'

        self.assertTrue(expected_ironic in errmsg
                        or expected_cpython in errmsg)

        # If we detect the cpython fix, verify that the redirect location is
        # now the same url but with extra leading '/' characters removed.
        if expected_cpython in errmsg:
            location = result[3].decode()
            if location.startswith('Location: '):
                location = location[len('Location: '):]
            location = location.rstrip('\r\n')
            self.assertTrue(
                location.startswith('/example.com/%2F..'),
                msg='Redirect location is not the expected sanitized URL',
            )

    def test_reject_open_redirect_3_slashes(self):
        self.test_reject_open_redirect(url='///example.com/%2F..')

    @mock.patch('websockify.websocketproxy.select_ssl_version',
                autospec=True)
    def test_ssl_min_version_is_not_set(self, mock_select_ssl):
        websocketproxy.IronicWebSocketProxy()
        self.assertFalse(mock_select_ssl.called)

    @mock.patch('websockify.websocketproxy.select_ssl_version',
                autospec=True)
    def test_ssl_min_version_not_set_by_default(self, mock_select_ssl):
        websocketproxy.IronicWebSocketProxy(ssl_minimum_version='default')
        self.assertFalse(mock_select_ssl.called)

    @mock.patch('websockify.websocketproxy.select_ssl_version',
                autospec=True)
    def test_non_default_ssl_min_version_is_set(self, mock_select_ssl):
        minver = 'tlsv1_3'
        websocketproxy.IronicWebSocketProxy(ssl_minimum_version=minver)
        mock_select_ssl.assert_called_once_with(minver)

    def test__close_connection(self):
        tsock = mock.MagicMock()
        self.wh.vmsg = mock.MagicMock()
        host = 'node1'
        port = '10000'

        self.wh._close_connection(tsock, host, port)
        tsock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        tsock.close.assert_called_once()
        self.wh.vmsg.assert_called_once_with(
            f"{host}:{port}: Websocket client or target closed")

    def test__close_connection_raise_OSError(self):
        tsock = mock.MagicMock()
        self.wh.vmsg = mock.MagicMock()
        host = 'node1'
        port = '10000'

        tsock.shutdown.side_effect = OSError("Error")

        self.wh._close_connection(tsock, host, port)

        tsock.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        tsock.close.assert_called_once()

        self.wh.vmsg.assert_called_once_with(
            f"{host}:{port}: Websocket client or target closed")


class IronicWebsocketSecurityProxyTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IronicWebsocketSecurityProxyTestCase, self).setUp()

        self.server = websocketproxy.IronicWebSocketProxy(
            security_proxy=mock.MagicMock(
                spec=base.SecurityProxy)
        )

        self.node = obj_utils.create_test_node(self.context)
        vnc_utils.novnc_authorize(self.node)
        uuid = self.node.uuid
        token = self.node.driver_internal_info['novnc_secret_token']

        with mock.patch('websockify.ProxyRequestHandler',
                        autospec=True):
            self.wh = websocketproxy.IronicProxyRequestHandler()
        self.wh.server = self.server
        self.wh.path = f"http://127.0.0.1/?node={uuid}&token={token}"
        self.wh.socket = mock.MagicMock()
        self.wh.msg = mock.MagicMock()
        self.wh.do_proxy = mock.MagicMock()
        self.wh.headers = mock.MagicMock()

        # register [cors] config options
        cors_middleware.CORS(None, CONF)

        def get_header(header):
            if header == 'Origin':
                return 'https://example.net:6080'
            elif header == 'Host':
                return 'example.net:6080'
            else:
                return

        self.wh.headers.get = get_header

    @mock.patch('ironic.console.websocketproxy.TenantSock.close',
                autospec=True)
    @mock.patch('ironic.console.websocketproxy.TenantSock.finish_up',
                autospec=True)
    def test_proxy_connect_ok(self, mock_finish, mock_close):

        sock = mock.MagicMock(
            spec=websocketproxy.TenantSock)
        self.server.security_proxy.connect.return_value = sock

        self.wh.new_websocket_client()

        self.wh.do_proxy.assert_called_with(sock)
        mock_finish.assert_called()
        mock_close.assert_not_called()

    @mock.patch('ironic.console.websocketproxy.TenantSock.close',
                autospec=True)
    @mock.patch('ironic.console.websocketproxy.TenantSock.finish_up',
                autospec=True)
    def test_proxy_connect_err(self, mock_finish, mock_close):

        ex = exception.SecurityProxyNegotiationFailed("Wibble")
        self.server.security_proxy.connect.side_effect = ex

        self.assertRaises(exception.SecurityProxyNegotiationFailed,
                          self.wh.new_websocket_client)

        self.assertEqual(len(self.wh.do_proxy.calls), 0)
        mock_close.assert_called()
        mock_finish.assert_not_called()
