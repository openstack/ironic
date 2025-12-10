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

"""Async Redfish authentication mechanisms."""

import abc

from oslo_log import log

from ironic.common.redfish import exceptions

LOG = log.getLogger(__name__)


class AsyncAuthBase(metaclass=abc.ABCMeta):
    """Base class for async Redfish authentication."""

    def __init__(self, username=None, password=None, root_prefix=None):
        """Initialize authentication.

        :param username: User account with admin/server-profile access.
        :param password: User account password.
        :param root_prefix: Root prefix of the Redfish API, used to build
            paths when they cannot be discovered. Defaults to
            '/redfish/v1'.
        """
        self._username = username
        self._password = password
        self._root_prefix = root_prefix or '/redfish/v1'
        self._connector = None
        self._root = None

    async def set_context(self, connector, root=None):
        """Set connector context and authenticate.

        :param connector: AsyncConnector instance.
        :param root: Optional ``AsyncResource`` for the service root.
            Session authentication discovers the Sessions URI from it;
            without it the conventional path is used instead.
        """
        self._connector = connector
        self._root = root
        self._connector.set_auth(self)
        await self.authenticate()

    async def authenticate(self):
        """Perform authentication.

        :raises: RuntimeError if connector is not set.
        """
        if self._connector is None:
            raise RuntimeError('Connector is missing. '
                               'Forgot to call set_context()?')
        await self._do_authenticate()

    @abc.abstractmethod
    async def _do_authenticate(self):
        """Perform the actual authentication.

        Must be implemented by subclasses.
        """

    @abc.abstractmethod
    def can_refresh_session(self):
        """Check if session can be refreshed.

        :returns: True if session refresh is supported, False otherwise.
        """

    async def close(self):
        """Clean up authentication resources.

        Override in subclasses if cleanup is needed.
        """

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


class AsyncBasicAuth(AsyncAuthBase):
    """HTTP Basic Authentication.

    Uses HTTP Basic authentication for all requests.
    """

    async def _do_authenticate(self):
        """Set up basic authentication on the connector.

        No actual HTTP request needed for basic auth.
        """
        LOG.debug('Setting basic authentication connector information.')
        self._connector.set_http_basic_auth(self._username, self._password)

    def can_refresh_session(self):
        """Basic auth cannot refresh sessions.

        :returns: False
        """
        return False


class AsyncSessionAuth(AsyncAuthBase):
    """Redfish Session Authentication.

    Creates and manages a Redfish session for authentication.
    """

    def __init__(self, username=None, password=None, root_prefix=None):
        """Initialize session authentication.

        :param username: User account with admin/server-profile access.
        :param password: User account password.
        :param root_prefix: Root prefix of the Redfish API, used for the
            fallback Sessions path. Defaults to '/redfish/v1'.
        """
        super().__init__(username, password, root_prefix)
        self._session_key = None
        self._session_resource_id = None
        self._session_auth_previously_successful = False

    def _get_sessions_path(self):
        """Resolve the URI of the Sessions collection.

        DSP0266 advises discovering this from ``Links/Sessions`` in the
        service root, so prefer that. A BMC that omits the link, or that
        made the root unreadable before authentication, leaves nothing
        to discover from; fall back to the conventional path under the
        configured root prefix, as sushy does. Hardcoding the fallback
        would ignore a custom root prefix.

        :returns: the Sessions collection URI.
        """
        sessions_path = None
        try:
            sessions_path = self._root.json['Links']['Sessions']['@odata.id']
        except (AttributeError, TypeError, KeyError):
            pass

        if not sessions_path:
            sessions_path = '%s/SessionService/Sessions' % (
                self._root_prefix.rstrip('/'))
            LOG.warning('Could not discover the Redfish Sessions path from '
                        'the service root, falling back to %(path)s.',
                        {'path': sessions_path})

        return sessions_path

    def get_session_key(self):
        """Get the session authentication key.

        :returns: Session key (X-Auth-Token value).
        """
        return self._session_key

    def get_session_resource_id(self):
        """Get the session resource ID/URI.

        :returns: Session resource URI for deletion.
        """
        return self._session_resource_id

    async def _do_authenticate(self):
        """Establish a Redfish session.

        :raises: MissingHeaderError if X-Auth-Token not in response.
        :raises: ConnectionError on connection failures.
        :raises: AccessError on authentication failures.
        :raises: HTTPError on other HTTP errors.
        """
        LOG.debug('Creating Redfish session for user %(user)s',
                  {'user': self._username})

        # POST to the Sessions collection to create a session. Record
        # where it lives so the connector can tell a failed login apart
        # from any other 401 and avoid recursing into authentication.
        session_service_path = self._get_sessions_path()
        self._connector.set_sessions_uri(session_service_path)

        try:
            response = await self._connector.post(
                session_service_path,
                data={'UserName': self._username, 'Password': self._password}
            )
        except exceptions.AccessError:
            LOG.error('Authentication to the session service failed. '
                      'Please check credentials and try again.')
            raise

        # Work out where the session lives before validating the token.
        # A BMC that returns a Location but no X-Auth-Token has created
        # a session we can neither use nor authenticate a DELETE for, and
        # the URI is the only thing that lets an operator find it.
        session_resource_id = None
        if 'Location' in response.headers:
            session_resource_id = response.headers['Location']
        else:
            # Try to get from response body
            try:
                body = response.json()
                session_resource_id = body.get('@odata.id')
            except Exception:
                LOG.warning('Could not determine session resource ID. '
                            'Session cleanup may not work.')

        # Extract session key from X-Auth-Token header
        if 'X-Auth-Token' not in response.headers:
            if session_resource_id:
                LOG.warning('The BMC created session %(session)s but did '
                            'not return an X-Auth-Token header. The session '
                            'cannot be used and may have to be deleted '
                            'manually.', {'session': session_resource_id})
            raise exceptions.MissingHeaderError(
                header='X-Auth-Token',
                response=response
            )

        self._session_key = response.headers['X-Auth-Token']
        self._session_resource_id = session_resource_id

        # Mark authentication as successful
        self._session_auth_previously_successful = True

        # Set the session token on the connector
        self._connector.set_http_session_auth(self._session_key)

        LOG.debug('Redfish session created successfully')

    def can_refresh_session(self):
        """Check if session can be refreshed.

        :returns: True if session key and resource ID are available.
        """
        return (self._session_key is not None
                and self._session_resource_id is not None)

    async def refresh_session(self):
        """Refresh the Redfish session.

        Creates a new session after the previous one has expired.

        :raises: MissingHeaderError if X-Auth-Token not in response.
        :raises: ConnectionError on connection failures.
        :raises: AccessError on authentication failures.
        :raises: HTTPError on other HTTP errors.
        """
        LOG.debug('Refreshing Redfish session')
        self.reset_session_attrs()
        await self._do_authenticate()

    def reset_session_attrs(self):
        """Reset session-related attributes."""
        self._session_key = None
        self._session_resource_id = None

        # Clear auth headers from connector
        if self._connector and self._connector._session:
            self._connector._session.auth = None
            if 'X-Auth-Token' in self._connector._session.headers:
                del self._connector._session.headers['X-Auth-Token']

    async def close(self):
        """Close the Redfish session.

        Attempts to DELETE the session from the BMC. A session the BMC
        has already dropped, by expiry or reboot, answers 404, which is
        the outcome this method wants rather than a failure: the goal is
        that the session no longer exists.
        """
        if self._session_resource_id:
            try:
                LOG.debug('Deleting Redfish session %(session)s',
                          {'session': self._session_resource_id})
                await self._connector.delete(self._session_resource_id)
            except exceptions.ResourceNotFoundError:
                LOG.debug('Redfish session %(session)s was already gone '
                          'from the BMC.',
                          {'session': self._session_resource_id})
            except (exceptions.AccessError,
                    exceptions.ServerSideError) as exc:
                LOG.warning('Received exception "%(exception)s" while '
                            'attempting to delete the active session: '
                            '%(session_id)s',
                            {'exception': exc,
                             'session_id': self._session_resource_id})
            finally:
                self.reset_session_attrs()


class AsyncSessionOrBasicAuth(AsyncSessionAuth):
    """Session authentication with fallback to basic auth.

    Attempts to use session-based authentication. If session creation
    fails, falls back to HTTP Basic authentication.
    """

    def __init__(self, username=None, password=None, root_prefix=None):
        """Initialize hybrid authentication.

        :param username: User account with admin/server-profile access.
        :param password: User account password.
        :param root_prefix: Root prefix of the Redfish API, used for the
            fallback Sessions path. Defaults to '/redfish/v1'.
        """
        super().__init__(username, password, root_prefix)
        self.basic_auth = AsyncBasicAuth(username=username, password=password,
                                         root_prefix=root_prefix)

    async def _fallback_to_basic_authentication(self):
        """Fall back to basic authentication."""
        LOG.info('Falling back to basic authentication')
        self.reset_session_attrs()
        await self.basic_auth.set_context(self._connector)

    async def _do_authenticate(self):
        """Establish authentication with session or basic fallback.

        Attempts session-based authentication first. If that fails and
        no session was previously established, falls back to basic auth.

        :raises: AccessError if both session and basic auth fail.
        :raises: ConnectionError if the BMC could not be reached.
        """
        try:
            # Attempt session-based authentication
            await super()._do_authenticate()
        except exceptions.ConnectionError as e:
            # A connectivity failure says nothing about whether the BMC
            # supports sessions, so falling back to basic authentication
            # here would silently downgrade the credentials for the whole
            # client over what may be a transient fault. Let the caller
            # see it: ironic treats a connection failure as a reason to
            # stop reusing the client.
            LOG.debug('Encountered a connectivity failure while attempting '
                      'to authenticate. We will not explicitly fallback. '
                      'Error: %(error)s', {'error': e})
            raise
        except exceptions.AccessError as e:
            # Only fallback if we've never successfully established a session
            if (not self.can_refresh_session()
                    and not self._session_auth_previously_successful):
                LOG.warning('Falling back to "Basic" authentication as we '
                            'have been unable to authenticate to the BMC. '
                            'Error: %(error)s', {'error': e})
                await self._fallback_to_basic_authentication()
            else:
                # We had a session before, don't fallback
                LOG.error('Session authentication failed after previously '
                          'working. Error: %(error)s', {'error': e})
                raise
        except exceptions.RedfishError as e:
            # Any other Redfish-level failure is taken as a sign that the
            # BMC does not usefully support sessions, so fall back if we
            # never had one. Deliberately not a bare ``Exception``: a
            # programming error in the session code says nothing about
            # the BMC, and silently continuing on basic auth would hide
            # it for the lifetime of the client.
            if (not self.can_refresh_session()
                    and not self._session_auth_previously_successful):
                LOG.debug('Session authentication error, trying basic auth. '
                          'Error: %(error)s', {'error': e})
                await self._fallback_to_basic_authentication()
            else:
                raise

    async def refresh_session(self):
        """Refresh session if available, otherwise no-op.

        Only refreshes if session authentication is being used.
        """
        if self.can_refresh_session():
            await super().refresh_session()
        else:
            LOG.debug('Cannot refresh session, using basic authentication')

    async def close(self):
        """Close session if one exists."""
        if self.can_refresh_session():
            await super().close()
