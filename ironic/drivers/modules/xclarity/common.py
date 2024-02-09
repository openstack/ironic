#    Copyright 2017 Lenovo, Inc.
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

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conf import CONF

LOG = logging.getLogger(__name__)

client = importutils.try_import('xclarity_client.client')
xclarity_client_constants = importutils.try_import('xclarity_client.constants')
xclarity_client_exceptions = importutils.try_import(
    'xclarity_client.exceptions')

REQUIRED_ON_DRIVER_INFO = {
    'xclarity_manager_ip': _("IP address of the XClarity Controller."),
    'xclarity_username': _("Username for the XClarity Controller "
                           "with administrator privileges."),
    'xclarity_password': _("Password for xclarity_username."),
    'xclarity_hardware_id': _("Server Hardware ID managed by XClarity."),
}

OPTIONAL_ON_DRIVER_INFO = {
    'xclarity_port': _("Port to be used for XClarity Controller connection. "
                       "Optional"),
}

COMMON_PROPERTIES = {}
COMMON_PROPERTIES.update(REQUIRED_ON_DRIVER_INFO)
COMMON_PROPERTIES.update(OPTIONAL_ON_DRIVER_INFO)


def get_properties():
    return COMMON_PROPERTIES


def parse_driver_info(node):
    """Parse a node's driver_info values.

    Parses the driver_info of the node, reads default values
    and returns a dict containing the combination of both.

    :param node: an ironic node object to get information from.
    :returns: a dict containing information parsed from driver_info.
    :raises: InvalidParameterValue if some required information
             is missing on the node or inputs is invalid.
    """
    driver_info = node.driver_info
    parsed_driver_info = {}

    error_msgs = []
    for param in REQUIRED_ON_DRIVER_INFO:
        if param == "xclarity_hardware_id":
            try:
                parsed_driver_info[param] = str(driver_info[param])
            except KeyError:
                error_msgs.append(_("'%s' not provided to XClarity.") % param)
            except UnicodeEncodeError:
                error_msgs.append(_("'%s' contains non-ASCII symbol.") % param)
        else:
            # corresponding config names don't have 'xclarity_' prefix
            if param in driver_info:
                parsed_driver_info[param] = str(driver_info[param])
            elif param not in driver_info and\
                    CONF.xclarity.get(param[len('xclarity_'):]) is not None:
                parsed_driver_info[param] = str(
                    CONF.xclarity.get(param[len('xclarity_'):]))
                LOG.warning('The configuration [xclarity]/%(config)s '
                            'is deprecated and will be removed in the '
                            'Stein release. Please update the node '
                            '%(node_uuid)s driver_info field to use '
                            '"%(field)s" instead',
                            {'config': param[len('xclarity_'):],
                             'node_uuid': node.uuid, 'field': param})
            else:
                error_msgs.append(_("'%s' not provided to XClarity.") % param)

    port = driver_info.get('xclarity_port', CONF.xclarity.get('port'))
    parsed_driver_info['xclarity_port'] = utils.validate_network_port(
        port, 'xclarity_port')

    if error_msgs:
        msg = (_('The following errors were encountered while parsing '
                 'driver_info:\n%s') % '\n'.join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    return parsed_driver_info


def get_xclarity_client(node):
    """Generates an instance of the XClarity client.

    Generates an instance of the XClarity client using the imported
    xclarity_client library.

    :param node: an ironic node object.
    :returns: an instance of the XClarity client
    :raises: XClarityError if can't get to the XClarity client
    """
    driver_info = parse_driver_info(node)
    try:
        xclarity_client = client.Client(
            ip=driver_info.get('xclarity_manager_ip'),
            username=driver_info.get('xclarity_username'),
            password=driver_info.get('xclarity_password'),
            port=driver_info.get('xclarity_port')
        )
    except xclarity_client_exceptions.XClarityError as exc:
        msg = (_("Error getting connection to XClarity address: %(ip)s. "
                 "Error: %(exc)s"),
               {'ip': driver_info.get('xclarity_manager_ip'), 'exc': exc})
        raise exception.XClarityError(error=msg)
    return xclarity_client


def get_server_hardware_id(node):
    """Validates node configuration and returns xclarity hardware id.

    Validates whether node configuration is consistent with XClarity and
    returns the XClarity Hardware ID for a specific node.
    :param node: node object to get information from
    :returns: the XClarity Hardware ID for a specific node
    :raises: MissingParameterValue if unable to validate XClarity Hardware ID

    """
    xclarity_hardware_id = node.driver_info.get('xclarity_hardware_id')
    if not xclarity_hardware_id:
        msg = (_("Error validating node driver info, "
                 "server uuid: %s missing xclarity_hardware_id") %
               node.uuid)
        raise exception.MissingParameterValue(err=msg)
    return xclarity_hardware_id


def translate_xclarity_power_state(power_state):
    """Translates XClarity's power state strings to be consistent with Ironic.

    :param power_state: power state string to be translated
    :returns: the translated power state
    """
    power_states_map = {
        xclarity_client_constants.STATE_POWER_ON: states.POWER_ON,
        xclarity_client_constants.STATE_POWER_OFF: states.POWER_OFF,
    }

    return power_states_map.get(power_state, states.ERROR)


def translate_xclarity_power_action(power_action):
    """Translates ironic's power action strings to XClarity's format.

    :param power_action: power action string to be translated
    :returns: the power action translated
    """

    power_action_map = {
        states.POWER_ON: xclarity_client_constants.ACTION_POWER_ON,
        states.POWER_OFF: xclarity_client_constants.ACTION_POWER_OFF,
        states.REBOOT: xclarity_client_constants.ACTION_REBOOT
    }

    return power_action_map[power_action]
