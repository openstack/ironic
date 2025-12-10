# Copyright 2024 Red Hat, Inc.
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

"""Unit tests for async Redfish authentication."""

import asyncio
from unittest import mock

from ironic.common.redfish import auth
from ironic.common.redfish import exceptions
from ironic.tests import base


class TestAsyncBasicAuth(base.TestCase):
    """Test AsyncBasicAuth class."""

    def setUp(self):
        super().setUp()
        self.username = 'admin'
        self.password = 'password123'
        self.auth = auth.AsyncBasicAuth(self.username, self.password)

    def test_do_authenticate(self):
        """Test basic authentication setup."""
        mock_connector = mock.AsyncMock()
        mock_connector.set_http_basic_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        asyncio.run(run_test())
        mock_connector.set_http_basic_auth.assert_called_once_with(
            self.username, self.password
        )

    def test_can_refresh_session(self):
        """Test that basic auth cannot refresh sessions."""
        self.assertFalse(self.auth.can_refresh_session())

    def test_set_context(self):
        """Test setting connector context."""
        mock_connector = mock.AsyncMock()
        mock_connector.set_auth = mock.MagicMock()
        mock_connector.set_http_basic_auth = mock.MagicMock()

        async def run_test():
            await self.auth.set_context(mock_connector)

        asyncio.run(run_test())
        mock_connector.set_auth.assert_called_once_with(self.auth)
        mock_connector.set_http_basic_auth.assert_called_once_with(
            self.username, self.password
        )

    def test_context_manager(self):
        """Test async context manager."""
        async def run_test():
            async with self.auth as a:
                self.assertIs(a, self.auth)

        asyncio.run(run_test())


class TestAsyncSessionAuth(base.TestCase):
    """Test AsyncSessionAuth class."""

    def setUp(self):
        super().setUp()
        self.username = 'admin'
        self.password = 'password123'
        self.auth = auth.AsyncSessionAuth(self.username, self.password)

    def test_do_authenticate_success(self):
        """Test successful session authentication."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.headers = {
            'X-Auth-Token': 'test-token-12345',
            'Location': '/redfish/v1/SessionService/Sessions/1'
        }
        mock_connector.post = mock.AsyncMock(return_value=mock_response)
        mock_connector.set_http_session_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        asyncio.run(run_test())

        # Verify session was created
        mock_connector.post.assert_called_once_with(
            '/redfish/v1/SessionService/Sessions',
            data={'UserName': self.username, 'Password': self.password}
        )

        # Verify session data was stored
        self.assertEqual('test-token-12345', self.auth._session_key)
        self.assertEqual('/redfish/v1/SessionService/Sessions/1',
                         self.auth._session_resource_id)
        self.assertTrue(self.auth._session_auth_previously_successful)

        # Verify token was set on connector
        mock_connector.set_http_session_auth.assert_called_once_with(
            'test-token-12345'
        )

    def test_do_authenticate_missing_token(self):
        """Test authentication failure when X-Auth-Token is missing."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.headers = {}  # Missing X-Auth-Token
        mock_connector.post = mock.AsyncMock(return_value=mock_response)

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        self.assertRaises(
            exceptions.MissingHeaderError,
            asyncio.run,
            run_test()
        )

    def test_do_authenticate_access_error(self):
        """Test authentication failure with AccessError."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_connector.post = mock.AsyncMock(
            side_effect=exceptions.AccessError(
                method='POST',
                url='/redfish/v1/SessionService/Sessions',
                response=mock_response
            )
        )

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        self.assertRaises(
            exceptions.AccessError,
            asyncio.run,
            run_test()
        )

    def test_can_refresh_session_with_session(self):
        """Test can_refresh_session returns True when session exists."""
        self.auth._session_key = 'test-token'
        self.auth._session_resource_id = '/session/1'

        self.assertTrue(self.auth.can_refresh_session())

    def test_can_refresh_session_without_session(self):
        """Test can_refresh_session returns False without session."""
        self.assertFalse(self.auth.can_refresh_session())

    def test_refresh_session(self):
        """Test session refresh."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.headers = {
            'X-Auth-Token': 'new-token-67890',
            'Location': '/redfish/v1/SessionService/Sessions/2'
        }
        mock_connector.post = mock.AsyncMock(return_value=mock_response)
        mock_connector.set_http_session_auth = mock.MagicMock()

        # Set up existing session
        self.auth._connector = mock_connector
        self.auth._session_key = 'old-token'
        self.auth._session_resource_id = '/session/1'

        async def run_test():
            await self.auth.refresh_session()

        asyncio.run(run_test())

        # Verify new session was created
        self.assertEqual('new-token-67890', self.auth._session_key)
        self.assertEqual('/redfish/v1/SessionService/Sessions/2',
                         self.auth._session_resource_id)

    def test_close_with_session(self):
        """Test close deletes the session."""
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock()

        self.auth._connector = mock_connector
        self.auth._session_resource_id = '/session/1'
        self.auth._session_key = 'test-token'

        async def run_test():
            await self.auth.close()

        asyncio.run(run_test())

        mock_connector.delete.assert_called_once_with('/session/1')
        self.assertIsNone(self.auth._session_key)
        self.assertIsNone(self.auth._session_resource_id)

    def test_close_without_session(self):
        """Test close does nothing when no session exists."""
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth.close()

        asyncio.run(run_test())

        mock_connector.delete.assert_not_called()

    def test_close_delete_error(self):
        """Test close handles deletion errors gracefully."""
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock(
            side_effect=exceptions.ServerSideError(
                method='DELETE',
                url='/session/1',
                response=None
            )
        )

        self.auth._connector = mock_connector
        self.auth._session_resource_id = '/session/1'
        self.auth._session_key = 'test-token'

        async def run_test():
            await self.auth.close()

        # Should not raise, just log warning
        asyncio.run(run_test())

        # Session attrs should still be reset
        self.assertIsNone(self.auth._session_key)
        self.assertIsNone(self.auth._session_resource_id)

    def test_close_session_already_gone(self):
        """A 404 on close is the wanted outcome, not a failure.

        The BMC expiring or rebooting away a session leaves nothing to
        delete, which is what close() is trying to achieve. Letting the
        404 out would make routine teardown look like an error.
        """
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock(
            side_effect=exceptions.ResourceNotFoundError(
                method='DELETE',
                url='/session/1',
                response=None
            )
        )

        self.auth._connector = mock_connector
        self.auth._session_resource_id = '/session/1'
        self.auth._session_key = 'test-token'

        async def run_test():
            await self.auth.close()

        asyncio.run(run_test())

        self.assertIsNone(self.auth._session_key)
        self.assertIsNone(self.auth._session_resource_id)

    def test_get_session_key(self):
        """Test getting session key."""
        self.auth._session_key = 'test-token'
        self.assertEqual('test-token', self.auth.get_session_key())

    def test_get_session_resource_id(self):
        """Test getting session resource ID."""
        self.auth._session_resource_id = '/session/1'
        self.assertEqual('/session/1', self.auth.get_session_resource_id())


class TestAsyncSessionOrBasicAuth(base.TestCase):
    """Test AsyncSessionOrBasicAuth class."""

    def setUp(self):
        super().setUp()
        self.username = 'admin'
        self.password = 'password123'
        self.auth = auth.AsyncSessionOrBasicAuth(self.username, self.password)

    def test_do_authenticate_session_success(self):
        """Test successful session authentication."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.headers = {
            'X-Auth-Token': 'test-token',
            'Location': '/session/1'
        }
        mock_connector.post = mock.AsyncMock(return_value=mock_response)
        mock_connector.set_http_session_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        asyncio.run(run_test())

        # Should use session auth
        self.assertEqual('test-token', self.auth._session_key)
        self.assertTrue(self.auth._session_auth_previously_successful)

    def test_do_authenticate_fallback_to_basic(self):
        """Test fallback to basic auth when session fails."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.status_code = 401
        mock_connector.post = mock.AsyncMock(
            side_effect=exceptions.AccessError(
                method='POST',
                url='/SessionService/Sessions',
                response=mock_response
            )
        )
        mock_connector.set_http_basic_auth = mock.MagicMock()
        mock_connector.set_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        asyncio.run(run_test())

        # Should have fallen back to basic auth
        self.assertFalse(self.auth._session_auth_previously_successful)
        self.assertFalse(self.auth.can_refresh_session())

    def test_do_authenticate_no_fallback_on_connection_error(self):
        """Test connectivity failures do not downgrade to basic auth."""
        mock_connector = mock.AsyncMock()
        mock_connector.post = mock.AsyncMock(
            side_effect=exceptions.ConnectionError(
                url='/SessionService/Sessions',
                error='connection refused'
            )
        )
        mock_connector.set_http_basic_auth = mock.MagicMock()
        mock_connector.set_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        self.assertRaises(
            exceptions.ConnectionError,
            asyncio.run,
            run_test()
        )

        # Must not have fallen back to basic authentication
        mock_connector.set_http_basic_auth.assert_not_called()

    def test_do_authenticate_no_fallback_on_non_redfish_error(self):
        """Test programming errors are not masked by the basic fallback."""
        mock_connector = mock.AsyncMock()
        mock_connector.post = mock.AsyncMock(side_effect=TypeError('boom'))
        mock_connector.set_http_basic_auth = mock.MagicMock()
        mock_connector.set_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        self.assertRaises(TypeError, asyncio.run, run_test())
        mock_connector.set_http_basic_auth.assert_not_called()

    def test_do_authenticate_no_fallback_after_success(self):
        """Test no fallback to basic after successful session auth."""
        mock_connector = mock.AsyncMock()

        # First successful session auth
        mock_response = mock.MagicMock()
        mock_response.headers = {
            'X-Auth-Token': 'test-token',
            'Location': '/session/1'
        }
        mock_connector.post = mock.AsyncMock(return_value=mock_response)
        mock_connector.set_http_session_auth = mock.MagicMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth._do_authenticate()

        asyncio.run(run_test())

        # Now simulate session expiry
        mock_response2 = mock.MagicMock()
        mock_response2.status_code = 401
        mock_connector.post = mock.AsyncMock(
            side_effect=exceptions.AccessError(
                method='POST',
                url='/SessionService/Sessions',
                response=mock_response2
            )
        )

        # Set flag to simulate previous successful session
        self.auth._session_auth_previously_successful = True
        self.auth._session_key = 'old-token'
        self.auth._session_resource_id = '/session/1'

        # Should not fallback, should raise
        async def run_test2():
            await self.auth._do_authenticate()

        self.assertRaises(
            exceptions.AccessError,
            asyncio.run,
            run_test2()
        )

    def test_refresh_session_with_session(self):
        """Test refresh when session is available."""
        mock_connector = mock.AsyncMock()
        mock_response = mock.MagicMock()
        mock_response.headers = {
            'X-Auth-Token': 'new-token',
            'Location': '/session/2'
        }
        mock_connector.post = mock.AsyncMock(return_value=mock_response)
        mock_connector.set_http_session_auth = mock.MagicMock()

        self.auth._connector = mock_connector
        self.auth._session_key = 'old-token'
        self.auth._session_resource_id = '/session/1'

        async def run_test():
            await self.auth.refresh_session()

        asyncio.run(run_test())

        # Should have refreshed
        self.assertEqual('new-token', self.auth._session_key)

    def test_refresh_session_without_session(self):
        """Test refresh when using basic auth (no-op)."""
        mock_connector = mock.AsyncMock()
        mock_connector.post = mock.AsyncMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth.refresh_session()

        # Should not raise, just no-op
        asyncio.run(run_test())

        mock_connector.post.assert_not_called()

    def test_close_with_session(self):
        """Test close with active session."""
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock()

        self.auth._connector = mock_connector
        self.auth._session_resource_id = '/session/1'
        self.auth._session_key = 'test-token'

        async def run_test():
            await self.auth.close()

        asyncio.run(run_test())

        mock_connector.delete.assert_called_once()

    def test_close_without_session(self):
        """Test close when using basic auth."""
        mock_connector = mock.AsyncMock()
        mock_connector.delete = mock.AsyncMock()

        self.auth._connector = mock_connector

        async def run_test():
            await self.auth.close()

        asyncio.run(run_test())

        mock_connector.delete.assert_not_called()


class TestSessionsPathDiscovery(base.TestCase):
    """The Sessions URI is discovered, not assumed.

    DSP0266 advises reading Links/Sessions from the service root. The
    conventional path is only a fallback, and hardcoding it ignored both
    a BMC that puts the collection elsewhere and a custom root prefix.
    """

    def _authenticate(self, root_json=None, root_prefix=None):
        """Authenticate and return the path the session was POSTed to."""
        session_auth = auth.AsyncSessionAuth(
            'admin', 'password123', root_prefix=root_prefix)

        response = mock.MagicMock()
        response.headers = {'X-Auth-Token': 'token', 'Location': '/s/1'}
        connector = mock.AsyncMock()
        connector.post = mock.AsyncMock(return_value=response)
        connector.set_http_session_auth = mock.MagicMock()
        connector.set_auth = mock.MagicMock()
        connector.set_sessions_uri = mock.MagicMock()

        root = None
        if root_json is not None:
            root = mock.Mock()
            root.json = root_json

        asyncio.run(session_auth.set_context(connector, root=root))
        return connector

    def test_path_discovered_from_service_root(self):
        """A BMC that advertises its Sessions URI is taken at its word."""
        connector = self._authenticate(
            root_json={'Links': {'Sessions': {'@odata.id': '/custom/Sess'}}})

        self.assertEqual('/custom/Sess', connector.post.call_args[0][0])

    def test_discovered_path_recorded_on_connector(self):
        """The resolved URI is handed to the connector.

        The connector needs it to tell a rejected login from an expired
        session; a discovered path need not end in '/Sessions'.
        """
        connector = self._authenticate(
            root_json={'Links': {'Sessions': {'@odata.id': '/custom/Sess'}}})

        connector.set_sessions_uri.assert_called_once_with('/custom/Sess')

    def test_falls_back_when_root_lacks_the_link(self):
        """A root without Links/Sessions falls back to the usual path."""
        connector = self._authenticate(root_json={'Name': 'root'})

        self.assertEqual('/redfish/v1/SessionService/Sessions',
                         connector.post.call_args[0][0])

    def test_falls_back_when_root_unavailable(self):
        """No service root at all still yields a usable path."""
        connector = self._authenticate()

        self.assertEqual('/redfish/v1/SessionService/Sessions',
                         connector.post.call_args[0][0])

    def test_fallback_respects_custom_root_prefix(self):
        """The fallback is built from the configured prefix.

        Regression test: the path used to be a literal, so a client
        constructed with a non-default root prefix would POST to the
        wrong place as soon as discovery failed.
        """
        connector = self._authenticate(root_json={}, root_prefix='/rf/v2')

        self.assertEqual('/rf/v2/SessionService/Sessions',
                         connector.post.call_args[0][0])

    def test_fallback_tolerates_trailing_slash_in_prefix(self):
        """A prefix with a trailing slash does not double up."""
        connector = self._authenticate(root_json={},
                                       root_prefix='/redfish/v1/')

        self.assertEqual('/redfish/v1/SessionService/Sessions',
                         connector.post.call_args[0][0])

    def test_malformed_link_falls_back(self):
        """A Links/Sessions that is not a mapping is ignored."""
        connector = self._authenticate(
            root_json={'Links': {'Sessions': 'not-a-dict'}})

        self.assertEqual('/redfish/v1/SessionService/Sessions',
                         connector.post.call_args[0][0])

    def test_empty_odata_id_falls_back(self):
        """An empty @odata.id is not a usable path."""
        connector = self._authenticate(
            root_json={'Links': {'Sessions': {'@odata.id': ''}}})

        self.assertEqual('/redfish/v1/SessionService/Sessions',
                         connector.post.call_args[0][0])
