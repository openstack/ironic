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
Common functionalities shared between different DRAC modules.
"""

from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils

drac_client = importutils.try_import('dracclient.client')
drac_constants = importutils.try_import('dracclient.constants')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'drac_address': _('IP address or hostname of the DRAC card. Required.'),
    'drac_username': _('username used for authentication. Required.'),
    'drac_password': _('password used for authentication. Required.')
}
OPTIONAL_PROPERTIES = {
    'drac_port': _('port used for WS-Man endpoint; default is 443. Optional.'),
    'drac_path': _('path used for WS-Man endpoint; default is "/wsman". '
                   'Optional.'),
    'drac_protocol': _('protocol used for WS-Man endpoint; one of http, https;'
                       ' default is "https". Optional.'),
}
DEPRECATED_PROPERTIES = {
    'drac_host': _('IP address or hostname of the DRAC card. DEPRECATED, '
                   'PLEASE USE "drac_address" INSTEAD.'),
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(DEPRECATED_PROPERTIES)


def parse_driver_info(node):
    """Parse a node's driver_info values.

    Parses the driver_info of the node, reads default values
    and returns a dict containing the combination of both.

    :param node: an ironic node object.
    :returns: a dict containing information from driver_info
              and default values.
    :raises: InvalidParameterValue if some mandatory information
             is missing on the node or on invalid inputs.
    """
    driver_info = node.driver_info
    parsed_driver_info = {}

    if 'drac_host' in driver_info and 'drac_address' not in driver_info:
        LOG.warning('The driver_info["drac_host"] property is deprecated '
                    'and will be removed in the Pike release. Please '
                    'update the node %s driver_info field to use '
                    '"drac_address" instead', node.uuid)
        address = driver_info.pop('drac_host', None)
        if address:
            driver_info['drac_address'] = address
    elif 'drac_host' in driver_info and 'drac_address' in driver_info:
        LOG.warning('Both driver_info["drac_address"] and '
                    'driver_info["drac_host"] properties are '
                    'specified for node %s. Please remove the '
                    '"drac_host" property from the node. Ignoring '
                    '"drac_host" for now', node.uuid)

    error_msgs = []
    for param in REQUIRED_PROPERTIES:
        try:
            parsed_driver_info[param] = str(driver_info[param])
        except KeyError:
            error_msgs.append(_("'%s' not supplied to DracDriver.") % param)
        except UnicodeEncodeError:
            error_msgs.append(_("'%s' contains non-ASCII symbol.") % param)

    parsed_driver_info['drac_port'] = driver_info.get('drac_port', 443)

    try:
        parsed_driver_info['drac_path'] = str(driver_info.get('drac_path',
                                                              '/wsman'))
    except UnicodeEncodeError:
        error_msgs.append(_("'drac_path' contains non-ASCII symbol."))

    try:
        parsed_driver_info['drac_protocol'] = str(
            driver_info.get('drac_protocol', 'https'))

        if parsed_driver_info['drac_protocol'] not in ['http', 'https']:
            error_msgs.append(_("'drac_protocol' must be either 'http' or "
                                "'https'."))
    except UnicodeEncodeError:
        error_msgs.append(_("'drac_protocol' contains non-ASCII symbol."))

    if error_msgs:
        msg = (_('The following errors were encountered while parsing '
                 'driver_info:\n%s') % '\n'.join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    port = parsed_driver_info['drac_port']
    parsed_driver_info['drac_port'] = utils.validate_network_port(
        port, 'drac_port')

    return parsed_driver_info


def get_drac_client(node):
    """Return a DRACClient object from python-dracclient library.

    :param node: an ironic node object.
    :returns: a DRACClient object.
    :raises: InvalidParameterValue if mandatory information is missing on the
             node or on invalid input.
    """
    driver_info = parse_driver_info(node)
    client = drac_client.DRACClient(driver_info['drac_address'],
                                    driver_info['drac_username'],
                                    driver_info['drac_password'],
                                    driver_info['drac_port'],
                                    driver_info['drac_path'],
                                    driver_info['drac_protocol'])

    return client
