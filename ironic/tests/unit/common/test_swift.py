# Copyright 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

import openstack
from openstack.connection import exceptions as openstack_exc

from ironic.common import exception
from ironic.common import keystone
from ironic.common import swift
from ironic.conf import CONF
from ironic.tests import base


@mock.patch.object(swift, 'get_swift_session', autospec=True,
                   return_value=mock.MagicMock(verify=False,
                                               cert=('spam', 'ham'),
                                               timeout=42))
@mock.patch.object(openstack.connection, 'Connection', autospec=True)
class SwiftTestCase(base.TestCase):

    def setUp(self):
        super(SwiftTestCase, self).setUp()
        self.swift_exception = openstack_exc.OpenStackCloudException()

    @mock.patch.object(keystone, 'get_auth', autospec=True,
                       return_value=mock.Mock())
    @mock.patch.object(keystone, 'get_endpoint', autospec=True,
                       return_value='http://example.com/v1')
    def test___init__(self, get_endpoint_mock, get_auth_mock, connection_mock,
                      session_mock):
        """Check if client is properly initialized with swift"""
        swiftapi = swift.SwiftAPI()
        connection_mock.assert_called_once_with(
            session=session_mock.return_value,
            oslo_conf=CONF
        )
        self.assertEqual(connection_mock.return_value, swiftapi.connection)

    def test_create_object(self, connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_object.return_value = 'object-uuid'

        object_uuid = swiftapi.create_object('container', 'object',
                                             'some-file-location',
                                             object_headers={'foo': 'bar'})

        connection.create_container.assert_called_once_with('container')
        connection.create_object.assert_called_once_with(
            'container', 'object', filename='some-file-location', foo='bar')
        self.assertEqual('object-uuid', object_uuid)

    def test_create_object_create_container_fails(self, connection_mock,
                                                  session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_container.side_effect = self.swift_exception
        self.assertRaises(exception.SwiftOperationError,
                          swiftapi.create_object, 'container',
                          'object', 'some-file-location')
        connection.create_container.assert_called_once_with('container')
        self.assertFalse(connection.create_object.called)

    def test_create_object_create_object_fails(self, connection_mock,
                                               session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_object.side_effect = self.swift_exception
        self.assertRaises(exception.SwiftOperationError,
                          swiftapi.create_object, 'container',
                          'object', 'some-file-location')
        connection.create_container.assert_called_once_with('container')
        connection.create_object.assert_called_once_with(
            'container', 'object', filename='some-file-location')

    def test_create_object_from_data(self, connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_object.return_value = 'object-uuid'

        object_uuid = swiftapi.create_object_from_data(
            'object', 'some-data', 'container')

        connection.create_container.assert_called_once_with('container')
        connection.create_object.assert_called_once_with(
            'container', 'object', data='some-data')
        self.assertEqual('object-uuid', object_uuid)

    def test_create_object_from_data_create_container_fails(
            self, connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_container.side_effect = self.swift_exception
        self.assertRaises(exception.SwiftOperationError,
                          swiftapi.create_object_from_data,
                          'object', 'some-data', 'container')
        connection.create_container.assert_called_once_with('container')
        self.assertFalse(connection.create_object.called)

    def test_create_object_from_data_create_object_fails(self, connection_mock,
                                                         session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        connection.create_object.side_effect = self.swift_exception
        self.assertRaises(exception.SwiftOperationError,
                          swiftapi.create_object_from_data,
                          'object', 'some-data', 'container')
        connection.create_container.assert_called_once_with('container')
        connection.create_object.assert_called_once_with(
            'container', 'object', data='some-data')

    @mock.patch.object(keystone, 'get_auth', autospec=True)
    @mock.patch.object(keystone, 'get_endpoint', autospec=True)
    def test_get_temp_url(self, get_endpoint_mock, get_auth_mock,
                          connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        get_endpoint_mock.return_value = 'http://example.com/v1/AUTH_tenant_id'
        object_store = connection.object_store
        object_store.get_temp_url_key.return_value = 'secretkey'

        object_store.generate_temp_url.return_value = \
            '/v1/AUTH_tenant_id/temp-url-path'
        temp_url_returned = swiftapi.get_temp_url('container', 'object', 10)
        object_path_expected = '/v1/AUTH_tenant_id/container/object'
        object_store.generate_temp_url.assert_called_once_with(
            object_path_expected, 10, 'GET', temp_url_key='secretkey')
        self.assertEqual('http://example.com/v1/AUTH_tenant_id/temp-url-path',
                         temp_url_returned)

    def test_delete_object(self, connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        connection = connection_mock.return_value
        swiftapi.delete_object('container', 'object')
        connection.delete_object.assert_called_once_with('container',
                                                         'object')

    def test_delete_object_exc_resource_not_found(self, connection_mock,
                                                  session_mock):
        swiftapi = swift.SwiftAPI()
        exc = openstack_exc.ResourceNotFound(message="Resource not found")
        connection = connection_mock.return_value
        connection.delete_object.side_effect = exc
        self.assertRaises(exception.SwiftObjectNotFoundError,
                          swiftapi.delete_object, 'container', 'object')
        connection.delete_object.assert_called_once_with('container',
                                                         'object')

    def test_delete_object_exc(self, connection_mock, session_mock):
        swiftapi = swift.SwiftAPI()
        exc = self.swift_exception
        connection = connection_mock.return_value
        connection.delete_object.side_effect = exc
        self.assertRaises(exception.SwiftOperationError,
                          swiftapi.delete_object, 'container', 'object')
        connection.delete_object.assert_called_once_with('container',
                                                         'object')
