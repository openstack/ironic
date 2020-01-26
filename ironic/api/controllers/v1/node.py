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

import datetime
from http import client as http_client

from ironic_lib import metrics_utils
import jsonschema
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest
import wsme

from ironic import api
from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import allocation
from ironic.api.controllers.v1 import bios
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import portgroup
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api.controllers.v1 import volume
from ironic.api import expose
from ironic.api import types as atypes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states as ir_states
from ironic.conductor import steps as conductor_steps
import ironic.conf
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

_DEFAULT_RETURN_FIELDS = ('instance_uuid', 'maintenance', 'power_state',
                          'provision_state', 'uuid', 'name')

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
        setattr(obj, field, atypes.Unset)


def reject_fields_in_newer_versions(obj):
    """When creating an object, reject fields that appear in newer versions."""
    for field in api_utils.disallowed_fields():
        if field == 'conductor_group':
            # NOTE(jroll) this is special-cased to "" and not Unset,
            # because it is used in hash ring calculations
            empty_value = ''
        elif field == 'name' and obj.name is None:
            # NOTE(dtantsur): for some reason we allow specifying name=None
            # explicitly even in old API versions..
            continue
        else:
            empty_value = atypes.Unset

        if getattr(obj, field, empty_value) != empty_value:
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

    :param obj: The object being returned to the API client that is
                to be updated by this method.
    """
    # if requested version is < 1.2, convert AVAILABLE to the old NOSTATE
    if (api.request.version.minor < versions.MINOR_2_AVAILABLE_STATE
            and obj.provision_state == ir_states.AVAILABLE):
        obj.provision_state = ir_states.NOSTATE
    # if requested version < 1.39, convert INSPECTWAIT to INSPECTING
    if (not api_utils.allow_inspect_wait_state()
            and obj.provision_state == ir_states.INSPECTWAIT):
        obj.provision_state = ir_states.INSPECTING


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
    @expose.expose(None, types.uuid_or_name, str, types.boolean,
                   status_code=http_client.NO_CONTENT)
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
    @expose.expose(str, types.uuid_or_name)
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
    @expose.expose(str, types.uuid_or_name)
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


class IndicatorState(base.APIBase):
    """API representation of indicator state."""

    state = atypes.wsattr(str)

    def __init__(self, **kwargs):
        self.state = kwargs.get('state')


class Indicator(base.APIBase):
    """API representation of an indicator."""

    name = atypes.wsattr(str)

    component = atypes.wsattr(str)

    readonly = types.BooleanType()

    states = atypes.ArrayType(str)

    links = atypes.wsattr([link.Link], readonly=True)

    def __init__(self, **kwargs):
        self.name = kwargs.get('name')
        self.component = kwargs.get('component')
        self.readonly = kwargs.get('readonly', True)
        self.states = kwargs.get('states', [])

    @staticmethod
    def _convert_with_links(node_uuid, indicator, url):
        """Add links to the indicator."""
        indicator.links = [
            link.Link.make_link(
                'self', url, 'nodes',
                '%s/management/indicators/%s' % (
                    node_uuid, indicator.name)),
            link.Link.make_link(
                'bookmark', url, 'nodes',
                '%s/management/indicators/%s' % (
                    node_uuid, indicator.name),
                bookmark=True)]
        return indicator

    @classmethod
    def convert_with_links(cls, node_uuid, rpc_component, rpc_name,
                           **rpc_fields):
        """Add links to the indicator."""
        indicator = Indicator(
            component=rpc_component, name=rpc_name, **rpc_fields)
        return cls._convert_with_links(
            node_uuid, indicator, pecan.request.host_url)


class IndicatorsCollection(atypes.Base):
    """API representation of the indicators for a node."""

    indicators = [Indicator]
    """Node indicators list"""

    @staticmethod
    def collection_from_dict(node_ident, indicators):
        col = IndicatorsCollection()

        indicator_list = []
        for component, names in indicators.items():
            for name, fields in names.items():
                indicator_at_component = IndicatorAtComponent(
                    component=component, name=name)
                indicator = Indicator.convert_with_links(
                    node_ident, component, indicator_at_component.unique_name,
                    **fields)
                indicator_list.append(indicator)
        col.indicators = indicator_list
        return col


class IndicatorController(rest.RestController):

    @METRICS.timer('IndicatorController.put')
    @expose.expose(None, types.uuid_or_name, str, str,
                   status_code=http_client.NO_CONTENT)
    def put(self, node_ident, indicator, state):
        """Set node hardware component indicator to the desired state.

        :param node_ident: the UUID or logical name of a node.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :param state: Indicator state, one of
            mod:`ironic.common.indicator_states`.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_indicator_state', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicator_at_component = IndicatorAtComponent(unique_name=indicator)
        pecan.request.rpcapi.set_indicator_state(
            pecan.request.context, rpc_node.uuid,
            indicator_at_component.component, indicator_at_component.name,
            state, topic=topic)

    @METRICS.timer('IndicatorController.get_one')
    @expose.expose(IndicatorState, types.uuid_or_name, str)
    def get_one(self, node_ident, indicator):
        """Get node hardware component indicator and its state.

        :param node_ident: the UUID or logical name of a node.
        :param indicator: Indicator ID (as reported by
            `get_supported_indicators`).
        :returns: a dict with the "state" key and one of
            mod:`ironic.common.indicator_states` as a value.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_indicator_state', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicator_at_component = IndicatorAtComponent(unique_name=indicator)
        state = pecan.request.rpcapi.get_indicator_state(
            pecan.request.context, rpc_node.uuid,
            indicator_at_component.component, indicator_at_component.name,
            topic=topic)
        return IndicatorState(state=state)

    @METRICS.timer('IndicatorController.get_all')
    @expose.expose(IndicatorsCollection, types.uuid_or_name, str,
                   ignore_extra_args=True)
    def get_all(self, node_ident):
        """Get node hardware components and their indicators.

        :param node_ident: the UUID or logical name of a node.
        :returns: A json object of hardware components
            (:mod:`ironic.common.components`) as keys with indicator IDs
            (from `get_supported_indicators`) as values.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_indicator_state', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        indicators = pecan.request.rpcapi.get_supported_indicators(
            pecan.request.context, rpc_node.uuid, topic=topic)

        return IndicatorsCollection.collection_from_dict(
            node_ident, indicators)


class InjectNmiController(rest.RestController):

    @METRICS.timer('InjectNmiController.put')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
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


class ConsoleInfo(base.Base):
    """API representation of the console information for a node."""

    console_enabled = types.boolean
    """The console state: if the console is enabled or not."""

    console_info = {str: types.jsontype}
    """The console information. It typically includes the url to access the
    console and the type of the application that hosts the console."""

    @classmethod
    def sample(cls):
        console = {'type': 'shellinabox', 'url': 'http://<hostname>:4201'}
        return cls(console_enabled=True, console_info=console)


class NodeConsoleController(rest.RestController):

    @METRICS.timer('NodeConsoleController.get')
    @expose.expose(ConsoleInfo, types.uuid_or_name)
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

        return ConsoleInfo(console_enabled=console_state, console_info=console)

    @METRICS.timer('NodeConsoleController.put')
    @expose.expose(None, types.uuid_or_name, types.boolean,
                   status_code=http_client.ACCEPTED)
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


class NodeStates(base.APIBase):
    """API representation of the states of a node."""

    console_enabled = types.boolean
    """Indicates whether the console access is enabled or disabled on
    the node."""

    power_state = str
    """Represent the current (not transition) power state of the node"""

    provision_state = str
    """Represent the current (not transition) provision state of the node"""

    provision_updated_at = datetime.datetime
    """The UTC date and time of the last provision state change"""

    target_power_state = str
    """The user modified desired power state of the node."""

    target_provision_state = str
    """The user modified desired provision state of the node."""

    last_error = str
    """Any error from the most recent (last) asynchronous transaction that
    started but failed to finish."""

    raid_config = atypes.wsattr({str: types.jsontype}, readonly=True)
    """Represents the RAID configuration that the node is configured with."""

    target_raid_config = atypes.wsattr({str: types.jsontype},
                                       readonly=True)
    """The desired RAID configuration, to be used the next time the node
    is configured."""

    @staticmethod
    def convert(rpc_node):
        attr_list = ['console_enabled', 'last_error', 'power_state',
                     'provision_state', 'target_power_state',
                     'target_provision_state', 'provision_updated_at']
        if api_utils.allow_raid_config():
            attr_list.extend(['raid_config', 'target_raid_config'])
        states = NodeStates()
        for attr in attr_list:
            setattr(states, attr, getattr(rpc_node, attr))
        update_state_in_older_versions(states)
        return states

    @classmethod
    def sample(cls):
        sample = cls(target_power_state=ir_states.POWER_ON,
                     target_provision_state=ir_states.ACTIVE,
                     last_error=None,
                     console_enabled=False,
                     provision_updated_at=None,
                     power_state=ir_states.POWER_ON,
                     provision_state=None,
                     raid_config=None,
                     target_raid_config=None)
        return sample


class NodeStatesController(rest.RestController):

    _custom_actions = {
        'power': ['PUT'],
        'provision': ['PUT'],
        'raid': ['PUT'],
    }

    console = NodeConsoleController()
    """Expose console as a sub-element of states"""

    @METRICS.timer('NodeStatesController.get')
    @expose.expose(NodeStates, types.uuid_or_name)
    def get(self, node_ident):
        """List the states of the node.

        :param node_ident: the UUID or logical_name of a node.
        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:get_states', node_ident)

        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        return NodeStates.convert(rpc_node)

    @METRICS.timer('NodeStatesController.raid')
    @expose.expose(None, types.uuid_or_name, body=types.jsontype)
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
    @expose.expose(None, types.uuid_or_name, str,
                   atypes.IntegerType(minimum=1),
                   status_code=http_client.ACCEPTED)
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
        # FIXME(naohirot): This check is workaround because
        #                  atypes.IntegerType(minimum=1) is not effective
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
                             clean_steps=None, rescue_password=None):
        topic = api.request.rpcapi.get_topic_for(rpc_node)
        # Note that there is a race condition. The node state(s) could change
        # by the time the RPC call is made and the TaskManager manager gets a
        # lock.
        if target in (ir_states.ACTIVE, ir_states.REBUILD):
            rebuild = (target == ir_states.REBUILD)
            api.request.rpcapi.do_node_deploy(context=api.request.context,
                                              node_id=rpc_node.uuid,
                                              rebuild=rebuild,
                                              configdrive=configdrive,
                                              topic=topic)
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
                api.request.context, rpc_node.uuid, clean_steps, topic)
        elif target in PROVISION_ACTION_STATES:
            api.request.rpcapi.do_provisioning_action(
                api.request.context, rpc_node.uuid, target, topic)
        else:
            msg = (_('The requested action "%(action)s" could not be '
                     'understood.') % {'action': target})
            raise exception.InvalidStateRequested(message=msg)

    @METRICS.timer('NodeStatesController.provision')
    @expose.expose(None, types.uuid_or_name, str,
                   types.jsontype, types.jsontype, str,
                   status_code=http_client.ACCEPTED)
    def provision(self, node_ident, target, configdrive=None,
                  clean_steps=None, rescue_password=None):
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
        :param rescue_password: A string representing the password to be set
            inside the rescue environment. This is required (and only valid),
            when target is "rescue".
        :raises: NodeLocked (HTTP 409) if the node is currently locked.
        :raises: ClientSideError (HTTP 409) if the node is already being
                 provisioned.
        :raises: InvalidParameterValue (HTTP 400), if validation of
                 clean_steps or power driver interface fails.
        :raises: InvalidStateRequested (HTTP 400) if the requested transition
                 is not possible from the current state.
        :raises: NodeInMaintenance (HTTP 400), if operation cannot be
                 performed because the node is in maintenance mode.
        :raises: NoFreeConductorWorker (HTTP 503) if no workers are available.
        :raises: NotAcceptable (HTTP 406) if the API version specified does
                 not allow the requested state transition.
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

        if clean_steps and target != ir_states.VERBS['clean']:
            msg = (_('"clean_steps" is only valid when setting target '
                     'provision state to %s') % ir_states.VERBS['clean'])
            raise exception.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)

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
                                  rescue_password)

        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        api.response.location = link.build_url('nodes', url_args)


def _check_clean_steps(clean_steps):
    """Ensure all necessary keys are present and correct in clean steps.

    Check that the user-specified clean steps are in the expected format and
    include the required information.

    :param clean_steps: a list of clean steps. For more details, see the
        clean_steps parameter of :func:`NodeStatesController.provision`.
    :raises: InvalidParameterValue if validation of clean steps fails.
    """
    try:
        jsonschema.validate(clean_steps, _CLEAN_STEPS_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise exception.InvalidParameterValue(_('Invalid clean_steps: %s') %
                                              exc)


class Traits(base.APIBase):
    """API representation of the traits for a node."""

    traits = atypes.ArrayType(str)
    """node traits"""

    @classmethod
    def sample(cls):
        traits = ["CUSTOM_TRAIT1", "CUSTOM_TRAIT2"]
        return cls(traits=traits)


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
    @expose.expose(Traits)
    def get_all(self):
        """List node traits."""
        node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:traits:list', self.node_ident)
        traits = objects.TraitList.get_by_node_id(api.request.context,
                                                  node.id)
        return Traits(traits=traits.get_trait_names())

    @METRICS.timer('NodeTraitsController.put')
    @expose.expose(None, str, atypes.ArrayType(str),
                   status_code=http_client.NO_CONTENT)
    def put(self, trait=None, traits=None):
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

        for trait in traits:
            api_utils.validate_trait(trait)

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
    @expose.expose(None, str,
                   status_code=http_client.NO_CONTENT)
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


class Node(base.APIBase):
    """API representation of a bare metal node.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a node.
    """

    _chassis_uuid = None

    def _get_chassis_uuid(self):
        return self._chassis_uuid

    def _set_chassis_uuid(self, value):
        if value in (atypes.Unset, None):
            self._chassis_uuid = value
        elif self._chassis_uuid != value:
            try:
                chassis = objects.Chassis.get(api.request.context, value)
                self._chassis_uuid = chassis.uuid
                # NOTE(lucasagomes): Create the chassis_id attribute on-the-fly
                #                    to satisfy the api -> rpc object
                #                    conversion.
                self.chassis_id = chassis.id
            except exception.ChassisNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = http_client.BAD_REQUEST
                raise

    uuid = types.uuid
    """Unique UUID for this node"""

    instance_uuid = types.uuid
    """The UUID of the instance in nova-compute"""

    name = atypes.wsattr(str)
    """The logical name for this node"""

    power_state = atypes.wsattr(str, readonly=True)
    """Represent the current (not transition) power state of the node"""

    target_power_state = atypes.wsattr(str, readonly=True)
    """The user modified desired power state of the node."""

    last_error = atypes.wsattr(str, readonly=True)
    """Any error from the most recent (last) asynchronous transaction that
    started but failed to finish."""

    provision_state = atypes.wsattr(str, readonly=True)
    """Represent the current (not transition) provision state of the node"""

    reservation = atypes.wsattr(str, readonly=True)
    """The hostname of the conductor that holds an exclusive lock on
    the node."""

    provision_updated_at = datetime.datetime
    """The UTC date and time of the last provision state change"""

    inspection_finished_at = datetime.datetime
    """The UTC date and time when the last hardware inspection finished
    successfully."""

    inspection_started_at = datetime.datetime
    """The UTC date and time when the hardware inspection was started"""

    maintenance = types.boolean
    """Indicates whether the node is in maintenance mode."""

    maintenance_reason = atypes.wsattr(str, readonly=True)
    """Indicates reason for putting a node in maintenance mode."""

    fault = atypes.wsattr(str, readonly=True)
    """Indicates the active fault of a node."""

    target_provision_state = atypes.wsattr(str, readonly=True)
    """The user modified desired provision state of the node."""

    console_enabled = types.boolean
    """Indicates whether the console access is enabled or disabled on
    the node."""

    instance_info = {str: types.jsontype}
    """This node's instance info."""

    driver = atypes.wsattr(str, mandatory=True)
    """The driver responsible for controlling the node"""

    driver_info = {str: types.jsontype}
    """This node's driver configuration"""

    driver_internal_info = atypes.wsattr({str: types.jsontype},
                                         readonly=True)
    """This driver's internal configuration"""

    clean_step = atypes.wsattr({str: types.jsontype}, readonly=True)
    """The current clean step"""

    deploy_step = atypes.wsattr({str: types.jsontype}, readonly=True)
    """The current deploy step"""

    raid_config = atypes.wsattr({str: types.jsontype}, readonly=True)
    """Represents the current RAID configuration of the node """

    target_raid_config = atypes.wsattr({str: types.jsontype},
                                       readonly=True)
    """The user modified RAID configuration of the node """

    extra = {str: types.jsontype}
    """This node's meta data"""

    resource_class = atypes.wsattr(atypes.StringType(max_length=80))
    """The resource class for the node, useful for classifying or grouping
       nodes. Used, for example, to classify nodes in Nova's placement
       engine."""

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {str: types.jsontype}
    """The physical characteristics of this node"""

    chassis_uuid = atypes.wsproperty(types.uuid, _get_chassis_uuid,
                                     _set_chassis_uuid)
    """The UUID of the chassis this node belongs"""

    links = atypes.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated node links"""

    ports = atypes.wsattr([link.Link], readonly=True)
    """Links to the collection of ports on this node"""

    portgroups = atypes.wsattr([link.Link], readonly=True)
    """Links to the collection of portgroups on this node"""

    volume = atypes.wsattr([link.Link], readonly=True)
    """Links to endpoint for retrieving volume resources on this node"""

    states = atypes.wsattr([link.Link], readonly=True)
    """Links to endpoint for retrieving and setting node states"""

    boot_interface = atypes.wsattr(str)
    """The boot interface to be used for this node"""

    console_interface = atypes.wsattr(str)
    """The console interface to be used for this node"""

    deploy_interface = atypes.wsattr(str)
    """The deploy interface to be used for this node"""

    inspect_interface = atypes.wsattr(str)
    """The inspect interface to be used for this node"""

    management_interface = atypes.wsattr(str)
    """The management interface to be used for this node"""

    network_interface = atypes.wsattr(str)
    """The network interface to be used for this node"""

    power_interface = atypes.wsattr(str)
    """The power interface to be used for this node"""

    raid_interface = atypes.wsattr(str)
    """The raid interface to be used for this node"""

    rescue_interface = atypes.wsattr(str)
    """The rescue interface to be used for this node"""

    storage_interface = atypes.wsattr(str)
    """The storage interface to be used for this node"""

    vendor_interface = atypes.wsattr(str)
    """The vendor interface to be used for this node"""

    traits = atypes.ArrayType(str)
    """The traits associated with this node"""

    bios_interface = atypes.wsattr(str)
    """The bios interface to be used for this node"""

    conductor_group = atypes.wsattr(str)
    """The conductor group to manage this node"""

    automated_clean = types.boolean
    """Indicates whether the node will perform automated clean or not."""

    protected = types.boolean
    """Indicates whether the node is protected from undeploying/rebuilding."""

    protected_reason = atypes.wsattr(str)
    """Indicates reason for protecting the node."""

    conductor = atypes.wsattr(str, readonly=True)
    """Represent the conductor currently serving the node"""

    owner = atypes.wsattr(str)
    """Field for storage of physical node owner"""

    lessee = atypes.wsattr(str)
    """Field for storage of physical node lessee"""

    description = atypes.wsattr(str)
    """Field for node description"""

    allocation_uuid = atypes.wsattr(types.uuid, readonly=True)
    """The UUID of the allocation this node belongs"""

    retired = types.boolean
    """Indicates whether the node is marked for retirement."""

    retired_reason = atypes.wsattr(str)
    """Indicates the reason for a node's retirement."""

    # NOTE(tenbrae): "conductor_affinity" shouldn't be presented on the
    #                API because it's an internal value. Don't add it here.

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Node.fields)
        # NOTE(lucasagomes): chassis_uuid is not part of objects.Node.fields
        # because it's an API-only attribute.
        fields.append('chassis_uuid')
        # NOTE(kaifeng) conductor is not part of objects.Node.fields too.
        fields.append('conductor')
        for k in fields:
            # Add fields we expose.
            if hasattr(self, k):
                self.fields.append(k)
                # TODO(jroll) is there a less hacky way to do this?
                if k == 'traits' and kwargs.get('traits') is not None:
                    value = [t['trait'] for t in kwargs['traits']['objects']]
                # NOTE(jroll) this is special-cased to "" and not Unset,
                # because it is used in hash ring calculations
                elif (k == 'conductor_group'
                      and (k not in kwargs or kwargs[k] is atypes.Unset)):
                    value = ''
                else:
                    value = kwargs.get(k, atypes.Unset)
                setattr(self, k, value)

        # NOTE(lucasagomes): chassis_id is an attribute created on-the-fly
        # by _set_chassis_uuid(), it needs to be present in the fields so
        # that as_dict() will contain chassis_id field when converting it
        # before saving it in the database.
        self.fields.append('chassis_id')
        if 'chassis_uuid' not in kwargs:
            setattr(self, 'chassis_uuid', kwargs.get('chassis_id',
                                                     atypes.Unset))

    @staticmethod
    def _convert_with_links(node, url, fields=None, show_states_links=True,
                            show_portgroups=True, show_volume=True):
        if fields is None:
            node.ports = [link.Link.make_link('self', url, 'nodes',
                                              node.uuid + "/ports"),
                          link.Link.make_link('bookmark', url, 'nodes',
                                              node.uuid + "/ports",
                                              bookmark=True)
                          ]
            if show_states_links:
                node.states = [link.Link.make_link('self', url, 'nodes',
                                                   node.uuid + "/states"),
                               link.Link.make_link('bookmark', url, 'nodes',
                                                   node.uuid + "/states",
                                                   bookmark=True)]
            if show_portgroups:
                node.portgroups = [
                    link.Link.make_link('self', url, 'nodes',
                                        node.uuid + "/portgroups"),
                    link.Link.make_link('bookmark', url, 'nodes',
                                        node.uuid + "/portgroups",
                                        bookmark=True)]

            if show_volume:
                node.volume = [
                    link.Link.make_link('self', url, 'nodes',
                                        node.uuid + "/volume"),
                    link.Link.make_link('bookmark', url, 'nodes',
                                        node.uuid + "/volume",
                                        bookmark=True)]

        node.links = [link.Link.make_link('self', url, 'nodes',
                                          node.uuid),
                      link.Link.make_link('bookmark', url, 'nodes',
                                          node.uuid, bookmark=True)
                      ]
        return node

    @classmethod
    def convert_with_links(cls, rpc_node, fields=None, sanitize=True):
        node = Node(**rpc_node.as_dict())

        if (api_utils.allow_expose_conductors()
                and (fields is None or 'conductor' in fields)):
            # NOTE(kaifeng) It is possible a node gets orphaned in certain
            # circumstances, set conductor to None in such case.
            try:
                host = api.request.rpcapi.get_conductor_for(rpc_node)
                node.conductor = host
            except (exception.NoValidHost, exception.TemporaryFailure):
                LOG.debug('Currently there is no conductor servicing node '
                          '%(node)s.', {'node': rpc_node.uuid})
                node.conductor = None

        if (api_utils.allow_allocations()
                and (fields is None or 'allocation_uuid' in fields)):
            node.allocation_uuid = None
            if rpc_node.allocation_id:
                try:
                    allocation = objects.Allocation.get_by_id(
                        api.request.context,
                        rpc_node.allocation_id)
                    node.allocation_uuid = allocation.uuid
                except exception.AllocationNotFound:
                    pass

        if fields is not None:
            api_utils.check_for_invalid_fields(
                fields, set(node.as_dict()) | {'allocation_uuid'})

        show_states_links = (
            api_utils.allow_links_node_states_and_driver_properties())
        show_portgroups = api_utils.allow_portgroups_subcontrollers()
        show_volume = api_utils.allow_volume()

        node = cls._convert_with_links(node, api.request.public_url,
                                       fields=fields,
                                       show_states_links=show_states_links,
                                       show_portgroups=show_portgroups,
                                       show_volume=show_volume)
        if not sanitize:
            return node

        node.sanitize(fields)

        return node

    def sanitize(self, fields):
        """Removes sensitive and unrequested data.

        Will only keep the fields specified in the ``fields`` parameter.

        :param fields:
            list of fields to preserve, or ``None`` to preserve them all
        :type fields: list of str
        """
        cdict = api.request.context.to_policy_values()
        # NOTE(tenbrae): the 'show_password' policy setting name exists for
        #             legacy purposes and can not be changed. Changing it will
        #             cause upgrade problems for any operators who have
        #             customized the value of this field
        show_driver_secrets = policy.check("show_password", cdict, cdict)
        show_instance_secrets = policy.check("show_instance_secrets",
                                             cdict, cdict)

        if not show_driver_secrets and self.driver_info != atypes.Unset:
            self.driver_info = strutils.mask_dict_password(
                self.driver_info, "******")

            # NOTE(derekh): mask ssh keys for the ssh power driver.
            # As this driver is deprecated masking here (opposed to strutils)
            # is simpler, and easier to backport. This can be removed along
            # with support for the ssh power driver.
            if self.driver_info.get('ssh_key_contents'):
                self.driver_info['ssh_key_contents'] = "******"

        if not show_instance_secrets and self.instance_info != atypes.Unset:
            self.instance_info = strutils.mask_dict_password(
                self.instance_info, "******")
            # NOTE(tenbrae): agent driver may store a swift temp_url on the
            # instance_info, which shouldn't be exposed to non-admin users.
            # Now that ironic supports additional policies, we need to hide
            # it here, based on this policy.
            # Related to bug #1613903
            if self.instance_info.get('image_url'):
                self.instance_info['image_url'] = "******"

        if self.driver_internal_info.get('agent_secret_token'):
            self.driver_internal_info['agent_secret_token'] = "******"

        update_state_in_older_versions(self)
        hide_fields_in_newer_versions(self)

        if fields is not None:
            self.unset_fields_except(fields)

        # NOTE(lucasagomes): The numeric ID should not be exposed to
        #                    the user, it's internal only.
        self.chassis_id = atypes.Unset

        show_states_links = (
            api_utils.allow_links_node_states_and_driver_properties())
        show_portgroups = api_utils.allow_portgroups_subcontrollers()
        show_volume = api_utils.allow_volume()

        if not show_volume:
            self.volume = atypes.Unset
        if not show_portgroups:
            self.portgroups = atypes.Unset
        if not show_states_links:
            self.states = atypes.Unset

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        node_uuid = '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        instance_uuid = 'dcf1fbc5-93fc-4596-9395-b80572f6267b'
        name = 'database16-dc02'
        sample = cls(uuid=node_uuid, instance_uuid=instance_uuid,
                     name=name, power_state=ir_states.POWER_ON,
                     target_power_state=ir_states.NOSTATE,
                     last_error=None, provision_state=ir_states.ACTIVE,
                     target_provision_state=ir_states.NOSTATE,
                     reservation=None, driver='fake', driver_info={},
                     driver_internal_info={}, extra={},
                     properties={
                         'memory_mb': '1024', 'local_gb': '10', 'cpus': '1'},
                     updated_at=time, created_at=time,
                     provision_updated_at=time, instance_info={},
                     maintenance=False, maintenance_reason=None, fault=None,
                     inspection_finished_at=None, inspection_started_at=time,
                     console_enabled=False, clean_step={}, deploy_step={},
                     raid_config=None, target_raid_config=None,
                     network_interface='flat', resource_class='baremetal-gold',
                     boot_interface=None, console_interface=None,
                     deploy_interface=None, inspect_interface=None,
                     management_interface=None, power_interface=None,
                     raid_interface=None, vendor_interface=None,
                     storage_interface=None, traits=[], rescue_interface=None,
                     bios_interface=None, conductor_group="",
                     automated_clean=None, protected=False,
                     protected_reason=None, owner=None,
                     allocation_uuid='982ddb5b-bce5-4d23-8fb8-7f710f648cd5',
                     retired=False, retired_reason=None, lessee=None)
        # NOTE(matty_dubs): The chassis_uuid getter() is based on the
        # _chassis_uuid variable:
        sample._chassis_uuid = 'edcad704-b2da-41d5-96d9-afd580ecfa12'
        fields = None if expand else _DEFAULT_RETURN_FIELDS
        return cls._convert_with_links(sample, 'http://localhost:6385',
                                       fields=fields)


class NodePatchType(types.JsonPatchType):

    _api_base = Node

    @staticmethod
    def internal_attrs():
        defaults = types.JsonPatchType.internal_attrs()
        # TODO(lucasagomes): Include maintenance once the endpoint
        # v1/nodes/<uuid>/maintenance do more things than updating the DB.
        return defaults + ['/console_enabled', '/last_error',
                           '/power_state', '/provision_state', '/reservation',
                           '/target_power_state', '/target_provision_state',
                           '/provision_updated_at', '/maintenance_reason',
                           '/driver_internal_info', '/inspection_finished_at',
                           '/inspection_started_at', '/clean_step',
                           '/deploy_step',
                           '/raid_config', '/target_raid_config',
                           '/fault', '/conductor', '/allocation_uuid']


class NodeCollection(collection.Collection):
    """API representation of a collection of nodes."""

    nodes = [Node]
    """A list containing nodes objects"""

    def __init__(self, **kwargs):
        self._type = 'nodes'

    @staticmethod
    def convert_with_links(nodes, limit, url=None, fields=None, **kwargs):
        collection = NodeCollection()
        collection.nodes = [Node.convert_with_links(n, fields=fields,
                                                    sanitize=False)
                            for n in nodes]
        collection.next = collection.get_next(limit, url=url, fields=fields,
                                              **kwargs)

        for node in collection.nodes:
            node.sanitize(fields)

        return collection

    @classmethod
    def sample(cls):
        sample = cls()
        node = Node.sample(expand=False)
        sample.nodes = [node]
        return sample


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
    @expose.expose(str, types.uuid_or_name)
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
    @expose.expose(str, types.uuid_or_name, str,
                   body=str)
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
        return api_utils.vendor_passthru(rpc_node.uuid, method, topic,
                                         data=data)


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
    @expose.expose(None, types.uuid_or_name, str,
                   status_code=http_client.ACCEPTED)
    def put(self, node_ident, reason=None):
        """Put the node in maintenance mode.

        :param node_ident: the UUID or logical_name of a node.
        :param reason: Optional, the reason why it's in maintenance.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:set_maintenance', node_ident)

        self._set_maintenance(rpc_node, True, reason=reason)

    @METRICS.timer('NodeMaintenanceController.delete')
    @expose.expose(None, types.uuid_or_name, status_code=http_client.ACCEPTED)
    def delete(self, node_ident):
        """Remove the node from maintenance mode.

        :param node_ident: the UUID or logical name of a node.

        """
        rpc_node = api_utils.check_node_policy_and_retrieve(
            'baremetal:node:clear_maintenance', node_ident)

        self._set_maintenance(rpc_node, False)


# NOTE(vsaienko) We don't support pagination with VIFs, so we don't use
# collection.Collection here.
class VifCollection(base.Base):
    """API representation of a collection of VIFs. """

    vifs = [types.viftype]
    """A list containing VIFs objects"""

    @staticmethod
    def collection_from_list(vifs):
        col = VifCollection()
        col.vifs = [types.VifType.frombasetype(vif) for vif in vifs]
        return col


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
    @expose.expose(VifCollection)
    def get_all(self):
        """Get a list of attached VIFs"""
        rpc_node, topic = self._get_node_and_topic('baremetal:node:vif:list')
        vifs = api.request.rpcapi.vif_list(api.request.context,
                                           rpc_node.uuid, topic=topic)
        return VifCollection.collection_from_list(vifs)

    @METRICS.timer('NodeVIFController.post')
    @expose.expose(None, body=types.viftype,
                   status_code=http_client.NO_CONTENT)
    def post(self, vif):
        """Attach a VIF to this node

        :param vif: a dictionary of information about a VIF.
            It must have an 'id' key, whose value is a unique identifier
            for that VIF.
        """
        rpc_node, topic = self._get_node_and_topic('baremetal:node:vif:attach')
        api.request.rpcapi.vif_attach(api.request.context, rpc_node.uuid,
                                      vif_info=vif, topic=topic)

    @METRICS.timer('NodeVIFController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
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
                             'traits']

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
        try:
            ident = types.uuid_or_name.validate(ident)
        except exception.InvalidUuidOrName as e:
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

        if instance_uuid:
            # NOTE(rloo) if instance_uuid is specified, the other query
            # parameters are ignored. Since there can be at most one node that
            # has this instance_uuid, we do not want to generate a 'next' link.

            nodes = self._get_nodes_by_instance(instance_uuid)

            # NOTE(rloo) if limit==1 and len(nodes)==1 (see
            # Collection.has_next()), a 'next' link will
            # be generated, which we don't want.
            limit = 0
        else:
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
            }
            filters = {}
            for key, value in possible_filters.items():
                if value is not None:
                    filters[key] = value

            nodes = objects.Node.list(api.request.context, limit, marker_obj,
                                      sort_key=sort_key, sort_dir=sort_dir,
                                      filters=filters)

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

        return NodeCollection.convert_with_links(nodes, limit,
                                                 url=resource_url,
                                                 fields=fields,
                                                 **parameters)

    def _get_nodes_by_instance(self, instance_uuid):
        """Retrieve a node by its instance uuid.

        It returns a list with the node, or an empty list if no node is found.
        """
        try:
            node = objects.Node.get_by_instance_uuid(api.request.context,
                                                     instance_uuid)
            return [node]
        except exception.InstanceNotFound:
            return []

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
        # NOTE(mgoddard): Traits cannot be updated via a node PATCH.
        fields = set(objects.Node.fields) - {'traits'}
        for field in fields:
            try:
                patch_val = getattr(node, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API, except
                # chassis_id. chassis_id would have been set (instead of
                # chassis_uuid) if the node belongs to a chassis. This
                # AttributeError is raised for chassis_id only if
                # 1. the node doesn't belong to a chassis or
                # 2. the node belonged to a chassis but is now being removed
                # from the chassis.
                if (field == "chassis_id" and rpc_node[field] is not None):
                    if not api_utils.allow_remove_chassis_uuid():
                        raise exception.NotAcceptable()
                    rpc_node[field] = None
                continue
            if patch_val == atypes.Unset:
                patch_val = None
            # conductor_group is case-insensitive, and we use it to calculate
            # the conductor to send an update too. lowercase it here instead
            # of just before saving so we calculate correctly.
            if field == 'conductor_group':
                patch_val = patch_val.lower()
            if rpc_node[field] != patch_val:
                rpc_node[field] = patch_val

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
    @expose.expose(NodeCollection, types.uuid, types.uuid, types.boolean,
                   types.boolean, types.boolean, str, types.uuid, int, str,
                   str, str, types.listtype, str,
                   str, str, types.boolean, str,
                   str, str, str, str)
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
    @expose.expose(NodeCollection, types.uuid, types.uuid, types.boolean,
                   types.boolean, types.boolean, str, types.uuid, int, str,
                   str, str, str, str,
                   str, str, str, str,
                   str, str)
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
    @expose.expose(str, types.uuid_or_name, types.uuid)
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
    @expose.expose(Node, types.uuid_or_name, types.listtype)
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

        return Node.convert_with_links(rpc_node, fields=fields)

    @METRICS.timer('NodesController.post')
    @expose.expose(Node, body=Node, status_code=http_client.CREATED)
    def post(self, node):
        """Create a new node.

        :param node: a node within the request body.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted()

        context = api.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:node:create', cdict, cdict)

        if node.conductor is not atypes.Unset:
            msg = _("Cannot specify conductor on node creation.")
            raise exception.Invalid(msg)

        reject_fields_in_newer_versions(node)

        if node.traits is not atypes.Unset:
            msg = _("Cannot specify node traits on node creation. Traits must "
                    "be set via the node traits API.")
            raise exception.Invalid(msg)

        if (node.protected is not atypes.Unset
                or node.protected_reason is not atypes.Unset):
            msg = _("Cannot specify protected or protected_reason on node "
                    "creation. These fields can only be set for active nodes")
            raise exception.Invalid(msg)

        if (node.description is not atypes.Unset
                and len(node.description) > _NODE_DESCRIPTION_MAX_LENGTH):
            msg = _("Cannot create node with description exceeding %s "
                    "characters") % _NODE_DESCRIPTION_MAX_LENGTH
            raise exception.Invalid(msg)

        if node.allocation_uuid is not atypes.Unset:
            msg = _("Allocation UUID cannot be specified, use allocations API")
            raise exception.Invalid(msg)

        # NOTE(tenbrae): get_topic_for checks if node.driver is in the hash
        #             ring and raises NoValidHost if it is not.
        #             We need to ensure that node has a UUID before it can
        #             be mapped onto the hash ring.
        if not node.uuid:
            node.uuid = uuidutils.generate_uuid()

        try:
            topic = api.request.rpcapi.get_topic_for(node)
        except exception.NoValidHost as e:
            # NOTE(tenbrae): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = http_client.BAD_REQUEST
            raise

        if node.name != atypes.Unset and node.name is not None:
            error_msg = _("Cannot create node with invalid name '%(name)s'")
            self._check_names_acceptable([node.name], error_msg)
        node.provision_state = api_utils.initial_node_provision_state()

        if not node.resource_class:
            node.resource_class = CONF.default_resource_class

        new_node = objects.Node(context, **node.as_dict())
        notify.emit_start_notification(context, new_node, 'create',
                                       chassis_uuid=node.chassis_uuid)
        with notify.handle_error_notification(context, new_node, 'create',
                                              chassis_uuid=node.chassis_uuid):
            new_node = api.request.rpcapi.create_node(context,
                                                      new_node, topic)
        # Set the HTTP Location Header
        api.response.location = link.build_url('nodes', new_node.uuid)
        api_node = Node.convert_with_links(new_node)
        notify.emit_end_notification(context, new_node, 'create',
                                     chassis_uuid=api_node.chassis_uuid)
        return api_node

    def _validate_patch(self, patch, reset_interfaces):
        if self.from_chassis:
            raise exception.OperationNotPermitted()

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

    def _authorize_patch_and_get_node(self, node_ident, patch):
        # deal with attribute-specific policy rules
        policy_checks = []
        generic_update = False
        for p in patch:
            if p['path'].startswith('/instance_info'):
                policy_checks.append('baremetal:node:update_instance_info')
            elif p['path'].startswith('/extra'):
                policy_checks.append('baremetal:node:update_extra')
            else:
                generic_update = True

        # always do at least one check
        if generic_update or not policy_checks:
            policy_checks.append('baremetal:node:update')

        return api_utils.check_multiple_node_policies_and_retrieve(
            policy_checks, node_ident, with_suffix=True)

    @METRICS.timer('NodesController.patch')
    @wsme.validate(types.uuid, types.boolean, [NodePatchType])
    @expose.expose(Node, types.uuid_or_name, types.boolean,
                   body=[NodePatchType])
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
        node_dict['chassis_uuid'] = node_dict.pop('chassis_id', None)
        node = Node(**api_utils.apply_jsonpatch(node_dict, patch))
        self._update_changed_fields(node, rpc_node)
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

        notify.emit_start_notification(context, rpc_node, 'update',
                                       chassis_uuid=node.chassis_uuid)
        with notify.handle_error_notification(context, rpc_node, 'update',
                                              chassis_uuid=node.chassis_uuid):
            new_node = api.request.rpcapi.update_node(context,
                                                      rpc_node, topic,
                                                      reset_interfaces)

        api_node = Node.convert_with_links(new_node)
        notify.emit_end_notification(context, new_node, 'update',
                                     chassis_uuid=api_node.chassis_uuid)

        return api_node

    @METRICS.timer('NodesController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
    def delete(self, node_ident):
        """Delete a node.

        :param node_ident: UUID or logical name of a node.
        """
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
