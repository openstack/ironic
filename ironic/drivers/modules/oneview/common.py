# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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

import re

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils
from six.moves.urllib import parse

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF
from ironic.drivers import utils

LOG = logging.getLogger(__name__)

hponeview_client = importutils.try_import('hpOneView.oneview_client')
redfish = importutils.try_import('redfish')
client_exception = importutils.try_import('hpOneView.exceptions')

REQUIRED_ON_DRIVER_INFO = {
    'server_hardware_uri': _("Server Hardware URI. Required in driver_info."),
}

REQUIRED_ON_PROPERTIES = {
    'server_hardware_type_uri': _(
        "Server Hardware Type URI. Required in properties/capabilities."
    ),
    'server_profile_template_uri': _(
        "Server Profile Template URI to clone from. "
        "Required in properties/capabilities."
    ),
}

OPTIONAL_ON_PROPERTIES = {
    'enclosure_group_uri': _(
        "Enclosure Group URI. Optional in properties/capabilities."),
}

ILOREST_BASE_PORT = "443"

COMMON_PROPERTIES = {}
COMMON_PROPERTIES.update(REQUIRED_ON_DRIVER_INFO)
COMMON_PROPERTIES.update(REQUIRED_ON_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_ON_PROPERTIES)

# NOTE(xavierr): We don't want to translate NODE_IN_USE_BY_ONEVIEW and
# SERVER_HARDWARE_ALLOCATION_ERROR to avoid inconsistency in the nodes
# caused by updates on translation in upgrades of ironic.
NODE_IN_USE_BY_ONEVIEW = 'node in use by OneView'
SERVER_HARDWARE_ALLOCATION_ERROR = 'server hardware allocation error'


def prepare_manager_url(manager_url):
    # NOTE(mrtenio) python-oneviewclient uses https or http in the manager_url
    # while python-hpOneView does not. This will not be necessary when
    # python-hpOneView client is the only OneView library.
    if manager_url:
        url_match = "^(http[s]?://)?([^/]+)(/.*)?$"
        manager_url = re.search(url_match, manager_url).group(2)
    return manager_url


def get_hponeview_client():
    """Generate an instance of the hpOneView client.

    Generates an instance of the hpOneView client using the hpOneView library.

    :returns: an instance of the OneViewClient
    :raises: InvalidParameterValue if mandatory information is missing on the
             node or on invalid input.
    :raises: OneViewError if try a secure connection without CA certificate.
    """
    manager_url = prepare_manager_url(CONF.oneview.manager_url)

    insecure = CONF.oneview.allow_insecure_connections
    ssl_certificate = CONF.oneview.tls_cacert_file

    if not (insecure or ssl_certificate):
        msg = _("TLS CA certificate to connect with OneView is missing.")
        raise exception.OneViewError(error=msg)

    # NOTE(nicodemos) Ignore the CA certificate if it's an insecure connection
    if insecure and ssl_certificate:
        LOG.warning("Performing an insecure connection with OneView, the CA "
                    "certificate file: %s will be ignored.", ssl_certificate)
        ssl_certificate = None

    config = {
        "ip": manager_url,
        "credentials": {
            "userName": CONF.oneview.username,
            "password": CONF.oneview.password
        },
        "ssl_certificate": ssl_certificate
    }
    return hponeview_client.OneViewClient(config)


def get_ilorest_client(server_hardware):
    """Generate an instance of the iLORest library client.

    :param: server_hardware: a server hardware uuid or uri
    :returns: an instance of the iLORest client
    :raises: InvalidParameterValue if mandatory information is missing on the
             node or on invalid input.
    """
    oneview_client = get_hponeview_client()
    remote_console = oneview_client.server_hardware.get_remote_console_url(
        server_hardware
    )
    host_ip, ilo_token = _get_ilo_access(remote_console)
    base_url = "https://%s:%s" % (host_ip, ILOREST_BASE_PORT)
    return redfish.rest_client(base_url=base_url, sessionkey=ilo_token)


def _get_ilo_access(remote_console):
    """Get the needed information to access ilo.

    Get the host_ip and a token of an iLO remote console instance which can be
    used to perform operations on that controller.

    The Remote Console url has the following format:
    hplocons://addr=1.2.3.4&sessionkey=a79659e3b3b7c8209c901ac3509a6719

    :param remote_console: OneView Remote Console object with a
                           remoteConsoleUrl
    :returns: A tuple with the Host IP and Token to access ilo, for
              example: ('1.2.3.4', 'a79659e3b3b7c8209c901ac3509a6719')
    """
    url = remote_console.get('remoteConsoleUrl')
    url_parse = parse.urlparse(url)
    host_ip = parse.parse_qs(url_parse.netloc).get('addr')[0]
    token = parse.parse_qs(url_parse.netloc).get('sessionkey')[0]
    return host_ip, token


def verify_node_info(node):
    """Verifies if fields and namespaces of a node are valid.

    Verifies if the 'driver_info' field and the 'properties/capabilities'
    namespace exist and are not empty.

    :param: node: node object to be verified
    :raises: InvalidParameterValue if required node capabilities and/or
             driver_info are malformed or missing
    :raises: MissingParameterValue if required node capabilities and/or
             driver_info are missing
    """
    capabilities_dict = utils.capabilities_to_dict(
        node.properties.get('capabilities', '')
    )
    driver_info = node.driver_info

    _verify_node_info('properties/capabilities', capabilities_dict,
                      REQUIRED_ON_PROPERTIES)

    _verify_node_info('driver_info', driver_info,
                      REQUIRED_ON_DRIVER_INFO)


def get_oneview_info(node):
    """Gets OneView information from the node.

    :param: node: node object to get information from
    :returns: a dictionary containing:
    :param server_hardware_uri: the uri of the server hardware in OneView
    :param server_hardware_type_uri: the uri of the server hardware type in
                                     OneView
    :param enclosure_group_uri: the uri of the enclosure group in OneView
    :server_profile_template_uri: the uri of the server profile template in
                                  OneView
    :raises: OneViewInvalidNodeParameter if node capabilities are malformed
    """

    try:
        capabilities_dict = utils.capabilities_to_dict(
            node.properties.get('capabilities', '')
        )
    except exception.InvalidParameterValue as e:
        raise exception.OneViewInvalidNodeParameter(node_uuid=node.uuid,
                                                    error=e)

    driver_info = node.driver_info

    oneview_info = {
        'server_hardware_uri':
            driver_info.get('server_hardware_uri'),
        'server_hardware_type_uri':
            capabilities_dict.get('server_hardware_type_uri'),
        'enclosure_group_uri':
            capabilities_dict.get('enclosure_group_uri'),
        'server_profile_template_uri':
            capabilities_dict.get('server_profile_template_uri'),
        'applied_server_profile_uri':
            driver_info.get('applied_server_profile_uri'),
    }

    return oneview_info


def validate_oneview_resources_compatibility(task):
    """Validate if the node configuration is consistent with OneView.

    This method calls hpOneView functions to validate if the node
    configuration is consistent with the OneView resources it represents,
    including serverHardwareUri, serverHardwareTypeUri, serverGroupUri
    serverProfileTemplateUri, enclosureGroupUri and node ports. If any
    validation fails, the driver will raise an appropriate OneViewError.

    :param task: a TaskManager instance containing the node to act on.
    :raises: OneViewError if any validation fails.
    """
    ports = task.ports
    oneview_client = get_hponeview_client()
    oneview_info = get_oneview_info(task.node)

    _validate_node_server_profile_template(oneview_client, oneview_info)
    _validate_node_server_hardware_type(oneview_client, oneview_info)
    _validate_node_enclosure_group(oneview_client, oneview_info)
    _validate_server_profile_template_mac_type(oneview_client, oneview_info)
    _validate_node_port_mac_server_hardware(
        oneview_client, oneview_info, ports)


def _verify_node_info(node_namespace, node_info_dict, info_required):
    """Verify if info_required is present in node_namespace of the node info.

    """
    missing_keys = set(info_required) - set(node_info_dict)

    if missing_keys:
        raise exception.MissingParameterValue(
            _("Missing the keys for the following OneView data in node's "
              "%(namespace)s: %(missing_keys)s.") %
            {'namespace': node_namespace,
             'missing_keys': ', '.join(missing_keys)
             }
        )

    # False and 0 can still be considered as valid values
    missing_values_keys = [k for k in info_required
                           if node_info_dict[k] in ('', None)]
    if missing_values_keys:
        missing_keys = ["%s:%s" % (node_namespace, k)
                        for k in missing_values_keys]
        raise exception.MissingParameterValue(
            _("Missing parameter value for: '%s'") % "', '".join(missing_keys)
        )


def node_has_server_profile(func):
    """Checks if the node's Server Hardware has a Server Profile associated.

    Decorator to execute before the function execution if the Server Profile
    is applied to the Server Hardware.

    :param func: a given decorated function.
    """
    def inner(self, *args, **kwargs):
        task = args[0]
        ensure_server_profile(task)
        return func(self, *args, **kwargs)
    return inner


def ensure_server_profile(task):
    """Checks if the node's Server Hardware has a Server Profile associated.

    Function to check if the Server Profile is applied to the Server Hardware.

    :param task: a TaskManager instance containing the node to act on.
    :raises: OneViewError if failed to get server profile from OneView
    """
    oneview_client = get_hponeview_client()
    try:
        profile_uri = task.node.driver_info.get('applied_server_profile_uri')
        oneview_client.server_profiles.get(profile_uri)
    except client_exception.HPOneViewException as exc:
        LOG.error(
            "Failed to get server profile: %(profile)s from OneView appliance "
            "for node %(node)s. Error: %(message)s", {
                "profile": profile_uri,
                "node": task.node.uuid,
                "message": exc
            }
        )
        raise exception.OneViewError(error=exc)


def _get_server_hardware_mac_from_ilo(server_hardware):
    """Get the MAC of Server Hardware's iLO controller.

    :param: server_hardware: a server hardware uuid or uri
    :returns: MAC of Server Hardware's iLO controller.
    :raises: InvalidParameterValue if required iLO credentials are missing.
    :raises: OneViewError if can't get mac from a server hardware via iLO or
             if fails to get JSON object with the default path.
    """
    try:
        ilo_client = get_ilorest_client(server_hardware)
        ilo_path = "/rest/v1/systems/1"
        hardware = jsonutils.loads(ilo_client.get(ilo_path).text)
        hardware_mac = hardware['HostCorrelation']['HostMACAddress'][0]
    except redfish.JsonDecodingError as exc:
        LOG.error("Failed in JSON object getting path: %s", ilo_path)
        raise exception.OneViewError(error=exc)
    except (ValueError, TypeError, IndexError) as exc:
        LOG.exception(
            "Failed to get mac from server hardware %(server_hardware)s "
            "via iLO. Error: %(message)s", {
                "server_hardware": server_hardware.get("uri"),
                "message": exc
            }
        )
        raise exception.OneViewError(error=exc)

    return hardware_mac


def _get_server_hardware_mac(server_hardware):
    """Get the MAC address of the first PXE bootable port of an Ethernet port.

    :param server_hardware: OneView Server Hardware object.
    :returns: MAC of the first Ethernet and function 'a' port of the
             Server Hardware object.
    :raises: OneViewError if there is no Ethernet port on the Server Hardware
             or if there is no portMap on the Server Hardware requested.
    """
    sh_physical_port = None

    if server_hardware.get('portMap'):
        for device in server_hardware.get(
                'portMap', {}).get('deviceSlots', ()):
            for physical_port in device.get('physicalPorts', ()):
                if physical_port.get('type') == 'Ethernet':
                    sh_physical_port = physical_port
                    break
        if sh_physical_port:
            for virtual_port in sh_physical_port.get('virtualPorts', ()):
                # NOTE(nicodemos): Ironic oneview drivers needs to use a
                # port that type is Ethernet and function identifier 'a' for
                # this FlexNIC to be able to make a deploy using PXE.
                if virtual_port.get('portFunction') == 'a':
                    return virtual_port.get('mac', ()).lower()
        raise exception.OneViewError(
            _("There is no Ethernet port on the Server Hardware: %s") %
            server_hardware.get('uri'))
    else:
        raise exception.OneViewError(
            _("The Server Hardware: %s doesn't have a list of adapters/slots, "
              "their ports and attributes. This information is available only "
              "for blade servers. Is this a rack server?") %
            server_hardware.get('uri'))


def _validate_node_server_profile_template(oneview_client, oneview_info):
    """Validate if the Server Profile Template is consistent.

    :param oneview_client: an instance of the HPE OneView client.
    :param oneview_info: the OneView related info in an Ironic node.
    :raises: OneViewError if the node's Server Profile Template is not
             consistent.
    """
    server_profile_template = oneview_client.server_profile_templates.get(
        oneview_info['server_profile_template_uri'])
    server_hardware = oneview_client.server_hardware.get(
        oneview_info['server_hardware_uri'])

    _validate_server_profile_template_server_hardware_type(
        server_profile_template, server_hardware)
    _validate_spt_enclosure_group(server_profile_template, server_hardware)
    _validate_server_profile_template_manage_boot(server_profile_template)


def _validate_server_profile_template_server_hardware_type(
        server_profile_template, server_hardware):
    """Validate if the Server Hardware Types are the same.

    Validate if the Server Profile Template and the Server Hardware have the
    same Server Hardware Type.

    :param server_profile_template: OneView Server Profile Template object.
    :param server_hardware: OneView Server Hardware object.
    :raises: OneViewError if the Server Profile Template and the Server
             Hardware does not have the same Server Hardware Type.
    """
    spt_server_hardware_type_uri = (
        server_profile_template.get('serverHardwareTypeUri')
    )
    sh_server_hardware_type_uri = server_hardware.get('serverHardwareTypeUri')

    if spt_server_hardware_type_uri != sh_server_hardware_type_uri:
        message = _(
            "Server profile template %(spt_uri)s serverHardwareTypeUri is "
            "inconsistent with server hardware %(server_hardware_uri)s "
            "serverHardwareTypeUri.") % {
                'spt_uri': server_profile_template.get('uri'),
                'server_hardware_uri': server_hardware.get('uri')}
        raise exception.OneViewError(message)


def _validate_spt_enclosure_group(server_profile_template, server_hardware):
    """Validate Server Profile Template's Enclosure Group and Hardware's.

    :param server_profile_template: OneView Server Profile Template object.
    :param server_hardware: OneView Server Hardware object.
    :raises: OneViewError if the Server Profile Template's Enclosure Group does
             not match the Server Hardware's.
    """
    spt_enclosure_group_uri = server_profile_template.get('enclosureGroupUri')
    sh_enclosure_group_uri = server_hardware.get('serverGroupUri')

    if spt_enclosure_group_uri != sh_enclosure_group_uri:
        message = _("Server profile template %(spt_uri)s enclosureGroupUri is "
                    "inconsistent with server hardware %(sh_uri)s "
                    "serverGroupUri.") % {
                        'spt_uri': server_profile_template.get('uri'),
                        'sh_uri': server_hardware.get('uri')}
        raise exception.OneViewError(message)


def _validate_server_profile_template_manage_boot(server_profile_template):
    """Validate if the Server Profile Template allows to manage the boot order.

    :param server_profile_template: OneView Server Profile Template object.
    :raises: OneViewError if the Server Profile Template does not allows to
             manage the boot order.
    """
    manage_boot = server_profile_template.get('boot', {}).get('manageBoot')

    if not manage_boot:
        message = _("Server Profile Template: %s, does not allow to manage "
                    "boot order.") % server_profile_template.get('uri')
        raise exception.OneViewError(message)


def _validate_node_server_hardware_type(oneview_client, oneview_info):
    """Validate if the node's Server Hardware Type matches Server Hardware's.

    :param: oneview_client: the HPE OneView Client.
    :param: oneview_info: the OneView related info in an Ironic node.
    :raises: OneViewError if the node's Server Hardware Type group doesn't
             match the Server Hardware's.
    """
    node_server_hardware_type_uri = oneview_info['server_hardware_type_uri']
    server_hardware = oneview_client.server_hardware.get(
        oneview_info['server_hardware_uri'])
    server_hardware_sht_uri = server_hardware.get('serverHardwareTypeUri')

    if server_hardware_sht_uri != node_server_hardware_type_uri:
        message = _("Node server_hardware_type_uri is inconsistent "
                    "with OneView's server hardware %(server_hardware_uri)s "
                    "serverHardwareTypeUri.") % {
                        'server_hardware_uri': server_hardware.get('uri')}
        raise exception.OneViewError(message)


def _validate_node_enclosure_group(oneview_client, oneview_info):
    """Validate if the node's Enclosure Group matches the Server Hardware's.

    :param oneview_client: an instance of the HPE OneView client.
    :param oneview_info: the OneView related info in an Ironic node.
    :raises: OneViewError if the node's enclosure group doesn't match the
             Server Hardware's.
    """
    server_hardware = oneview_client.server_hardware.get(
        oneview_info['server_hardware_uri'])
    sh_enclosure_group_uri = server_hardware.get('serverGroupUri')
    node_enclosure_group_uri = oneview_info['enclosure_group_uri']

    if node_enclosure_group_uri and (
            sh_enclosure_group_uri != node_enclosure_group_uri):
        message = _(
            "Node enclosure_group_uri '%(node_enclosure_group_uri)s' "
            "is inconsistent with OneView's server hardware "
            "serverGroupUri '%(sh_enclosure_group_uri)s' of "
            "ServerHardware %(server_hardware)s") % {
                'node_enclosure_group_uri': node_enclosure_group_uri,
                'sh_enclosure_group_uri': sh_enclosure_group_uri,
                'server_hardware': server_hardware.get('uri')}
        raise exception.OneViewError(message)


def _validate_node_port_mac_server_hardware(oneview_client,
                                            oneview_info, ports):
    """Validate if a port matches the node's Server Hardware's MAC.

    :param oneview_client: an instance of the HPE OneView client.
    :param oneview_info: the OneView related info in an Ironic node.
    :param ports: a list of Ironic node's ports.
    :raises: OneViewError if there is no port with MAC address matching one
    in OneView.

    """
    server_hardware = oneview_client.server_hardware.get(
        oneview_info['server_hardware_uri'])

    if not ports:
        return

    # NOTE(nicodemos) If hponeview client's unable to get the MAC of the Server
    # Hardware and raises an exception, the driver will try to get it from
    # the iLOrest client.
    try:
        mac = _get_server_hardware_mac(server_hardware)
    except exception.OneViewError:
        mac = _get_server_hardware_mac_from_ilo(server_hardware)

    incompatible_macs = []
    for port in ports:
        if port.address.lower() == mac.lower():
            return
        incompatible_macs.append(port.address)

    message = _("The ports of the node are not compatible with its "
                "server hardware %(server_hardware_uri)s. There are no Ironic "
                "port MAC's: %(port_macs)s, that matches with the "
                "server hardware's MAC: %(server_hardware_mac)s") % {
                    'server_hardware_uri': server_hardware.get('uri'),
                    'port_macs': ', '.join(incompatible_macs),
                    'server_hardware_mac': mac}
    raise exception.OneViewError(message)


def _validate_server_profile_template_mac_type(oneview_client, oneview_info):
    """Validate if the node's Server Profile Template's MAC type is physical.

    :param oneview_client: an instance of the HPE OneView client.
    :param oneview_info: the OneView related info in an Ironic node.
    :raises: OneViewError if the node's Server Profile Template's MAC type is
             not physical.
    """
    server_profile_template = oneview_client.server_profile_templates.get(
        oneview_info['server_profile_template_uri']
    )
    if server_profile_template.get('macType') != 'Physical':
        message = _("The server profile template %s is not set to use "
                    "physical MAC.") % server_profile_template.get('uri')
        raise exception.OneViewError(message)
