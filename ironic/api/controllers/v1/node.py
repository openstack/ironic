# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
import datetime
from http import client as http_client
import json

from ironic_lib import metrics_utils
import jsonschema
from jsonschema import exceptions as json_schema_exc
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest

from ironic import api
from ironic.api.controllers import link
from ironic.api.controllers.v1 import allocation
from ironic.api.controllers.v1 import bios
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import portgroup
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api.controllers.v1 import volume
from ironic.api import method
from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states as ir_states
from ironic.conductor import steps as conductor_steps
import ironic.conf
from ironic.drivers import base as driver_base
from ironic import objects


CONF = ironic.conf.CONF

LOG = log.getLogger(__name__)
_CLEAN_STEPS_SCHEMA = {
    "$schema": "http://json-schema.org/schema#",
    "title": "Clean steps schema",
    "type": "array",
    # list of clean steps
    "items": {
        "type": "object",
        # args is optional
        "required": ["interface", "step"],
        "properties": {
            "interface": {
                "description": "driver interface",
                "enum": list(conductor_steps.CLEANING_INTERFACE_PRIORITY)
                # interface value must be one of the valid interfaces
            },
            "step": {
                "description": "name of clean step",
                "type": "string",
                "minLength": 1
            },
            "args": {
                "description": "additional args",
                "type": "object",
                "properties": {}
            },
        },
        # interface, step and args are the only expected keys
        "additionalProperties": False
    }
}

_DEPLOY_STEPS_SCHEMA = {
    "$schema": "http://json-schema.org/schema#",
    "title": "Deploy steps schema",
    "type": "array",
    "items": api_utils.DEPLOY_STEP_SCHEMA
}

METRICS = metrics_utils.get_metrics_logger(__name__)

# Vendor information for node's driver:
#   key = driver name;
#   value = dictionary of node vendor methods of that driver:
#             key = method name.
#             value = dictionary with the metadata of that method.
# NOTE(lucasagomes). This is cached for the lifetime of the API
# service. If one or more conductor services are restarted with new driver
# versions, the API service should be restarted.
_VENDOR_METHODS = {}

_DEFAULT_RETURN_FIELDS = ['instance_uuid', 'maintenance', 'power_state',
                          'provision_state', 'uuid', 'name']

# States where calling do_provisioning_action makes sense
PROVISION_ACTION_STATES = (ir_states.VERBS['manage'],
                           ir_states.VERBS['provide'],
                           ir_states.VERBS['abort'],
                           ir_states.VERBS['adopt'])

_NODES_CONTROLLER_RESERVED_WORDS = None

ALLOWED_TARGET_POWER_STATES = (ir_states.POWER_ON,
                               ir_states.POWER_OFF,
                               ir_states.REBOOT,
                               ir_states.SOFT_REBOOT,
                               ir_states.SOFT_POWER_OFF)

_NODE_DESCRIPTION_MAX_LENGTH = 4096

_NETWORK_DATA_SCHEMA = None


def network_data_schema():
    global _NETWORK_DATA_SCHEMA
    if _NETWORK_DATA_SCHEMA is None:
        with open(CONF.api.network_data_schema) as fl:
            _NETWORK_DATA_SCHEMA = json.load(fl)
    return _NETWORK_DATA_SCHEMA


def node_schema():
    network_data = network_data_schema()
    return {
        'type': 'object',
        'properties': {
            'automated_clean': {'type': ['string', 'boolean', 'null']},
            'bios_interface': {'type': ['string', 'null']},
            'boot_interface': {'type': ['string', 'null']},
            'chassis_uuid': {'type': ['string', 'null']},
            'conductor_group': {'type': ['string', 'null']},
            'console_enabled': {'type': ['string', 'boolean', 'null']},
            'console_interface': {'type': ['string', 'null']},
            'deploy_interface': {'type': ['string', 'null']},
            'description': {'type': ['string', 'null'],
                            'maxLength': _NODE_DESCRIPTION_MAX_LENGTH},
            'driver': {'type': 'string'},
            'driver_info': {'type': ['object', 'null']},
            'extra': {'type': ['object', 'null']},
            'inspect_interface': {'type': ['string', 'null']},
            'instance_info': {'type': ['object', 'null']},
            'instance_uuid': {'type': ['string', 'null']},
            'lessee': {'type': ['string', 'null']},
            'management_interface': {'type': ['string', 'null']},
            'maintenance': {'type': ['string', 'boolean', 'null']},
            'name': {'type': ['string', 'null']},
            'network_data': {'anyOf': [
                {'type': 'null'},
                {'type': 'object', 'additionalProperties': False},
                network_data
            ]},
            'network_interface': {'type': ['string', 'null']},
            'owner': {'type': ['string', 'null']},
            'power_interface': {'type': ['string', 'null']},
            'properties': {'type': ['object', 'null']},
            'raid_interface': {'type': ['string', 'null']},
            'rescue_interface': {'type': ['string', 'null']},
            'resource_class': {'type': ['string', 'null'], 'maxLength': 80},
            'retired': {'type': ['string', 'boolean', 'null']},
            'retired_reason': {'type': ['string', 'null']},
            'storage_interface': {'type': ['string', 'null']},
            'uuid': {'type': ['string', 'null']},
            'vendor_interface': {'type': ['string', 'null']},
        },
        'required': ['driver'],
        'additionalProperties': False,
        'definitions': network_data.get('definitions', {})
    }


def node_patch_schema():
    node_patch = copy.deepcopy(node_schema())
    # add schema for patchable fields
    node_patch['properties']['protected'] = {
        'type': ['string', 'boolean', 'null']}
    node_patch['properties']['protected_reason'] = {
        'type': ['string', 'null']}
    return node_patch


NODE_VALIDATE_EXTRA = args.dict_valid(
    automated_clean=args.boolean,
    chassis_uuid=args.uuid,
    console_enabled=args.boolean,
    instance_uuid=args.uuid,
    protected=args.boolean,
    maintenance=args.boolean,
    retired=args.boolean,
    uuid=args.uuid,
)


_NODE_VALIDATOR = None
_NODE_PATCH_VALIDATOR = None


def node_validator(name, value):
    global _NODE_VALIDATOR
    if _NODE_VALIDATOR is None:
        _NODE_VALIDATOR = args.and_valid(
            args.schema(node_schema()),
            NODE_VALIDATE_EXTRA
        )
    return _NODE_VALIDATOR(name, value)


def node_patch_validator(name, value):
    global _NODE_PATCH_VALIDATOR
    if _NODE_PATCH_VALIDATOR is None:
        _NODE_PATCH_VALIDATOR = args.and_valid(
            args.schema(node_patch_schema()),
            NODE_VALIDATE_EXTRA
        )
    return _NODE_PATCH_VALIDATOR(name, value)


PATCH_ALLOWED_FIELDS = [
    'automated_clean',
    'bios_interface',
    'boot_interface',
    'chassis_uuid',
    'conductor_group',
    'console_interface',
    'deploy_interface',
    'description',
    'driver',
    'driver_info',
    'extra',
    'inspect_interface',
    'instance_info',
    'instance_uuid',
    'lessee',
    'maintenance',
    'management_interface',
    'name',
    'network_data',
    'network_interface',
    'owner',
    'power_interface',
    'properties',
    'protected',
    'protected_reason',
    'raid_interface',
    'rescue_interface',
    'resource_class',
    'retired',
    'retired_reason',
    'storage_interface',
    'vendor_interface'
]

TRAITS_SCHEMA = {
    'type': 'object',
    'properties': {
        'traits': {
            'type': 'array',
            'items': api_utils.TRAITS_SCHEMA
        },
    },
    'additionalProperties': False,
}

VIF_VALIDATOR = args.and_valid(
    args.schema({
        'type': 'object',
        'properties': {
            'id': {'type': 'string'},
        },
        'required': ['id'],
        'additionalProperties': True,
    }),
    args.dict_valid(id=args.uuid_or_name)
)


def get_nodes_controller_reserved_names():
    global _NODES_CONTROLLER_RESERVED_WORDS
    if _NODES_CONTROLLER_RESERVED_WORDS is None:
        _NODES_CONTROLLER_RESERVED_WORDS = (
            api_utils.get_controller_reserved_names(NodesController))
    return _NODES_CONTROLLER_RESERVED_WORDS


def hide_fields_in_newer_versions(obj):
    """This method hides fields that were added in newer API versions.

    Certain node fields were introduced at certain API versions.
    These fields are only made available when the request's API version
    matches or exceeds the versions when these fields were introduced.
    """
    for field in api_utils.disallowed_fields():
        obj.pop(field, None)


def reject_fields_in_newer_versions(obj):
    """When creating an object, reject fields that appear in newer versions."""
    for field in api_utils.disallowed_fields():
        if field == 'conductor_group':
            # NOTE(jroll) this is special-cased to "" and not Unset,
            # because it is used in hash ring calculations
            empty_value = ''
        elif field == 'name' and obj.get('name') is None:
            # NOTE(dtantsur): for some reason we allow specifying name=None
            # explicitly even in old API versions..
            continue
        else:
            empty_value = None

        if obj.get(field, empty_value) != empty_value:
            LOG.debug('Field %(field)s is not acceptable in version %(ver)s',
                      {'field': field, 'ver': api.request.version})
            raise exception.NotAcceptable()


def reject_patch_in_newer_versions(patch):
    for field in api_utils.disallowed_fields():
        value = api_utils.get_patch_values(patch, '/%s' % field)
        if value:
            LOG.debug('Field %(field)s is not acceptable in version %(ver)s',
                      {'field': field, 'ver': api.request.version})
            raise exception.NotAcceptable()


def update_state_in_older_versions(obj):
    """Change provision state names for API backwards compatibility.

    :param obj: The dict being returned to the API client that is
                to be updated by this method.
    """
    # if requested version is < 1.2, convert AVAILABLE to the old NOSTATE
    if (api.request.version.minor < versions.MINOR_2_AVAILABLE_STATE
            and obj.get('provision_state') == ir_states.AVAILABLE):
        obj['provision_state'] = ir_states.NOSTATE
    # if requested version < 1.39, convert INSPECTWAIT to INSPECTING
    if (not api_utils.allow_inspect_wait_state()
            and obj.get('provision_state') == ir_states.INSPECTWAIT):
        obj['provision_state'] = ir_states.INSPECTING


def validate_network_data(network_data):
    """Validates node network_data field.

    This method validates network data configuration against JSON
    schema.

    :param network_data: a network_data field to validate
    :raises: Invalid if network data is not schema-compliant
    """
    try:
        jsonschema.validate(network_data, network_data_schema())

    except json_schema_exc.ValidationError as e:
        # NOTE: Even though e.message is deprecated in general, it is
        # said in jsonschema documentation to use this still.
        msg = _("Invalid network_data: %s ") % e.message
        raise exception.Invalid(msg)


class BootDeviceController(rest.RestController):

    _custom_actions = {
        'supported': ['GET'],
    }

    def _get_boot_device(self, rpc_node, supported=False):
        """Get the current boot device or a list of supported devices.

        :param rpc_node: RPC Node object.
        :param supported: Boolean value. If true return a list of
                          supported boot devices, if false return the
                          current boot device. Default: False.
        :returns: The current boot device or a list of the supported
                  boot devices.

        """
        topic = api.request.rpcapi.get_topic_for(rpc_node)
        if supported:
            return api.request.rpcapi.get_supported_boot_devices(
                api.request.context, rpc_node.uuid, topic)
        else:
            return api.request.rpcapi.get_boot_device(api.request.context,
                                                      rpc_node.uuid, topic)

    @METRICS.timer('BootDeviceController.put')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(node_ident=args.uuid_or_name, boot_device=args.string,
                   persistent=args.boolean)
    def put(self, node_ident, boot_device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param node_ident: the UUID or logical name of a node.
        :param boot_device: the boot device, one of
                            :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_boot_device', node_ident)

        topic = api.request.rpcapi.get_topic_for(rpc_node)
        api.request.rpcapi.set_boot_device(api.request.context,
                                           rpc_node.uuid,
                                           boot_device,
                                           persistent=persistent,
                                           topic=topic)

    @METRICS.timer('BootDeviceController.get')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def get(self, node_ident):
        """Get the current boot device for a node.

        :param node_ident: the UUID or logical name of a node.
        :returns: a json object containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_boot_device', node_ident)

        return self._get_boot_device(rpc_node)

    @METRICS.timer('BootDeviceController.supported')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def supported(self, node_ident):
        """Get a list of the supported boot devices.

        :param node_ident: the UUID or logical name of a node.
        :returns: A json object with the list of supported boot
                  devices.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_boot_device', node_ident)

        boot_devices = self._get_boot_device(rpc_node, supported=True)
        return {'supported_boot_devices': boot_devices}


class IndicatorAtComponent(object):

    def __init__(self, **kwargs):
        name = kwargs.get('name')
        component = kwargs.get('component')
        unique_name = kwargs.get('unique_name')

        if name and component:
            self.unique_name = name + '@' + component
            self.name = name
            self.component = component

        elif unique_name:
            try:
                index = unique_name.index('@')

            except ValueError:
                raise exception.InvalidParameterValue(
                    _('Malformed indicator name "%s"') % unique_name)

            self.component = unique_name[index + 1:]
            self.name = unique_name[:index]
            self.unique_name = unique_name

        else:
            raise exception.MissingParameterValue(
                _('Missing indicator name "%s"'))


def indicator_convert_with_links(node_uuid, rpc_component, rpc_name,
                                 **rpc_fields):
    """Add links to the indicator."""
    url = api.request.public_url
    return {
        'name': rpc_name,
        'component': rpc_component,
        'readonly': rpc_fields.get('readonly', True),
        'states': rpc_fields.get('states', []),
        'links': [
            link.make_link(
                'self', url, 'nodes',
                '%s/management/indicators/%s' % (
                    node_uuid, rpc_name)),
            link.make_link(
                'bookmark', url, 'nodes',
                '%s/management/indicators/%s' % (
                    node_uuid, rpc_name),
                bookmark=True)
        ]
    }


def indicator_list_from_dict(node_ident, indicators):
    indicator_list = []
    for component, names in indicators.items():
        for name, fields in names.items():
            indicator_at_component = IndicatorAtComponent(
                component=component, name=name)
            indicator = indicator_convert_with_links(
                node_ident, component, indicator_at_component.unique_name,
                **fields)
            indicator_list.append(indicator)
    return {'indicators': indicator_list}


class IndicatorController(rest.RestController):

    @METRICS.timer('IndicatorController.put')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(node_ident=args.uuid_or_name, indicator=args.string,
                   state=args.string)
    def put(self, node_ident, indicator, state):
        """Set node hardware component indicator to the desired state.

        :param node_ident: the UUID or logical name of a node.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :param state: Indicator state, one of
            mod:`ironic.common.indicator_states`.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_indicator_state',
            node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicator_at_component = IndicatorAtComponent(unique_name=indicator)
        pecan.request.rpcapi.set_indicator_state(
            pecan.request.context, rpc_node.uuid,
            indicator_at_component.component, indicator_at_component.name,
            state, topic=topic)

    @METRICS.timer('IndicatorController.get_one')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name, indicator=args.string)
    def get_one(self, node_ident, indicator):
        """Get node hardware component indicator and its state.

        :param node_ident: the UUID or logical name of a node.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :returns: a dict with the "state" key and one of
            mod:`ironic.common.indicator_states` as a value.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_indicator_state',
            node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicator_at_component = IndicatorAtComponent(unique_name=indicator)
        state = pecan.request.rpcapi.get_indicator_state(
            pecan.request.context, rpc_node.uuid,
            indicator_at_component.component, indicator_at_component.name,
            topic=topic)
        return {'state': state}

    @METRICS.timer('IndicatorController.get_all')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def get_all(self, node_ident, **kwargs):
        """Get node hardware components and their indicators.

        :param node_ident: the UUID or logical name of a node.
        :returns: A json object of hardware components
            (:mod:`ironic.common.components`) as keys with indicator IDs
            (from `get_supported_indicators`) as values.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_indicator_state',
            node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicators = pecan.request.rpcapi.get_supported_indicators(
            pecan.request.context, rpc_node.uuid, topic=topic)

        return indicator_list_from_dict(
            node_ident, indicators)


class InjectNmiController(rest.RestController):

    @METRICS.timer('InjectNmiController.put')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(node_ident=args.uuid_or_name)
    def put(self, node_ident):
        """Inject NMI for a node.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param node_ident: the UUID or logical name of a node.
        :raises: NotFound if requested version of the API doesn't support
                 inject nmi.
        :raises: HTTPForbidden if the policy is not authorized.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management or management.inject_nmi.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.
        """
        if not api_utils.allow_inject_nmi():
            raise exception.NotFound()

        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:inject_nmi', node_ident)

        topic = api.request.rpcapi.get_topic_for(rpc_node)
        api.request.rpcapi.inject_nmi(api.request.context,
                                      rpc_node.uuid,
                                      topic=topic)


class NodeManagementController(rest.RestController):

    boot_device = BootDeviceController()
    """Expose boot_device as a sub-element of management"""

    inject_nmi = InjectNmiController()
    """Expose inject_nmi as a sub-element of management"""

    indicators = IndicatorController()
    """Expose indicators as a sub-element of management"""


class NodeConsoleController(rest.RestController):

    @METRICS.timer('NodeConsoleController.get')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def get(self, node_ident):
        """Get connection information about the console.

        :param node_ident: UUID or logical name of a node.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_console', node_ident)

        topic = api.request.rpcapi.get_topic_for(rpc_node)
        try:
            console = api.request.rpcapi.get_console_information(
                api.request.context, rpc_node.uuid, topic)
            console_state = True
        except exception.NodeConsoleNotEnabled:
            console = None
            console_state = False

        return {'console_enabled': console_state, 'console_info': console}

    @METRICS.timer('NodeConsoleController.put')
    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name, enabled=args.boolean)
    def put(self, node_ident, enabled):
        """Start and stop the node console.

        :param node_ident: UUID or logical name of a node.
        :param enabled: Boolean value; whether to enable or disable the
                console.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_console_state', node_ident)

        topic = api.request.rpcapi.get_topic_for(rpc_node)
        api.request.rpcapi.set_console_mode(api.request.context,
                                            rpc_node.uuid, enabled, topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states', 'console'])
        api.response.location = link.build_url('nodes', url_args)


def node_states_convert(rpc_node):
    attr_list = ['console_enabled', 'last_error', 'power_state',
                 'provision_state', 'target_power_state',
                 'target_provision_state', 'provision_updated_at']
    if api_utils.allow_raid_config():
        attr_list.extend(['raid_config', 'target_raid_config'])
    states = {}
    for attr in attr_list:
        states[attr] = getattr(rpc_node, attr)
        if isinstance(states[attr], datetime.datetime):
            states[attr] = states[attr].isoformat()
    update_state_in_older_versions(states)
    return states


class NodeStatesController(rest.RestController):

    _custom_actions = {
        'power': ['PUT'],
        'provision': ['PUT'],
        'raid': ['PUT'],
    }

    console = NodeConsoleController()
    """Expose console as a sub-element of states"""

    @METRICS.timer('NodeStatesController.get')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def get(self, node_ident):
        """List the states of the node.

        :param node_ident: the UUID or logical_name of a node.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_states', node_ident)

        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        return node_states_convert(rpc_node)

    @METRICS.timer('NodeStatesController.raid')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('target_raid_config')
    @args.validate(node_ident=args.uuid_or_name,
                   target_raid_config=args.types(dict))
    def raid(self, node_ident, target_raid_config):
        """Set the target raid config of the node.

        :param node_ident: the UUID or logical name of a node.
        :param target_raid_config: Desired target RAID configuration of
            the node. It may be an empty dictionary as well.
        :raises: UnsupportedDriverExtension, if the node's driver doesn't
            support RAID configuration.
        :raises: InvalidParameterValue, if validation of target raid config
            fails.
        :raises: NotAcceptable, if requested version of the API is less than
            1.12.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_raid_state', node_ident)

        if not api_utils.allow_raid_config():
            raise exception.NotAcceptable()
        topic = api.request.rpcapi.get_topic_for(rpc_node)
        try:
            api.request.rpcapi.set_target_raid_config(
                api.request.context, rpc_node.uuid,
                target_raid_config, topic=topic)
        except exception.UnsupportedDriverExtension as e:
            # Change error code as 404 seems appropriate because RAID is a
            # standard interface and all drivers might not have it.
            e.code = http_client.NOT_FOUND
            raise

    @METRICS.timer('NodeStatesController.power')
    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name, target=args.string,
                   timeout=args.integer)
    def power(self, node_ident, target, timeout=None):
        """Set the power state of the node.

        :param node_ident: the UUID or logical name of a node.
        :param target: The desired power state of the node.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
          power state. ``None`` indicates to use default timeout.
        :raises: ClientSideError (HTTP 409) if a power operation is
                 already in progress.
        :raises: InvalidStateRequested (HTTP 400) if the requested target
                 state is not valid or if the node is in CLEANING state.
        :raises: NotAcceptable (HTTP 406) for soft reboot, soft power off or
          timeout parameter, if requested version of the API is less than 1.27.
        :raises: Invalid (HTTP 400) if timeout value is less than 1.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_power_state', node_ident)

        # TODO(lucasagomes): Test if it's able to transition to the
        #                    target state from the current one
        topic = api.request.rpcapi.get_topic_for(rpc_node)

        if ((target in [ir_states.SOFT_REBOOT, ir_states.SOFT_POWER_OFF]
             or timeout) and not api_utils.allow_soft_power_off()):
            raise exception.NotAcceptable()
        if timeout is not None and timeout < 1:
            raise exception.Invalid(
                _("timeout has to be positive integer"))

        if target not in ALLOWED_TARGET_POWER_STATES:
            raise exception.InvalidStateRequested(
                action=target, node=node_ident,
                state=rpc_node.power_state)

        # Don't change power state for nodes being cleaned
        elif rpc_node.provision_state in (ir_states.CLEANWAIT,
                                          ir_states.CLEANING):
            raise exception.InvalidStateRequested(
                action=target, node=node_ident,
                state=rpc_node.provision_state)

        api.request.rpcapi.change_node_power_state(api.request.context,
                                                   rpc_node.uuid, target,
                                                   timeout=timeout,
                                                   topic=topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        api.response.location = link.build_url('nodes', url_args)

    def _do_provision_action(self, rpc_node, target, configdrive=None,
                             clean_steps=None, deploy_steps=None,
                             rescue_password=None, disable_ramdisk=None):
        topic = api.request.rpcapi.get_topic_for(rpc_node)
        # Note that there is a race condition. The node state(s) could change
        # by the time the RPC call is made and the TaskManager manager gets a
        # lock.
        if target in (ir_states.ACTIVE, ir_states.REBUILD):
            rebuild = (target == ir_states.REBUILD)
            if deploy_steps:
                _check_deploy_steps(deploy_steps)
            api.request.rpcapi.do_node_deploy(context=api.request.context,
                                              node_id=rpc_node.uuid,
                                              rebuild=rebuild,
                                              configdrive=configdrive,
                                              topic=topic,
                                              deploy_steps=deploy_steps)
        elif (target == ir_states.VERBS['unrescue']):
            api.request.rpcapi.do_node_unrescue(
                api.request.context, rpc_node.uuid, topic)
        elif (target == ir_states.VERBS['rescue']):
            if not (rescue_password and rescue_password.strip()):
                msg = (_('A non-empty "rescue_password" is required when '
                         'setting target provision state to %s') %
                       ir_states.VERBS['rescue'])
                raise exception.ClientSideError(
                    msg, status_code=http_client.BAD_REQUEST)
            api.request.rpcapi.do_node_rescue(
                api.request.context, rpc_node.uuid, rescue_password, topic)
        elif target == ir_states.DELETED:
            api.request.rpcapi.do_node_tear_down(
                api.request.context, rpc_node.uuid, topic)
        elif target == ir_states.VERBS['inspect']:
            api.request.rpcapi.inspect_hardware(
                api.request.context, rpc_node.uuid, topic=topic)
        elif target == ir_states.VERBS['clean']:
            if not clean_steps:
                msg = (_('"clean_steps" is required when setting target '
                         'provision state to %s') % ir_states.VERBS['clean'])
                raise exception.ClientSideError(
                    msg, status_code=http_client.BAD_REQUEST)
            _check_clean_steps(clean_steps)
            api.request.rpcapi.do_node_clean(
                api.request.context, rpc_node.uuid, clean_steps,
                disable_ramdisk, topic=topic)
        elif target in PROVISION_ACTION_STATES:
            api.request.rpcapi.do_provisioning_action(
                api.request.context, rpc_node.uuid, target, topic)
        else:
            msg = (_('The requested action "%(action)s" could not be '
                     'understood.') % {'action': target})
            raise exception.InvalidStateRequested(message=msg)

    @METRICS.timer('NodeStatesController.provision')
    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name, target=args.string,
                   configdrive=args.types(type(None), dict, str),
                   clean_steps=args.types(type(None), list),
                   deploy_steps=args.types(type(None), list),
                   rescue_password=args.string,
                   disable_ramdisk=args.boolean)
    def provision(self, node_ident, target, configdrive=None,
                  clean_steps=None, deploy_steps=None,
                  rescue_password=None, disable_ramdisk=None):
        """Asynchronous trigger the provisioning of the node.

        This will set the target provision state of the node, and a
        background task will begin which actually applies the state
        change. This call will return a 202 (Accepted) indicating the
        request was accepted and is in progress; the client should
        continue to GET the status of this node to observe the status
        of the requested action.

        :param node_ident: UUID or logical name of a node.
        :param target: The desired provision state of the node or verb.
        :param configdrive: Optional. A gzipped and base64 encoded
            configdrive or a dict to build a configdrive from. Only valid when
            setting provision state to "active" or "rebuild".
        :param clean_steps: An ordered list of cleaning steps that will be
            performed on the node. A cleaning step is a dictionary with
            required keys 'interface' and 'step', and optional key 'args'. If
            specified, the value for 'args' is a keyword variable argument
            dictionary that is passed to the cleaning step method.::

              { 'interface': <driver_interface>,
                'step': <name_of_clean_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>} }

            For example (this isn't a real example, this cleaning step
            doesn't exist)::

              { 'interface': 'deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }

            This is required (and only valid) when target is "clean".
        :param deploy_steps: A list of deploy steps that will be performed on
            the node. A deploy step is a dictionary with required keys
            'interface', 'step', 'priority' and 'args'. If specified, the value
            for 'args' is a keyword variable argument dictionary that is passed
            to the deploy step method.::

              { 'interface': <driver_interface>,
                'step': <name_of_deploy_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>}
                'priority': <integer>}

            For example (this isn't a real example, this deploy step doesn't
            exist)::

              { 'interface': 'deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True},
                'priority': 90 }

            This is used only when target is "active" or "rebuild" and is
            optional.
        :param rescue_password: A string representing the password to be set
            inside the rescue environment. This is required (and only valid),
            when target is "rescue".
        :param disable_ramdisk: Whether to skip booting ramdisk for cleaning.
        :raises: NodeLocked (HTTP 409) if the node is currently locked.
        :raises: ClientSideError (HTTP 409) if the node is already being
                 provisioned.
        :raises: InvalidParameterValue (HTTP 400), if validation of
                 clean_steps, deploy_steps or power driver interface fails.
        :raises: InvalidStateRequested (HTTP 400) if the requested transition
                 is not possible from the current state.
        :raises: NodeInMaintenance (HTTP 400), if operation cannot be
                 performed because the node is in maintenance mode.
        :raises: NoFreeConductorWorker (HTTP 503) if no workers are available.
        :raises: NotAcceptable (HTTP 406) if the API version specified does
                 not allow the requested state transition or parameters.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_provision_state', node_ident)

        api_utils.check_allow_management_verbs(target)

        if (target in (ir_states.ACTIVE, ir_states.REBUILD)
                and rpc_node.maintenance):
            raise exception.NodeInMaintenance(op=_('provisioning'),
                                              node=rpc_node.uuid)

        m = ir_states.machine.copy()
        m.initialize(rpc_node.provision_state)
        if not m.is_actionable_event(ir_states.VERBS.get(target, target)):
            # Normally, we let the task manager recognize and deal with
            # NodeLocked exceptions. However, that isn't done until the RPC
            # calls below.
            # In order to main backward compatibility with our API HTTP
            # response codes, we have this check here to deal with cases where
            # a node is already being operated on (DEPLOYING or such) and we
            # want to continue returning 409. Without it, we'd return 400.
            if rpc_node.reservation:
                raise exception.NodeLocked(node=rpc_node.uuid,
                                           host=rpc_node.reservation)

            raise exception.InvalidStateRequested(
                action=target, node=rpc_node.uuid,
                state=rpc_node.provision_state)

        api_utils.check_allow_configdrive(target, configdrive)
        api_utils.check_allow_clean_disable_ramdisk(target, disable_ramdisk)

        if clean_steps and target != ir_states.VERBS['clean']:
            msg = (_('"clean_steps" is only valid when setting target '
                     'provision state to %s') % ir_states.VERBS['clean'])
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)

        api_utils.check_allow_deploy_steps(target, deploy_steps)

        if (rescue_password is not None
            and target != ir_states.VERBS['rescue']):
            msg = (_('"rescue_password" is only valid when setting target '
                     'provision state to %s') % ir_states.VERBS['rescue'])
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)

        if (rpc_node.provision_state == ir_states.INSPECTWAIT
                and target == ir_states.VERBS['abort']):
            if not api_utils.allow_inspect_abort():
                raise exception.NotAcceptable()

        self._do_provision_action(rpc_node, target, configdrive, clean_steps,
                                  deploy_steps, rescue_password,
                                  disable_ramdisk)

        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        api.response.location = link.build_url('nodes', url_args)


def _check_clean_steps(clean_steps):
    """Ensure all necessary keys are present and correct in steps for clean

    :param clean_steps: a list of steps. For more details, see the
        clean_steps parameter of :func:`NodeStatesController.provision`.
    :raises: InvalidParameterValue if validation of steps fails.
    """
    _check_steps(clean_steps, 'clean', _CLEAN_STEPS_SCHEMA)


def _check_deploy_steps(deploy_steps):
    """Ensure all necessary keys are present and correct in steps for deploy

    :param deploy_steps: a list of steps. For more details, see the
        deploy_steps parameter of :func:`NodeStatesController.provision`.
    :raises: InvalidParameterValue if validation of steps fails.
    """
    _check_steps(deploy_steps, 'deploy', _DEPLOY_STEPS_SCHEMA)


def _check_steps(steps, step_type, schema):
    """Ensure all necessary keys are present and correct in steps.

    Check that the user-specified steps are in the expected format and include
    the required information.

    :param steps: a list of steps. For more details, see the
        clean_steps and deploy_steps parameter of
        :func:`NodeStatesController.provision`.
    :param step_type: 'clean' or 'deploy' step type
    :param schema: JSON schema to use for validation.
    :raises: InvalidParameterValue if validation of steps fails.
    """
    try:
        jsonschema.validate(steps, schema)
    except jsonschema.ValidationError as exc:
        raise exception.InvalidParameterValue(_('Invalid %s_steps: %s') %
                                              (step_type, exc))


def _get_chassis_uuid(node):
    """Return the UUID of a node's chassis, or None.

    :param node: a Node object.
    :returns: the UUID of the node's chassis, or None if the node has no
        chassis set.
    """
    if not node.chassis_id:
        return
    chassis = objects.Chassis.get_by_id(api.request.context, node.chassis_id)
    return chassis.uuid


def _replace_chassis_uuid_with_id(node_dict):
    chassis_uuid = node_dict.pop('chassis_uuid', None)
    if not chassis_uuid:
        node_dict['chassis_id'] = None
        return

    try:
        chassis = objects.Chassis.get_by_uuid(api.request.context,
                                              chassis_uuid)
        node_dict['chassis_id'] = chassis.id
    except exception.ChassisNotFound as e:
        # Change error code because 404 (NotFound) is inappropriate
        # response for requests acting on nodes
        e.code = http_client.BAD_REQUEST  # BadRequest
        raise
    return chassis


def _make_trait_list(context, node_id, traits):
    """Return a TraitList object for the specified node and traits.

    The Trait objects will not be created in the database.

    :param context: a request context.
    :param node_id: the ID of a node.
    :param traits: a list of trait strings to add to the TraitList.
    :returns: a TraitList object.
    """
    trait_objs = [objects.Trait(context, node_id=node_id, trait=t)
                  for t in traits]
    return objects.TraitList(context, objects=trait_objs)


class NodeTraitsController(rest.RestController):

    def __init__(self, node_ident):
        super(NodeTraitsController, self).__init__()
        self.node_ident = node_ident

    @METRICS.timer('NodeTraitsController.get_all')
    @method.expose()
    def get_all(self):
        """List node traits."""
        node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:traits:list', self.node_ident)
        traits = objects.TraitList.get_by_node_id(api.request.context,
                                                  node.id)
        return {'traits': traits.get_trait_names()}

    @METRICS.timer('NodeTraitsController.put')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('body')
    @args.validate(trait=args.schema(api_utils.TRAITS_SCHEMA),
                   body=args.schema(TRAITS_SCHEMA))
    def put(self, trait=None, body=None):
        """Add a trait to a node.

        :param trait: String value; trait to add to a node, or None. Mutually
            exclusive with 'traits'. If not None, adds this trait to the node.
        :param traits: List of Strings; traits to set for a node, or None.
            Mutually exclusive with 'trait'. If not None, replaces the node's
            traits with this list.
        """
        context = api.request.context
        node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:traits:set', self.node_ident)

        traits = None
        if body and 'traits' in body:
            traits = body['traits']

        if (trait and traits is not None) or not (trait or traits is not None):
            msg = _("A single node trait may be added via PUT "
                    "/v1/nodes/<node identifier>/traits/<trait> with no body, "
                    "or all node traits may be replaced via PUT "
                    "/v1/nodes/<node identifier>/traits with the list of "
                    "traits specified in the request body.")
            raise exception.Invalid(msg)

        if trait:
            if api.request.body and api.request.json_body:
                # Ensure PUT nodes/uuid1/traits/trait1 with a non-empty body
                # fails.
                msg = _("No body should be provided when adding a trait")
                raise exception.Invalid(msg)
            traits = [trait]
            replace = False
            new_traits = {t.trait for t in node.traits} | {trait}
        else:
            replace = True
            new_traits = set(traits)

        # Update the node's traits to reflect the desired state.
        node.traits = _make_trait_list(context, node.id, sorted(new_traits))
        node.obj_reset_changes()
        chassis_uuid = _get_chassis_uuid(node)
        notify.emit_start_notification(context, node, 'update',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, node, 'update',
                                              chassis_uuid=chassis_uuid):
            topic = api.request.rpcapi.get_topic_for(node)
            api.request.rpcapi.add_node_traits(
                context, node.id, traits, replace=replace, topic=topic)
        notify.emit_end_notification(context, node, 'update',
                                     chassis_uuid=chassis_uuid)

        if not replace:
            # For single traits, set the HTTP Location Header.
            url_args = '/'.join((self.node_ident, 'traits', trait))
            api.response.location = link.build_url('nodes', url_args)

    @METRICS.timer('NodeTraitsController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(trait=args.string)
    def delete(self, trait=None):
        """Remove one or all traits from a node.

        :param trait: String value; trait to remove from a node, or None. If
                      None, all traits are removed.
        """
        context = api.request.context
        node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:traits:delete', self.node_ident)

        if trait:
            traits = [trait]
            new_traits = {t.trait for t in node.traits} - {trait}
        else:
            traits = None
            new_traits = set()

        # Update the node's traits to reflect the desired state.
        node.traits = _make_trait_list(context, node.id, sorted(new_traits))
        node.obj_reset_changes()
        chassis_uuid = _get_chassis_uuid(node)
        notify.emit_start_notification(context, node, 'update',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, node, 'update',
                                              chassis_uuid=chassis_uuid):
            topic = api.request.rpcapi.get_topic_for(node)
            try:
                api.request.rpcapi.remove_node_traits(
                    context, node.id, traits, topic=topic)
            except exception.NodeTraitNotFound:
                # NOTE(hshiina): Internal node ID should not be exposed.
                raise exception.NodeTraitNotFound(node_id=node.uuid,
                                                  trait=trait)
        notify.emit_end_notification(context, node, 'update',
                                     chassis_uuid=chassis_uuid)


def _get_fields_for_node_query(fields=None):

    valid_fields = ['automated_clean',
                    'bios_interface',
                    'boot_interface',
                    'clean_step',
                    'conductor_group',
                    'console_enabled',
                    'console_interface',
                    'deploy_interface',
                    'deploy_step',
                    'description',
                    'driver',
                    'driver_info',
                    'driver_internal_info',
                    'extra',
                    'fault',
                    'inspection_finished_at',
                    'inspection_started_at',
                    'inspect_interface',
                    'instance_info',
                    'instance_uuid',
                    'last_error',
                    'lessee',
                    'maintenance',
                    'maintenance_reason',
                    'management_interface',
                    'name',
                    'network_data',
                    'network_interface',
                    'owner',
                    'power_interface',
                    'power_state',
                    'properties',
                    'protected',
                    'protected_reason',
                    'provision_state',
                    'provision_updated_at',
                    'raid_config',
                    'raid_interface',
                    'rescue_interface',
                    'reservation',
                    'resource_class',
                    'retired',
                    'retired_reason',
                    'storage_interface',
                    'target_power_state',
                    'target_provision_state',
                    'target_raid_config',
                    'traits',
                    'vendor_interface']

    if not fields:
        return valid_fields
    else:
        object_fields = fields[:]
        api_fulfilled_fields = ['allocation_uuid', 'chassis_uuid',
                                'conductor']
        for api_field in api_fulfilled_fields:
            if api_field in object_fields:
                object_fields.remove(api_field)

        query_fields = ['uuid', 'traits'] + api_fulfilled_fields \
            + valid_fields
        for field in fields:
            if field not in query_fields:
                msg = 'Field %s is not a valid field.' % field
                raise exception.Invalid(msg)

        return object_fields


def node_convert_with_links(rpc_node, fields=None, sanitize=True):

    # NOTE(TheJulia): This takes approximately 10% of the time to
    # collect and return requests to API consumer, specifically
    # for the nova sync query which is the most intense overhead
    # an integrated deployment can really face.
    node = api_utils.object_to_dict(
        rpc_node,
        link_resource='nodes',
        fields=_get_fields_for_node_query(fields))

    if node.get('traits') is not None:
        node['traits'] = rpc_node.traits.get_trait_names()

    if (api_utils.allow_expose_conductors()
            and (fields is None or 'conductor' in fields)):
        # NOTE(kaifeng) It is possible a node gets orphaned in certain
        # circumstances, set conductor to None in such case.
        try:
            host = api.request.rpcapi.get_conductor_for(rpc_node)
            node['conductor'] = host
        except (exception.NoValidHost, exception.TemporaryFailure):
            LOG.debug('Currently there is no conductor servicing node '
                      '%(node)s.', {'node': rpc_node.uuid})
            node['conductor'] = None

    # If allocations ever become the primary use path, this absolutely
    # needs to become a join. :\
    if (api_utils.allow_allocations()
            and (fields is None or 'allocation_uuid' in fields)):
        node['allocation_uuid'] = None
        if rpc_node.allocation_id:
            try:
                allocation = objects.Allocation.get_by_id(
                    api.request.context,
                    rpc_node.allocation_id)
                node['allocation_uuid'] = allocation.uuid
            except exception.AllocationNotFound:
                pass
    if fields is None or 'chassis_uuid' in fields:
        node['chassis_uuid'] = _get_chassis_uuid(rpc_node)

    if fields is not None:
        api_utils.check_for_invalid_fields(
            fields, set(node))

    show_states_links = (
        api_utils.allow_links_node_states_and_driver_properties())
    show_portgroups = api_utils.allow_portgroups_subcontrollers()
    show_volume = api_utils.allow_volume()

    url = api.request.public_url

    if fields is None:
        node['ports'] = [link.make_link('self', url, 'nodes',
                                        node['uuid'] + "/ports"),
                         link.make_link('bookmark', url, 'nodes',
                                        node['uuid'] + "/ports",
                                        bookmark=True)]
        if show_states_links:
            node['states'] = [link.make_link('self', url, 'nodes',
                                             node['uuid'] + "/states"),
                              link.make_link('bookmark', url, 'nodes',
                                             node['uuid'] + "/states",
                                             bookmark=True)]
        if show_portgroups:
            node['portgroups'] = [
                link.make_link('self', url, 'nodes',
                               node['uuid'] + "/portgroups"),
                link.make_link('bookmark', url, 'nodes',
                               node['uuid'] + "/portgroups",
                               bookmark=True)]

        if show_volume:
            node['volume'] = [
                link.make_link('self', url, 'nodes',
                               node['uuid'] + "/volume"),
                link.make_link('bookmark', url, 'nodes',
                               node['uuid'] + "/volume",
                               bookmark=True)]

    if not sanitize:
        return node

    node_sanitize(node, fields)

    return node


def node_sanitize(node, fields, cdict=None,
                  show_driver_secrets=None,
                  show_instance_secrets=None,
                  evaluate_additional_policies=None):
    """Removes sensitive and unrequested data.

    Will only keep the fields specified in the ``fields`` parameter.

    :param fields:
        list of fields to preserve, or ``None`` to preserve them all
    :type fields: list of str
    :param cdict: Context dictionary for policy values evaluation.
                  If not provided, it will be executed by the method,
                  however for enumarting node lists, it is more efficent
                  to provide.
    :param show_driver_secrets: A boolean value to allow external single
                                evaluation of policy instead of once per
                                node. Default None.
    :param show_instance_secrets: A boolean value to allow external
                                  evaluation of policy instead of once
                                  per node. Default None.
    :param evaluate_additional_policies: A boolean value to allow external
                                         evaluation of policy instead of once
                                         per node. Default None.
    """
    # NOTE(TheJulia): As of ironic 18.0, this method is about 88% of
    # the time spent preparing to return a node to. If it takes us
    # ~ 4.5 seconds to get 1000 nodes, we spend approximately 4 seconds
    # PER 1000 in this call. When the calling method provides
    # cdict, show_driver_secrets, show_instane_secrets, and
    # evaluate_additional_policies, then performance of this method takes
    # roughly half of the time, but performance increases in excess of 200%
    # as policy checks are costly.

    if not cdict:
        cdict = api.request.context.to_policy_values()

    # We need a new target_dict for each node as owner/lessee field have
    # explicit associations and target comparison.
    target_dict = dict(cdict)

    # These fields are node specific.
    owner = node.get('owner')
    lessee = node.get('lessee')

    if owner:
        target_dict['node.owner'] = owner
    if lessee:
        target_dict['node.lessee'] = lessee

    # Scrub the dictionary's contents down to what was requested.
    api_utils.sanitize_dict(node, fields)

    # NOTE(tenbrae): the 'show_password' policy setting name exists for
    #             legacy purposes and can not be changed. Changing it will
    #             cause upgrade problems for any operators who have
    #             customized the value of this field
    # NOTE(TheJulia): These methods use policy.check and normally return
    # False in a noauth or password auth based situation, because the
    # effective caller doesn't match the policy check rule.
    if show_driver_secrets is None:
        show_driver_secrets = policy.check("show_password",
                                           cdict, target_dict)
    if show_instance_secrets is None:
        show_instance_secrets = policy.check("show_instance_secrets",
                                             cdict, target_dict)

    # TODO(TheJulia): The above checks need to be migrated in some direction,
    # but until we have auditing clarity, it might not be a big deal.

    # Determine if we need to do the additional checks. Keep in mind
    # nova integrated with ironic is API read heavy, so it is ideal
    # to keep the policy checks for say system-member based roles to
    # a minimum as they are likely the regular API users as well.
    # Also, the default for the filter_threshold is system-member.
    if evaluate_additional_policies is None:
        evaluate_additional_policies = not policy.check_policy(
            "baremetal:node:get:filter_threshold",
            target_dict, cdict)

    node_keys = node.keys()

    if evaluate_additional_policies:
        # Perform extended sanitization of nodes based upon policy
        # baremetal:node:get:filter_threshold
        _node_sanitize_extended(node, node_keys, target_dict, cdict)

    if 'driver_info' in node_keys:
        if (evaluate_additional_policies
            and not policy.check("baremetal:node:get:driver_info",
                                 target_dict, cdict)):
            # Guard infrastructure intenral details from being visible.
            node['driver_info'] = {
                'content': '** Redacted - requires baremetal:node:get:'
                           'driver_info permission. **'}
        if not show_driver_secrets:
            node['driver_info'] = strutils.mask_dict_password(
                node['driver_info'], "******")

    if not show_instance_secrets and 'instance_info' in node_keys:
        node['instance_info'] = strutils.mask_dict_password(
            node['instance_info'], "******")
        # NOTE(tenbrae): agent driver may store a swift temp_url on the
        # instance_info, which shouldn't be exposed to non-admin users.
        # Now that ironic supports additional policies, we need to hide
        # it here, based on this policy.
        # Related to bug #1613903
        if node['instance_info'].get('image_url'):
            node['instance_info']['image_url'] = "******"

    if node.get('driver_internal_info', {}).get('agent_secret_token'):
        node['driver_internal_info']['agent_secret_token'] = "******"

    if 'provision_state' in node_keys:
        # Update legacy state data for provision state, but only if
        # the key is present.
        update_state_in_older_versions(node)
    hide_fields_in_newer_versions(node)

    show_states_links = (
        api_utils.allow_links_node_states_and_driver_properties())
    show_portgroups = api_utils.allow_portgroups_subcontrollers()
    show_volume = api_utils.allow_volume()

    if not show_volume:
        node.pop('volume', None)
    if not show_portgroups:
        node.pop('portgroups', None)
    if not show_states_links:
        node.pop('states', None)


def _node_sanitize_extended(node, node_keys, target_dict, cdict):
    # NOTE(TheJulia): The net effect of this is that by default,
    # at least matching common/policy.py defaults. is these should
    # be stripped out.
    if ('last_error' in node_keys
        and not policy.check("baremetal:node:get:last_error",
                             target_dict, cdict)):
        # Guard the last error from being visible as it can contain
        # hostnames revealing infrastucture internal details.
        node['last_error'] = ('** Value Redacted - Requires '
                              'baremetal:node:get:last_error '
                              'permission. **')
    if ('reservation' in node_keys
        and not policy.check("baremetal:node:get:reservation",
                             target_dict, cdict)):
        # Guard conductor names from being visible.
        node['reservation'] = ('** Redacted - requires baremetal:'
                               'node:get:reservation permission. **')
    if ('driver_internal_info' in node_keys
        and not policy.check("baremetal:node:get:driver_internal_info",
                             target_dict, cdict)):
        # Guard conductor names from being visible.
        node['driver_internal_info'] = {
            'content': '** Redacted - Requires baremetal:node:get:'
                       'driver_internal_info permission. **'}


def node_list_convert_with_links(nodes, limit, url=None, fields=None,
                                 **kwargs):
    cdict = api.request.context.to_policy_values()
    target_dict = dict(cdict)
    sanitizer_args = {
        'cdict': cdict,
        'show_driver_secrets': policy.check("show_password", cdict,
                                            target_dict),
        'show_instance_secrets': policy.check("show_instance_secrets",
                                              cdict, target_dict),
        'evaluate_additional_policies': not policy.check_policy(
            "baremetal:node:get:filter_threshold",
            target_dict, cdict),
    }

    return collection.list_convert_with_links(
        items=[node_convert_with_links(n, fields=fields,
                                       sanitize=False)
               for n in nodes],
        item_name='nodes',
        limit=limit,
        url=url,
        fields=fields,
        sanitize_func=node_sanitize,
        sanitizer_args=sanitizer_args,
        **kwargs
    )


class NodeVendorPassthruController(rest.RestController):
    """REST controller for VendorPassthru.

    This controller allow vendors to expose a custom functionality in
    the Ironic API. Ironic will merely relay the message from here to the
    appropriate driver, no introspection will be made in the message body.
    """

    _custom_actions = {
        'methods': ['GET']
    }

    @METRICS.timer('NodeVendorPassthruController.methods')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name)
    def methods(self, node_ident):
        """Retrieve information about vendor methods of the given node.

        :param node_ident: UUID or logical name of a node.
        :returns: dictionary with <vendor method name>:<method metadata>
                  entries.
        :raises: NodeNotFound if the node is not found.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:vendor_passthru', node_ident)

        # Raise an exception if node is not found
        if rpc_node.driver not in _VENDOR_METHODS:
            topic = api.request.rpcapi.get_topic_for(rpc_node)
            ret = api.request.rpcapi.get_node_vendor_passthru_methods(
                api.request.context, rpc_node.uuid, topic=topic)
            _VENDOR_METHODS[rpc_node.driver] = ret

        return _VENDOR_METHODS[rpc_node.driver]

    @METRICS.timer('NodeVendorPassthruController._default')
    @method.expose()
    @method.body('data')
    @args.validate(node_ident=args.uuid_or_name, method=args.string)
    def _default(self, node_ident, method, data=None):
        """Call a vendor extension.

        :param node_ident: UUID or logical name of a node.
        :param method: name of the method in vendor driver.
        :param data: body of data to supply to the specified method.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:vendor_passthru', node_ident)

        # Raise an exception if node is not found
        topic = api.request.rpcapi.get_topic_for(rpc_node)
        resp = api_utils.vendor_passthru(rpc_node.uuid, method, topic,
                                         data=data)
        api.response.status_code = resp.status_code
        return resp.obj


class NodeMaintenanceController(rest.RestController):

    def _set_maintenance(self, rpc_node, maintenance_mode, reason=None):
        context = api.request.context
        rpc_node.maintenance = maintenance_mode
        rpc_node.maintenance_reason = reason
        notify.emit_start_notification(context, rpc_node, 'maintenance_set')
        with notify.handle_error_notification(context, rpc_node,
                                              'maintenance_set'):
            try:
                topic = api.request.rpcapi.get_topic_for(rpc_node)
            except exception.NoValidHost as e:
                e.code = http_client.BAD_REQUEST
                raise

            new_node = api.request.rpcapi.update_node(context, rpc_node,
                                                      topic=topic)
        notify.emit_end_notification(context, new_node, 'maintenance_set')

    @METRICS.timer('NodeMaintenanceController.put')
    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name, reason=args.string)
    def put(self, node_ident, reason=None):
        """Put the node in maintenance mode.

        :param node_ident: the UUID or logical_name of a node.
        :param reason: Optional, the reason why it's in maintenance.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_maintenance', node_ident)

        self._set_maintenance(rpc_node, True, reason=reason)

    @METRICS.timer('NodeMaintenanceController.delete')
    @method.expose(status_code=http_client.ACCEPTED)
    @args.validate(node_ident=args.uuid_or_name)
    def delete(self, node_ident):
        """Remove the node from maintenance mode.

        :param node_ident: the UUID or logical name of a node.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:clear_maintenance', node_ident)

        self._set_maintenance(rpc_node, False)


class NodeVIFController(rest.RestController):

    def __init__(self, node_ident):
        self.node_ident = node_ident

    def _get_node_and_topic(self, policy_name):
        rpc_node = api_utils.check_node_policy_and_retrieve(
            policy_name, self.node_ident)
        try:
            return rpc_node, api.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = http_client.BAD_REQUEST
            raise

    @METRICS.timer('NodeVIFController.get_all')
    @method.expose()
    def get_all(self):
        """Get a list of attached VIFs"""
        rpc_node, topic = self._get_node_and_topic('baremetal:node:vif:list')
        vifs = api.request.rpcapi.vif_list(api.request.context,
                                           rpc_node.uuid, topic=topic)
        return {'vifs': vifs}

    @METRICS.timer('NodeVIFController.post')
    @method.expose(status_code=http_client.NO_CONTENT)
    @method.body('vif')
    @args.validate(vif=VIF_VALIDATOR)
    def post(self, vif):
        """Attach a VIF to this node

        :param vif: a dictionary of information about a VIF.
            It must have an 'id' key, whose value is a unique identifier
            for that VIF.
        """
        rpc_node, topic = self._get_node_and_topic('baremetal:node:vif:attach')
        if api.request.version.minor >= versions.MINOR_67_NODE_VIF_ATTACH_PORT:
            if 'port_uuid' in vif and 'portgroup_uuid' in vif:
                msg = _("Cannot specify both port_uuid and portgroup_uuid")
                raise exception.Invalid(msg)
        api.request.rpcapi.vif_attach(api.request.context, rpc_node.uuid,
                                      vif_info=vif, topic=topic)

    @METRICS.timer('NodeVIFController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(vif_id=args.uuid_or_name)
    def delete(self, vif_id):
        """Detach a VIF from this node

        :param vif_id: The ID of a VIF to detach
        """
        rpc_node, topic = self._get_node_and_topic('baremetal:node:vif:detach')
        api.request.rpcapi.vif_detach(api.request.context, rpc_node.uuid,
                                      vif_id=vif_id, topic=topic)


class NodesController(rest.RestController):
    """REST controller for Nodes."""

    # NOTE(lucasagomes): For future reference. If we happen
    # to need to add another sub-controller in this class let's
    # try to make it a parameter instead of an endpoint due
    # https://bugs.launchpad.net/ironic/+bug/1572651, e.g, instead of
    # v1/nodes/(ident)/detail we could have v1/nodes/(ident)?detail=True

    states = NodeStatesController()
    """Expose the state controller action as a sub-element of nodes"""

    vendor_passthru = NodeVendorPassthruController()
    """A resource used for vendors to expose a custom functionality in
    the API"""

    management = NodeManagementController()
    """Expose management as a sub-element of nodes"""

    maintenance = NodeMaintenanceController()
    """Expose maintenance as a sub-element of nodes"""

    from_chassis = False
    """A flag to indicate if the requests to this controller are coming
    from the top-level resource Chassis"""

    _custom_actions = {
        'detail': ['GET'],
        'validate': ['GET'],
    }

    invalid_sort_key_list = ['properties', 'driver_info', 'extra',
                             'instance_info', 'driver_internal_info',
                             'clean_step', 'deploy_step',
                             'raid_config', 'target_raid_config',
                             'traits', 'network_data']

    _subcontroller_map = {
        'ports': port.PortsController,
        'portgroups': portgroup.PortgroupsController,
        'vifs': NodeVIFController,
        'volume': volume.VolumeController,
        'traits': NodeTraitsController,
        'bios': bios.NodeBiosController,
        'allocation': allocation.NodeAllocationController,
    }

    @pecan.expose()
    def _lookup(self, ident, *remainder):

        if ident in self._subcontroller_map:
            pecan.abort(http_client.NOT_FOUND)

        try:
            ident = args.uuid_or_name('node', ident)
        except exception.InvalidParameterValue as e:
            pecan.abort(http_client.BAD_REQUEST, e.args[0])
        if not remainder:
            return
        if ((remainder[0] == 'portgroups'
                and not api_utils.allow_portgroups_subcontrollers())
            or (remainder[0] == 'vifs'
                and not api_utils.allow_vifs_subcontroller())
            or (remainder[0] == 'bios'
                and not api_utils.allow_bios_interface())
            or (remainder[0] == 'allocation'
                and not api_utils.allow_allocations())):
            pecan.abort(http_client.NOT_FOUND)
        if remainder[0] == 'traits' and not api_utils.allow_traits():
            # NOTE(mgoddard): Returning here will ensure we exhibit the
            # behaviour of previous releases for microversions without this
            # endpoint.
            return
        subcontroller = self._subcontroller_map.get(remainder[0])
        if subcontroller:
            return subcontroller(node_ident=ident), remainder[1:]

    def _filter_by_conductor(self, nodes, conductor):
        filtered_nodes = []
        for n in nodes:
            try:
                host = api.request.rpcapi.get_conductor_for(n)
                if host == conductor:
                    filtered_nodes.append(n)
            except (exception.NoValidHost, exception.TemporaryFailure):
                # NOTE(kaifeng) Node gets orphaned in case some conductor
                # offline or all conductors are offline.
                pass

        return filtered_nodes

    def _get_nodes_collection(self, chassis_uuid, instance_uuid, associated,
                              maintenance, retired, provision_state, marker,
                              limit, sort_key, sort_dir, driver=None,
                              resource_class=None, resource_url=None,
                              fields=None, fault=None, conductor_group=None,
                              detail=None, conductor=None, owner=None,
                              lessee=None, project=None,
                              description_contains=None):
        if self.from_chassis and not chassis_uuid:
            raise exception.MissingParameterValue(
                _("Chassis id not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(api.request.context,
                                                  marker)

        # The query parameters for the 'next' URL
        parameters = {}
        possible_filters = {
            'maintenance': maintenance,
            'chassis_uuid': chassis_uuid,
            'associated': associated,
            'provision_state': provision_state,
            'driver': driver,
            'resource_class': resource_class,
            'fault': fault,
            'conductor_group': conductor_group,
            'owner': owner,
            'lessee': lessee,
            'project': project,
            'description_contains': description_contains,
            'retired': retired,
            'instance_uuid': instance_uuid
        }
        filters = {}
        for key, value in possible_filters.items():
            if value is not None:
                filters[key] = value

        if fields:
            obj_fields = fields[:]
            required_object_fields = ('allocation_id', 'chassis_id',
                                      'uuid', 'owner', 'lessee',
                                      'created_at', 'updated_at')
            for req_field in required_object_fields:
                if req_field not in obj_fields:
                    obj_fields.append(req_field)
        else:
            # map the name for the call, as we did not pickup a specific
            # list of fields to return.
            obj_fields = fields
        # NOTE(TheJulia): When a data set of the nodeds list is being
        # requested, this method takes approximately 3-3.5% of the time
        # when requesting specific fields aligning with Nova's sync
        # process. (Local DB though)

        nodes = objects.Node.list(api.request.context, limit, marker_obj,
                                  sort_key=sort_key, sort_dir=sort_dir,
                                  filters=filters, fields=obj_fields)

        # Special filtering on results based on conductor field
        if conductor:
            nodes = self._filter_by_conductor(nodes, conductor)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}
        if associated:
            parameters['associated'] = associated
        if maintenance:
            parameters['maintenance'] = maintenance
        if retired:
            parameters['retired'] = retired

        if detail is not None:
            parameters['detail'] = detail

        if instance_uuid:
            # NOTE(rloo) if limit==1 and len(nodes)==1 (see
            # Collection.has_next()), a 'next' link will
            # be generated, which we don't want.
            # NOTE(TheJulia): This is done after the query as
            # instance_uuid is a unique constraint in the DB
            # and we cannot pass a limit of 0 to sqlalchemy
            # and expect a response.
            limit = 0

        return node_list_convert_with_links(nodes, limit,
                                            url=resource_url,
                                            fields=fields,
                                            **parameters)

    def _check_names_acceptable(self, names, error_msg):
        """Checks all node 'name's are acceptable, it does not return a value.

        This function will raise an exception for unacceptable names.

        :param names: list of node names to check
        :param error_msg: error message in case of exception.ClientSideError,
            should contain %(name)s placeholder.
        :raises: exception.NotAcceptable
        :raises: exception.ClientSideError
        """
        if not api_utils.allow_node_logical_names():
            raise exception.NotAcceptable()

        reserved_names = get_nodes_controller_reserved_names()
        for name in names:
            if not api_utils.is_valid_node_name(name):
                raise exception.ClientSideError(
                    error_msg % {'name': name},
                    status_code=http_client.BAD_REQUEST)
            if name in reserved_names:
                raise exception.ClientSideError(
                    'The word "%(name)s" is reserved and can not be used as a '
                    'node name. Reserved words are: %(reserved)s.' %
                    {'name': name,
                     'reserved': ', '.join(reserved_names)},
                    status_code=http_client.BAD_REQUEST)

    def _update_changed_fields(self, node, rpc_node):
        """Update rpc_node based on changed fields in a node.

        """

        original_chassis_id = rpc_node.chassis_id
        chassis = _replace_chassis_uuid_with_id(node)

        # conductor_group is case-insensitive, and we use it to
        # calculate the conductor to send an update too. lowercase
        # it here instead of just before saving so we calculate
        # correctly.
        node['conductor_group'] = node['conductor_group'].lower()

        # Node object protected field is not nullable
        if node.get('protected') is None:
            node['protected'] = False

        # NOTE(mgoddard): Traits cannot be updated via a node PATCH.
        api_utils.patch_update_changed_fields(
            node, rpc_node,
            fields=set(objects.Node.fields) - {'traits'},
            schema=node_patch_schema(),
            id_map={'chassis_id': chassis and chassis.id or None}
        )

        if original_chassis_id and not rpc_node.chassis_id:
            if not api_utils.allow_remove_chassis_uuid():
                raise exception.NotAcceptable()

    def _check_driver_changed_and_console_enabled(self, rpc_node, node_ident):
        """Checks if the driver and the console is enabled in a node.

        If it does, is necessary to prevent updating it because the new driver
        will not be able to stop a console started by the previous one.

        :param rpc_node: RPC Node object to be verified.
        :param node_ident: the UUID or logical name of a node.
        :raises: exception.ClientSideError
        """
        delta = rpc_node.obj_what_changed()
        if 'driver' in delta and rpc_node.console_enabled:
            raise exception.ClientSideError(
                _("Node %s can not update the driver while the console is "
                  "enabled. Please stop the console first.") % node_ident,
                status_code=http_client.CONFLICT)

    @METRICS.timer('NodesController.get_all')
    @method.expose()
    @args.validate(chassis_uuid=args.uuid, instance_uuid=args.uuid,
                   associated=args.boolean, maintenance=args.boolean,
                   retired=args.boolean, provision_state=args.string,
                   marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, driver=args.string,
                   fields=args.string_list, resource_class=args.string,
                   fault=args.string, conductor_group=args.string,
                   detail=args.boolean, conductor=args.string,
                   owner=args.string, description_contains=args.string,
                   lessee=args.string, project=args.string)
    def get_all(self, chassis_uuid=None, instance_uuid=None, associated=None,
                maintenance=None, retired=None, provision_state=None,
                marker=None, limit=None, sort_key='id', sort_dir='asc',
                driver=None, fields=None, resource_class=None, fault=None,
                conductor_group=None, detail=None, conductor=None,
                owner=None, description_contains=None, lessee=None,
                project=None):
        """Retrieve a list of nodes.

        :param chassis_uuid: Optional UUID of a chassis, to get only nodes for
                             that chassis.
        :param instance_uuid: Optional UUID of an instance, to find the node
                              associated with that instance.
        :param associated: Optional boolean whether to return a list of
                           associated or unassociated nodes. May be combined
                           with other parameters.
        :param maintenance: Optional boolean value that indicates whether
                            to get nodes in maintenance mode ("True"), or not
                            in maintenance mode ("False").
        :param retired: Optional boolean value that indicates whether
                        to get retired nodes.
        :param provision_state: Optional string value to get only nodes in
                                that provision state.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param driver: Optional string value to get only nodes using that
                       driver.
        :param resource_class: Optional string value to get only nodes with
                               that resource_class.
        :param conductor_group: Optional string value to get only nodes with
                                that conductor_group.
        :param conductor: Optional string value to get only nodes managed by
                          that conductor.
        :param owner: Optional string value that set the owner whose nodes
                      are to be retrurned.
        :param lessee: Optional string value that set the lessee whose nodes
                      are to be returned.
        :param project: Optional string value that set the project - lessee or
                        owner - whose nodes are to be returned.
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        :param fault: Optional string value to get only nodes with that fault.
        :param description_contains: Optional string value to get only nodes
                                     with description field contains matching
                                     value.
        """
        project = api_utils.check_list_policy('node', project)

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)
        api_utils.check_allowed_fields([sort_key])
        api_utils.check_for_invalid_state_and_allow_filter(provision_state)
        api_utils.check_allow_specify_driver(driver)
        api_utils.check_allow_specify_resource_class(resource_class)
        api_utils.check_allow_filter_by_fault(fault)
        api_utils.check_allow_filter_by_conductor_group(conductor_group)
        api_utils.check_allow_filter_by_conductor(conductor)
        api_utils.check_allow_filter_by_owner(owner)
        api_utils.check_allow_filter_by_lessee(lessee)

        fields = api_utils.get_request_return_fields(fields, detail,
                                                     _DEFAULT_RETURN_FIELDS)
        extra_args = {'description_contains': description_contains}
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance, retired,
                                          provision_state, marker,
                                          limit, sort_key, sort_dir,
                                          driver=driver,
                                          resource_class=resource_class,
                                          fields=fields, fault=fault,
                                          conductor_group=conductor_group,
                                          detail=detail,
                                          conductor=conductor,
                                          owner=owner, lessee=lessee,
                                          project=project,
                                          **extra_args)

    @METRICS.timer('NodesController.detail')
    @method.expose()
    @args.validate(chassis_uuid=args.uuid, instance_uuid=args.uuid,
                   associated=args.boolean, maintenance=args.boolean,
                   retired=args.boolean, provision_state=args.string,
                   marker=args.uuid, limit=args.integer, sort_key=args.string,
                   sort_dir=args.string, driver=args.string,
                   resource_class=args.string, fault=args.string,
                   conductor_group=args.string, conductor=args.string,
                   owner=args.string, description_contains=args.string,
                   lessee=args.string, project=args.string)
    def detail(self, chassis_uuid=None, instance_uuid=None, associated=None,
               maintenance=None, retired=None, provision_state=None,
               marker=None, limit=None, sort_key='id', sort_dir='asc',
               driver=None, resource_class=None, fault=None,
               conductor_group=None, conductor=None, owner=None,
               description_contains=None, lessee=None, project=None):
        """Retrieve a list of nodes with detail.

        :param chassis_uuid: Optional UUID of a chassis, to get only nodes for
                           that chassis.
        :param instance_uuid: Optional UUID of an instance, to find the node
                              associated with that instance.
        :param associated: Optional boolean whether to return a list of
                           associated or unassociated nodes. May be combined
                           with other parameters.
        :param maintenance: Optional boolean value that indicates whether
                            to get nodes in maintenance mode ("True"), or not
                            in maintenance mode ("False").
        :param retired: Optional boolean value that indicates whether
                        to get nodes which are retired.
        :param provision_state: Optional string value to get only nodes in
                                that provision state.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
                      This value cannot be larger than the value of max_limit
                      in the [api] section of the ironic configuration, or only
                      max_limit resources will be returned.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        :param driver: Optional string value to get only nodes using that
                       driver.
        :param resource_class: Optional string value to get only nodes with
                               that resource_class.
        :param fault: Optional string value to get only nodes with that fault.
        :param conductor_group: Optional string value to get only nodes with
                                that conductor_group.
        :param owner: Optional string value that set the owner whose nodes
                      are to be retrurned.
        :param lessee: Optional string value that set the lessee whose nodes
                      are to be returned.
        :param project: Optional string value that set the project - lessee or
                        owner - whose nodes are to be returned.
        :param description_contains: Optional string value to get only nodes
                                     with description field contains matching
                                     value.
        """
        project = api_utils.check_list_policy('node', project)

        api_utils.check_for_invalid_state_and_allow_filter(provision_state)
        api_utils.check_allow_specify_driver(driver)
        api_utils.check_allow_specify_resource_class(resource_class)
        api_utils.check_allow_filter_by_fault(fault)
        api_utils.check_allow_filter_by_conductor_group(conductor_group)
        api_utils.check_allow_filter_by_owner(owner)
        api_utils.check_allow_filter_by_lessee(lessee)
        api_utils.check_allowed_fields([sort_key])
        # /detail should only work against collections
        parent = api.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound()

        api_utils.check_allow_filter_by_conductor(conductor)

        resource_url = '/'.join(['nodes', 'detail'])
        extra_args = {'description_contains': description_contains}
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance, retired,
                                          provision_state, marker,
                                          limit, sort_key, sort_dir,
                                          driver=driver,
                                          resource_class=resource_class,
                                          resource_url=resource_url,
                                          fault=fault,
                                          conductor_group=conductor_group,
                                          conductor=conductor,
                                          owner=owner, lessee=lessee,
                                          project=project,
                                          **extra_args)

    @METRICS.timer('NodesController.validate')
    @method.expose()
    @args.validate(node=args.uuid_or_name, node_uuid=args.uuid)
    def validate(self, node=None, node_uuid=None):
        """Validate the driver interfaces, using the node's UUID or name.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node.
        :param node_uuid: UUID of a node.
        """
        if node is not None:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            if (not api_utils.allow_node_logical_names()
                and not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:validate', node_uuid or node)

        topic = api.request.rpcapi.get_topic_for(rpc_node)
        return api.request.rpcapi.validate_driver_interfaces(
            api.request.context, rpc_node.uuid, topic)

    @METRICS.timer('NodesController.get_one')
    @method.expose()
    @args.validate(node_ident=args.uuid_or_name, fields=args.string_list)
    def get_one(self, node_ident, fields=None):
        """Retrieve information about the given node.

        :param node_ident: UUID or logical name of a node.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted()

        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get', node_ident, with_suffix=True)

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)

        return node_convert_with_links(rpc_node, fields=fields)

    @METRICS.timer('NodesController.post')
    @method.expose(status_code=http_client.CREATED)
    @method.body('node')
    @args.validate(node=node_validator)
    def post(self, node):
        """Create a new node.

        :param node: a node within the request body.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted()

        context = api.request.context
        api_utils.check_policy('baremetal:node:create')

        reject_fields_in_newer_versions(node)

        # NOTE(tenbrae): get_topic_for checks if node.driver is in the hash
        #             ring and raises NoValidHost if it is not.
        #             We need to ensure that node has a UUID before it can
        #             be mapped onto the hash ring.
        if not node.get('uuid'):
            node['uuid'] = uuidutils.generate_uuid()

        # NOTE(jroll) this is special-cased to "" and not None,
        # because it is used in hash ring calculations
        if not node.get('conductor_group'):
            node['conductor_group'] = ''

        if node.get('name') is not None:
            error_msg = _("Cannot create node with invalid name '%(name)s'")
            self._check_names_acceptable([node['name']], error_msg)
        node['provision_state'] = api_utils.initial_node_provision_state()

        if not node.get('resource_class'):
            node['resource_class'] = CONF.default_resource_class

        chassis = _replace_chassis_uuid_with_id(node)
        chassis_uuid = chassis and chassis.uuid or None

        new_node = objects.Node(context, **node)

        try:
            topic = api.request.rpcapi.get_topic_for(new_node)
        except exception.NoValidHost as e:
            # NOTE(tenbrae): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = http_client.BAD_REQUEST
            raise

        notify.emit_start_notification(context, new_node, 'create',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, new_node, 'create',
                                              chassis_uuid=chassis_uuid):
            new_node = api.request.rpcapi.create_node(context,
                                                      new_node, topic)
        # Set the HTTP Location Header
        api.response.location = link.build_url('nodes', new_node.uuid)
        api_node = node_convert_with_links(new_node)
        chassis_uuid = api_node.get('chassis_uuid')
        notify.emit_end_notification(context, new_node, 'create',
                                     chassis_uuid=chassis_uuid)
        return api_node

    def _validate_patch(self, patch, reset_interfaces):
        if self.from_chassis:
            raise exception.OperationNotPermitted()

        api_utils.patch_validate_allowed_fields(patch, PATCH_ALLOWED_FIELDS)

        reject_patch_in_newer_versions(patch)

        traits = api_utils.get_patch_values(patch, '/traits')
        if traits:
            msg = _("Cannot update node traits via node patch. Node traits "
                    "should be updated via the node traits API.")
            raise exception.Invalid(msg)

        driver = api_utils.get_patch_values(patch, '/driver')
        if reset_interfaces and not driver:
            msg = _("The reset_interfaces parameter can only be used when "
                    "changing the node's driver.")
            raise exception.Invalid(msg)

        description = api_utils.get_patch_values(patch, '/description')
        if description and len(description[0]) > _NODE_DESCRIPTION_MAX_LENGTH:
            msg = _("Cannot update node with description exceeding %s "
                    "characters") % _NODE_DESCRIPTION_MAX_LENGTH
            raise exception.Invalid(msg)

        network_data_fields = api_utils.get_patch_values(
            patch, '/network_data')

        for network_data in network_data_fields:
            validate_network_data(network_data)

    def _authorize_patch_and_get_node(self, node_ident, patch):
        # deal with attribute-specific policy rules
        policy_checks = []
        generic_update = False
        for p in patch:
            if p['path'].startswith('/instance_info'):
                policy_checks.append('baremetal:node:update_instance_info')
            elif p['path'].startswith('/extra'):
                policy_checks.append('baremetal:node:update_extra')
            elif (p['path'].startswith('/automated_clean')
                  and strutils.bool_from_string(p['value'], default=None)
                  is False):
                policy_checks.append('baremetal:node:disable_cleaning')
            elif p['path'].startswith('/driver_info'):
                policy_checks.append('baremetal:node:update:driver_info')
            elif p['path'].startswith('/properties'):
                policy_checks.append('baremetal:node:update:properties')
            elif p['path'].startswith('/chassis_uuid'):
                policy_checks.append('baremetal:node:update:chassis_uuid')
            elif p['path'].startswith('/instance_uuid'):
                policy_checks.append('baremetal:node:update:instance_uuid')
            elif p['path'].startswith('/lessee'):
                policy_checks.append('baremetal:node:update:lessee')
            elif p['path'].startswith('/owner'):
                policy_checks.append('baremetal:node:update:owner')
            elif p['path'].startswith('/driver'):
                policy_checks.append('baremetal:node:update:driver_interfaces')
            elif ((p['path'].lstrip('/').rsplit(sep="_", maxsplit=1)[0]
                   in driver_base.ALL_INTERFACES)
                  and (p['path'].lstrip('/').rsplit(sep="_", maxsplit=1)[-1]
                       == "interface")):
                # TODO(TheJulia): Replace the above check with something like
                # elif (p['path'].lstrip('/').removesuffix('_interface')
                # when the minimum supported version is Python 3.9.
                policy_checks.append('baremetal:node:update:driver_interfaces')
            elif p['path'].startswith('/network_data'):
                policy_checks.append('baremetal:node:update:network_data')
            elif p['path'].startswith('/conductor_group'):
                policy_checks.append('baremetal:node:update:conductor_group')
            elif p['path'].startswith('/name'):
                policy_checks.append('baremetal:node:update:name')
            elif p['path'].startswith('/retired'):
                policy_checks.append('baremetal:node:update:retired')
            else:
                generic_update = True
        # always do at least one check
        if generic_update or not policy_checks:
            policy_checks.append('baremetal:node:update')

        return api_utils.check_multiple_node_policies_and_retrieve(
            policy_checks, node_ident, with_suffix=True)

    @METRICS.timer('NodesController.patch')
    @method.expose()
    @method.body('patch')
    @args.validate(node_ident=args.uuid_or_name, reset_interfaces=args.boolean,
                   patch=args.patch)
    def patch(self, node_ident, reset_interfaces=None, patch=None):
        """Update an existing node.

        :param node_ident: UUID or logical name of a node.
        :param reset_interfaces: whether to reset hardware interfaces to their
            defaults. Only valid when updating the driver field.
        :param patch: a json PATCH document to apply to this node.
        """
        if (reset_interfaces is not None and not
                api_utils.allow_reset_interfaces()):
            raise exception.NotAcceptable()

        self._validate_patch(patch, reset_interfaces)

        context = api.request.context
        rpc_node = self._authorize_patch_and_get_node(node_ident, patch)

        remove_inst_uuid_patch = [{'op': 'remove', 'path': '/instance_uuid'}]
        if rpc_node.maintenance and patch == remove_inst_uuid_patch:
            LOG.debug('Removing instance uuid %(instance)s from node %(node)s',
                      {'instance': rpc_node.instance_uuid,
                       'node': rpc_node.uuid})
        # Check if node is transitioning state, although nodes in some states
        # can be updated.
        elif (rpc_node.target_provision_state and rpc_node.provision_state
              not in ir_states.UPDATE_ALLOWED_STATES):
            msg = _("Node %s can not be updated while a state transition "
                    "is in progress.")
            raise exception.ClientSideError(
                msg % node_ident, status_code=http_client.CONFLICT)
        elif (rpc_node.provision_state == ir_states.INSPECTING
              and api_utils.allow_inspect_wait_state()):
            msg = _('Cannot update node "%(node)s" while it is in state '
                    '"%(state)s".') % {'node': rpc_node.uuid,
                                       'state': ir_states.INSPECTING}
            raise exception.ClientSideError(msg,
                                            status_code=http_client.CONFLICT)
        elif api_utils.get_patch_values(patch, '/owner'):

            # check if updating a provisioned node's owner is allowed
            if rpc_node.provision_state == ir_states.ACTIVE:
                try:
                    api_utils.check_owner_policy(
                        'node',
                        'baremetal:node:update_owner_provisioned',
                        rpc_node['owner'], rpc_node['lessee'])
                except exception.HTTPForbidden:
                    msg = _('Cannot update owner of node "%(node)s" while it '
                            'is in state "%(state)s".') % {
                                'node': rpc_node.uuid,
                                'state': ir_states.ACTIVE}
                    raise exception.ClientSideError(
                        msg, status_code=http_client.CONFLICT)

            # check if node has an associated allocation with an owner
            if rpc_node.allocation_id:
                try:
                    allocation = objects.Allocation.get_by_id(
                        context,
                        rpc_node.allocation_id)
                    if allocation.owner is not None:
                        msg = _('Cannot update owner of node "%(node)s" while '
                                'it is allocated to an allocation with an '
                                ' owner.') % {'node': rpc_node.uuid}
                        raise exception.ClientSideError(
                            msg, status_code=http_client.CONFLICT)
                except exception.AllocationNotFound:
                    pass

        names = api_utils.get_patch_values(patch, '/name')
        if len(names):
            error_msg = (_("Node %s: Cannot change name to invalid name ")
                         % node_ident)
            error_msg += "'%(name)s'"
            self._check_names_acceptable(names, error_msg)

        node_dict = rpc_node.as_dict()
        # NOTE(lucasagomes):
        # 1) Remove chassis_id because it's an internal value and
        #    not present in the API object
        # 2) Add chassis_uuid
        node_dict['chassis_uuid'] = _get_chassis_uuid(rpc_node)

        node_dict = api_utils.apply_jsonpatch(node_dict, patch)

        api_utils.patched_validate_with_schema(
            node_dict, node_patch_schema(), node_patch_validator)

        self._update_changed_fields(node_dict, rpc_node)
        # NOTE(tenbrae): we calculate the rpc topic here in case node.driver
        #             has changed, so that update is sent to the
        #             new conductor, not the old one which may fail to
        #             load the new driver.
        try:
            topic = api.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            # NOTE(tenbrae): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = http_client.BAD_REQUEST
            raise
        self._check_driver_changed_and_console_enabled(rpc_node, node_ident)

        chassis_uuid = _get_chassis_uuid(rpc_node)
        notify.emit_start_notification(context, rpc_node, 'update',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, rpc_node, 'update',
                                              chassis_uuid=chassis_uuid):
            new_node = api.request.rpcapi.update_node(context,
                                                      rpc_node, topic,
                                                      reset_interfaces)

        api_node = node_convert_with_links(new_node)
        chassis_uuid = api_node.get('chassis_uuid')
        notify.emit_end_notification(context, new_node, 'update',
                                     chassis_uuid=chassis_uuid)

        return api_node

    @METRICS.timer('NodesController.delete')
    @method.expose(status_code=http_client.NO_CONTENT)
    @args.validate(node_ident=args.uuid_or_name)
    def delete(self, node_ident, *args):
        """Delete a node.

        :param node_ident: UUID or logical name of a node.
        """

        # occurs when deleting traits with an old API version
        if args:
            raise exception.NotFound()

        if self.from_chassis:
            raise exception.OperationNotPermitted()

        context = api.request.context
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:delete', node_ident, with_suffix=True)

        chassis_uuid = _get_chassis_uuid(rpc_node)
        notify.emit_start_notification(context, rpc_node, 'delete',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, rpc_node, 'delete',
                                              chassis_uuid=chassis_uuid):
            try:
                topic = api.request.rpcapi.get_topic_for(rpc_node)
            except exception.NoValidHost as e:
                e.code = http_client.BAD_REQUEST
                raise

            api.request.rpcapi.destroy_node(context, rpc_node.uuid, topic)
        notify.emit_end_notification(context, rpc_node, 'delete',
                                     chassis_uuid=chassis_uuid)
