#   Copyright 2025 Red Hat, Inc.
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

"""Functions for VNC graphical console drivers and novncproxy"""

import datetime
import secrets
from urllib import parse

from oslo_utils import timeutils

from ironic.common import exception
from ironic.conf import CONF


def novnc_authorize(node):
    """Create and save a console token

    A random token is created and is stored in the node
    ``driver_internal_info` along with creation time.

    This is called by graphical console drivers when ``start_console`` is
    called.

    :param node: the node object
    :returns: an authorized token
    """
    token = secrets.token_urlsafe()
    node.set_driver_internal_info('novnc_secret_token', token)
    node.timestamp_driver_internal_info('novnc_secret_token_created')
    node.save()
    return token


def novnc_unauthorize(node):
    """Clear any existing console token

    :param node: the node object
    """
    node.del_driver_internal_info('novnc_secret_token')
    node.del_driver_internal_info('novnc_secret_token_created')
    node.save()


def novnc_validate(node, token):
    """Validate the token.

    :param node: the node object
    :param token: the token for the authorization
    :returns: The ConsoleAuthToken object if valid

    The token is valid if the token is in the database and the expires
    time has not passed.
    """
    if not token:
        raise exception.NotAuthorized()
    node_token = node.driver_internal_info.get('novnc_secret_token')
    if not node_token:
        # missing token info for node
        raise exception.NotAuthorized()

    if token != node_token:
        # token doesn't match
        raise exception.NotAuthorized()

    if token_valid_until(node) < timeutils.utcnow():
        # token has expired
        raise exception.NotAuthorized()


def token_valid_until(node):
    """Calculate when the token will expire

    :param node: the node object
    :returns: a datetime object representing expiration time
    :raises: NotAuthorized if no timestamp is stored in the node
    """
    token_created = node.driver_internal_info.get('novnc_secret_token_created')
    if not token_created:
        # missing token created timestamp for node
        raise exception.NotAuthorized()
    timeout = CONF.vnc.token_timeout
    created_dt = datetime.datetime.strptime(token_created,
                                            '%Y-%m-%dT%H:%M:%S.%f')

    time_delta = datetime.timedelta(seconds=timeout)

    return created_dt + time_delta


def get_console(node):
    """Get the type and connection information about the console

    :param node: the node object
    :returns: A dict containing keys 'type', 'url'
    """
    uuid = node.uuid
    base_url = CONF.vnc.public_url
    token = node.driver_internal_info.get('novnc_secret_token')
    path = parse.quote(f"websockify?node={uuid}&token={token}")
    url = f"{base_url}?path={path}"
    return {'type': 'vnc', 'url': url}
