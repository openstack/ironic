# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
Common functionalities shared between different iLO modules.
"""

from oslo.config import cfg
from oslo.utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.openstack.common import log as logging

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')


STANDARD_LICENSE = 1
ESSENTIALS_LICENSE = 2
ADVANCED_LICENSE = 3


opts = [
    cfg.IntOpt('client_timeout',
               default=60,
               help='Timeout (in seconds) for iLO operations'),
    cfg.IntOpt('client_port',
               default=443,
               help='Port to be used for iLO operations'),
]

CONF = cfg.CONF
CONF.register_opts(opts, group='ilo')

LOG = logging.getLogger(__name__)

REQUIRED_PROPERTIES = {
    'ilo_address': _("IP address or hostname of the iLO. Required."),
    'ilo_username': _("username for the iLO with administrator privileges. "
                      "Required."),
    'ilo_password': _("password for ilo_username. Required.")
}
OPTIONAL_PROPERTIES = {
    'client_port': _("port to be used for iLO operations. Optional."),
    'client_timeout': _("timeout (in seconds) for iLO operations. Optional.")
}
COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def parse_driver_info(node):
    """Gets the driver specific Node deployment info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver.

    :param node: an ironic node object.
    :returns: a dict containing information from driver_info
        and default values.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    info = node.driver_info
    d_info = {}

    error_msgs = []
    for param in REQUIRED_PROPERTIES:
        try:
            d_info[param] = info[param]
        except KeyError:
            error_msgs.append(_("'%s' not supplied to IloDriver.") % param)
    if error_msgs:
        msg = (_("The following parameters were mising while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.MissingParameterValue(msg)

    for param in OPTIONAL_PROPERTIES:
        value = info.get(param, CONF.ilo.get(param))
        try:
            value = int(value)
        except ValueError:
            error_msgs.append(_("'%s' is not an integer.") % param)
            continue
        d_info[param] = value

    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    return d_info


def get_ilo_object(node):
    """Gets an IloClient object from proliantutils library.

    Given an ironic node object, this method gives back a IloClient object
    to do operations on the iLO.

    :param node: an ironic node object.
    :returns: an IloClient object.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    driver_info = parse_driver_info(node)
    ilo_object = ilo_client.IloClient(driver_info['ilo_address'],
                                      driver_info['ilo_username'],
                                      driver_info['ilo_password'],
                                      driver_info['client_timeout'],
                                      driver_info['client_port'])
    return ilo_object


def get_ilo_license(node):
    """Gives the current installed license on the node.

    Given an ironic node object, this method queries the iLO
    for currently installed license and returns it back.

    :param node: an ironic node object.
    :returns: a constant defined in this module which
        refers to the current license installed on the node.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    :raises: IloOperationError if it failed to retrieve the
        installed licenses from the iLO.
    """
    # Get the ilo client object, and then the license from the iLO
    ilo_object = get_ilo_object(node)
    try:
        license_info = ilo_object.get_all_licenses()
    except ilo_client.IloError as ilo_exception:
        raise exception.IloOperationError(operation=_('iLO license check'),
                                          error=str(ilo_exception))

    # Check the license to see if the given license exists
    current_license_type = license_info['LICENSE_TYPE']

    if current_license_type.endswith("Advanced"):
        return ADVANCED_LICENSE
    elif current_license_type.endswith("Essentials"):
        return ESSENTIALS_LICENSE
    else:
        return STANDARD_LICENSE
