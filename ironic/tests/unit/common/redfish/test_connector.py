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

"""Unit tests for async Redfish connector."""

import asyncio
from http import client as http_client
from unittest import mock

import httpx

from ironic.common.redfish import connector
from ironic.common.redfish import exceptions
from ironic.tests import base


class MockResponse:
    """Mock HTTP response for testing."""

    def __init__(self, json_data=None, status_code=200, headers=None):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            request = mock.Mock(url='http://test.com')
            raise httpx.HTTPStatusError('Error', request=request,
                                        response=self)


def make_mock_client(side_effect, calls):
    """Build a mock httpx.AsyncClient class recording its invocations.

    :param side_effect: either a single value used for every call, or a
        list of per-call values. An exception instance is raised, anything
        else is returned as the response.
    :param calls: list to which the HTTP method of each request is
        appended, so tests can assert on the number of attempts made.
    :returns: a class suitable for patching over httpx.AsyncClient.
    """
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.auth = None
            self.headers = {}

        async def request(self, *args, **kwargs):
            calls.append(kwargs.get('method'))
            if isinstance(side_effect, list):
                result = side_effect[len(calls) - 1]
            else:
                result = side_effect
            if isinstance(result, Exception):
                raise result
            return result

        async def aclose(self):
            pass

    return MockAsyncClient


class TestAsyncConnector(base.TestCase):
    """Test AsyncConnector class."""

    def setUp(self):
        super().setUp()
        self.base_url = 'https://bmc.example.com'
        self.connector = connector.AsyncConnector(
            url=self.base_url,
            verify=True,
            default_request_timeout=60
        )

    def test_context_manager(self):
        """Test async context manager initialization and cleanup."""
        async def run_test():
            async with connector.AsyncConnector(self.base_url) as conn:
                self.assertIsNotNone(conn._session)
                self.assertIsInstance(conn._session, httpx.AsyncClient)
                return conn

        conn = asyncio.run(run_test())
        # Session should be closed after exit
        self.assertIsNone(conn._session)

    def test_get_success(self):
        """Test successful GET request."""
        mock_response = MockResponse(
            json_data={'test': 'data', 'value': 123},
            status_code=200
        )

        async def run_test():
            # Create async methods for the mock session
            async def async_request(*args, **kwargs):
                return mock_response

            async def async_aclose():
                pass

            # Create a mock session class with required async methods
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    result = await conn.get('/test/path')
                    # get() returns the response, not the parsed body,
                    # so that callers can reach headers such as ETag.
                    self.assertIs(mock_response, result)
                    self.assertEqual({'test': 'data', 'value': 123},
                                     result.json())

        asyncio.run(run_test())

    def test_get_with_headers(self):
        """Test GET request with custom headers."""
        mock_response = MockResponse(json_data={}, status_code=200)

        async def run_test():
            # Track the request calls
            request_calls = []

            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    request_calls.append((args, kwargs))
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    custom_headers = {'X-Custom-Header': 'value'}
                    await conn.get('/test', headers=custom_headers)

                    # Verify headers were passed
                    self.assertEqual(1, len(request_calls))
                    call_kwargs = request_calls[0][1]
                    headers = call_kwargs['headers']
                    self.assertIn('X-Custom-Header', headers)
                    self.assertEqual('value', headers['X-Custom-Header'])

        asyncio.run(run_test())

    def test_get_404_error(self):
        """Test GET request with 404 Not Found error."""
        mock_response = MockResponse(status_code=http_client.NOT_FOUND)

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    try:
                        await conn.get('/nonexistent')
                        return None  # Should not reach here
                    except exceptions.ResourceNotFoundError as e:
                        return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.ResourceNotFoundError)

    def test_get_401_error(self):
        """Test GET request with 401 Unauthorized error."""
        mock_response = MockResponse(status_code=http_client.UNAUTHORIZED)

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    try:
                        await conn.get('/protected')
                        return None  # Should not reach here
                    except exceptions.AccessError as e:
                        return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.AccessError)

    def test_get_500_error(self):
        """Test GET request with 500 Internal Server Error.

        A server-side error is retried, so the delays between attempts
        are patched out: left real, this test waits the full
        3 x server_side_retries_delay before the error surfaces.
        """
        calls = []
        client = make_mock_client(
            MockResponse(status_code=http_client.INTERNAL_SERVER_ERROR),
            calls)

        async def run_test():
            with mock.patch('httpx.AsyncClient', client):
                async with connector.AsyncConnector(self.base_url) as conn:
                    try:
                        await conn.get('/error')
                        return None  # Should not reach here
                    except exceptions.ServerSideError as e:
                        return e

        with mock.patch('asyncio.sleep', new_callable=mock.AsyncMock) as slp:
            exception = asyncio.run(run_test())

        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.ServerSideError)
        # the retries themselves are the reason this test was slow, so
        # assert them rather than just silencing the wait
        self.assertEqual(4, len(calls))
        self.assertEqual(3, slp.call_count)

    def _run_request(self, side_effect, operation, connector_kwargs=None):
        """Run a single connector operation against a mock client.

        Sleeps are patched out so retry tests do not actually wait.

        :param side_effect: passed to make_mock_client.
        :param operation: coroutine function taking the connector.
        :param connector_kwargs: extra kwargs for AsyncConnector.
        :returns: tuple of (result or raised exception, calls, mock_sleep).
        """
        calls = []
        client = make_mock_client(side_effect, calls)

        async def run_test():
            async with connector.AsyncConnector(
                    self.base_url, **(connector_kwargs or {})) as conn:
                try:
                    return await operation(conn)
                except exceptions.ConnectionError as e:
                    return e

        with mock.patch('asyncio.sleep', new_callable=mock.AsyncMock) as slp:
            with mock.patch('httpx.AsyncClient', client):
                result = asyncio.run(run_test())
        return result, calls, slp

    def test_get_connection_error_retried(self):
        """Connect errors are retried: the BMC never saw the request."""
        result, calls, mock_sleep = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.get('/test'))

        # The default is 3 retries, which is 4 attempts: the first try
        # is not a retry.
        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(4, len(calls))
        self.assertEqual(3, mock_sleep.call_count)

    def test_get_read_timeout_retried(self):
        """GET is idempotent, so a read timeout is safe to replay."""
        result, calls, _ = self._run_request(
            httpx.ReadTimeout('Request timed out'),
            lambda conn: conn.get('/slow'))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(4, len(calls))

    def test_delete_read_timeout_retried(self):
        """DELETE is idempotent, so a read timeout is safe to replay."""
        result, calls, _ = self._run_request(
            httpx.ReadTimeout('Request timed out'),
            lambda conn: conn.delete('/redfish/v1/SessionService/Sessions/1'))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(4, len(calls))

    def test_get_retry_eventually_succeeds(self):
        """A transient failure followed by success returns the response."""
        result, calls, _ = self._run_request(
            [httpx.ConnectError('Connection failed'),
             MockResponse(json_data={'Name': 'ok'})],
            lambda conn: conn.get('/test'))

        self.assertEqual({'Name': 'ok'}, result.json())
        self.assertEqual(2, len(calls))

    def test_post_read_timeout_not_retried(self):
        """A read timeout on POST must not replay a possibly-applied action.

        The request was fully sent, so the BMC may already have acted on
        it. Replaying it risks duplicating the action.
        """
        result, calls, mock_sleep = self._run_request(
            httpx.ReadTimeout('Request timed out'),
            lambda conn: conn.post('/redfish/v1/Systems/1/Actions/'
                                   'ComputerSystem.Reset',
                                   data={'ResetType': 'ForceRestart'}))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))
        mock_sleep.assert_not_called()

    def test_post_write_timeout_not_retried(self):
        """A write timeout on POST may also have been delivered in full."""
        result, calls, _ = self._run_request(
            httpx.WriteTimeout('Write timed out'),
            lambda conn: conn.post('/redfish/v1/SessionService/Sessions',
                                   data={'UserName': 'admin'}))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))

    def test_patch_read_timeout_not_retried(self):
        """A read timeout on PATCH is not replayed either."""
        result, calls, _ = self._run_request(
            httpx.ReadTimeout('Request timed out'),
            lambda conn: conn.patch('/redfish/v1/Systems/1',
                                    data={'Boot': {}}))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))

    def test_post_connect_error_retried(self):
        """Connect errors on POST are still retried: nothing was sent."""
        result, calls, _ = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.post('/redfish/v1/Systems/1/Actions/'
                                   'ComputerSystem.Reset',
                                   data={'ResetType': 'ForceRestart'}))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(4, len(calls))

    def test_non_transient_request_error_not_retried(self):
        """Errors outside the transient set are raised on first attempt."""
        result, calls, _ = self._run_request(
            httpx.UnsupportedProtocol('Bad protocol'),
            lambda conn: conn.get('/test'))

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))

    def test_retry_honours_configured_limits(self):
        """Retry count and delay come from the connector configuration."""
        result, calls, mock_sleep = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.get('/test'),
            connector_kwargs={'server_side_retries': 2,
                              'server_side_retries_delay': 7})

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(3, len(calls))
        self.assertEqual([mock.call(7)] * 2, mock_sleep.call_args_list)

    def test_no_retries_configured_means_one_attempt(self):
        """Zero retries must disable retrying, not fall back to a default.

        Both counts were previously read as ``x or default``, so a
        configured 0 was indistinguishable from unset and the transport
        loop still made the default number of attempts. The HTTP error
        path below reads the same value without a fallback, so the two
        disagreed on what 0 meant for the very same request.
        """
        result, calls, mock_sleep = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.get('/test'),
            connector_kwargs={'server_side_retries': 0})

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))
        mock_sleep.assert_not_called()

    def test_zero_delay_configured_is_not_replaced(self):
        """A configured delay of 0 means retry immediately."""
        result, calls, mock_sleep = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.get('/test'),
            connector_kwargs={'server_side_retries': 2,
                              'server_side_retries_delay': 0})

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(3, len(calls))
        self.assertEqual([mock.call(0)] * 2, mock_sleep.call_args_list)

    def test_negative_retries_still_makes_one_attempt(self):
        """A negative count must not skip the loop body.

        ``range()`` over a non-positive count would leave the response
        variable unbound and raise UnboundLocalError further down,
        turning a misconfiguration into a crash rather than a request.
        """
        result, calls, _ = self._run_request(
            httpx.ConnectError('Connection failed'),
            lambda conn: conn.get('/test'),
            connector_kwargs={'server_side_retries': -1})

        self.assertIsInstance(result, exceptions.ConnectionError)
        self.assertEqual(1, len(calls))

    def test_zero_retries_still_returns_a_successful_response(self):
        """With retries disabled a working BMC is still reached once."""
        result, calls, _ = self._run_request(
            [MockResponse(json_data={'Name': 'ok'})],
            lambda conn: conn.get('/test'),
            connector_kwargs={'server_side_retries': 0})

        self.assertEqual({'Name': 'ok'}, result.json())
        self.assertEqual(1, len(calls))

    def test_post_success(self):
        """Test successful POST request."""
        mock_response = MockResponse(
            status_code=201,
            headers={'Location': '/resource/1'}
        )

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    data = {'key': 'value'}
                    response = await conn.post('/create', data=data)
                    self.assertEqual(201, response.status_code)
                    self.assertEqual('/resource/1',
                                     response.headers['Location'])

        asyncio.run(run_test())

    def test_set_http_basic_auth(self):
        """Test setting HTTP basic authentication."""
        async def run_test():
            async with connector.AsyncConnector(self.base_url) as conn:
                conn.set_http_basic_auth('admin', 'password')
                # httpx sets a BasicAuth object, not a tuple
                import httpx
                self.assertIsInstance(conn._session.auth, httpx.BasicAuth)

        asyncio.run(run_test())

    def test_set_http_session_auth(self):
        """Test setting session authentication."""
        async def run_test():
            async with connector.AsyncConnector(self.base_url) as conn:
                token = 'test-token-12345'
                conn.set_http_session_auth(token)
                self.assertIsNone(conn._session.auth)
                self.assertEqual(token, conn._session.headers['X-Auth-Token'])

        asyncio.run(run_test())

    def test_prepare_url_absolute(self):
        """Test URL preparation with absolute URL."""
        url = self.connector._prepare_url('https://other.example.com/path')
        self.assertEqual('https://other.example.com/path', url)

    def test_prepare_url_relative(self):
        """Test URL preparation with relative path."""
        url = self.connector._prepare_url('/redfish/v1/Systems')
        self.assertEqual('https://bmc.example.com/redfish/v1/Systems', url)

    def test_prepare_headers_defaults(self):
        """Test header preparation with defaults."""
        headers = self.connector._prepare_headers(None)
        self.assertEqual('application/json', headers['Content-Type'])
        self.assertEqual('4.0', headers['OData-Version'])
        self.assertEqual('identity', headers['Accept-Encoding'])

    def test_prepare_headers_custom(self):
        """Test header preparation with custom headers."""
        custom = {'X-Custom': 'value', 'Content-Type': 'text/plain'}
        headers = self.connector._prepare_headers(custom)
        self.assertEqual('text/plain', headers['Content-Type'])
        self.assertEqual('value', headers['X-Custom'])
        self.assertEqual('4.0', headers['OData-Version'])

    def test_prepare_headers_remove_default(self):
        """Test removing default header by setting to None."""
        custom = {'Content-Type': None}
        headers = self.connector._prepare_headers(custom)
        self.assertNotIn('Content-Type', headers)
        self.assertEqual('4.0', headers['OData-Version'])

    def test_close(self):
        """Test explicit close method."""
        async def run_test():
            async with connector.AsyncConnector(self.base_url) as conn:
                self.assertIsNotNone(conn._session)
                await conn.close()
                self.assertIsNone(conn._session)

        asyncio.run(run_test())

    def test_delete_success(self):
        """Test successful DELETE request."""
        mock_response = MockResponse(status_code=204)

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    response = await conn.delete('/resource/1')
                    self.assertEqual(204, response.status_code)

        asyncio.run(run_test())

    def test_patch_success(self):
        """Test successful PATCH request."""
        mock_response = MockResponse(status_code=200)

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    data = {'field': 'new_value'}
                    response = await conn.patch('/resource/1', data=data)
                    self.assertEqual(200, response.status_code)

        asyncio.run(run_test())

    def test_put_success(self):
        """Test successful PUT request."""
        mock_response = MockResponse(status_code=200)

        async def run_test():
            class MockAsyncClient:
                def __init__(self, *args, **kwargs):
                    self.auth = None
                    self.headers = {}

                async def request(self, *args, **kwargs):
                    return mock_response

                async def aclose(self):
                    pass

            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(self.base_url) as conn:
                    data = {'complete': 'replacement'}
                    response = await conn.put('/resource/1', data=data)
                    self.assertEqual(200, response.status_code)

        asyncio.run(run_test())


class TestSessionsPathRecognition(base.TestCase):
    """A rejected login must not be retried as an expired session.

    The guard used to match the '/Sessions' suffix, which only held
    because the path was hardcoded. Now that it is discovered from the
    service root it can be anything, so the resolved URI is recorded and
    compared instead.
    """

    def setUp(self):
        super().setUp()
        self.conn = connector.AsyncConnector('https://bmc.example.com')

    def test_suffix_match_used_before_discovery(self):
        """Until a URI is recorded, fall back to the conventional suffix."""
        self.assertTrue(
            self.conn._is_sessions_path('/redfish/v1/SessionService/Sessions'))
        self.assertFalse(self.conn._is_sessions_path('/redfish/v1/Systems/1'))

    def test_recorded_uri_matches(self):
        """A discovered URI is recognised even without the suffix."""
        self.conn.set_sessions_uri('/custom/Login')

        self.assertTrue(self.conn._is_sessions_path('/custom/Login'))

    def test_recorded_uri_without_sessions_suffix_would_escape_suffix_check(
            self):
        """Regression: the old suffix check missed such a path entirely."""
        self.conn.set_sessions_uri('/custom/Login')

        self.assertFalse('/custom/Login'.endswith('/Sessions'))
        self.assertTrue(self.conn._is_sessions_path('/custom/Login'))

    def test_trailing_slashes_ignored(self):
        """Trailing slashes on either side do not defeat the match."""
        self.conn.set_sessions_uri('/custom/Login/')

        self.assertTrue(self.conn._is_sessions_path('/custom/Login'))
        self.assertTrue(self.conn._is_sessions_path('/custom/Login/'))

    def test_other_paths_not_matched_once_recorded(self):
        """A recorded URI narrows the match rather than widening it."""
        self.conn.set_sessions_uri('/custom/Login')

        self.assertFalse(
            self.conn._is_sessions_path('/redfish/v1/SessionService/Sessions'))
        self.assertFalse(self.conn._is_sessions_path('/redfish/v1/Systems/1'))

    def test_no_reauth_loop_on_the_login_request(self):
        """A 401 from the Sessions URI itself is raised, not re-tried."""
        auth = mock.Mock()
        auth.can_refresh_session = mock.Mock(return_value=True)
        auth.refresh_session = mock.AsyncMock()

        calls = []
        client = make_mock_client(MockResponse(status_code=401), calls)

        async def run_test():
            async with connector.AsyncConnector('https://bmc') as conn:
                conn.set_auth(auth)
                conn.set_sessions_uri('/custom/Login')
                try:
                    await conn.post('/custom/Login', data={'UserName': 'a'})
                except exceptions.AccessError as e:
                    return e

        with mock.patch('httpx.AsyncClient', client):
            result = asyncio.run(run_test())

        self.assertIsInstance(result, exceptions.AccessError)
        auth.refresh_session.assert_not_called()
        self.assertEqual(1, len(calls))


class TestConnectTimeout(base.TestCase):
    """A BMC that swallows packets must fail fast, as it does in sushy.

    Without a separate connect timeout every attempt waits out the much
    longer read timeout, and the retry loop multiplies that: 4 attempts
    at 60s plus the delays between them is over four minutes before the
    caller sees an error.
    """

    def test_no_connect_timeout_passes_the_plain_value(self):
        """Unset, nothing changes: httpx gets the read timeout as before."""
        conn = connector.AsyncConnector('https://bmc.example.com',
                                        default_request_timeout=60)

        self.assertEqual(60, conn._build_timeout(60))

    def test_connect_timeout_is_applied(self):
        conn = connector.AsyncConnector('https://bmc.example.com',
                                        default_request_timeout=60,
                                        connect_timeout=5)

        timeout = conn._build_timeout(60)

        self.assertIsInstance(timeout, httpx.Timeout)
        self.assertEqual(5, timeout.connect)
        # the rest still gets the longer read timeout: some BMCs hold a
        # request open for a long time before answering
        self.assertEqual(60, timeout.read)
        self.assertEqual(60, timeout.write)

    def test_explicit_httpx_timeout_is_left_alone(self):
        """A caller that built its own timeout keeps it."""
        conn = connector.AsyncConnector('https://bmc.example.com',
                                        connect_timeout=5)
        given = httpx.Timeout(10, connect=1)

        self.assertIs(given, conn._build_timeout(given))

    def test_per_request_timeout_keeps_the_connect_timeout(self):
        """A caller overriding the read timeout still fails fast."""
        conn = connector.AsyncConnector('https://bmc.example.com',
                                        default_request_timeout=60,
                                        connect_timeout=5)

        timeout = conn._build_timeout(600)

        self.assertEqual(5, timeout.connect)
        self.assertEqual(600, timeout.read)

    def test_client_is_built_with_the_connect_timeout(self):
        """The timeout reaches the httpx client, not just _build_timeout."""
        captured = {}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                self.auth = None
                self.headers = {}

            async def aclose(self):
                pass

        async def run_test():
            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(
                        'https://bmc.example.com',
                        default_request_timeout=60,
                        connect_timeout=5):
                    pass

        asyncio.run(run_test())

        self.assertEqual(5, captured['timeout'].connect)
        self.assertEqual(60, captured['timeout'].read)


class TestRedirects(base.TestCase):

    def test_redirects_are_followed(self):
        """sushy follows redirects via requests; httpx must be told to.

        BMCs redirect in practice, so leaving the httpx default would
        fail where sushy succeeds.
        """
        captured = {}

        class MockAsyncClient:
            def __init__(self, *args, **kwargs):
                captured.update(kwargs)
                self.auth = None
                self.headers = {}

            async def aclose(self):
                pass

        async def run_test():
            with mock.patch('httpx.AsyncClient', MockAsyncClient):
                async with connector.AsyncConnector(
                        'https://bmc.example.com'):
                    pass

        asyncio.run(run_test())

        self.assertTrue(captured['follow_redirects'])


class TestAuthHeaderHygiene(base.TestCase):

    def _connector_with_session(self):
        conn = connector.AsyncConnector('https://bmc.example.com')
        conn._session = mock.Mock()
        conn._session.headers = {}
        conn._session.auth = None
        return conn

    def test_basic_auth_clears_a_stale_session_token(self):
        """Falling back to basic auth must drop the rejected token.

        AsyncSessionOrBasicAuth switches to basic auth after session
        auth fails; sending the old token alongside the credentials
        meant to replace it invites the BMC to reject both.
        """
        conn = self._connector_with_session()
        conn.set_http_session_auth('stale-token')
        self.assertEqual('stale-token', conn._session.headers['X-Auth-Token'])

        conn.set_http_basic_auth('admin', 'password')

        self.assertNotIn('X-Auth-Token', conn._session.headers)
        self.assertEqual(('admin', 'password'), conn._session.auth)

    def test_basic_auth_without_a_token_is_fine(self):
        """Clearing a token that was never set must not raise."""
        conn = self._connector_with_session()

        conn.set_http_basic_auth('admin', 'password')

        self.assertEqual(('admin', 'password'), conn._session.auth)

    def test_session_auth_clears_basic_auth(self):
        conn = self._connector_with_session()
        conn.set_http_basic_auth('admin', 'password')

        conn.set_http_session_auth('a-token')

        self.assertIsNone(conn._session.auth)
        self.assertEqual('a-token', conn._session.headers['X-Auth-Token'])


class TestCheckRetryOnException(base.TestCase):
    """Vendor retry detection must survive the bodies BMCs really send."""

    def setUp(self):
        super().setUp()
        self.conn = connector.AsyncConnector('https://bmc.example.com')

    def _check(self, json_data):
        return self.conn.check_retry_on_exception(
            MockResponse(json_data=json_data))

    def test_idrac_not_ready_is_retried(self):
        self.assertTrue(self._check({
            'error': {'@Message.ExtendedInfo': [{'MessageId': 'SYS518'}]}}))

    def test_ilo_invalid_state_is_retried(self):
        self.assertTrue(self._check({
            'error': {'@Message.ExtendedInfo': [
                {'MessageId': 'Base.1.0.InvalidOperationForSystemState'}]}}))

    def test_unrelated_message_is_not_retried(self):
        self.assertFalse(self._check({
            'error': {'@Message.ExtendedInfo': [
                {'MessageId': 'Base.1.0.GeneralError'}]}}))

    def test_null_error_does_not_raise(self):
        """An explicit null error: get('error', {}) returns None, not {}."""
        self.assertFalse(self._check({'error': None}))

    def test_null_extended_info_does_not_raise(self):
        self.assertFalse(
            self._check({'error': {'@Message.ExtendedInfo': None}}))

    def test_null_entry_in_extended_info_does_not_raise(self):
        self.assertFalse(self._check({
            'error': {'@Message.ExtendedInfo': [None]}}))

    def test_null_message_id_does_not_raise(self):
        self.assertFalse(self._check({
            'error': {'@Message.ExtendedInfo': [{'MessageId': None}]}}))

    def test_a_good_entry_after_a_null_one_is_still_found(self):
        """Skipping a bad entry must not abandon the rest of the list."""
        self.assertTrue(self._check({
            'error': {'@Message.ExtendedInfo': [
                None, {'MessageId': 'SYS518'}]}}))

    def test_missing_keys(self):
        self.assertFalse(self._check({}))

    def test_non_dict_body(self):
        self.assertFalse(self._check(['not', 'a', 'dict']))
