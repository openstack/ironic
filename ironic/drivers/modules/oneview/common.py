#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LW
from ironic.common import states
from ironic.drivers import utils


LOG = logging.getLogger(__name__)

client = importutils.try_import('oneview_client.client')
oneview_states = importutils.try_import('oneview_client.states')
oneview_exceptions = importutils.try_import('oneview_client.exceptions')

opts = [
    cfg.StrOpt('manager_url',
               help=_('URL where OneView is available')),
    cfg.StrOpt('username',
               help=_('OneView username to be used')),
    cfg.StrOpt('password',
               secret=True,
               help=_('OneView password to be used')),
    cfg.BoolOpt('allow_insecure_connections',
                default=False,
                help=_('Option to allow insecure connection with OneView')),
    cfg.StrOpt('tls_cacert_file',
               help=_('Path to CA certificate')),
    cfg.IntOpt('max_polling_attempts',
               default=12,
               help=_('Max connection retries to check changes on OneView')),
]

CONF = cfg.CONF
CONF.register_opts(opts, group='oneview')

REQUIRED_ON_DRIVER_INFO = {
    'server_hardware_uri': _("Server Hardware URI. Required in driver_info."),
}

REQUIRED_ON_PROPERTIES = {
    'server_hardware_type_uri': _(
        "Server Hardware Type URI. Required in properties/capabilities."
    ),
}

# TODO(gabriel-bezerra): Move 'server_profile_template_uri' to
# REQUIRED_ON_PROPERTIES after Mitaka. See methods get_oneview_info,
# verify_node_info from this file; and test_verify_node_info_missing_spt
# and test_deprecated_spt_in_driver_info* from test_common tests.
OPTIONAL_ON_PROPERTIES = {
    'enclosure_group_uri': _(
        "Enclosure Group URI. Optional in properties/capabilities."),

    'server_profile_template_uri': _(
        "Server Profile Template URI to clone from. "
        "Deprecated in driver_info. "
        "Required in properties/capabilities."),
}

COMMON_PROPERTIES = {}
COMMON_PROPERTIES.update(REQUIRED_ON_DRIVER_INFO)
COMMON_PROPERTIES.update(REQUIRED_ON_PROPERTIES)
COMMON_PROPERTIES.update(OPTIONAL_ON_PROPERTIES)


def get_oneview_client():
    """Generates an instance of the OneView client.

    Generates an instance of the OneView client using the imported
    oneview_client library.

    :returns: an instance of the OneView client
    """

    oneview_client = client.Client(
        manager_url=CONF.oneview.manager_url,
        username=CONF.oneview.username,
        password=CONF.oneview.password,
        allow_insecure_connections=CONF.oneview.allow_insecure_connections,
        tls_cacert_file=CONF.oneview.tls_cacert_file,
        max_polling_attempts=CONF.oneview.max_polling_attempts
    )
    return oneview_client


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

    # TODO(gabriel-bezerra): Remove this after Mitaka
    try:
        _verify_node_info('properties/capabilities', capabilities_dict,
                          ['server_profile_template_uri'])

    except exception.MissingParameterValue:
        try:
            _verify_node_info('driver_info', driver_info,
                              ['server_profile_template_uri'])

            LOG.warning(
                _LW("Using 'server_profile_template_uri' in driver_info is "
                    "now deprecated and will be ignored in future releases. "
                    "Node %s should have it in its properties/capabilities "
                    "instead."),
                node.uuid
            )
        except exception.MissingParameterValue:
            raise exception.MissingParameterValue(
                _("Missing 'server_profile_template_uri' parameter value in "
                  "properties/capabilities")
            )
    # end
    _verify_node_info('driver_info', driver_info,
                      REQUIRED_ON_DRIVER_INFO)


def get_oneview_info(node):
    """Gets OneView information from the node.

    :param: node: node object to get information from
    :returns: a dictionary containing:
        :server_hardware_uri: the uri of the server hardware in OneView
        :server_hardware_type_uri: the uri of the server hardware type in
            OneView
        :enclosure_group_uri: the uri of the enclosure group in OneView
        :server_profile_template_uri: the uri of the server profile template in
            OneView
    :raises InvalidParameterValue if node capabilities are malformed
    """

    capabilities_dict = utils.capabilities_to_dict(
        node.properties.get('capabilities', '')
    )

    driver_info = node.driver_info

    oneview_info = {
        'server_hardware_uri':
            driver_info.get('server_hardware_uri'),
        'server_hardware_type_uri':
            capabilities_dict.get('server_hardware_type_uri'),
        'enclosure_group_uri':
            capabilities_dict.get('enclosure_group_uri'),
        'server_profile_template_uri':
            capabilities_dict.get('server_profile_template_uri') or
            driver_info.get('server_profile_template_uri'),
    }

    return oneview_info


def validate_oneview_resources_compatibility(task):
    """Validates if the node configuration is consistent with OneView.

    This method calls python-oneviewclient functions to validate if the node
    configuration is consistent with the OneView resources it represents,
    including server_hardware_uri, server_hardware_type_uri,
    server_profile_template_uri, enclosure_group_uri and node ports. Also
    verifies if a Server Profile is applied to the Server Hardware the node
    represents. If any validation fails, python-oneviewclient will raise
    an appropriate OneViewException.

    :param: task: a TaskManager instance containing the node to act on.
    """

    node = task.node
    node_ports = task.ports
    try:
        oneview_client = get_oneview_client()
        oneview_info = get_oneview_info(node)

        oneview_client.validate_node_server_hardware(
            oneview_info, node.properties.get('memory_mb'),
            node.properties.get('cpus')
        )
        oneview_client.validate_node_server_hardware_type(oneview_info)
        oneview_client.check_server_profile_is_applied(oneview_info)
        oneview_client.is_node_port_mac_compatible_with_server_profile(
            oneview_info, node_ports
        )
        oneview_client.validate_node_enclosure_group(oneview_info)
        oneview_client.validate_node_server_profile_template(oneview_info)
    except oneview_exceptions.OneViewException as oneview_exc:
        msg = (_("Error validating node resources with OneView: %s")
               % oneview_exc)
        LOG.error(msg)
        raise exception.OneViewError(error=msg)


def translate_oneview_power_state(power_state):
    """Translates OneView's power states strings to Ironic's format.

    :param: power_state: power state string to be translated
    :returns: the power state translated
    """

    power_states_map = {
        oneview_states.ONEVIEW_POWER_ON: states.POWER_ON,
        oneview_states.ONEVIEW_POWERING_OFF: states.POWER_ON,
        oneview_states.ONEVIEW_POWER_OFF: states.POWER_OFF,
        oneview_states.ONEVIEW_POWERING_ON: states.POWER_OFF,
        oneview_states.ONEVIEW_RESETTING: states.REBOOT
    }

    return power_states_map.get(power_state, states.ERROR)


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
    """Checks if the node's Server Hardware as a Server Profile associated.

    """
    def inner(*args, **kwargs):
        task = args[1]
        oneview_info = get_oneview_info(task.node)
        oneview_client = get_oneview_client()
        try:
            node_has_server_profile = (
                oneview_client.get_server_profile_from_hardware(oneview_info)
            )
        except oneview_exceptions.OneViewException as oneview_exc:
            LOG.error(
                _LE("Failed to get server profile from OneView appliance for"
                    "node %(node)s. Error: %(message)s"),
                {"node": task.node.uuid, "message": oneview_exc}
            )
            raise exception.OneViewError(error=oneview_exc)
        if not node_has_server_profile:
            raise exception.OperationNotPermitted(
                _("A Server Profile is not associated with node %s.") %
                task.node.uuid
            )
        return func(*args, **kwargs)
    return inner
