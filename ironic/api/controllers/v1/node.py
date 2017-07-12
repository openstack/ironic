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

from ironic_lib import metrics_utils
import jsonschema
from oslo_log import log
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest
from six.moves import http_client
import wsme
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import notification_utils as notify
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import portgroup
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.controllers.v1 import versions
from ironic.api.controllers.v1 import volume
from ironic.api import expose
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import policy
from ironic.common import states as ir_states
from ironic.conductor import utils as conductor_utils
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
                "enum": list(conductor_utils.CLEANING_INTERFACE_PRIORITY)
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
    if pecan.request.version.minor < versions.MINOR_3_DRIVER_INTERNAL_INFO:
        obj.driver_internal_info = wsme.Unset

    if not api_utils.allow_node_logical_names():
        obj.name = wsme.Unset

    # if requested version is < 1.6, hide inspection_*_at fields
    if pecan.request.version.minor < versions.MINOR_6_INSPECT_STATE:
        obj.inspection_finished_at = wsme.Unset
        obj.inspection_started_at = wsme.Unset

    if pecan.request.version.minor < versions.MINOR_7_NODE_CLEAN:
        obj.clean_step = wsme.Unset

    if pecan.request.version.minor < versions.MINOR_12_RAID_CONFIG:
        obj.raid_config = wsme.Unset
        obj.target_raid_config = wsme.Unset

    if pecan.request.version.minor < versions.MINOR_20_NETWORK_INTERFACE:
        obj.network_interface = wsme.Unset

    if not api_utils.allow_resource_class():
        obj.resource_class = wsme.Unset

    if not api_utils.allow_dynamic_interfaces():
        for field in api_utils.V31_FIELDS:
            setattr(obj, field, wsme.Unset)

    if not api_utils.allow_storage_interface():
        obj.storage_interface = wsme.Unset


def update_state_in_older_versions(obj):
    """Change provision state names for API backwards compatibility.

    :param obj: The object being returned to the API client that is
                to be updated by this method.
    """
    # if requested version is < 1.2, convert AVAILABLE to the old NOSTATE
    if (pecan.request.version.minor < versions.MINOR_2_AVAILABLE_STATE and
            obj.provision_state == ir_states.AVAILABLE):
        obj.provision_state = ir_states.NOSTATE


class BootDeviceController(rest.RestController):

    _custom_actions = {
        'supported': ['GET'],
    }

    def _get_boot_device(self, node_ident, supported=False):
        """Get the current boot device or a list of supported devices.

        :param node_ident: the UUID or logical name of a node.
        :param supported: Boolean value. If true return a list of
                          supported boot devices, if false return the
                          current boot device. Default: False.
        :returns: The current boot device or a list of the supported
                  boot devices.

        """
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        if supported:
            return pecan.request.rpcapi.get_supported_boot_devices(
                pecan.request.context, rpc_node.uuid, topic)
        else:
            return pecan.request.rpcapi.get_boot_device(pecan.request.context,
                                                        rpc_node.uuid, topic)

    @METRICS.timer('BootDeviceController.put')
    @expose.expose(None, types.uuid_or_name, wtypes.text, types.boolean,
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_boot_device', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.set_boot_device(pecan.request.context,
                                             rpc_node.uuid,
                                             boot_device,
                                             persistent=persistent,
                                             topic=topic)

    @METRICS.timer('BootDeviceController.get')
    @expose.expose(wtypes.text, types.uuid_or_name)
    def get(self, node_ident):
        """Get the current boot device for a node.

        :param node_ident: the UUID or logical name of a node.
        :returns: a json object containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_boot_device', cdict, cdict)

        return self._get_boot_device(node_ident)

    @METRICS.timer('BootDeviceController.supported')
    @expose.expose(wtypes.text, types.uuid_or_name)
    def supported(self, node_ident):
        """Get a list of the supported boot devices.

        :param node_ident: the UUID or logical name of a node.
        :returns: A json object with the list of supported boot
                  devices.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_boot_device', cdict, cdict)

        boot_devices = self._get_boot_device(node_ident, supported=True)
        return {'supported_boot_devices': boot_devices}


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

        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:inject_nmi', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.inject_nmi(pecan.request.context,
                                        rpc_node.uuid,
                                        topic=topic)


class NodeManagementController(rest.RestController):

    boot_device = BootDeviceController()
    """Expose boot_device as a sub-element of management"""

    inject_nmi = InjectNmiController()
    """Expose inject_nmi as a sub-element of management"""


class ConsoleInfo(base.APIBase):
    """API representation of the console information for a node."""

    console_enabled = types.boolean
    """The console state: if the console is enabled or not."""

    console_info = {wtypes.text: types.jsontype}
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_console', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        try:
            console = pecan.request.rpcapi.get_console_information(
                pecan.request.context, rpc_node.uuid, topic)
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_console_state', cdict, cdict)

        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.set_console_mode(pecan.request.context,
                                              rpc_node.uuid, enabled, topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states', 'console'])
        pecan.response.location = link.build_url('nodes', url_args)


class NodeStates(base.APIBase):
    """API representation of the states of a node."""

    console_enabled = types.boolean
    """Indicates whether the console access is enabled or disabled on
    the node."""

    power_state = wtypes.text
    """Represent the current (not transition) power state of the node"""

    provision_state = wtypes.text
    """Represent the current (not transition) provision state of the node"""

    provision_updated_at = datetime.datetime
    """The UTC date and time of the last provision state change"""

    target_power_state = wtypes.text
    """The user modified desired power state of the node."""

    target_provision_state = wtypes.text
    """The user modified desired provision state of the node."""

    last_error = wtypes.text
    """Any error from the most recent (last) asynchronous transaction that
    started but failed to finish."""

    raid_config = wsme.wsattr({wtypes.text: types.jsontype}, readonly=True)
    """Represents the RAID configuration that the node is configured with."""

    target_raid_config = wsme.wsattr({wtypes.text: types.jsontype},
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get_states', cdict, cdict)

        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        rpc_node = api_utils.get_rpc_node(node_ident)
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_raid_state', cdict, cdict)

        if not api_utils.allow_raid_config():
            raise exception.NotAcceptable()
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        try:
            pecan.request.rpcapi.set_target_raid_config(
                pecan.request.context, rpc_node.uuid,
                target_raid_config, topic=topic)
        except exception.UnsupportedDriverExtension as e:
            # Change error code as 404 seems appropriate because RAID is a
            # standard interface and all drivers might not have it.
            e.code = http_client.NOT_FOUND
            raise

    @METRICS.timer('NodeStatesController.power')
    @expose.expose(None, types.uuid_or_name, wtypes.text,
                   wtypes.IntegerType(minimum=1),
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_power_state', cdict, cdict)

        # TODO(lucasagomes): Test if it's able to transition to the
        #                    target state from the current one
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        if ((target in [ir_states.SOFT_REBOOT, ir_states.SOFT_POWER_OFF] or
             timeout) and not api_utils.allow_soft_power_off()):
            raise exception.NotAcceptable()
        # FIXME(naohirot): This check is workaround because
        #                  wtypes.IntegerType(minimum=1) is not effective
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

        pecan.request.rpcapi.change_node_power_state(pecan.request.context,
                                                     rpc_node.uuid, target,
                                                     timeout=timeout,
                                                     topic=topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        pecan.response.location = link.build_url('nodes', url_args)

    @METRICS.timer('NodeStatesController.provision')
    @expose.expose(None, types.uuid_or_name, wtypes.text,
                   wtypes.text, types.jsontype,
                   status_code=http_client.ACCEPTED)
    def provision(self, node_ident, target, configdrive=None,
                  clean_steps=None):
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
            configdrive. Only valid when setting provision state
            to "active".
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_provision_state', cdict, cdict)

        api_utils.check_allow_management_verbs(target)
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

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

        if configdrive and target != ir_states.ACTIVE:
            msg = (_('Adding a config drive is only supported when setting '
                     'provision state to %s') % ir_states.ACTIVE)
            raise wsme.exc.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)

        if clean_steps and target != ir_states.VERBS['clean']:
            msg = (_('"clean_steps" is only valid when setting target '
                     'provision state to %s') % ir_states.VERBS['clean'])
            raise wsme.exc.ClientSideError(
                msg, status_code=http_client.BAD_REQUEST)

        # Note that there is a race condition. The node state(s) could change
        # by the time the RPC call is made and the TaskManager manager gets a
        # lock.
        if target == ir_states.ACTIVE:
            pecan.request.rpcapi.do_node_deploy(pecan.request.context,
                                                rpc_node.uuid, False,
                                                configdrive, topic)
        elif target == ir_states.REBUILD:
            pecan.request.rpcapi.do_node_deploy(pecan.request.context,
                                                rpc_node.uuid, True,
                                                None, topic)
        elif target == ir_states.DELETED:
            pecan.request.rpcapi.do_node_tear_down(
                pecan.request.context, rpc_node.uuid, topic)
        elif target == ir_states.VERBS['inspect']:
            pecan.request.rpcapi.inspect_hardware(
                pecan.request.context, rpc_node.uuid, topic=topic)
        elif target == ir_states.VERBS['clean']:
            if not clean_steps:
                msg = (_('"clean_steps" is required when setting target '
                         'provision state to %s') % ir_states.VERBS['clean'])
                raise wsme.exc.ClientSideError(
                    msg, status_code=http_client.BAD_REQUEST)
            _check_clean_steps(clean_steps)
            pecan.request.rpcapi.do_node_clean(
                pecan.request.context, rpc_node.uuid, clean_steps, topic)
        elif target in PROVISION_ACTION_STATES:
            pecan.request.rpcapi.do_provisioning_action(
                pecan.request.context, rpc_node.uuid, target, topic)
        else:
            msg = (_('The requested action "%(action)s" could not be '
                     'understood.') % {'action': target})
            raise exception.InvalidStateRequested(message=msg)

        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        pecan.response.location = link.build_url('nodes', url_args)


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


class Node(base.APIBase):
    """API representation of a bare metal node.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a node.
    """

    _chassis_uuid = None

    def _get_chassis_uuid(self):
        return self._chassis_uuid

    def _set_chassis_uuid(self, value):
        if value in (wtypes.Unset, None):
            self._chassis_uuid = value
        elif self._chassis_uuid != value:
            try:
                chassis = objects.Chassis.get(pecan.request.context, value)
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

    name = wsme.wsattr(wtypes.text)
    """The logical name for this node"""

    power_state = wsme.wsattr(wtypes.text, readonly=True)
    """Represent the current (not transition) power state of the node"""

    target_power_state = wsme.wsattr(wtypes.text, readonly=True)
    """The user modified desired power state of the node."""

    last_error = wsme.wsattr(wtypes.text, readonly=True)
    """Any error from the most recent (last) asynchronous transaction that
    started but failed to finish."""

    provision_state = wsme.wsattr(wtypes.text, readonly=True)
    """Represent the current (not transition) provision state of the node"""

    reservation = wsme.wsattr(wtypes.text, readonly=True)
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

    maintenance_reason = wsme.wsattr(wtypes.text, readonly=True)
    """Indicates reason for putting a node in maintenance mode."""

    target_provision_state = wsme.wsattr(wtypes.text, readonly=True)
    """The user modified desired provision state of the node."""

    console_enabled = types.boolean
    """Indicates whether the console access is enabled or disabled on
    the node."""

    instance_info = {wtypes.text: types.jsontype}
    """This node's instance info."""

    driver = wsme.wsattr(wtypes.text, mandatory=True)
    """The driver responsible for controlling the node"""

    driver_info = {wtypes.text: types.jsontype}
    """This node's driver configuration"""

    driver_internal_info = wsme.wsattr({wtypes.text: types.jsontype},
                                       readonly=True)
    """This driver's internal configuration"""

    clean_step = wsme.wsattr({wtypes.text: types.jsontype}, readonly=True)
    """The current clean step"""

    raid_config = wsme.wsattr({wtypes.text: types.jsontype}, readonly=True)
    """Represents the current RAID configuration of the node """

    target_raid_config = wsme.wsattr({wtypes.text: types.jsontype},
                                     readonly=True)
    """The user modified RAID configuration of the node """

    extra = {wtypes.text: types.jsontype}
    """This node's meta data"""

    resource_class = wsme.wsattr(wtypes.StringType(max_length=80))
    """The resource class for the node, useful for classifying or grouping
       nodes. Used, for example, to classify nodes in Nova's placement
       engine."""

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {wtypes.text: types.jsontype}
    """The physical characteristics of this node"""

    chassis_uuid = wsme.wsproperty(types.uuid, _get_chassis_uuid,
                                   _set_chassis_uuid)
    """The UUID of the chassis this node belongs"""

    links = wsme.wsattr([link.Link], readonly=True)
    """A list containing a self link and associated node links"""

    ports = wsme.wsattr([link.Link], readonly=True)
    """Links to the collection of ports on this node"""

    portgroups = wsme.wsattr([link.Link], readonly=True)
    """Links to the collection of portgroups on this node"""

    volume = wsme.wsattr([link.Link], readonly=True)
    """Links to endpoint for retrieving volume resources on this node"""

    states = wsme.wsattr([link.Link], readonly=True)
    """Links to endpoint for retrieving and setting node states"""

    boot_interface = wsme.wsattr(wtypes.text)
    """The boot interface to be used for this node"""

    console_interface = wsme.wsattr(wtypes.text)
    """The console interface to be used for this node"""

    deploy_interface = wsme.wsattr(wtypes.text)
    """The deploy interface to be used for this node"""

    inspect_interface = wsme.wsattr(wtypes.text)
    """The inspect interface to be used for this node"""

    management_interface = wsme.wsattr(wtypes.text)
    """The management interface to be used for this node"""

    network_interface = wsme.wsattr(wtypes.text)
    """The network interface to be used for this node"""

    power_interface = wsme.wsattr(wtypes.text)
    """The power interface to be used for this node"""

    raid_interface = wsme.wsattr(wtypes.text)
    """The raid interface to be used for this node"""

    storage_interface = wsme.wsattr(wtypes.text)
    """The storage interface to be used for this node"""

    vendor_interface = wsme.wsattr(wtypes.text)
    """The vendor interface to be used for this node"""

    # NOTE(deva): "conductor_affinity" shouldn't be presented on the
    #             API because it's an internal value. Don't add it here.

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Node.fields)
        # NOTE(lucasagomes): chassis_uuid is not part of objects.Node.fields
        # because it's an API-only attribute.
        fields.append('chassis_uuid')
        for k in fields:
            # Add fields we expose.
            if hasattr(self, k):
                self.fields.append(k)
                setattr(self, k, kwargs.get(k, wtypes.Unset))

        # NOTE(lucasagomes): chassis_id is an attribute created on-the-fly
        # by _set_chassis_uuid(), it needs to be present in the fields so
        # that as_dict() will contain chassis_id field when converting it
        # before saving it in the database.
        self.fields.append('chassis_id')
        if 'chassis_uuid' not in kwargs:
            setattr(self, 'chassis_uuid', kwargs.get('chassis_id',
                                                     wtypes.Unset))

    @staticmethod
    def _convert_with_links(node, url, fields=None, show_states_links=True,
                            show_portgroups=True, show_volume=True):
        # NOTE(lucasagomes): Since we are able to return a specified set of
        # fields the "uuid" can be unset, so we need to save it in another
        # variable to use when building the links
        node_uuid = node.uuid
        if fields is not None:
            node.unset_fields_except(fields)
        else:
            node.ports = [link.Link.make_link('self', url, 'nodes',
                                              node_uuid + "/ports"),
                          link.Link.make_link('bookmark', url, 'nodes',
                                              node_uuid + "/ports",
                                              bookmark=True)
                          ]
            if show_states_links:
                node.states = [link.Link.make_link('self', url, 'nodes',
                                                   node_uuid + "/states"),
                               link.Link.make_link('bookmark', url, 'nodes',
                                                   node_uuid + "/states",
                                                   bookmark=True)]
            if show_portgroups:
                node.portgroups = [
                    link.Link.make_link('self', url, 'nodes',
                                        node_uuid + "/portgroups"),
                    link.Link.make_link('bookmark', url, 'nodes',
                                        node_uuid + "/portgroups",
                                        bookmark=True)]

            if show_volume:
                node.volume = [
                    link.Link.make_link('self', url, 'nodes',
                                        node_uuid + "/volume"),
                    link.Link.make_link('bookmark', url, 'nodes',
                                        node_uuid + "/volume",
                                        bookmark=True)]

        # NOTE(lucasagomes): The numeric ID should not be exposed to
        #                    the user, it's internal only.
        node.chassis_id = wtypes.Unset

        node.links = [link.Link.make_link('self', url, 'nodes',
                                          node_uuid),
                      link.Link.make_link('bookmark', url, 'nodes',
                                          node_uuid, bookmark=True)
                      ]
        return node

    @classmethod
    def convert_with_links(cls, rpc_node, fields=None):
        node = Node(**rpc_node.as_dict())

        if fields is not None:
            api_utils.check_for_invalid_fields(fields, node.as_dict())

        cdict = pecan.request.context.to_policy_values()
        # NOTE(deva): the 'show_password' policy setting name exists for legacy
        #             purposes and can not be changed. Changing it will cause
        #             upgrade problems for any operators who have customized
        #             the value of this field
        show_driver_secrets = policy.check("show_password", cdict, cdict)
        show_instance_secrets = policy.check("show_instance_secrets",
                                             cdict, cdict)

        if not show_driver_secrets and node.driver_info != wtypes.Unset:
            node.driver_info = strutils.mask_dict_password(
                node.driver_info, "******")

            # NOTE(derekh): mask ssh keys for the ssh power driver.
            # As this driver is deprecated masking here (opposed to strutils)
            # is simpler, and easier to backport. This can be removed along
            # with support for the ssh power driver.
            if node.driver_info.get('ssh_key_contents'):
                node.driver_info['ssh_key_contents'] = "******"

        if not show_instance_secrets and node.instance_info != wtypes.Unset:
            node.instance_info = strutils.mask_dict_password(
                node.instance_info, "******")
            # NOTE(deva): agent driver may store a swift temp_url on the
            # instance_info, which shouldn't be exposed to non-admin users.
            # Now that ironic supports additional policies, we need to hide
            # it here, based on this policy.
            # Related to bug #1613903
            if node.instance_info.get('image_url'):
                node.instance_info['image_url'] = "******"

        update_state_in_older_versions(node)
        hide_fields_in_newer_versions(node)
        show_states_links = (
            api_utils.allow_links_node_states_and_driver_properties())
        show_portgroups = api_utils.allow_portgroups_subcontrollers()
        show_volume = api_utils.allow_volume()
        return cls._convert_with_links(node, pecan.request.public_url,
                                       fields=fields,
                                       show_states_links=show_states_links,
                                       show_portgroups=show_portgroups,
                                       show_volume=show_volume)

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
                     maintenance=False, maintenance_reason=None,
                     inspection_finished_at=None, inspection_started_at=time,
                     console_enabled=False, clean_step={},
                     raid_config=None, target_raid_config=None,
                     network_interface='flat', resource_class='baremetal-gold',
                     boot_interface=None, console_interface=None,
                     deploy_interface=None, inspect_interface=None,
                     management_interface=None, power_interface=None,
                     raid_interface=None, vendor_interface=None,
                     storage_interface=None)
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
                           '/raid_config', '/target_raid_config']


class NodeCollection(collection.Collection):
    """API representation of a collection of nodes."""

    nodes = [Node]
    """A list containing nodes objects"""

    def __init__(self, **kwargs):
        self._type = 'nodes'

    @staticmethod
    def convert_with_links(nodes, limit, url=None, fields=None, **kwargs):
        collection = NodeCollection()
        collection.nodes = [Node.convert_with_links(n, fields=fields)
                            for n in nodes]
        collection.next = collection.get_next(limit, url=url, **kwargs)
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
    @expose.expose(wtypes.text, types.uuid_or_name)
    def methods(self, node_ident):
        """Retrieve information about vendor methods of the given node.

        :param node_ident: UUID or logical name of a node.
        :returns: dictionary with <vendor method name>:<method metadata>
                  entries.
        :raises: NodeNotFound if the node is not found.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:vendor_passthru', cdict, cdict)

        # Raise an exception if node is not found
        rpc_node = api_utils.get_rpc_node(node_ident)

        if rpc_node.driver not in _VENDOR_METHODS:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            ret = pecan.request.rpcapi.get_node_vendor_passthru_methods(
                pecan.request.context, rpc_node.uuid, topic=topic)
            _VENDOR_METHODS[rpc_node.driver] = ret

        return _VENDOR_METHODS[rpc_node.driver]

    @METRICS.timer('NodeVendorPassthruController._default')
    @expose.expose(wtypes.text, types.uuid_or_name, wtypes.text,
                   body=wtypes.text)
    def _default(self, node_ident, method, data=None):
        """Call a vendor extension.

        :param node_ident: UUID or logical name of a node.
        :param method: name of the method in vendor driver.
        :param data: body of data to supply to the specified method.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:vendor_passthru', cdict, cdict)

        # Raise an exception if node is not found
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        return api_utils.vendor_passthru(rpc_node.uuid, method, topic,
                                         data=data)


class NodeMaintenanceController(rest.RestController):

    def _set_maintenance(self, node_ident, maintenance_mode, reason=None):
        context = pecan.request.context
        rpc_node = api_utils.get_rpc_node(node_ident)
        rpc_node.maintenance = maintenance_mode
        rpc_node.maintenance_reason = reason
        notify.emit_start_notification(context, rpc_node, 'maintenance_set')
        with notify.handle_error_notification(context, rpc_node,
                                              'maintenance_set'):
            try:
                topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            except exception.NoValidHost as e:
                e.code = http_client.BAD_REQUEST
                raise

            new_node = pecan.request.rpcapi.update_node(context, rpc_node,
                                                        topic=topic)
        notify.emit_end_notification(context, new_node, 'maintenance_set')

    @METRICS.timer('NodeMaintenanceController.put')
    @expose.expose(None, types.uuid_or_name, wtypes.text,
                   status_code=http_client.ACCEPTED)
    def put(self, node_ident, reason=None):
        """Put the node in maintenance mode.

        :param node_ident: the UUID or logical_name of a node.
        :param reason: Optional, the reason why it's in maintenance.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:set_maintenance', cdict, cdict)

        self._set_maintenance(node_ident, True, reason=reason)

    @METRICS.timer('NodeMaintenanceController.delete')
    @expose.expose(None, types.uuid_or_name, status_code=http_client.ACCEPTED)
    def delete(self, node_ident):
        """Remove the node from maintenance mode.

        :param node_ident: the UUID or logical name of a node.

        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:clear_maintenance', cdict, cdict)

        self._set_maintenance(node_ident, False)


# NOTE(vsaienko) We don't support pagination with VIFs, so we don't use
# collection.Collection here.
class VifCollection(wtypes.Base):
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

    def _get_node_and_topic(self):
        rpc_node = api_utils.get_rpc_node(self.node_ident)
        try:
            return rpc_node, pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = http_client.BAD_REQUEST
            raise

    @METRICS.timer('NodeVIFController.get_all')
    @expose.expose(VifCollection)
    def get_all(self):
        """Get a list of attached VIFs"""
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:vif:list', cdict, cdict)
        rpc_node, topic = self._get_node_and_topic()
        vifs = pecan.request.rpcapi.vif_list(pecan.request.context,
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
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:vif:attach', cdict, cdict)
        rpc_node, topic = self._get_node_and_topic()
        pecan.request.rpcapi.vif_attach(pecan.request.context, rpc_node.uuid,
                                        vif_info=vif, topic=topic)

    @METRICS.timer('NodeVIFController.delete')
    @expose.expose(None, types.uuid_or_name,
                   status_code=http_client.NO_CONTENT)
    def delete(self, vif_id):
        """Detach a VIF from this node

        :param vif_id: The ID of a VIF to detach
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:vif:detach', cdict, cdict)
        rpc_node, topic = self._get_node_and_topic()
        pecan.request.rpcapi.vif_detach(pecan.request.context, rpc_node.uuid,
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
                             'clean_step', 'raid_config', 'target_raid_config']

    _subcontroller_map = {
        'ports': port.PortsController,
        'portgroups': portgroup.PortgroupsController,
        'vifs': NodeVIFController,
        'volume': volume.VolumeController,
    }

    @pecan.expose()
    def _lookup(self, ident, *remainder):
        try:
            ident = types.uuid_or_name.validate(ident)
        except exception.InvalidUuidOrName as e:
            pecan.abort(http_client.BAD_REQUEST, e.args[0])
        if not remainder:
            return
        if ((remainder[0] == 'portgroups' and
                not api_utils.allow_portgroups_subcontrollers()) or
            (remainder[0] == 'vifs' and
                not api_utils.allow_vifs_subcontroller())):
            pecan.abort(http_client.NOT_FOUND)
        subcontroller = self._subcontroller_map.get(remainder[0])
        if subcontroller:
            return subcontroller(node_ident=ident), remainder[1:]

    def _get_nodes_collection(self, chassis_uuid, instance_uuid, associated,
                              maintenance, provision_state, marker, limit,
                              sort_key, sort_dir, driver=None,
                              resource_class=None,
                              resource_url=None, fields=None):
        if self.from_chassis and not chassis_uuid:
            raise exception.MissingParameterValue(
                _("Chassis id not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(pecan.request.context,
                                                  marker)

        if sort_key in self.invalid_sort_key_list:
            raise exception.InvalidParameterValue(
                _("The sort_key value %(key)s is an invalid field for "
                  "sorting") % {'key': sort_key})

        if instance_uuid:
            nodes = self._get_nodes_by_instance(instance_uuid)
        else:
            filters = {}
            if chassis_uuid:
                filters['chassis_uuid'] = chassis_uuid
            if associated is not None:
                filters['associated'] = associated
            if maintenance is not None:
                filters['maintenance'] = maintenance
            if provision_state:
                filters['provision_state'] = provision_state
            if driver:
                filters['driver'] = driver
            if resource_class is not None:
                filters['resource_class'] = resource_class

            nodes = objects.Node.list(pecan.request.context, limit, marker_obj,
                                      sort_key=sort_key, sort_dir=sort_dir,
                                      filters=filters)

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}
        if associated:
            parameters['associated'] = associated
        if maintenance:
            parameters['maintenance'] = maintenance
        return NodeCollection.convert_with_links(nodes, limit,
                                                 url=resource_url,
                                                 fields=fields,
                                                 **parameters)

    def _get_nodes_by_instance(self, instance_uuid):
        """Retrieve a node by its instance uuid.

        It returns a list with the node, or an empty list if no node is found.
        """
        try:
            node = objects.Node.get_by_instance_uuid(pecan.request.context,
                                                     instance_uuid)
            return [node]
        except exception.InstanceNotFound:
            return []

    def _check_names_acceptable(self, names, error_msg):
        """Checks all node 'name's are acceptable, it does not return a value.

        This function will raise an exception for unacceptable names.

        :param names: list of node names to check
        :param error_msg: error message in case of wsme.exc.ClientSideError,
            should contain %(name)s placeholder.
        :raises: exception.NotAcceptable
        :raises: wsme.exc.ClientSideError
        """
        if not api_utils.allow_node_logical_names():
            raise exception.NotAcceptable()

        reserved_names = get_nodes_controller_reserved_names()
        for name in names:
            if not api_utils.is_valid_node_name(name):
                raise wsme.exc.ClientSideError(
                    error_msg % {'name': name},
                    status_code=http_client.BAD_REQUEST)
            if name in reserved_names:
                raise wsme.exc.ClientSideError(
                    'The word "%(name)s" is reserved and can not be used as a '
                    'node name. Reserved words are: %(reserved)s.' %
                    {'name': name,
                     'reserved': ', '.join(reserved_names)},
                    status_code=http_client.BAD_REQUEST)

    def _update_changed_fields(self, node, rpc_node):
        """Update rpc_node based on changed fields in a node.

        """
        for field in objects.Node.fields:
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
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_node[field] != patch_val:
                rpc_node[field] = patch_val

    def _check_driver_changed_and_console_enabled(self, rpc_node, node_ident):
        """Checks if the driver and the console is enabled in a node.

        If it does, is necessary to prevent updating it because the new driver
        will not be able to stop a console started by the previous one.

        :param rpc_node: RPC Node object to be verified.
        :param node_ident: the UUID or logical name of a node.
        :raises: wsme.exc.ClientSideError
        """
        delta = rpc_node.obj_what_changed()
        if 'driver' in delta and rpc_node.console_enabled:
            raise wsme.exc.ClientSideError(
                _("Node %s can not update the driver while the console is "
                  "enabled. Please stop the console first.") % node_ident,
                status_code=http_client.CONFLICT)

    @METRICS.timer('NodesController.get_all')
    @expose.expose(NodeCollection, types.uuid, types.uuid, types.boolean,
                   types.boolean, wtypes.text, types.uuid, int, wtypes.text,
                   wtypes.text, wtypes.text, types.listtype, wtypes.text)
    def get_all(self, chassis_uuid=None, instance_uuid=None, associated=None,
                maintenance=None, provision_state=None, marker=None,
                limit=None, sort_key='id', sort_dir='asc', driver=None,
                fields=None, resource_class=None):
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
        :param fields: Optional, a list with a specified set of fields
                       of the resource to be returned.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get', cdict, cdict)

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)
        api_utils.check_allowed_fields([sort_key])
        api_utils.check_for_invalid_state_and_allow_filter(provision_state)
        api_utils.check_allow_specify_driver(driver)
        api_utils.check_allow_specify_resource_class(resource_class)
        if fields is None:
            fields = _DEFAULT_RETURN_FIELDS
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance,
                                          provision_state, marker,
                                          limit, sort_key, sort_dir,
                                          driver=driver,
                                          resource_class=resource_class,
                                          fields=fields)

    @METRICS.timer('NodesController.detail')
    @expose.expose(NodeCollection, types.uuid, types.uuid, types.boolean,
                   types.boolean, wtypes.text, types.uuid, int, wtypes.text,
                   wtypes.text, wtypes.text, wtypes.text)
    def detail(self, chassis_uuid=None, instance_uuid=None, associated=None,
               maintenance=None, provision_state=None, marker=None,
               limit=None, sort_key='id', sort_dir='asc', driver=None,
               resource_class=None):
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
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get', cdict, cdict)

        api_utils.check_for_invalid_state_and_allow_filter(provision_state)
        api_utils.check_allow_specify_driver(driver)
        api_utils.check_allow_specify_resource_class(resource_class)
        api_utils.check_allowed_fields([sort_key])
        # /detail should only work against collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound()

        resource_url = '/'.join(['nodes', 'detail'])
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance,
                                          provision_state, marker,
                                          limit, sort_key, sort_dir,
                                          driver=driver,
                                          resource_class=resource_class,
                                          resource_url=resource_url)

    @METRICS.timer('NodesController.validate')
    @expose.expose(wtypes.text, types.uuid_or_name, types.uuid)
    def validate(self, node=None, node_uuid=None):
        """Validate the driver interfaces, using the node's UUID or name.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node.
        :param node_uuid: UUID of a node.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:validate', cdict, cdict)

        if node is not None:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            if (not api_utils.allow_node_logical_names() and
                not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        rpc_node = api_utils.get_rpc_node(node_uuid or node)

        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        return pecan.request.rpcapi.validate_driver_interfaces(
            pecan.request.context, rpc_node.uuid, topic)

    @METRICS.timer('NodesController.get_one')
    @expose.expose(Node, types.uuid_or_name, types.listtype)
    def get_one(self, node_ident, fields=None):
        """Retrieve information about the given node.

        :param node_ident: UUID or logical name of a node.
        :param fields: Optional, a list with a specified set of fields
            of the resource to be returned.
        """
        cdict = pecan.request.context.to_policy_values()
        policy.authorize('baremetal:node:get', cdict, cdict)

        if self.from_chassis:
            raise exception.OperationNotPermitted()

        api_utils.check_allow_specify_fields(fields)
        api_utils.check_allowed_fields(fields)

        rpc_node = api_utils.get_rpc_node(node_ident)
        return Node.convert_with_links(rpc_node, fields=fields)

    @METRICS.timer('NodesController.post')
    @expose.expose(Node, body=Node, status_code=http_client.CREATED)
    def post(self, node):
        """Create a new node.

        :param node: a node within the request body.
        """
        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:node:create', cdict, cdict)

        if self.from_chassis:
            raise exception.OperationNotPermitted()

        if (not api_utils.allow_resource_class() and
                node.resource_class is not wtypes.Unset):
            raise exception.NotAcceptable()

        n_interface = node.network_interface
        if (not api_utils.allow_network_interface() and
                n_interface is not wtypes.Unset):
            raise exception.NotAcceptable()

        if not api_utils.allow_dynamic_interfaces():
            for field in api_utils.V31_FIELDS:
                if getattr(node, field) is not wsme.Unset:
                    raise exception.NotAcceptable()

        if (not api_utils.allow_storage_interface() and
                node.storage_interface is not wtypes.Unset):
            raise exception.NotAcceptable()

        # NOTE(deva): get_topic_for checks if node.driver is in the hash ring
        #             and raises NoValidHost if it is not.
        #             We need to ensure that node has a UUID before it can
        #             be mapped onto the hash ring.
        if not node.uuid:
            node.uuid = uuidutils.generate_uuid()

        try:
            topic = pecan.request.rpcapi.get_topic_for(node)
        except exception.NoValidHost as e:
            # NOTE(deva): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = http_client.BAD_REQUEST
            raise

        if node.name != wtypes.Unset and node.name is not None:
            error_msg = _("Cannot create node with invalid name '%(name)s'")
            self._check_names_acceptable([node.name], error_msg)
        node.provision_state = api_utils.initial_node_provision_state()

        new_node = objects.Node(context, **node.as_dict())
        notify.emit_start_notification(context, new_node, 'create',
                                       chassis_uuid=node.chassis_uuid)
        with notify.handle_error_notification(context, new_node, 'create',
                                              chassis_uuid=node.chassis_uuid):
            new_node = pecan.request.rpcapi.create_node(context,
                                                        new_node, topic)
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('nodes', new_node.uuid)
        api_node = Node.convert_with_links(new_node)
        notify.emit_end_notification(context, new_node, 'create',
                                     chassis_uuid=api_node.chassis_uuid)
        return api_node

    @METRICS.timer('NodesController.patch')
    @wsme.validate(types.uuid, [NodePatchType])
    @expose.expose(Node, types.uuid_or_name, body=[NodePatchType])
    def patch(self, node_ident, patch):
        """Update an existing node.

        :param node_ident: UUID or logical name of a node.
        :param patch: a json PATCH document to apply to this node.
        """
        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:node:update', cdict, cdict)

        if self.from_chassis:
            raise exception.OperationNotPermitted()

        resource_class = api_utils.get_patch_values(patch, '/resource_class')
        if resource_class and not api_utils.allow_resource_class():
            raise exception.NotAcceptable()

        n_interfaces = api_utils.get_patch_values(patch, '/network_interface')
        if n_interfaces and not api_utils.allow_network_interface():
            raise exception.NotAcceptable()

        if not api_utils.allow_dynamic_interfaces():
            for field in api_utils.V31_FIELDS:
                if api_utils.get_patch_values(patch, '/%s' % field):
                    raise exception.NotAcceptable()

        s_interface = api_utils.get_patch_values(patch, '/storage_interface')
        if s_interface and not api_utils.allow_storage_interface():
            raise exception.NotAcceptable()

        rpc_node = api_utils.get_rpc_node(node_ident)

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
            raise wsme.exc.ClientSideError(
                msg % node_ident, status_code=http_client.CONFLICT)

        names = api_utils.get_patch_values(patch, '/name')
        if len(names):
            error_msg = (_("Node %s: Cannot change name to invalid name ")
                         % node_ident)
            error_msg += "'%(name)s'"
            self._check_names_acceptable(names, error_msg)
        try:
            node_dict = rpc_node.as_dict()
            # NOTE(lucasagomes):
            # 1) Remove chassis_id because it's an internal value and
            #    not present in the API object
            # 2) Add chassis_uuid
            node_dict['chassis_uuid'] = node_dict.pop('chassis_id', None)
            node = Node(**api_utils.apply_jsonpatch(node_dict, patch))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)
        self._update_changed_fields(node, rpc_node)
        # NOTE(deva): we calculate the rpc topic here in case node.driver
        #             has changed, so that update is sent to the
        #             new conductor, not the old one which may fail to
        #             load the new driver.
        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            # NOTE(deva): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = http_client.BAD_REQUEST
            raise
        self._check_driver_changed_and_console_enabled(rpc_node, node_ident)

        notify.emit_start_notification(context, rpc_node, 'update',
                                       chassis_uuid=node.chassis_uuid)
        with notify.handle_error_notification(context, rpc_node, 'update',
                                              chassis_uuid=node.chassis_uuid):
            new_node = pecan.request.rpcapi.update_node(context,
                                                        rpc_node, topic)

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
        context = pecan.request.context
        cdict = context.to_policy_values()
        policy.authorize('baremetal:node:delete', cdict, cdict)

        if self.from_chassis:
            raise exception.OperationNotPermitted()

        rpc_node = api_utils.get_rpc_node(node_ident)
        chassis_uuid = None
        if rpc_node.chassis_id:
            chassis_uuid = objects.Chassis.get_by_id(context,
                                                     rpc_node.chassis_id).uuid
        notify.emit_start_notification(context, rpc_node, 'delete',
                                       chassis_uuid=chassis_uuid)
        with notify.handle_error_notification(context, rpc_node, 'delete',
                                              chassis_uuid=chassis_uuid):
            try:
                topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            except exception.NoValidHost as e:
                e.code = http_client.BAD_REQUEST
                raise

            pecan.request.rpcapi.destroy_node(context, rpc_node.uuid, topic)
        notify.emit_end_notification(context, rpc_node, 'delete',
                                     chassis_uuid=chassis_uuid)
