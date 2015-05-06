# Copyright 2015 Cloudbase Solutions Srl
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

import copy
import re

import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic.drivers.modules.msftocs import msftocsclient

REQUIRED_PROPERTIES = {
    'msftocs_base_url': _('Base url of the OCS chassis manager REST API, '
                          'e.g.: http://10.0.0.1:8000. Required.'),
    'msftocs_blade_id': _('Blade id, must be a number between 1 and the '
                          'maximum number of blades available in the chassis. '
                          'Required.'),
    'msftocs_username': _('Username to access the chassis manager REST API. '
                          'Required.'),
    'msftocs_password': _('Password to access the chassis manager REST API. '
                          'Required.'),
}


def get_client_info(driver_info):
    """Returns an instance of the REST API client and the blade id.

    :param driver_info: the node's driver_info dict.
    """
    client = msftocsclient.MSFTOCSClientApi(driver_info['msftocs_base_url'],
                                            driver_info['msftocs_username'],
                                            driver_info['msftocs_password'])
    return client, driver_info['msftocs_blade_id']


def get_properties():
    """Returns the driver's properties."""
    return copy.deepcopy(REQUIRED_PROPERTIES)


def _is_valid_url(url):
    """Checks whether a URL is valid.

    :param url: a url string.
    :returns: True if the url is valid or None, False otherwise.
    """
    r = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)*[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)

    return bool(isinstance(url, six.string_types) and r.search(url))


def _check_required_properties(driver_info):
    """Checks if all required properties are present.

    :param driver_info: the node's driver_info dict.
    :raises: MissingParameterValue if one or more required properties are
        missing.
    """
    missing_properties = set(REQUIRED_PROPERTIES) - set(driver_info)
    if missing_properties:
        raise exception.MissingParameterValue(
            _('The following parameters were missing: %s') %
            ' '.join(missing_properties))


def parse_driver_info(node):
    """Checks for the required properties and values validity.

    :param node: the target node.
    :raises: MissingParameterValue if one or more required properties are
        missing.
    :raises: InvalidParameterValue if a parameter value is invalid.
    """
    driver_info = node.driver_info
    _check_required_properties(driver_info)

    base_url = driver_info.get('msftocs_base_url')
    if not _is_valid_url(base_url):
        raise exception.InvalidParameterValue(
            _('"%s" is not a valid "msftocs_base_url"') % base_url)

    blade_id = driver_info.get('msftocs_blade_id')
    try:
        blade_id = int(blade_id)
    except ValueError:
        raise exception.InvalidParameterValue(
            _('"%s" is not a valid "msftocs_blade_id"') % blade_id)
    if blade_id < 1:
        raise exception.InvalidParameterValue(
            _('"msftocs_blade_id" must be greater than 0. The provided value '
              'is: %s') % blade_id)
