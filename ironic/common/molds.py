# Copyright (c) 2021 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import base64
import requests
import tenacity

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import swift

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


def save_configuration(task, url, data):
    """Store configuration mold to indicated location.

    :param task: A TaskManager instance.
    :param name: URL of the configuration item to save to.
    :param data: Content of JSON data to save.

    :raises IronicException: If using Swift storage and no authentication
        token found in task's context.
    :raises HTTPError: If failed to complete HTTP request.
    """
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            requests.exceptions.ConnectionError),
        stop=tenacity.stop_after_attempt(CONF.molds.retry_attempts),
        wait=tenacity.wait_fixed(CONF.molds.retry_interval),
        reraise=True
    )
    def _request(url, data, auth_header):
        return requests.put(
            url, data=json.dumps(data, indent=2), headers=auth_header)

    auth_header = _get_auth_header(task)
    response = _request(url, data, auth_header)
    response.raise_for_status()


def get_configuration(task, url):
    """Gets configuration mold from indicated location.

    :param task: A TaskManager instance.
    :param url: URL of the configuration item to get.

    :returns: JSON configuration mold

    :raises IronicException: If using Swift storage and no authentication
        token found in task's context.
    :raises HTTPError: If failed to complete HTTP request.
    """
    @tenacity.retry(
        retry=tenacity.retry_if_exception_type(
            requests.exceptions.ConnectionError),
        stop=tenacity.stop_after_attempt(CONF.molds.retry_attempts),
        wait=tenacity.wait_fixed(CONF.molds.retry_interval),
        reraise=True
    )
    def _request(url, auth_header):
        return requests.get(url, headers=auth_header)

    auth_header = _get_auth_header(task)
    response = _request(url, auth_header)
    if response.status_code == requests.codes.ok:
        if not response.content:
            raise exception.IronicException(_(
                "Configuration mold for node %(node_uuid)s at %(url)s is "
                "empty") % {'node_uuid': task.node.uuid, 'url': url})
        try:
            return response.json()
        except json.decoder.JSONDecodeError as jde:
            raise exception.IronicException(_(
                "Configuration mold for node %(node_uuid)s at %(url)s has "
                "invalid JSON: %(error)s)")
                % {'node_uuid': task.node.uuid, 'url': url, 'error': jde})

    response.raise_for_status()


def _get_auth_header(task):
    """Based on setup of configuration mold storage gets authentication header

    :param task: A TaskManager instance.
    :raises IronicException: If using Swift storage and no authentication
        token found in task's context.
    """
    auth_header = None
    if CONF.molds.storage == 'swift':
        # TODO(ajya) Need to update to use Swift client and context session
        auth_token = swift.get_swift_session().get_token()
        if auth_token:
            auth_header = {'X-Auth-Token': auth_token}
        else:
            raise exception.IronicException(
                _('Missing auth_token for configuration mold access for node '
                  '%s') % task.node.uuid)
    elif CONF.molds.storage == 'http':
        if CONF.molds.user and CONF.molds.password:
            auth_header = {'Authorization': 'Basic %s'
                           % base64.encode_as_text(
                               '%s:%s' % (CONF.molds.user,
                                          CONF.molds.password))}
    return auth_header
