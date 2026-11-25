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

"""Unit tests for async Redfish client."""

import asyncio
from unittest import mock

from ironic.common.redfish import client
from ironic.common.redfish import exceptions
from ironic.common.redfish import resource
from ironic.tests import base
from ironic.tests.unit.common.redfish import utils


class TestAsyncRedfishClient(base.TestCase):
    """Test AsyncRedfishClient class."""

    def setUp(self):
        super().setUp()
        self.base_url = 'https://bmc.example.com'
        self.username = 'admin'
        self.password = 'password123'

    def test_init(self):
        """Test client initialization."""
        client_obj = client.AsyncRedfishClient(
            self.base_url,
            username=self.username,
            password=self.password,
            auth_type='basic'
        )

        self.assertEqual(self.base_url, client_obj._base_url)
        self.assertEqual('/redfish/v1', client_obj._root_prefix)
        self.assertEqual('basic', client_obj._auth_type)

    def test_init_invalid_auth_type(self):
        """Test initialization with invalid auth type."""
        self.assertRaises(
            ValueError,
            client.AsyncRedfishClient,
            self.base_url,
            auth_type='invalid'
        )

    def test_ensure_initialized_not_initialized(self):
        """Test accessing methods before initialization."""
        client_obj = client.AsyncRedfishClient(self.base_url)
        self.assertRaises(RuntimeError, client_obj._ensure_initialized)

    def test_close(self):
        """Test explicit close method."""
        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    client_obj = client.AsyncRedfishClient(self.base_url)
                    await client_obj.close()

                    mock_auth.close.assert_called_once()
                    mock_conn.close.assert_called_once()

        asyncio.run(run_test())

    def test_collection_systems(self):
        """Test getting the Systems collection."""
        root_data = {
            'Systems': {'@odata.id': '/redfish/v1/Systems'}
        }

        collection_data = {
            'Members': [
                {'@odata.id': '/redfish/v1/Systems/1'},
                {'@odata.id': '/redfish/v1/Systems/2'},
                {'@odata.id': '/redfish/v1/Systems/3'}
            ]
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    side_effect=[utils.json_response(root_data),
                                 utils.json_response(collection_data)]
                )
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        collection = await client_obj.collection('Systems')

                        self.assertIsInstance(
                            collection, resource.AsyncResourceCollection)
                        self.assertEqual(3, len(collection))

        asyncio.run(run_test())

    def test_collection_managers(self):
        """Test getting the Managers collection."""
        root_data = {
            'Managers': {'@odata.id': '/redfish/v1/Managers'}
        }

        collection_data = {
            'Members': [
                {'@odata.id': '/redfish/v1/Managers/BMC'}
            ]
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    side_effect=[utils.json_response(root_data),
                                 utils.json_response(collection_data)]
                )
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        collection = await client_obj.collection('Managers')

                        self.assertIsInstance(
                            collection, resource.AsyncResourceCollection)
                        self.assertEqual(1, len(collection))

        asyncio.run(run_test())

    def test_collection_not_found(self):
        """Test getting a collection that doesn't exist."""
        root_data = {
            'Systems': {'@odata.id': '/redfish/v1/Systems'}
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    return_value=utils.json_response(root_data))
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        try:
                            await client_obj.collection('NonExistent')
                            return None  # Should not reach here
                        except exceptions.ResourceNotFoundError as e:
                            return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.ResourceNotFoundError)

    def test_resource_by_name(self):
        """Test getting a resource by name."""
        root_data = {
            'UpdateService': {'@odata.id': '/redfish/v1/UpdateService'}
        }

        update_service_data = {
            '@odata.id': '/redfish/v1/UpdateService',
            'ServiceEnabled': True
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    side_effect=[utils.json_response(root_data),
                                 utils.json_response(update_service_data)]
                )
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        update_service = await client_obj.resource(
                            'UpdateService')

                        self.assertIsInstance(update_service,
                                              resource.AsyncResource)
                        self.assertEqual('/redfish/v1/UpdateService',
                                         update_service.path)
                        self.assertTrue(
                            update_service.field('ServiceEnabled'))

        asyncio.run(run_test())

    def test_resource_by_path(self):
        """Test getting a resource by absolute path."""
        root_data = {
            'RedfishVersion': '1.6.0'
        }

        system_data = {
            '@odata.id': '/redfish/v1/Systems/1',
            'Manufacturer': 'Dell',
            'Model': 'PowerEdge R640'
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    side_effect=[utils.json_response(root_data),
                                 utils.json_response(system_data)]
                )
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        system = await client_obj.resource(
                            '/redfish/v1/Systems/1')

                        self.assertIsInstance(system, resource.AsyncResource)
                        self.assertEqual('/redfish/v1/Systems/1', system.path)
                        self.assertEqual('Dell', system.field('Manufacturer'))
                        self.assertEqual('PowerEdge R640',
                                         system.field('Model'))

        asyncio.run(run_test())

    def test_resource_not_found(self):
        """Test getting a resource that doesn't exist."""
        root_data = {
            'UpdateService': {'@odata.id': '/redfish/v1/UpdateService'}
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    return_value=utils.json_response(root_data))
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        try:
                            await client_obj.resource('NonExistent')
                            return None  # Should not reach here
                        except exceptions.ResourceNotFoundError as e:
                            return e

        exception = asyncio.run(run_test())
        self.assertIsNotNone(exception)
        self.assertIsInstance(exception, exceptions.ResourceNotFoundError)

    def test_redfish_version(self):
        """Test getting Redfish version."""
        root_data = {
            'RedfishVersion': '1.6.0'
        }

        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    return_value=utils.json_response(root_data))
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url,
                        username=self.username,
                        password=self.password
                    ) as client_obj:
                        version = client_obj.redfish_version
                        self.assertEqual('1.6.0', version)

        asyncio.run(run_test())

    def test_redfish_version_missing(self):
        """A root without RedfishVersion reports None, as sushy does.

        DSP0266 requires the property, but refusing to work with a BMC
        that omits it would be a steep price for a version string.
        """
        async def run_test():
            with mock.patch('ironic.common.redfish.connector.AsyncConnector',
                            autospec=True) as mock_conn_class:
                mock_conn = mock.AsyncMock()
                mock_conn.get = mock.AsyncMock(
                    return_value=utils.json_response({'Name': 'root'}))
                mock_conn.__aenter__ = mock.AsyncMock(return_value=mock_conn)
                mock_conn.__aexit__ = mock.AsyncMock()
                mock_conn.close = mock.AsyncMock()
                mock_conn_class.return_value = mock_conn

                with mock.patch(
                        'ironic.common.redfish.auth.AsyncSessionOrBasicAuth',
                        autospec=True
                ) as mock_auth_class:
                    mock_auth = mock.AsyncMock()
                    mock_auth.set_context = mock.AsyncMock()
                    mock_auth.close = mock.AsyncMock()
                    mock_auth_class.return_value = mock_auth

                    async with client.AsyncRedfishClient(
                        self.base_url
                    ) as client_obj:
                        self.assertIsNone(client_obj.redfish_version)

        asyncio.run(run_test())


class TestConnectTimeoutPassThrough(base.TestCase):
    """The connect timeout has to reach the connector to do anything.

    The connector grew the parameter, but the client did not pass it,
    so a deployment setting [redfish]connect_timeout still waited out
    the much longer request timeout on every connection attempt.
    """

    @mock.patch('ironic.common.redfish.connector.AsyncConnector',
                autospec=True)
    def test_connect_timeout_reaches_the_connector(self, mock_conn_class):
        client.AsyncRedfishClient('https://bmc.example.com',
                                  default_request_timeout=60,
                                  connect_timeout=5)

        kwargs = mock_conn_class.call_args.kwargs
        self.assertEqual(5, kwargs['connect_timeout'])
        self.assertEqual(60, kwargs['default_request_timeout'])

    @mock.patch('ironic.common.redfish.connector.AsyncConnector',
                autospec=True)
    def test_connect_timeout_defaults_to_none(self, mock_conn_class):
        """Unset, nothing changes for existing callers."""
        client.AsyncRedfishClient('https://bmc.example.com')

        self.assertIsNone(mock_conn_class.call_args.kwargs['connect_timeout'])


class TestClientTaskMonitors(base.TestCase):
    """Task monitors are built from the client's own connector.

    Otherwise a caller has to reach into the client's private connector
    to poll an operation the client itself started.
    """

    def setUp(self):
        super().setUp()
        self.base_url = 'https://bmc.example.com'
        self.task_uri = '/redfish/v1/TaskService/Tasks/1'

    def _client(self, mock_conn):
        client_obj = client.AsyncRedfishClient(self.base_url)
        client_obj._connector = mock_conn
        client_obj._initialized = True
        return client_obj

    def test_task_monitor_requires_initialization(self):
        client_obj = client.AsyncRedfishClient(self.base_url)

        self.assertRaises(RuntimeError, asyncio.run,
                          client_obj.task_monitor(mock.Mock(), self.task_uri))

    def test_get_task_monitor_requires_initialization(self):
        client_obj = client.AsyncRedfishClient(self.base_url)

        self.assertRaises(RuntimeError, asyncio.run,
                          client_obj.get_task_monitor(self.task_uri))

    def test_task_monitor_from_a_202_uses_the_client_connector(self):
        mock_conn = mock.AsyncMock()
        response = utils.json_response(
            None, status_code=202, headers={'Location': self.task_uri})

        async def run_test():
            return await self._client(mock_conn).task_monitor(
                response, '/redfish/v1/Systems/1')

        monitor = asyncio.run(run_test())

        self.assertEqual(self.task_uri, monitor.task_monitor_uri)
        self.assertIs(mock_conn, monitor._connector)

    def test_get_task_monitor_polls_before_returning(self):
        """A resumed monitor must report the BMC, not an assumption."""
        mock_conn = mock.AsyncMock()
        mock_conn.get = mock.AsyncMock(
            return_value=utils.json_response(None, status_code=200))

        async def run_test():
            return await self._client(mock_conn).get_task_monitor(
                self.task_uri)

        monitor = asyncio.run(run_test())

        mock_conn.get.assert_called_once_with(path=self.task_uri)
        self.assertIs(mock_conn, monitor._connector)
        # a 200 means the task is done, which only a poll could tell us
        self.assertFalse(monitor.is_processing)


class TestClientInitOrder(base.TestCase):
    """The service root is read before authenticating.

    Session auth discovers its Sessions URI from the root's Links, so
    the root has to be fetched first. DSP0266 requires the root to be
    served without authentication, which is what makes that safe.
    """

    def _client(self, **kwargs):
        return client.AsyncRedfishClient(
            'https://bmc.example.com', username='admin', password='pw',
            **kwargs)

    def test_root_is_fetched_before_authentication(self):
        """Ordering is observable in the sequence of calls."""
        order = []
        obj = self._client()

        async def fake_refresh(expand=False):
            order.append('root')
            return obj._root

        async def fake_set_context(connector, root=None):
            order.append('auth')

        async def run_test():
            with mock.patch.object(obj._connector, '__aenter__',
                                   new=mock.AsyncMock()):
                with mock.patch.object(resource.AsyncResource, 'refresh',
                                       new=fake_refresh):
                    with mock.patch.object(obj._auth, 'set_context',
                                           new=fake_set_context):
                        await obj.__aenter__()

        asyncio.run(run_test())
        self.assertEqual(['root', 'auth'], order)

    def test_root_is_handed_to_the_authenticator(self):
        """Auth receives the root so it can discover the Sessions URI."""
        obj = self._client()
        received = {}

        async def fake_refresh(expand=False):
            return obj._root

        async def fake_set_context(connector, root=None):
            received['root'] = root

        async def run_test():
            with mock.patch.object(obj._connector, '__aenter__',
                                   new=mock.AsyncMock()):
                with mock.patch.object(resource.AsyncResource, 'refresh',
                                       new=fake_refresh):
                    with mock.patch.object(obj._auth, 'set_context',
                                           new=fake_set_context):
                        await obj.__aenter__()

        asyncio.run(run_test())
        self.assertIs(obj._root, received['root'])

    def test_root_requiring_auth_is_read_after_logging_in(self):
        """A non-compliant BMC that 401s on the root still works.

        Such a BMC offers nothing to discover from, so authenticate
        against the fallback path first and read the root afterwards.
        """
        obj = self._client()
        order = []
        attempts = []

        async def fake_refresh(expand=False):
            attempts.append(1)
            order.append('root')
            if len(attempts) == 1:
                raise exceptions.AccessError(
                    method='GET', url='/redfish/v1', response=None)
            return obj._root

        async def fake_set_context(connector, root=None):
            order.append('auth')
            received.append(root)

        received = []

        async def run_test():
            with mock.patch.object(obj._connector, '__aenter__',
                                   new=mock.AsyncMock()):
                with mock.patch.object(resource.AsyncResource, 'refresh',
                                       new=fake_refresh):
                    with mock.patch.object(obj._auth, 'set_context',
                                           new=fake_set_context):
                        await obj.__aenter__()

        asyncio.run(run_test())
        self.assertEqual(['root', 'auth', 'root'], order)
        # Nothing to discover from, so auth gets no root and falls back.
        self.assertEqual([None], received)

    def test_root_prefix_is_passed_to_the_authenticator(self):
        """A custom prefix reaches auth, so the fallback path follows it."""
        obj = self._client(root_prefix='/rf/v2')

        self.assertEqual('/rf/v2', obj._auth._root_prefix)
