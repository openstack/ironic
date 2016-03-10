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

from oslo_config import cfg
from six.moves import http_client
from six.moves.urllib import parse
from swiftclient import client as swift_client
from swiftclient import exceptions as swift_exceptions
from swiftclient import utils as swift_utils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import keystone

swift_opts = [
    cfg.IntOpt('swift_max_retries',
               default=2,
               help=_('Maximum number of times to retry a Swift request, '
                      'before failing.'))
]


CONF = cfg.CONF
CONF.register_opts(swift_opts, group='swift')

CONF.import_opt('admin_user', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('admin_tenant_name', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('admin_password', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('auth_uri', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('auth_version', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('insecure', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('cafile', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')
CONF.import_opt('region_name', 'keystonemiddleware.auth_token',
                group='keystone_authtoken')


class SwiftAPI(object):
    """API for communicating with Swift."""

    def __init__(self,
                 user=None,
                 tenant_name=None,
                 key=None,
                 auth_url=None,
                 auth_version=None,
                 region_name=None):
        """Constructor for creating a SwiftAPI object.

        :param user: the name of the user for Swift account
        :param tenant_name: the name of the tenant for Swift account
        :param key: the 'password' or key to authenticate with
        :param auth_url: the url for authentication
        :param auth_version: the version of api to use for authentication
        :param region_name: the region used for getting endpoints of swift
        """
        user = user or CONF.keystone_authtoken.admin_user
        tenant_name = tenant_name or CONF.keystone_authtoken.admin_tenant_name
        key = key or CONF.keystone_authtoken.admin_password
        auth_url = auth_url or CONF.keystone_authtoken.auth_uri
        auth_version = auth_version or CONF.keystone_authtoken.auth_version
        auth_url = keystone.get_keystone_url(auth_url, auth_version)
        params = {'retries': CONF.swift.swift_max_retries,
                  'insecure': CONF.keystone_authtoken.insecure,
                  'cacert': CONF.keystone_authtoken.cafile,
                  'user': user,
                  'tenant_name': tenant_name,
                  'key': key,
                  'authurl': auth_url,
                  'auth_version': auth_version}
        region_name = region_name or CONF.keystone_authtoken.region_name
        if region_name:
            params['os_options'] = {'region_name': region_name}

        self.connection = swift_client.Connection(**params)

    def create_object(self, container, object, filename,
                      object_headers=None):
        """Uploads a given file to Swift.

        :param container: The name of the container for the object.
        :param object: The name of the object in Swift
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
                                                      object,
                                                      fileobj,
                                                      headers=object_headers)
            except swift_exceptions.ClientException as e:
                operation = _("put object")
                raise exception.SwiftOperationError(operation=operation,
                                                    error=e)

        return obj_uuid

    def get_temp_url(self, container, object, timeout):
        """Returns the temp url for the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param object: The name of the Swift object.
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

        storage_url, token = self.connection.get_auth()
        parse_result = parse.urlparse(storage_url)
        swift_object_path = '/'.join((parse_result.path, container, object))
        temp_url_key = account_info['x-account-meta-temp-url-key']
        url_path = swift_utils.generate_temp_url(swift_object_path, timeout,
                                                 temp_url_key, 'GET')
        return parse.urlunparse((parse_result.scheme,
                                 parse_result.netloc,
                                 url_path,
                                 None,
                                 None,
                                 None))

    def delete_object(self, container, object):
        """Deletes the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param object: The name of the object in Swift to be deleted.
        :raises: SwiftObjectNotFoundError, if object is not found in Swift.
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            self.connection.delete_object(container, object)
        except swift_exceptions.ClientException as e:
            operation = _("delete object")
            if e.http_status == http_client.NOT_FOUND:
                raise exception.SwiftObjectNotFoundError(object=object,
                                                         container=container,
                                                         operation=operation)

            raise exception.SwiftOperationError(operation=operation, error=e)

    def head_object(self, container, object):
        """Retrieves the information about the given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param object: The name of the object in Swift
        :returns: The information about the object as returned by
            Swift client's head_object call.
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            return self.connection.head_object(container, object)
        except swift_exceptions.ClientException as e:
            operation = _("head object")
            raise exception.SwiftOperationError(operation=operation, error=e)

    def update_object_meta(self, container, object, object_headers):
        """Update the metadata of a given Swift object.

        :param container: The name of the container in which Swift object
            is placed.
        :param object: The name of the object in Swift
        :param object_headers: the headers for the object to pass to Swift
        :raises: SwiftOperationError, if operation with Swift fails.
        """
        try:
            self.connection.post_object(container, object, object_headers)
        except swift_exceptions.ClientException as e:
            operation = _("post object")
            raise exception.SwiftOperationError(operation=operation, error=e)
