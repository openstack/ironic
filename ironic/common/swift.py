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

from urllib import parse as urlparse

import openstack
from openstack.connection import exceptions as openstack_exc
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf import CONF

LOG = log.getLogger(__name__)

_SWIFT_SESSION = None


def get_swift_session():
    global _SWIFT_SESSION
    if not _SWIFT_SESSION:
        auth = keystone.get_auth('swift')
        _SWIFT_SESSION = keystone.get_session('swift', auth=auth)
    return _SWIFT_SESSION


class SwiftAPI(object):
    """API for communicating with Swift."""

    def __init__(self):
        """Initialize the connection with swift"""
        self.connection = openstack.connection.Connection(
            session=get_swift_session(),
            oslo_conf=CONF)

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
            self.connection.create_container(container)
        except openstack_exc.OpenStackCloudException as e:
            operation = _("put container")
            raise exception.SwiftOperationError(operation=operation, error=e)

        if object_headers is None:
            object_headers = {}

        try:
            obj_uuid = self.connection.create_object(
                container, obj, filename=filename, **object_headers)
        except openstack_exc.OpenStackCloudException as e:
            operation = _("put object")
            raise exception.SwiftOperationError(operation=operation,
                                                error=e)

        return obj_uuid

    def create_object_from_data(self, obj, data, container):
        """Uploads a given string to Swift.

        :param obj: The name of the object in Swift
        :param data: string data to put in the object
        :param container: The name of the container for the object.
            Defaults to the value set in the configuration options.
        :returns: The Swift UUID of the object
        :raises: utils.Error, if any operation with Swift fails.
        """
        try:
            self.connection.create_container(container)
        except openstack_exc.OpenStackCloudException as e:
            operation = _("put container")
            raise exception.SwiftOperationError(operation=operation, error=e)

        try:
            obj_uuid = self.connection.create_object(
                container, obj, data=data)
        except openstack_exc.OpenStackCloudException as e:
            operation = _("put object")
            raise exception.SwiftOperationError(operation=operation, error=e)

        return obj_uuid

    def get_temp_url_key(self):
        """Get the best temporary url key from the account headers."""
        return self.connection.object_store.get_temp_url_key()

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
        endpoint = keystone.get_endpoint('swift', session=get_swift_session())
        parse_result = urlparse.urlparse(endpoint)
        swift_object_path = '/'.join((parse_result.path, container, obj))
        temp_url_key = self.get_temp_url_key()
        if not temp_url_key:
            raise exception.MissingParameterValue(_(
                'Swift temporary URLs require a shared secret to be '
                'created. You must provide pre-generate the key on '
                'the project used to access Swift.'))
        url_path = self.generate_temp_url(
            swift_object_path, timeout, 'GET', temp_url_key=temp_url_key)
        return urlparse.urlunparse(
            (parse_result.scheme, parse_result.netloc, url_path,
             None, None, None))

    def generate_temp_url(self, path, timeout, method, temp_url_key):
        """Returns the temp url for a given path"""
        return self.connection.object_store.generate_temp_url(
            path, timeout, method, temp_url_key=temp_url_key)

    def get_object(self, object, container):
        """Downloads a given object from Swift.

        :param object: The name of the object in Swift
        :param container: The name of the container for the object.
            Defaults to the value set in the configuration options.
        :returns: Swift object
        :raises: utils.Error, if the Swift operation fails.
        """
        try:
            headers, obj = self.connection.get_object(
                object, container=container)
        except openstack_exc.OpenStackCloudException as e:
            operation = _("get object")
            raise exception.SwiftOperationError(operation=operation, error=e)

        return obj

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
        except openstack_exc.OpenStackCloudException as e:
            operation = _("delete object")
            if isinstance(e, openstack_exc.ResourceNotFound):
                raise exception.SwiftObjectNotFoundError(obj=obj,
                                                         container=container,
                                                         operation=operation)

            raise exception.SwiftOperationError(operation=operation, error=e)
