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
"""
iBMC Driver common utils
"""

import functools
import os

from oslo_log import log
from oslo_utils import importutils
from oslo_utils import netutils
from oslo_utils import strutils
import retrying

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conductor import task_manager
from ironic.conf import CONF

ibmc_client = importutils.try_import('ibmcclient')
ibmc_error = importutils.try_import('ibmc_client.exceptions')

if ibmc_error:
    try:
        # NOTE(Qianbiao.NG) from python-ibmcclient>=0.2.2, ConnectionError is
        # renamed to IBMCConnectionError
        ibmc_error.IBMCConnectionError
    except AttributeError:
        ibmc_error.IBMCConnectionError = ibmc_error.ConnectionError

LOG = log.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ibmc_address': _('The URL address to the iBMC controller. It must '
                      'include the authority portion of the URL. '
                      'If the scheme is missing, https is assumed. '
                      'For example: https://mgmt.vendor.com. Required.'),
    'ibmc_username': _('User account with admin/server-profile access '
                       'privilege. Required.'),
    'ibmc_password': _('User account password. Required.'),
}

OPTIONAL_PROPERTIES = {
    'ibmc_verify_ca': _('Either a Boolean value, a path to a CA_BUNDLE '
                        'file or directory with certificates of trusted '
                        'CAs. If set to True the driver will verify the '
                        'host certificates; if False the driver will '
                        'ignore verifying the SSL certificate. If it\'s '
                        'a path the driver will use the specified '
                        'certificate or one of the certificates in the '
                        'directory. Defaults to True. Optional.'),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def parse_driver_info(node):
    """Parse the information required for Ironic to connect to iBMC.

    :param node: an Ironic node object
    :returns: dictionary of parameters
    :raises: InvalidParameterValue on malformed parameter(s)
    :raises: MissingParameterValue on missing parameter(s)
    """
    driver_info = node.driver_info or {}
    missing_info = [key for key in REQUIRED_PROPERTIES
                    if not driver_info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            'Missing the following iBMC properties in node '
            '%(node)s driver_info: %(info)s') % {'node': node.uuid,
                                                 'info': missing_info})

    # Validate the iBMC address
    address = driver_info['ibmc_address']
    if '://' not in address:
        address = 'https://%s' % address

    parsed = netutils.urlsplit(address)
    if not parsed.netloc:
        raise exception.InvalidParameterValue(
            _('Invalid iBMC address %(address)s set in '
              'driver_info/ibmc_address on node %(node)s') %
            {'address': address, 'node': node.uuid})

    # Check if verify_ca is a Boolean or a file/directory in the file-system
    verify_ca = driver_info.get('ibmc_verify_ca', True)
    if isinstance(verify_ca, str):
        if not os.path.exists(verify_ca):
            try:
                verify_ca = strutils.bool_from_string(verify_ca, strict=True)
            except ValueError:
                raise exception.InvalidParameterValue(
                    _('Invalid value type set in driver_info/'
                      'ibmc_verify_ca on node %(node)s. '
                      'The value should be a Boolean or the path '
                      'to a file/directory, not "%(value)s"'
                      ) % {'value': verify_ca, 'node': node.uuid})
    elif not isinstance(verify_ca, bool):
        raise exception.InvalidParameterValue(
            _('Invalid value type set in driver_info/ibmc_verify_ca '
              'on node %(node)s. The value should be a Boolean or the path '
              'to a file/directory, not "%(value)s"') % {'value': verify_ca,
                                                         'node': node.uuid})
    return {'address': address,
            'username': driver_info.get('ibmc_username'),
            'password': driver_info.get('ibmc_password'),
            'verify_ca': verify_ca}


def revert_dictionary(d):
    return {v: k for k, v in d.items()}


def handle_ibmc_exception(action):
    """Decorator to handle iBMC client exception.

    Decorated functions must take a :class:`TaskManager` as the first
    parameter.
    """

    def decorator(f):

        def should_retry(e):
            connect_error = isinstance(e, exception.IBMCConnectionError)
            if connect_error:
                LOG.info(_('Failed to connect to iBMC, will retry now. '
                           'Max retry times is %(retry_times)d.'),
                         {'retry_times': CONF.ibmc.connection_attempts})
            return connect_error

        @retrying.retry(
            retry_on_exception=should_retry,
            stop_max_attempt_number=CONF.ibmc.connection_attempts,
            wait_fixed=CONF.ibmc.connection_retry_interval * 1000)
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            # NOTE(dtantsur): this code could be written simpler, but then unit
            # testing decorated functions is pretty hard, as we usually pass a
            # Mock object instead of TaskManager there.
            if len(args) > 1:
                is_task_mgr = isinstance(args[1], task_manager.TaskManager)
                task = args[1] if is_task_mgr else args[0]
            else:
                task = args[0]

            node = task.node

            try:
                return f(*args, **kwargs)
            except ibmc_error.IBMCConnectionError as e:
                error = (_('Failed to connect to iBMC for node %(node)s, '
                           'Error: %(error)s')
                         % {'node': node.uuid, 'error': e})
                LOG.error(error)
                raise exception.IBMCConnectionError(node=node.uuid,
                                                    error=error)
            except ibmc_error.IBMCClientError as e:
                error = (_('Failed to %(action)s for node %(node)s, '
                           'Error %(error)s')
                         % {'node': node.uuid, 'action': action, 'error': e})
                LOG.error(error)
                raise exception.IBMCError(node=node.uuid, error=error)

        return wrapper

    return decorator
