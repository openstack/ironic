#
# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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

from six.moves import http_client
from six.moves.urllib import parse
from swiftclient import client as swift_client
from swiftclient import exceptions as swift_exceptions
from swiftclient import utils as swift_utils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import CONF

_SWIFT_SESSION = None


def _get_swift_session():
    global _SWIFT_SESSION
    if not _SWIFT_SESSION:
        auth = keystone.get_auth('swift')
        _SWIFT_SESSION = keystone.get_session('swift', auth=auth)
    return _SWIFT_SESSION


class SwiftAPI(object):
    """API for communicating with Swift."""

    def __init__(self):
        """Initialize the connection with swift or radosgw

        :raises: ConfigInvalid if required keystone authorization credentials
         with swift are missing.
        """
        params = {}
        if CONF.deploy.object_store_endpoint_type == 'radosgw':
            params = {'authurl': CONF.swift.auth_url,
                      'user': CONF.swift.username,
                      'key': CONF.swift.password}
        else:
            # NOTE(aNuposic): Session will be initiated only when connection
            # with swift is initialized. Since v3.2.0 swiftclient supports
            # instantiating the API client from keystoneauth session.
            params = {'session': _get_swift_session()}

            if CONF.swift.endpoint_override:
                params['os_options'] = {
                    'object_storage_url': CONF.swift.endpoint_override}

        self.connection = swift_client.Connection(**params)

    def create_object(self, container, obj, filename,
                      object_headers=None):
        """Uploads a given file to Swift.

        :param container: The name of the container for the object.
        :param obj: The name of the object in Swift
        :param filename: The file to upload, as the object data
        :param object_headers: the headers for the object to pass to Swift
        :returns: The Swift UUID of the object
        :raises: SwiftOperationError, if any operation with Swift fails.
        """
        try:
            self.connection.put_container(container)
        except swift_exceptions.ClientException as e:
            operation = _("put container")
            raise exception.SwiftOperationError(operation=operation, error=e)

        with open(filename, "r") as fileobj:

            try:
                obj_uuid = self.connection.put_object(container,
                                                      obj,
                                                      fileobj,
                                                      headers=object_headers)
            except swift_exceptions.ClientException as e:
                operation = _("put object")
                raise exception.SwiftOperationError(operation=operation,
                                                    error=e)

        return obj_uuid

    def get_temp_url(self, container, obj, timeout):
        """Returns the temp url for the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param obj: The name of the Swift object.
        :param timeout: The timeout in seconds after which the generated url
            should expire.
        :returns: The temp url for the object.
        :raises: SwiftOperationError, if any operation with Swift fails.
        """
        try:
            account_info = self.connection.head_account()
        except swift_exceptions.ClientException as e:
            operation = _("head account")
            raise exception.SwiftOperationError(operation=operation,
                                                error=e)

        parse_result = parse.urlparse(self.connection.url)
        swift_object_path = '/'.join((parse_result.path, container, obj))
        temp_url_key = account_info['x-account-meta-temp-url-key']
        url_path = swift_utils.generate_temp_url(swift_object_path, timeout,
                                                 temp_url_key, 'GET')
        return parse.urlunparse((parse_result.scheme,
                                 parse_result.netloc,
                                 url_path,
                                 None,
                                 None,
                                 None))

    def delete_object(self, container, obj):
        """Deletes the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param obj: The name of the object in Swift to be deleted.
        :raises: SwiftObjectNotFoundError, if object is not found in Swift.
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            self.connection.delete_object(container, obj)
        except swift_exceptions.ClientException as e:
            operation = _("delete object")
            if e.http_status == http_client.NOT_FOUND:
                raise exception.SwiftObjectNotFoundError(obj=obj,
                                                         container=container,
                                                         operation=operation)

            raise exception.SwiftOperationError(operation=operation, error=e)

    def head_object(self, container, obj):
        """Retrieves the information about the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param obj: The name of the object in Swift
        :returns: The information about the object as returned by
            Swift client's head_object call.
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            return self.connection.head_object(container, obj)
        except swift_exceptions.ClientException as e:
            operation = _("head object")
            raise exception.SwiftOperationError(operation=operation, error=e)

    def update_object_meta(self, container, obj, object_headers):
        """Update the metadata of a given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param obj: The name of the object in Swift
        :param object_headers: the headers for the object to pass to Swift
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            self.connection.post_object(container, obj, object_headers)
        except swift_exceptions.ClientException as e:
            operation = _("post object")
            raise exception.SwiftOperationError(operation=operation, error=e)
