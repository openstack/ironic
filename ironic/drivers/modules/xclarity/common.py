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
from ironic.conf import CONF

LOG = logging.getLogger(__name__)

client = importutils.try_import('xclarity_client.client')
xclarity_client_constants = importutils.try_import('xclarity_client.constants')
xclarity_client_exceptions = importutils.try_import(
    'xclarity_client.exceptions')

REQUIRED_ON_DRIVER_INFO = {
    'xclarity_hardware_id': _("XClarity Server Hardware ID. "
                              "Required in driver_info."),
}

COMMON_PROPERTIES = {
    'xclarity_address': _("IP address of the XClarity node."),
    'xclarity_username': _("Username for the XClarity with administrator "
                           "privileges."),
    'xclarity_password': _("Password for xclarity_username."),
    'xclarity_port': _("Port to be used for xclarity_username."),
}

COMMON_PROPERTIES.update(REQUIRED_ON_DRIVER_INFO)


def get_properties():
    return COMMON_PROPERTIES


def get_xclarity_client():
    """Generates an instance of the XClarity client.

    Generates an instance of the XClarity client using the imported
    xclarity_client library.

    :returns: an instance of the XClarity client
    :raises: XClarityError if can't get to the XClarity client
    """
    try:
        xclarity_client = client.Client(
            ip=CONF.xclarity.manager_ip,
            username=CONF.xclarity.username,
            password=CONF.xclarity.password,
            port=CONF.xclarity.port
        )
    except xclarity_client_exceptions.XClarityError as exc:
        msg = (_("Error getting connection to XClarity manager IP: %(ip)s. "
                 "Error: %(exc)s"), {'ip': CONF.xclarity.manager_ip,
                                     'exc': exc})
        raise XClarityError(error=msg)
    return xclarity_client


def get_server_hardware_id(node):
    """Validates node configuration and returns xclarity hardware id.

    Validates whether node configutation is consistent with XClarity and
    returns the XClarity Hardware ID for a specific node.
    :param: node: node object to get information from
    :returns: the XClarity Hardware ID for a specific node
    :raises: MissingParameterValue if unable to validate XClarity Hardware ID

    """
    xclarity_hardware_id = node.driver_info.get('xclarity_hardware_id')
    if not xclarity_hardware_id:
        msg = (_("Error validating node driver info, "
                 "server uuid: %s missing xclarity_hardware_id") %
               node.uuid)
        raise exception.MissingParameterValue(error=msg)
    return xclarity_hardware_id


def translate_xclarity_power_state(power_state):
    """Translates XClarity's power state strings to be consistent with Ironic.

    :param: power_state: power state string to be translated
    :returns: the translated power state
    """
    power_states_map = {
        xclarity_client_constants.STATE_POWER_ON: states.POWER_ON,
        xclarity_client_constants.STATE_POWER_OFF: states.POWER_OFF,
    }

    return power_states_map.get(power_state, states.ERROR)


def translate_xclarity_power_action(power_action):
    """Translates ironic's power action strings to XClarity's format.

    :param: power_action: power action string to be translated
    :returns: the power action translated
    """

    power_action_map = {
        states.POWER_ON: xclarity_client_constants.ACTION_POWER_ON,
        states.POWER_OFF: xclarity_client_constants.ACTION_POWER_OFF,
        states.REBOOT: xclarity_client_constants.ACTION_REBOOT
    }

    return power_action_map[power_action]


def is_node_managed_by_xclarity(xclarity_client, node):
    """Determines whether dynamic allocation is enabled for a specifc node.

    :param: xclarity_client: an instance of the XClarity client
    :param: node: node object to get information from
    :returns: Boolean depending on whether node is managed by XClarity
    """
    try:
        hardware_id = get_server_hardware_id(node)
        return xclarity_client.is_node_managed(hardware_id)
    except exception.MissingParameterValue:
        return False


class XClarityError(exception.IronicException):
    _msg_fmt = _("XClarity exception occurred. Error: %(error)s")
