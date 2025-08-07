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

import ipaddress
import os
import socket
from unittest import mock

import bcrypt
from cryptography.hazmat import backends
from cryptography import x509

from ironic.common import utils
from ironic.conductor import local_rpc
from ironic.conf import CONF
from ironic.tests import base as tests_base


@mock.patch('atexit.register', autospec=True)
@mock.patch.object(local_rpc, '_lo_has_ipv6', autospec=True)
class ConfigureTestCase(tests_base.TestCase):

    def setUp(self):
        super().setUp()
        CONF.set_override('rpc_transport', 'none')
        self.addCleanup(self._cleanup_files)

    def _cleanup_files(self):
        if CONF.json_rpc.cert_file:
            utils.unlink_without_raise(CONF.json_rpc.cert_file)
        if CONF.json_rpc.key_file:
            utils.unlink_without_raise(CONF.json_rpc.key_file)
        if CONF.json_rpc.http_basic_auth_user_file:
            utils.unlink_without_raise(CONF.json_rpc.http_basic_auth_user_file)

    def _verify_tls(self, ipv6=True):
        self.assertTrue(os.path.exists(CONF.json_rpc.key_file))
        with open(CONF.json_rpc.cert_file, 'rb') as fp:
            cert = x509.load_pem_x509_certificate(
                fp.read(), backends.default_backend())
        # NOTE(dtantsur): most of the TLS generation is tested in
        # test_tls_utils, here only the relevant parts
        subject_alt_name = cert.extensions.get_extension_for_oid(
            x509.ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
        expected = (ipaddress.IPv6Address('::1') if ipv6
                    else ipaddress.IPv4Address('127.0.0.1'))
        self.assertEqual(
            [expected],
            subject_alt_name.value.get_values_for_type(x509.IPAddress))

    def _verify_password(self):
        self.assertEqual('ironic', CONF.json_rpc.username)
        self.assertTrue(CONF.json_rpc.password)
        with open(CONF.json_rpc.http_basic_auth_user_file) as fp:
            username, hashed = fp.read().strip().split(':', 1)
        self.assertEqual(username, CONF.json_rpc.username)
        self.assertTrue(
            bcrypt.checkpw(CONF.json_rpc.password.encode(), hashed.encode()))

    def test_wrong_rpc_transport(self, mock_lo_has_ipv6, mock_atexit_register):
        CONF.set_override('rpc_transport', 'oslo')
        local_rpc.configure()
        mock_lo_has_ipv6.assert_not_called()
        mock_atexit_register.assert_not_called()
        self.assertIsNone(CONF.json_rpc.cert_file)

    def test_default(self, mock_lo_has_ipv6, mock_atexit_register):
        mock_lo_has_ipv6.return_value = True

        local_rpc.configure()

        self.assertTrue(CONF.json_rpc.use_ssl)
        self.assertEqual('http_basic', CONF.json_rpc.auth_type)
        self.assertEqual('http_basic', CONF.json_rpc.auth_strategy)
        self.assertEqual('::1', CONF.json_rpc.host_ip)
        self._verify_password()
        self._verify_tls(ipv6=True)

    def test_ipv4(self, mock_lo_has_ipv6, mock_atexit_register):
        mock_lo_has_ipv6.return_value = False

        local_rpc.configure()

        self.assertTrue(CONF.json_rpc.use_ssl)
        self.assertEqual('http_basic', CONF.json_rpc.auth_type)
        self.assertEqual('http_basic', CONF.json_rpc.auth_strategy)
        self.assertEqual('127.0.0.1', CONF.json_rpc.host_ip)
        self._verify_password()
        self._verify_tls(ipv6=False)


@mock.patch('socket.socket', autospec=True)
class LoHasIpv6TestCase(tests_base.TestCase):

    def test_ipv6_available(self, mock_socket):
        # Mock successful IPv6 socket creation and bind
        mock_sock = mock.Mock()
        mock_sock.__enter__ = mock.Mock(return_value=mock_sock)
        mock_sock.__exit__ = mock.Mock(return_value=False)
        mock_socket.return_value = mock_sock

        result = local_rpc._lo_has_ipv6()

        # Verify socket operations
        mock_socket.assert_called_once_with(socket.AF_INET6,
                                            socket.SOCK_STREAM)
        mock_sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET,
                                                     socket.SO_REUSEADDR,
                                                     1)
        mock_sock.bind.assert_called_once_with(('::1', 0))
        self.assertTrue(result)

    def test_ipv6_not_available_os_error(self, mock_socket):
        # Mock failed IPv6 socket bind (IPv6 not available)
        mock_sock = mock.Mock()
        mock_sock.__enter__ = mock.Mock(return_value=mock_sock)
        mock_sock.__exit__ = mock.Mock(return_value=False)
        mock_socket.return_value = mock_sock
        mock_sock.bind.side_effect = OSError("Cannot assign requested address")

        result = local_rpc._lo_has_ipv6()

        # Verify socket operations attempted
        mock_socket.assert_called_once_with(socket.AF_INET6,
                                            socket.SOCK_STREAM)
        mock_sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET,
                                                     socket.SO_REUSEADDR,
                                                     1)
        mock_sock.bind.assert_called_once_with(('::1', 0))
        self.assertFalse(result)

    def test_ipv6_not_available_socket_error(self, mock_socket):
        # Mock socket.error during bind
        mock_sock = mock.Mock()
        mock_sock.__enter__ = mock.Mock(return_value=mock_sock)
        mock_sock.__exit__ = mock.Mock(return_value=False)
        mock_socket.return_value = mock_sock
        mock_sock.bind.side_effect = socket.error("Network unreachable")

        result = local_rpc._lo_has_ipv6()

        # Verify socket operations attempted
        mock_socket.assert_called_once_with(socket.AF_INET6,
                                            socket.SOCK_STREAM)
        mock_sock.setsockopt.assert_called_once_with(socket.SOL_SOCKET,
                                                     socket.SO_REUSEADDR,
                                                     1)
        mock_sock.bind.assert_called_once_with(('::1', 0))
        self.assertFalse(result)

    def test_ipv6_not_available_socket_creation_fails(self, mock_socket):
        # Mock socket creation failure
        mock_socket.side_effect = OSError("Address family not supported")

        result = local_rpc._lo_has_ipv6()

        # Verify socket creation attempted
        mock_socket.assert_called_once_with(socket.AF_INET6,
                                            socket.SOCK_STREAM)
        self.assertFalse(result)
