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

"""Async HTTP connector for Redfish using httpx."""

import asyncio
from http import client as http_client
import re
from urllib import parse as urlparse

import httpx
from oslo_log import log

from ironic.common.redfish import exceptions
from sushy import utils

LOG = log.getLogger(__name__)

# Transient failures where the request provably never reached the BMC: no
# connection was ever established, so replaying it cannot duplicate an
# action and it is safe to retry for any HTTP method.
SAFE_RETRY_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
)

# Transient failures that happen once the request is on the wire. The BMC
# may have received the request in full and acted on it, so these are only
# retried for methods where replaying cannot change state twice.
UNSAFE_RETRY_EXCEPTIONS = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
)

# Methods that can be replayed safely after the request has been sent.
# DELETE is included since deleting twice leaves the same state (the second
# attempt merely 404s). POST/PATCH/PUT are deliberately excluded.
IDEMPOTENT_METHODS = frozenset(['GET', 'HEAD', 'OPTIONS', 'DELETE'])


class AsyncConnector:
    """Async HTTP connector using httpx.AsyncClient.

    Provides asynchronous HTTP operations for Redfish BMC communication.
    """

    def __init__(self, url, verify=True, default_request_timeout=60,
                 response_callback=None, server_side_retries=3,
                 server_side_retries_delay=2, connect_timeout=None):
        """Initialize the async connector.

        :param url: Base URL for the Redfish service.
        :param verify: Either a boolean to verify certificates, or path to
            a CA certificate bundle.
        :param default_request_timeout: Default timeout in seconds for
            HTTP requests. Used as the read timeout when
            ``connect_timeout`` is given.
        :param response_callback: Optional callback function to invoke on
            every HTTP response. Takes response object as parameter.
        :param server_side_retries: Number of retries for server-side errors.
        :param server_side_retries_delay: Delay in seconds between server-side
            retries.
        :param connect_timeout: Timeout in seconds for establishing the TCP
            connection. Mirrors sushy's ``connect_timeout``: a BMC that
            drops packets rather than refusing the connection is failed
            fast, instead of holding every attempt open for the much
            longer read timeout. Defaults to the read timeout when unset.
        """
        self._url = url
        self._verify = verify
        self._default_request_timeout = default_request_timeout
        self._connect_timeout = connect_timeout
        self._session = None
        self._auth = None
        self._response_callback = response_callback
        self._server_side_retries = server_side_retries
        self._server_side_retries_delay = server_side_retries_delay

        # Track session service URI to prevent recursive auth
        self._sessions_uri = None

    def _build_timeout(self, timeout):
        """Turn a read timeout into an httpx timeout for a request.

        :param timeout: read timeout in seconds, or an ``httpx.Timeout``
            a caller has already built.
        :returns: the value to hand to httpx.
        """
        if self._connect_timeout is None or isinstance(timeout, httpx.Timeout):
            return timeout
        # Everything but connect keeps the read timeout, matching how
        # sushy passes requests a (connect, read) pair.
        return httpx.Timeout(timeout, connect=self._connect_timeout)

    async def __aenter__(self):
        """Async context manager entry."""
        self._session = httpx.AsyncClient(
            verify=self._verify,
            timeout=self._build_timeout(self._default_request_timeout),
            # Similar to sushy, we close connections after each request
            # as some BMCs struggle with persistent connections
            headers={'Connection': 'close'},
            # httpx does not follow redirects by default, where requests
            # does. sushy is built on requests and so has always followed
            # them, and BMCs do redirect in practice (canonicalising a
            # path, or bouncing http to https), so keep that behaviour
            # rather than silently failing where sushy succeeds.
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._session:
            await self._session.aclose()
            self._session = None

    def set_auth(self, auth):
        """Set the authentication mechanism.

        :param auth: Authentication object (AsyncAuthBase instance).
        """
        self._auth = auth

    def set_sessions_uri(self, sessions_uri):
        """Record where the Sessions collection lives.

        Set by session authentication once it has resolved the URI, so
        that :meth:`_is_sessions_path` can recognise the login request
        itself rather than guessing from the path.

        :param sessions_uri: URI of the Sessions collection.
        """
        self._sessions_uri = sessions_uri

    def _is_sessions_path(self, path):
        """Whether a request targets the Sessions collection.

        A 401 on session creation is a rejected login, not an expired
        session, so it must not trigger another attempt to log in.
        Compare against the recorded URI where there is one: the path is
        discovered from the service root and need not end in
        '/Sessions'. Until it has been resolved, and for auth types that
        never resolve it, fall back to the conventional suffix.

        :param path: request path to test.
        :returns: True if the path is the Sessions collection.
        """
        path = path.rstrip('/')
        if self._sessions_uri:
            return path == self._sessions_uri.rstrip('/')
        return path.endswith('/Sessions')

    def set_http_basic_auth(self, username, password):
        """Set HTTP Basic authentication.

        :param username: Username for basic auth.
        :param password: Password for basic auth.
        """
        if self._session:
            # Drop any token left over from session auth. Falling back
            # from session to basic auth (AsyncSessionOrBasicAuth) would
            # otherwise keep sending a token the BMC has already
            # rejected, alongside the credentials meant to replace it.
            self._session.headers.pop('X-Auth-Token', None)
            # httpx uses a tuple for basic auth
            self._session.auth = (username, password)

    def set_http_session_auth(self, session_auth_token):
        """Set session-based authentication.

        :param session_auth_token: Session authentication token.
        """
        if self._session:
            # Clear basic auth if set
            self._session.auth = None
            # Add X-Auth-Token header
            self._session.headers['X-Auth-Token'] = session_auth_token

    async def close(self):
        """Close the connector and HTTP session."""
        if self._session:
            await self._session.aclose()
            self._session = None

    def _prepare_url(self, path):
        """Prepare the full URL from path.

        A path that is already an absolute URL is returned unchanged,
        since urljoin() ignores the base whenever the second argument
        carries its own scheme and host.

        :param path: Sub-URI path or absolute URL.
        :returns: Full URL.
        """
        return urlparse.urljoin(self._url, path)

    def _prepare_headers(self, headers):
        """Prepare HTTP headers with defaults.

        :param headers: Optional dictionary of headers.
        :returns: Dictionary of headers with defaults applied.
        """
        headers = (headers or {}).copy()
        lc_headers = [k.lower() for k in headers]

        # Add default headers if not present
        if 'content-type' not in lc_headers:
            headers['Content-Type'] = 'application/json'
        if 'odata-version' not in lc_headers:
            headers['OData-Version'] = '4.0'
        # Use identity encoding to avoid compression issues with ETags
        if 'accept-encoding' not in lc_headers:
            headers['Accept-Encoding'] = 'identity'

        # Remove headers with None values (allows removing defaults)
        headers = {k: v for k, v in headers.items() if v is not None}

        return headers

    def check_retry_on_exception(self, response):
        """Check if the exception in response should be retried.

        This method checks for vendor-specific error conditions that should
        trigger a retry (e.g., iDRAC not ready, iLO not ready).

        :param response: httpx.Response object.
        :returns: True if the request should be retried, False otherwise.
        """
        try:
            body = response.json()
        except Exception:
            return False

        # Check for iDRAC not ready (SYS518)
        if isinstance(body, dict):
            # Use `or` rather than a default: a BMC may send these keys
            # with an explicit null, which get() happily returns. sushy
            # guards the same way.
            error = body.get('error') or {}
            extended_info = error.get('@Message.ExtendedInfo') or []
            for info in extended_info:
                if not isinstance(info, dict):
                    continue
                message_id = info.get('MessageId') or ''
                # iDRAC: SYS518 - The system is not ready
                if 'SYS518' in message_id:
                    LOG.debug('Detected iDRAC not ready (SYS518), will retry')
                    return True
                # iLO: InvalidOperationForSystemState
                if 'InvalidOperationForSystemState' in message_id:
                    LOG.debug('Detected iLO invalid operation state, '
                              'will retry')
                    return True

        return False

    def _raise_for_response(self, method, url, response):
        """Raise appropriate exception for HTTP error responses.

        :param method: HTTP method used.
        :param url: URL that was requested.
        :param response: httpx.Response object.
        :raises: Various sushy exceptions based on status code.
        """
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code

            # Map HTTP status codes to sushy exceptions
            if status_code == http_client.NOT_FOUND:
                raise exceptions.ResourceNotFoundError(
                    method=method, url=url, response=e.response)
            elif status_code in (http_client.UNAUTHORIZED,
                                 http_client.FORBIDDEN):
                raise exceptions.AccessError(
                    method=method, url=url, response=e.response)
            elif status_code == http_client.BAD_REQUEST:
                raise exceptions.BadRequestError(
                    method=method, url=url, response=e.response)
            elif status_code == http_client.NOT_ACCEPTABLE:
                raise exceptions.NotAcceptableError(
                    method=method, url=url, response=e.response)
            elif status_code >= 500:
                raise exceptions.ServerSideError(
                    method=method, url=url, response=e.response)
            else:
                raise exceptions.HTTPError(
                    method=method, url=url, response=e.response)

    async def _request(self, method, path, data=None, headers=None,
                       timeout=None, allow_reauth=True,
                       server_side_retries_left=None):
        """Internal async HTTP request handler with retry logic.

        :param method: HTTP method (GET, POST, etc.).
        :param path: Sub-URI path to the resource.
        :param data: Optional JSON data for request body.
        :param headers: Optional dictionary of headers.
        :param timeout: Optional timeout override.
        :param allow_reauth: Allow re-authentication on AccessError.
        :param server_side_retries_left: Remaining server-side retries.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        if not self._session:
            raise exceptions.ConnectionError(
                url=path,
                error="Connector not initialized. Use async context manager.")

        if server_side_retries_left is None:
            server_side_retries_left = self._server_side_retries

        url = self._prepare_url(path)
        headers = self._prepare_headers(headers)
        timeout = timeout or self._default_request_timeout

        LOG.debug('Async HTTP request: %(method)s %(url)s; '
                  'headers: %(headers)s; body: %(data)s',
                  {'method': method, 'url': url,
                   'headers': utils.sanitize(headers),
                   'data': utils.sanitize(data)})

        # Retry loop for transient connection errors.
        # The max() keeps a negative count from skipping the loop
        # entirely and leaving ``response`` unbound.
        max_attempts = max(1, self._server_side_retries + 1)
        delay = self._server_side_retries_delay
        idempotent = method in IDEMPOTENT_METHODS
        for attempt in range(max_attempts):
            try:
                response = await self._session.request(
                    method=method,
                    url=url,
                    json=data,
                    headers=headers,
                    timeout=self._build_timeout(timeout)
                )
                break  # Success, exit retry loop
            except SAFE_RETRY_EXCEPTIONS + UNSAFE_RETRY_EXCEPTIONS as e:
                # The request may already have been delivered to and acted
                # upon by the BMC. Replaying it could duplicate the action
                # (e.g. a second ComputerSystem.Reset, or a session we can
                # never delete because its token was never returned), so
                # only non-idempotent methods are given up on immediately.
                if isinstance(e, UNSAFE_RETRY_EXCEPTIONS) and not idempotent:
                    LOG.error(
                        '%(method)s %(url)s timed out after the request was '
                        'sent: %(error)s. Not retrying a non-idempotent '
                        'request, the BMC may already have acted on it.',
                        {'method': method, 'url': url, 'error': e})
                    raise exceptions.ConnectionError(url=url, error=e)
                if attempt >= max_attempts - 1:
                    LOG.error(
                        'Request to %(url)s failed after %(max)d attempts: '
                        '%(error)s',
                        {'url': url, 'max': max_attempts, 'error': e})
                    raise exceptions.ConnectionError(url=url, error=e)
                LOG.warning(
                    'Transient connection error on attempt %(attempt)d/'
                    '%(max)d for %(url)s: %(error)s. Retrying...',
                    {'attempt': attempt + 1, 'max': max_attempts,
                     'url': url, 'error': e})
                await asyncio.sleep(delay)
            except httpx.RequestError as e:
                # Don't retry other request errors
                LOG.error('Request to %(url)s failed: %(error)s',
                          {'url': url, 'error': e})
                raise exceptions.ConnectionError(url=url, error=e)

        # Call response callback if configured
        if self._response_callback:
            self._response_callback(response)

        # Handle HTTP errors with retry logic
        try:
            self._raise_for_response(method, url, response)
        except exceptions.AccessError:
            # Try to refresh session if authentication failed
            if (allow_reauth and self._auth
                    and self._auth.can_refresh_session()
                    and not self._is_sessions_path(path)):
                LOG.debug('AccessError detected, attempting session refresh')
                try:
                    await self._auth.refresh_session()
                    # Retry with allow_reauth=False to prevent infinite
                    # recursion
                    return await self._request(
                        method, path, data=data, headers=headers,
                        timeout=timeout, allow_reauth=False,
                        server_side_retries_left=server_side_retries_left)
                except Exception as refresh_error:
                    LOG.warning('Session refresh failed: %(error)s',
                                {'error': refresh_error})
                    raise
            else:
                raise
        except exceptions.ServerSideError:
            # Retry server-side errors for GET requests or vendor-specific
            # errors
            if server_side_retries_left > 0:
                should_retry = (method == 'GET'
                                or self.check_retry_on_exception(response))
                if should_retry:
                    LOG.warning('ServerSideError on %(method)s %(url)s, '
                                '%(retries)d retries left. Retrying...',
                                {'method': method, 'url': url,
                                 'retries': server_side_retries_left})
                    await asyncio.sleep(self._server_side_retries_delay)
                    return await self._request(
                        method, path, data=data, headers=headers,
                        timeout=timeout, allow_reauth=allow_reauth,
                        server_side_retries_left=server_side_retries_left - 1)
            raise
        except exceptions.BadRequestError:
            # Retry bad request errors for vendor-specific error messages
            if server_side_retries_left > 0 and method != 'GET':
                if self.check_retry_on_exception(response):
                    LOG.warning(
                        'BadRequestError with retry condition on '
                        '%(method)s %(url)s, %(retries)d retries left. '
                        'Retrying...',
                        {'method': method, 'url': url,
                         'retries': server_side_retries_left})
                    await asyncio.sleep(self._server_side_retries_delay)
                    return await self._request(
                        method, path, data=data, headers=headers,
                        timeout=timeout, allow_reauth=allow_reauth,
                        server_side_retries_left=server_side_retries_left - 1)
            raise
        except exceptions.NotAcceptableError:
            # HPE Gen 10 Plus workaround: retry GET without Accept-Encoding
            if (method == 'GET'
                    and headers.get('Accept-Encoding') == 'identity'):
                LOG.debug(
                    'NotAcceptableError on GET, retrying without '
                    'Accept-Encoding header (HPE Gen 10 Plus workaround)')
                # Remove Accept-Encoding header and retry
                headers_without_encoding = headers.copy()
                headers_without_encoding['Accept-Encoding'] = None
                return await self._request(
                    method, path, data=data, headers=headers_without_encoding,
                    timeout=timeout, allow_reauth=allow_reauth,
                    server_side_retries_left=server_side_retries_left)
            raise

        LOG.debug('Async HTTP response for %(method)s %(url)s: '
                  'status code: %(code)s',
                  {'method': method, 'url': url,
                   'code': response.status_code})

        return response

    async def get(self, path='', headers=None, timeout=None):
        """Async HTTP GET method.

        Returns the response object rather than the parsed body so that
        callers can read headers (notably ETag, needed for conditional
        updates) and the status code. This matches the other verbs.

        :param path: Optional sub-URI path to the resource.
        :param headers: Optional dictionary of headers.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        return await self._request('GET', path, headers=headers,
                                   timeout=timeout)

    async def post(self, path='', data=None, headers=None, timeout=None):
        """Async HTTP POST method.

        :param path: Optional sub-URI path to the resource.
        :param data: Optional JSON data for request body.
        :param headers: Optional dictionary of headers.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        return await self._request('POST', path, data=data, headers=headers,
                                   timeout=timeout)

    async def delete(self, path='', headers=None, timeout=None):
        """Async HTTP DELETE method.

        :param path: Optional sub-URI path to the resource.
        :param headers: Optional dictionary of headers.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        return await self._request('DELETE', path, headers=headers,
                                   timeout=timeout)

    async def _etag_handler(self, path='', data=None, headers=None,
                            etag=None, timeout=None):
        """eTag handler with workarounds for PATCH requests with eTags.

        :param path: Optional sub-URI path to the resource.
        :param data: Optional JSON data.
        :param headers: Optional dictionary of headers.
        :param etag: eTag string.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: HTTPError on HTTP errors.
        """
        # NOTE(janders) in case headers with empty-string eTag are passed
        # in, disregard it.
        if headers:
            if headers.get('If-Match') == '':
                del headers['If-Match']
        if etag:
            if not headers:
                headers = {}
            headers['If-Match'] = etag
        try:
            response = await self._request('PATCH', path, data=data,
                                           headers=headers,
                                           timeout=timeout)
        except exceptions.HTTPError as resp:
            LOG.warning("Initial request with eTag failed: %s", resp)
            if resp.status_code == http_client.PRECONDITION_FAILED:
                # NOTE(janders) if there was no eTag provided AND the
                # response is HTTP 412 Precondition Failed, raise the
                # exception
                if not etag:
                    raise
                # checking for weak eTag
                pattern = re.compile(r'^(W\/)("\w*")$')
                match = pattern.match(etag)
                if match:
                    LOG.info("Weak eTag provided with original request to "
                             "%s. Attempting conversion to strong eTag "
                             "and re-trying.", path)
                    # trying weak eTag converted to strong
                    headers['If-Match'] = match.group(2)
                    try:
                        response = await self._request('PATCH', path,
                                                       data=data,
                                                       headers=headers,
                                                       timeout=timeout)
                    except exceptions.HTTPError as resp:
                        if (resp.status_code
                                == http_client.PRECONDITION_FAILED):
                            LOG.warning(
                                "Request to %s with weak eTag "
                                "converted to strong eTag also "
                                "failed. Making the final attempt "
                                "with no eTag specified.", path)
                        response = None
                    if response:
                        return response
                else:
                    # eTag is strong, if it failed the only other thing
                    # to try is removing it entirely
                    LOG.warning("Strong eTag provided - retrying request to "
                                "%s with eTag removed.", path)
                del headers['If-Match']
                try:
                    response = await self._request('PATCH', path, data=data,
                                                   headers=headers,
                                                   timeout=timeout)
                except exceptions.HTTPError as resp:
                    LOG.error("Final re-try with eTag removed has failed, "
                              "raising exception %s", resp)
                    raise
            else:
                raise
        return response

    async def patch(self, path='', data=None, headers=None, etag=None,
                    timeout=None):
        """Async HTTP PATCH method.

        :param path: Optional sub-URI path to the resource.
        :param data: Optional JSON data for request body.
        :param headers: Optional dictionary of headers.
        :param etag: Optional eTag string.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        return await self._etag_handler(path, data, headers, etag, timeout)

    async def put(self, path='', data=None, headers=None, timeout=None):
        """Async HTTP PUT method.

        :param path: Optional sub-URI path to the resource.
        :param data: Optional JSON data for request body.
        :param headers: Optional dictionary of headers.
        :param timeout: Optional timeout in seconds.
        :returns: httpx.Response object.
        :raises: ConnectionError on request failures.
        :raises: Various HTTP exceptions on HTTP errors.
        """
        return await self._request('PUT', path, data=data, headers=headers,
                                   timeout=timeout)
