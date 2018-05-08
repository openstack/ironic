# Copyright 2015 FUJITSU LIMITED
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
Common functionalities shared between different iRMC modules.
"""
from oslo_log import log as logging
from oslo_utils import importutils
import six

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF

scci = importutils.try_import('scciclient.irmc.scci')
elcm = importutils.try_import('scciclient.irmc.elcm')

LOG = logging.getLogger(__name__)
REQUIRED_PROPERTIES = {
    'irmc_address': _("IP address or hostname of the iRMC. Required."),
    'irmc_username': _("Username for the iRMC with administrator privileges. "
                       "Required."),
    'irmc_password': _("Password for irmc_username. Required."),
}
OPTIONAL_PROPERTIES = {
    'irmc_port': _("Port to be used for iRMC operations; either 80 or 443. "
                   "The default value is 443. Optional."),
    'irmc_auth_method': _("Authentication method for iRMC operations; "
                          "either 'basic' or 'digest'. The default value is "
                          "'basic'. Optional."),
    'irmc_client_timeout': _("Timeout (in seconds) for iRMC operations. "
                             "The default value is 60. Optional."),
    'irmc_sensor_method': _("Sensor data retrieval method; either "
                            "'ipmitool' or 'scci'. The default value is "
                            "'ipmitool'. Optional."),
    'irmc_snmp_version': _("SNMP protocol version; either 'v1', 'v2c', or "
                           "'v3'. The default value is 'v2c'. Optional."),
    'irmc_snmp_port': _("SNMP port. The default is 161. Optional."),
    'irmc_snmp_community': _("SNMP community required for versions 'v1' and "
                             "'v2c'. The default value is 'public'. "
                             "Optional."),
    'irmc_snmp_security': _("SNMP security name required for version 'v3'. "
                            "Optional."),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)


def parse_driver_info(node):
    """Gets the specific Node driver info.

    This method validates whether the 'driver_info' property of the
    supplied node contains the required information for this driver.

    :param node: An ironic node object.
    :returns: A dict containing information from driver_info
        and default values.
    :raises: InvalidParameterValue if invalid value is contained
        in the 'driver_info' property.
    :raises: MissingParameterValue if some mandatory key is missing
        in the 'driver_info' property.
    """
    info = node.driver_info
    missing_info = [key for key in REQUIRED_PROPERTIES if not info.get(key)]
    if missing_info:
        raise exception.MissingParameterValue(_(
            "Missing the following iRMC parameters in node's"
            " driver_info: %s.") % missing_info)

    req = {key: value for key, value in info.items()
           if key in REQUIRED_PROPERTIES}
    # corresponding config names don't have 'irmc_' prefix
    opt = {param: info.get(param, CONF.irmc.get(param[len('irmc_'):]))
           for param in OPTIONAL_PROPERTIES}
    d_info = dict(req, **opt)

    error_msgs = []
    if (d_info['irmc_auth_method'].lower() not in ('basic', 'digest')):
        error_msgs.append(
            _("Value '%s' is not supported for 'irmc_auth_method'.") %
            d_info['irmc_auth_method'])
    if d_info['irmc_port'] not in (80, 443):
        error_msgs.append(
            _("Value '%s' is not supported for 'irmc_port'.") %
            d_info['irmc_port'])
    if not isinstance(d_info['irmc_client_timeout'], int):
        error_msgs.append(
            _("Value '%s' is not an integer for 'irmc_client_timeout'") %
            d_info['irmc_client_timeout'])
    if d_info['irmc_sensor_method'].lower() not in ('ipmitool', 'scci'):
        error_msgs.append(
            _("Value '%s' is not supported for 'irmc_sensor_method'.") %
            d_info['irmc_sensor_method'])
    if d_info['irmc_snmp_version'].lower() not in ('v1', 'v2c', 'v3'):
        error_msgs.append(
            _("Value '%s' is not supported for 'irmc_snmp_version'.") %
            d_info['irmc_snmp_version'])
    if not isinstance(d_info['irmc_snmp_port'], int):
        error_msgs.append(
            _("Value '%s' is not an integer for 'irmc_snmp_port'") %
            d_info['irmc_snmp_port'])
    if (d_info['irmc_snmp_version'].lower() in ('v1', 'v2c')
        and d_info['irmc_snmp_community']
        and not isinstance(d_info['irmc_snmp_community'], six.string_types)):
        error_msgs.append(
            _("Value '%s' is not a string for 'irmc_snmp_community'") %
            d_info['irmc_snmp_community'])
    if d_info['irmc_snmp_version'].lower() == 'v3':
        if d_info['irmc_snmp_security']:
            if not isinstance(d_info['irmc_snmp_security'], six.string_types):
                error_msgs.append(
                    _("Value '%s' is not a string for "
                      "'irmc_snmp_security'") % d_info['irmc_snmp_security'])
        else:
            error_msgs.append(
                _("'irmc_snmp_security' has to be set for SNMP version 3."))
    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    return d_info


def get_irmc_client(node):
    """Gets an iRMC SCCI client.

    Given an ironic node object, this method gives back a iRMC SCCI client
    to do operations on the iRMC.

    :param node: An ironic node object.
    :returns: scci_cmd partial function which takes a SCCI command param.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    """
    driver_info = parse_driver_info(node)

    scci_client = scci.get_client(
        driver_info['irmc_address'],
        driver_info['irmc_username'],
        driver_info['irmc_password'],
        port=driver_info['irmc_port'],
        auth_method=driver_info['irmc_auth_method'],
        client_timeout=driver_info['irmc_client_timeout'])
    return scci_client


def update_ipmi_properties(task):
    """Update ipmi properties to node driver_info.

    :param task: A task from TaskManager.
    """
    node = task.node
    info = node.driver_info

    # updating ipmi credentials
    info['ipmi_address'] = info.get('irmc_address')
    info['ipmi_username'] = info.get('irmc_username')
    info['ipmi_password'] = info.get('irmc_password')

    # saving ipmi credentials to task object
    task.node.driver_info = info


def get_irmc_report(node):
    """Gets iRMC SCCI report.

    Given an ironic node object, this method gives back a iRMC SCCI report.

    :param node: An ironic node object.
    :returns: A xml.etree.ElementTree object.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node.
    :raises: scci.SCCIInvalidInputError if required parameters are invalid.
    :raises: scci.SCCIClientError if SCCI failed.
    """
    driver_info = parse_driver_info(node)

    return scci.get_report(
        driver_info['irmc_address'],
        driver_info['irmc_username'],
        driver_info['irmc_password'],
        port=driver_info['irmc_port'],
        auth_method=driver_info['irmc_auth_method'],
        client_timeout=driver_info['irmc_client_timeout'])


def set_secure_boot_mode(node, enable):
    """Enable or disable UEFI Secure Boot

    :param node: An ironic node object.
    :param enable: Boolean value. True if the secure boot to be
        enabled.
    :raises: IRMCOperationError if the operation fails.
    """
    driver_info = parse_driver_info(node)

    try:
        elcm.set_secure_boot_mode(driver_info, enable)
        LOG.info("Set secure boot to %(flag)s for node %(node)s",
                 {'flag': enable, 'node': node.uuid})
    except scci.SCCIError as irmc_exception:
        LOG.error("Failed to set secure boot to %(flag)s for node %(node)s",
                  {'flag': enable, 'node': node.uuid})
        raise exception.IRMCOperationError(
            operation=_("setting secure boot mode"),
            error=irmc_exception)
