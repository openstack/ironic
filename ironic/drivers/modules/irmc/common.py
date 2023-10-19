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
import os

from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import strutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import utils
from ironic.conf import CONF
import ironic.drivers.modules.irmc.packaging_version as version
from ironic.drivers.modules import snmp

scci = importutils.try_import('scciclient.irmc.scci')
elcm = importutils.try_import('scciclient.irmc.elcm')
scci_mod = importutils.try_import('scciclient')

LOG = logging.getLogger(__name__)


# List of xxx_interface & implementation pair which uses SNMP internally
# and iRMC driver supports
INTERFACE_IMPL_LIST_WITH_SNMP = {
    'inspect_interface': {'irmc', },
    'power_interface': {'irmc', }}

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
}

OPTIONAL_DRIVER_INFO_PROPERTIES = {
    'irmc_verify_ca': _('Either a Boolean value, a path to a CA_BUNDLE '
                        'file or directory with certificates of trusted '
                        'CAs. If set to True the driver will verify the '
                        'host certificates; if False the driver will '
                        'ignore verifying the SSL certificate. If it\'s '
                        'a path the driver will use the specified '
                        'certificate or one of the certificates in the '
                        'directory. Defaults to True. Optional'),
}

SNMP_PROPERTIES = {
    'irmc_snmp_version': _("SNMP protocol version; either 'v1', 'v2c', or "
                           "'v3'. The default value is 'v2c'. Optional."),
    'irmc_snmp_port': _("SNMP port. The default is 161. Optional."),
    'irmc_snmp_community': _("SNMP community required for versions 'v1' and "
                             "'v2c'. The default value is 'public'. "
                             "Optional."),
    'irmc_snmp_security': _("SNMP security name required for version 'v3'. "
                            "Optional."),
}

SNMP_V3_REQUIRED_PROPERTIES = {
    'irmc_snmp_user': _("SNMPv3 User-based Security Model (USM) username. "
                        "Required for version 'v3’. "),
    'irmc_snmp_auth_password': _("SNMPv3 message authentication key. Must be "
                                 "8+ characters long. Required when message "
                                 "authentication is used. Will be ignored if "
                                 "the version of python-scciclient is before "
                                 "0.11.3."),
    'irmc_snmp_priv_password': _("SNMPv3 message privacy key. Must be 8+ "
                                 "characters long. Required when message "
                                 "privacy is used. Will be ignored if the "
                                 "version of python-scciclient is before "
                                 "0.11.3."),
}

SNMP_V3_OPTIONAL_PROPERTIES = {
    'irmc_snmp_auth_proto': _("SNMPv3 message authentication protocol ID. "
                              "Required for version 'v3'. Will be ignored if "
                              "the version of python-scciclient is before "
                              "0.11.3. If using iRMC S4/S5, only 'sha' is "
                              "supported. If using iRMC S6, the valid "
                              "options are 'sha256', 'sha384', 'sha512'."),
    'irmc_snmp_priv_proto': _("SNMPv3 message privacy (encryption) protocol "
                              "ID. Required for version 'v3'. Will be ignored "
                              "if the version of python-scciclient is before "
                              "0.11.3. 'aes' is supported."),
}

COMMON_PROPERTIES = REQUIRED_PROPERTIES.copy()
COMMON_PROPERTIES.update(OPTIONAL_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_DRIVER_INFO_PROPERTIES)
COMMON_PROPERTIES.update(SNMP_PROPERTIES)
COMMON_PROPERTIES.update(SNMP_V3_REQUIRED_PROPERTIES)
COMMON_PROPERTIES.update(SNMP_V3_OPTIONAL_PROPERTIES)

SCCI_CERTIFICATION_SUPPORT_VERSION_RANGES = [
    {'min': '0.8.2', 'max': '0.9.0'},
    {'min': '0.9.4', 'max': '0.10.0'},
    {'min': '0.10.1', 'max': '0.11.0'},
    {'min': '0.11.3', 'max': '0.12.0'},
    {'min': '0.12.0', 'max': '0.13.0'}]

SCCI_SNMPv3_AUTHENTICATION_SUPPORT_VERSION_RANGES = [
    {'min': '0.10.1', 'max': '0.11.0'},
    {'min': '0.11.3', 'max': '0.12.0'},
    {'min': '0.12.2', 'max': '0.13.0'}]


def _scci_version_in(version_ranges):
    scciclient_version = version.parse(scci_mod.__version__)
    for rangev in version_ranges:
        if (version.parse(rangev['min']) <= scciclient_version
                < version.parse(rangev['max'])):
            return True
    return False


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
    opt_driver_info = {param: info.get(param)
                       for param in OPTIONAL_DRIVER_INFO_PROPERTIES}
    d_info = dict(req, **opt, **opt_driver_info)
    d_info['irmc_port'] = utils.validate_network_port(
        d_info['irmc_port'], 'irmc_port')

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

    verify_ca = d_info.get('irmc_verify_ca')
    if verify_ca is None:
        d_info['irmc_verify_ca'] = verify_ca = CONF.webserver_verify_ca

    # Check if verify_ca is a Boolean or a file/directory in the file-system
    if isinstance(verify_ca, str):
        if ((os.path.isdir(verify_ca) and os.path.isabs(verify_ca))
            or (os.path.isfile(verify_ca) and os.path.isabs(verify_ca))):
            # If it's fullpath and dir/file, we don't need to do anything
            pass
        else:
            try:
                d_info['irmc_verify_ca'] = strutils.bool_from_string(
                    verify_ca, strict=True)
            except ValueError:
                error_msgs.append(
                    _('Invalid value type set in driver_info/'
                      'irmc_verify_ca on node %(node)s. '
                      'The value should be a Boolean or the path '
                      'to a file/directory, not "%(value)s"'
                      ) % {'value': verify_ca, 'node': node.uuid})
    elif isinstance(verify_ca, bool):
        # If it's a boolean it's grand, we don't need to do anything
        pass
    else:
        error_msgs.append(
            _('Invalid value type set in driver_info/irmc_verify_ca '
              'on node %(node)s. The value should be a Boolean or the path '
              'to a file/directory, not "%(value)s"') % {'value': verify_ca,
                                                         'node': node.uuid})

    if error_msgs:
        msg = (_("The following errors were encountered while parsing "
                 "driver_info:\n%s") % "\n".join(error_msgs))
        raise exception.InvalidParameterValue(msg)

    d_info.update(_parse_snmp_driver_info(node, info))

    return d_info


def _parse_snmp_driver_info(node, info):
    """Parses the SNMP related driver_info parameters.

    :param node: An Ironic node object.
    :param info: driver_info dictionary.
    :returns: A dictionary containing SNMP information.
    :raises: MissingParameterValue if any of the mandatory
        parameter values are not provided.
    :raises: InvalidParameterValue if there is any invalid
        value provided.
    """
    snmp_info = {param: info.get(param, CONF.irmc.get(param[len('irmc_'):]))
                 for param in SNMP_PROPERTIES}
    valid_versions = {"v1": snmp.SNMP_V1,
                      "v2c": snmp.SNMP_V2C,
                      "v3": snmp.SNMP_V3}

    for int_name, impl_list in INTERFACE_IMPL_LIST_WITH_SNMP.items():
        if getattr(node, int_name) in impl_list:
            break
    else:
        return snmp_info

    if snmp_info['irmc_snmp_version'].lower() not in valid_versions:
        raise exception.InvalidParameterValue(_(
            "Value '%s' is not supported for 'irmc_snmp_version'.") %
            snmp_info['irmc_snmp_version']
        )
    snmp_info["irmc_snmp_version"] = \
        valid_versions[snmp_info["irmc_snmp_version"].lower()]

    snmp_info['irmc_snmp_port'] = utils.validate_network_port(
        snmp_info['irmc_snmp_port'], 'irmc_snmp_port')

    if snmp_info['irmc_snmp_version'] != snmp.SNMP_V3:
        if (snmp_info['irmc_snmp_community']
            and not isinstance(snmp_info['irmc_snmp_community'], str)):
            raise exception.InvalidParameterValue(_(
                "Value '%s' is not a string for 'irmc_snmp_community'") %
                snmp_info['irmc_snmp_community'])
        if utils.is_fips_enabled():
            raise exception.InvalidParameterValue(_(
                "'v3' has to be set for 'irmc_snmp_version' "
                "when FIPS mode is enabled."))

    else:
        # Parse snmp user info
        if 'irmc_snmp_user' in info:
            if not isinstance(info['irmc_snmp_user'], str):
                raise exception.InvalidParameterValue(_(
                    "Value %s is not a string for 'irmc_snmp_user'.") %
                    info['irmc_snmp_user'])
            snmp_info['irmc_snmp_user'] = info['irmc_snmp_user']
            if snmp_info['irmc_snmp_security']:
                LOG.warning(_("'irmc_snmp_security' is ignored in favor of "
                              "'irmc_snmp_user'. Please remove "
                              "'irmc_snmp_security' from node %s "
                              "configuration."), node.uuid)
        else:
            if not snmp_info['irmc_snmp_security']:
                raise exception.MissingParameterValue(_(
                    "'irmc_snmp_user' should be set when using SNMPv3."))
            if not isinstance(snmp_info['irmc_snmp_security'], str):
                raise exception.InvalidParameterValue(_(
                    "Value %s is not a string for 'irmc_snmp_security'.") %
                    snmp_info['irmc_snmp_security'])
            snmp_info['irmc_snmp_user'] = snmp_info['irmc_snmp_security']

        if _scci_version_in(SCCI_SNMPv3_AUTHENTICATION_SUPPORT_VERSION_RANGES):
            snmp_info.update(_parse_snmp_v3_crypto_info(info))
        else:
            # For compatible with old version of python-scciclient
            snmp_info['irmc_snmp_security'] = snmp_info['irmc_snmp_user']
            if 'irmc_snmp_auth_password' in info or \
                    'irmc_snmp_priv_password' in info:
                LOG.warning(_("'irmc_snmp_auth_password' and "
                              "'irmc_snmp_priv_password' in node %(node)s "
                              "configuration are ignored. "
                              "Python-scciclient version %(version)s can only "
                              "communicate with iRMC with no authentication "
                              "protocol setted. This means the authentication "
                              "protocol, private protocol and password of the "
                              "server's SNMPv3 user should all be blank, "
                              "otherwise python-scciclient will encounter an "
                              "authentication error. If you want to set "
                              "password, please update python-scciclient to "
                              "a newer version (>=0.11.3, <0.12.0)."),
                            {'node': node.uuid,
                             'version': scci_mod.__version__})

    return snmp_info


def _parse_snmp_v3_crypto_info(info):
    snmp_info = {}
    valid_values = {'irmc_snmp_auth_proto': ['sha', 'sha256', 'sha384',
                                             'sha512'],
                    'irmc_snmp_priv_proto': ['aes']}
    valid_protocols = {'irmc_snmp_auth_proto': snmp.snmp_auth_protocols,
                       'irmc_snmp_priv_proto': snmp.snmp_priv_protocols}
    snmp_keys = {'irmc_snmp_auth_password', 'irmc_snmp_priv_password'}

    for param in snmp_keys:
        try:
            snmp_info[param] = info[param]
        except KeyError:
            raise exception.MissingParameterValue(_(
                "%s should be set when using SNMPv3.") % param)

        if not isinstance(snmp_info[param], str):
            raise exception.InvalidParameterValue(_(
                "The value of %s is not a string.") % param)
        if len(snmp_info[param]) < 8:
            raise exception.InvalidParameterValue(_(
                "%s is too short. (8+ chars required)") % param)

    for param in SNMP_V3_OPTIONAL_PROPERTIES:
        value = None
        try:
            value = info[param]
            if value not in valid_values[param]:
                raise exception.InvalidParameterValue(_(
                    "Invalid value %(value)s given for driver info parameter "
                    "%(param)s, the valid values are %(valid_values)s.") %
                    {'param': param,
                     'value': value,
                     'valid_values': valid_values[param]})
        except KeyError:
            value = CONF.irmc.get(param[len('irmc_'):])
        snmp_info[param] = valid_protocols[param].get(value)
        if not snmp_info[param]:
            raise exception.InvalidParameterValue(_(
                "Unknown SNMPv3 protocol %(value)s given for "
                "driver info parameter %(param)s") % {'param': param,
                                                      'value': value})

    return snmp_info


def get_irmc_client(node):
    """Gets an iRMC SCCI client.

    Given an ironic node object, this method gives back a iRMC SCCI client
    to do operations on the iRMC.

    :param node: An ironic node object.
    :returns: scci_cmd partial function which takes a SCCI command param.
    :raises: InvalidParameterValue on invalid inputs.
    :raises: MissingParameterValue if some mandatory information
        is missing on the node
    :raises: IRMCOperationError if iRMC operation failed
    """
    driver_info = parse_driver_info(node)

    if _scci_version_in(SCCI_CERTIFICATION_SUPPORT_VERSION_RANGES):
        scci_client = scci.get_client(
            driver_info['irmc_address'],
            driver_info['irmc_username'],
            driver_info['irmc_password'],
            port=driver_info['irmc_port'],
            auth_method=driver_info['irmc_auth_method'],
            verify=driver_info.get('irmc_verify_ca'),
            client_timeout=driver_info['irmc_client_timeout'])
    else:
        if driver_info['irmc_port'] == 443:
            LOG.warning("Installed version of python-scciclient doesn't "
                        "support certification on HTTPS connection.")
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

    if _scci_version_in(SCCI_CERTIFICATION_SUPPORT_VERSION_RANGES):
        report = scci.get_report(
            driver_info['irmc_address'],
            driver_info['irmc_username'],
            driver_info['irmc_password'],
            port=driver_info['irmc_port'],
            auth_method=driver_info['irmc_auth_method'],
            verify=driver_info.get('irmc_verify_ca'),
            client_timeout=driver_info['irmc_client_timeout'])
    else:
        if driver_info['irmc_port'] == 443:
            LOG.warning("Installed version of python-scciclient doesn't "
                        "support certification on HTTPS connection.")
        report = scci.get_report(
            driver_info['irmc_address'],
            driver_info['irmc_username'],
            driver_info['irmc_password'],
            port=driver_info['irmc_port'],
            auth_method=driver_info['irmc_auth_method'],
            client_timeout=driver_info['irmc_client_timeout'])
    return report


def get_secure_boot_mode(node):
    """Get the current secure boot mode.

    :param node: An ironic node object.
    :raises: UnsupportedDriverExtension if secure boot is not present.
    :raises: IRMCOperationError if the operation fails.
    """
    driver_info = parse_driver_info(node)

    try:
        return elcm.get_secure_boot_mode(driver_info)
    except elcm.SecureBootConfigNotFound:
        raise exception.UnsupportedDriverExtension(
            driver=node.driver, extension='get_secure_boot_state')
    except scci.SCCIError as irmc_exception:
        LOG.error("Failed to get secure boot for node %s", node.uuid)
        raise exception.IRMCOperationError(
            operation=_("getting secure boot mode"),
            error=irmc_exception)


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
