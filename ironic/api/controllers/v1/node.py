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

import ast
import datetime

from oslo_config import cfg
from oslo_utils import strutils
from oslo_utils import uuidutils
import pecan
from pecan import rest
import wsme
from wsme import types as wtypes

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.api import expose
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states as ir_states
from ironic import objects
from ironic.openstack.common import log


CONF = cfg.CONF
CONF.import_opt('heartbeat_timeout', 'ironic.conductor.manager',
                group='conductor')

LOG = log.getLogger(__name__)

# Vendor information for node's driver:
#   key = driver name;
#   value = dictionary of node vendor methods of that driver:
#             key = method name.
#             value = dictionary with the metadata of that method.
# NOTE(lucasagomes). This is cached for the lifetime of the API
# service. If one or more conductor services are restarted with new driver
# versions, the API service should be restarted.
_VENDOR_METHODS = {}


def hide_fields_in_newer_versions(obj):
    # if requested version is < 1.3, hide driver_internal_info
    if pecan.request.version.minor < 3:
        obj.driver_internal_info = wsme.Unset

    if not api_utils.allow_node_logical_names():
        obj.name = wsme.Unset

    # if requested version is < 1.6, hide inspection_*_at fields
    if pecan.request.version.minor < 6:
        obj.inspection_finished_at = wsme.Unset
        obj.inspection_started_at = wsme.Unset


def assert_juno_provision_state_name(obj):
    # if requested version is < 1.2, convert AVAILABLE to the old NOSTATE
    if (pecan.request.version.minor < 2 and
            obj.provision_state == ir_states.AVAILABLE):
        obj.provision_state = ir_states.NOSTATE


def check_allow_management_verbs(verb):
    # v1.4 added the MANAGEABLE state and two verbs to move nodes into
    # and out of that state. Reject requests to do this in older versions
    if (pecan.request.version.minor < 4 and
            verb in [ir_states.VERBS['manage'], ir_states.VERBS['provide']]):
                raise exception.NotAcceptable()
    if (pecan.request.version.minor < 6 and
            verb == ir_states.VERBS['inspect']):
                raise exception.NotAcceptable()


class NodePatchType(types.JsonPatchType):

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
                           '/inspection_started_at', ]

    @staticmethod
    def mandatory_attrs():
        return ['/chassis_uuid', '/driver']


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

    @expose.expose(None, types.uuid_or_name, wtypes.text, types.boolean,
                         status_code=204)
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
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.set_boot_device(pecan.request.context,
                                             rpc_node.uuid,
                                             boot_device,
                                             persistent=persistent,
                                             topic=topic)

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
        return self._get_boot_device(node_ident)

    @expose.expose(wtypes.text, types.uuid_or_name)
    def supported(self, node_ident):
        """Get a list of the supported boot devices.

        :param node_ident: the UUID or logical name of a node.
        :returns: A json object with the list of supported boot
                  devices.

        """
        boot_devices = self._get_boot_device(node_ident, supported=True)
        return {'supported_boot_devices': boot_devices}


class NodeManagementController(rest.RestController):

    boot_device = BootDeviceController()
    """Expose boot_device as a sub-element of management"""


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

    @expose.expose(ConsoleInfo, types.uuid_or_name)
    def get(self, node_ident):
        """Get connection information about the console.

        :param node_ident: UUID or logical name of a node.
        """
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

    @expose.expose(None, types.uuid_or_name, types.boolean,
                         status_code=202)
    def put(self, node_ident, enabled):
        """Start and stop the node console.

        :param node_ident: UUID or logical name of a node.
        :param enabled: Boolean value; whether to enable or disable the
                console.
        """
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

    @staticmethod
    def convert(rpc_node):
        attr_list = ['console_enabled', 'last_error', 'power_state',
                     'provision_state', 'target_power_state',
                     'target_provision_state', 'provision_updated_at']
        states = NodeStates()
        for attr in attr_list:
            setattr(states, attr, getattr(rpc_node, attr))
        assert_juno_provision_state_name(states)
        return states

    @classmethod
    def sample(cls):
        sample = cls(target_power_state=ir_states.POWER_ON,
                     target_provision_state=ir_states.ACTIVE,
                     last_error=None,
                     console_enabled=False,
                     provision_updated_at=None,
                     power_state=ir_states.POWER_ON,
                     provision_state=None)
        return sample


class NodeStatesController(rest.RestController):

    _custom_actions = {
        'power': ['PUT'],
        'provision': ['PUT'],
    }

    console = NodeConsoleController()
    """Expose console as a sub-element of states"""

    @expose.expose(NodeStates, types.uuid_or_name)
    def get(self, node_ident):
        """List the states of the node.

        :param node_ident: the UUID or logical_name of a node.
        """
        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        rpc_node = api_utils.get_rpc_node(node_ident)
        return NodeStates.convert(rpc_node)

    @expose.expose(None, types.uuid_or_name, wtypes.text,
                         status_code=202)
    def power(self, node_ident, target):
        """Set the power state of the node.

        :param node_ident: the UUID or logical name of a node.
        :param target: The desired power state of the node.
        :raises: ClientSideError (HTTP 409) if a power operation is
                 already in progress.
        :raises: InvalidStateRequested (HTTP 400) if the requested target
                 state is not valid or if the node is in CLEANING state.

        """
        # TODO(lucasagomes): Test if it's able to transition to the
        #                    target state from the current one
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        if target not in [ir_states.POWER_ON,
                          ir_states.POWER_OFF,
                          ir_states.REBOOT]:
            raise exception.InvalidStateRequested(
                    action=target, node=node_ident,
                    state=rpc_node.power_state)

        # Don't change power state for nodes in cleaning
        elif rpc_node.provision_state == ir_states.CLEANING:
            raise exception.InvalidStateRequested(
                    action=target, node=node_ident,
                    state=rpc_node.provision_state)

        pecan.request.rpcapi.change_node_power_state(pecan.request.context,
                                                     rpc_node.uuid, target,
                                                     topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        pecan.response.location = link.build_url('nodes', url_args)

    @expose.expose(None, types.uuid_or_name, wtypes.text,
                         wtypes.text, status_code=202)
    def provision(self, node_ident, target, configdrive=None):
        """Asynchronous trigger the provisioning of the node.

        This will set the target provision state of the node, and a
        background task will begin which actually applies the state
        change. This call will return a 202 (Accepted) indicating the
        request was accepted and is in progress; the client should
        continue to GET the status of this node to observe the status
        of the requested action.

        :param node_ident: UUID or logical name of a node.
        :param target: The desired provision state of the node.
        :param configdrive: Optional. A gzipped and base64 encoded
            configdrive. Only valid when setting provision state
            to "active".
        :raises: NodeLocked (HTTP 409) if the node is currently locked.
        :raises: ClientSideError (HTTP 409) if the node is already being
                 provisioned.
        :raises: InvalidStateRequested (HTTP 400) if the requested transition
                 is not possible from the current state.
        :raises: NotAcceptable (HTTP 406) if the API version specified does
                 not allow the requested state transition.
        """
        check_allow_management_verbs(target)
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        # Normally, we let the task manager recognize and deal with
        # NodeLocked exceptions. However, that isn't done until the RPC calls
        # below. In order to main backward compatibility with our API HTTP
        # response codes, we have this check here to deal with cases where
        # a node is already being operated on (DEPLOYING or such) and we
        # want to continue returning 409. Without it, we'd return 400.
        if rpc_node.reservation:
            raise exception.NodeLocked(node=rpc_node.uuid,
                                       host=rpc_node.reservation)

        if (target in (ir_states.ACTIVE, ir_states.REBUILD)
                and rpc_node.maintenance):
            raise exception.NodeInMaintenance(op=_('provisioning'),
                                              node=rpc_node.uuid)

        m = ir_states.machine.copy()
        m.initialize(rpc_node.provision_state)
        if not m.is_valid_event(ir_states.VERBS.get(target, target)):
            raise exception.InvalidStateRequested(
                    action=target, node=rpc_node.uuid,
                    state=rpc_node.provision_state)

        if configdrive and target != ir_states.ACTIVE:
            msg = (_('Adding a config drive is only supported when setting '
                     'provision state to %s') % ir_states.ACTIVE)
            raise wsme.exc.ClientSideError(msg, status_code=400)

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
        elif target in (
                ir_states.VERBS['manage'], ir_states.VERBS['provide']):
            pecan.request.rpcapi.do_provisioning_action(
                    pecan.request.context, rpc_node.uuid, target, topic)
        else:
            msg = (_('The requested action "%(action)s" could not be '
                     'understood.') % {'action': target})
            raise exception.InvalidStateRequested(message=msg)

        # Set the HTTP Location Header
        url_args = '/'.join([node_ident, 'states'])
        pecan.response.location = link.build_url('nodes', url_args)


class Node(base.APIBase):
    """API representation of a bare metal node.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a node.
    """

    _chassis_uuid = None

    def _get_chassis_uuid(self):
        return self._chassis_uuid

    def _set_chassis_uuid(self, value):
        if value and self._chassis_uuid != value:
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
                e.code = 400  # BadRequest
                raise e
        elif value == wtypes.Unset:
            self._chassis_uuid = wtypes.Unset

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

    extra = {wtypes.text: types.jsontype}
    """This node's meta data"""

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

    # NOTE(deva): "conductor_affinity" shouldn't be presented on the
    #             API because it's an internal value. Don't add it here.

    def __init__(self, **kwargs):
        self.fields = []
        fields = list(objects.Node.fields)
        # NOTE(lucasagomes): chassis_uuid is not part of objects.Node.fields
        # because it's an API-only attribute.
        fields.append('chassis_uuid')
        for k in fields:
            # Skip fields we do not expose.
            if not hasattr(self, k):
                continue
            self.fields.append(k)
            setattr(self, k, kwargs.get(k, wtypes.Unset))

        # NOTE(lucasagomes): chassis_id is an attribute created on-the-fly
        # by _set_chassis_uuid(), it needs to be present in the fields so
        # that as_dict() will contain chassis_id field when converting it
        # before saving it in the database.
        self.fields.append('chassis_id')
        setattr(self, 'chassis_uuid', kwargs.get('chassis_id', wtypes.Unset))

    @staticmethod
    def _convert_with_links(node, url, expand=True, show_password=True):
        if not expand:
            except_list = ['instance_uuid', 'maintenance', 'power_state',
                           'provision_state', 'uuid', 'name']
            node.unset_fields_except(except_list)
        else:
            if not show_password:
                node.driver_info = ast.literal_eval(strutils.mask_password(
                                                    node.driver_info,
                                                    "******"))
            node.ports = [link.Link.make_link('self', url, 'nodes',
                                              node.uuid + "/ports"),
                          link.Link.make_link('bookmark', url, 'nodes',
                                              node.uuid + "/ports",
                                              bookmark=True)
                          ]

        # NOTE(lucasagomes): The numeric ID should not be exposed to
        #                    the user, it's internal only.
        node.chassis_id = wtypes.Unset

        node.links = [link.Link.make_link('self', url, 'nodes',
                                          node.uuid),
                      link.Link.make_link('bookmark', url, 'nodes',
                                          node.uuid, bookmark=True)
                      ]
        return node

    @classmethod
    def convert_with_links(cls, rpc_node, expand=True):
        node = Node(**rpc_node.as_dict())
        assert_juno_provision_state_name(node)
        hide_fields_in_newer_versions(node)
        return cls._convert_with_links(node, pecan.request.host_url,
                                       expand,
                                       pecan.request.context.show_password)

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
                     properties={'memory_mb': '1024', 'local_gb': '10',
                     'cpus': '1'}, updated_at=time, created_at=time,
                     provision_updated_at=time, instance_info={},
                     maintenance=False, maintenance_reason=None,
                     inspection_finished_at=None, inspection_started_at=time,
                     console_enabled=False, clean_step='')
        # NOTE(matty_dubs): The chassis_uuid getter() is based on the
        # _chassis_uuid variable:
        sample._chassis_uuid = 'edcad704-b2da-41d5-96d9-afd580ecfa12'
        return cls._convert_with_links(sample, 'http://localhost:6385', expand)


class NodeCollection(collection.Collection):
    """API representation of a collection of nodes."""

    nodes = [Node]
    """A list containing nodes objects"""

    def __init__(self, **kwargs):
        self._type = 'nodes'

    @staticmethod
    def convert_with_links(nodes, limit, url=None, expand=False, **kwargs):
        collection = NodeCollection()
        collection.nodes = [Node.convert_with_links(n, expand) for n in nodes]
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

    @expose.expose(wtypes.text, types.uuid_or_name)
    def methods(self, node_ident):
        """Retrieve information about vendor methods of the given node.

        :param node_ident: UUID or logical name of a node.
        :returns: dictionary with <vendor method name>:<method metadata>
                  entries.
        :raises: NodeNotFound if the node is not found.
        """
        # Raise an exception if node is not found
        rpc_node = api_utils.get_rpc_node(node_ident)

        if rpc_node.driver not in _VENDOR_METHODS:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            ret = pecan.request.rpcapi.get_node_vendor_passthru_methods(
                        pecan.request.context, rpc_node.uuid, topic=topic)
            _VENDOR_METHODS[rpc_node.driver] = ret

        return _VENDOR_METHODS[rpc_node.driver]

    @expose.expose(wtypes.text, types.uuid_or_name, wtypes.text,
                         body=wtypes.text)
    def _default(self, node_ident, method, data=None):
        """Call a vendor extension.

        :param node_ident: UUID or logical name of a node.
        :param method: name of the method in vendor driver.
        :param data: body of data to supply to the specified method.
        """
        # Raise an exception if node is not found
        rpc_node = api_utils.get_rpc_node(node_ident)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        # Raise an exception if method is not specified
        if not method:
            raise wsme.exc.ClientSideError(_("Method not specified"))

        if data is None:
            data = {}

        http_method = pecan.request.method.upper()
        ret, is_async = pecan.request.rpcapi.vendor_passthru(
                            pecan.request.context, rpc_node.uuid, method,
                            http_method, data, topic)
        status_code = 202 if is_async else 200
        return wsme.api.Response(ret, status_code=status_code)


class NodeMaintenanceController(rest.RestController):

    def _set_maintenance(self, node_ident, maintenance_mode, reason=None):
        rpc_node = api_utils.get_rpc_node(node_ident)
        rpc_node.maintenance = maintenance_mode
        rpc_node.maintenance_reason = reason

        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = 400
            raise e
        pecan.request.rpcapi.update_node(pecan.request.context,
                                         rpc_node, topic=topic)

    @expose.expose(None, types.uuid_or_name, wtypes.text,
                         status_code=202)
    def put(self, node_ident, reason=None):
        """Put the node in maintenance mode.

        :param node_ident: the UUID or logical_name of a node.
        :param reason: Optional, the reason why it's in maintenance.

        """
        self._set_maintenance(node_ident, True, reason=reason)

    @expose.expose(None, types.uuid_or_name, status_code=202)
    def delete(self, node_ident):
        """Remove the node from maintenance mode.

        :param node_ident: the UUID or logical name of a node.

        """
        self._set_maintenance(node_ident, False)


class NodesController(rest.RestController):
    """REST controller for Nodes."""

    states = NodeStatesController()
    """Expose the state controller action as a sub-element of nodes"""

    vendor_passthru = NodeVendorPassthruController()
    """A resource used for vendors to expose a custom functionality in
    the API"""

    ports = port.PortsController()
    """Expose ports as a sub-element of nodes"""

    management = NodeManagementController()
    """Expose management as a sub-element of nodes"""

    maintenance = NodeMaintenanceController()
    """Expose maintenance as a sub-element of nodes"""

    # Set the flag to indicate that the requests to this resource are
    # coming from a top-level resource
    ports.from_nodes = True

    from_chassis = False
    """A flag to indicate if the requests to this controller are coming
    from the top-level resource Chassis"""

    _custom_actions = {
        'detail': ['GET'],
        'validate': ['GET'],
    }

    def _get_nodes_collection(self, chassis_uuid, instance_uuid, associated,
                              maintenance, marker, limit, sort_key, sort_dir,
                              expand=False, resource_url=None):
        if self.from_chassis and not chassis_uuid:
            raise exception.MissingParameterValue(_(
                  "Chassis id not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(pecan.request.context,
                                                  marker)
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
                                                 expand=expand,
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

    @expose.expose(NodeCollection, types.uuid, types.uuid,
               types.boolean, types.boolean, types.uuid, int, wtypes.text,
               wtypes.text)
    def get_all(self, chassis_uuid=None, instance_uuid=None, associated=None,
                maintenance=None, marker=None, limit=None, sort_key='id',
                sort_dir='asc'):
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
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance, marker,
                                          limit, sort_key, sort_dir)

    @expose.expose(NodeCollection, types.uuid, types.uuid,
            types.boolean, types.boolean, types.uuid, int, wtypes.text,
            wtypes.text)
    def detail(self, chassis_uuid=None, instance_uuid=None, associated=None,
               maintenance=None, marker=None, limit=None, sort_key='id',
               sort_dir='asc'):
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
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        # /detail should only work against collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['nodes', 'detail'])
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance, marker,
                                          limit, sort_key, sort_dir, expand,
                                          resource_url)

    @expose.expose(wtypes.text, types.uuid_or_name, types.uuid)
    def validate(self, node=None, node_uuid=None):
        """Validate the driver interfaces, using the node's UUID or name.

        Note that the 'node_uuid' interface is deprecated in favour
        of the 'node' interface

        :param node: UUID or name of a node.
        :param node_uuid: UUID of a node.
        """
        if node:
            # We're invoking this interface using positional notation, or
            # explicitly using 'node'.  Try and determine which one.
            if (not api_utils.allow_node_logical_names() and
                not uuidutils.is_uuid_like(node)):
                raise exception.NotAcceptable()

        rpc_node = api_utils.get_rpc_node(node_uuid or node)

        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        return pecan.request.rpcapi.validate_driver_interfaces(
                pecan.request.context, rpc_node.uuid, topic)

    @expose.expose(Node, types.uuid_or_name)
    def get_one(self, node_ident):
        """Retrieve information about the given node.

        :param node_ident: UUID or logical name of a node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = api_utils.get_rpc_node(node_ident)
        return Node.convert_with_links(rpc_node)

    @expose.expose(Node, body=Node, status_code=201)
    def post(self, node):
        """Create a new node.

        :param node: a node within the request body.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        # NOTE(deva): get_topic_for checks if node.driver is in the hash ring
        #             and raises NoValidHost if it is not.
        #             We need to ensure that node has a UUID before it can
        #             be mapped onto the hash ring.
        if not node.uuid:
            node.uuid = uuidutils.generate_uuid()

        try:
            pecan.request.rpcapi.get_topic_for(node)
        except exception.NoValidHost as e:
            # NOTE(deva): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = 400
            raise e

        # Verify that if we're creating a new node with a 'name' set
        # that it is a valid name
        if node.name:
            if not api_utils.allow_node_logical_names():
                raise exception.NotAcceptable()
            if not api_utils.is_valid_node_name(node.name):
                msg = _("Cannot create node with invalid name %(name)s")
                raise wsme.exc.ClientSideError(msg % {'name': node.name},
                                               status_code=400)

        new_node = objects.Node(pecan.request.context,
                                **node.as_dict())
        new_node.create()
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('nodes', new_node.uuid)
        return Node.convert_with_links(new_node)

    @wsme.validate(types.uuid, [NodePatchType])
    @expose.expose(Node, types.uuid_or_name, body=[NodePatchType])
    def patch(self, node_ident, patch):
        """Update an existing node.

        :param node_ident: UUID or logical name of a node.
        :param patch: a json PATCH document to apply to this node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = api_utils.get_rpc_node(node_ident)

        # Check if node is transitioning state, although nodes in some states
        # can be updated.
        if (rpc_node.provision_state == ir_states.CLEANING and
                patch == [{'op': 'remove', 'path': '/instance_uuid'}]):
            # Allow node.instance_uuid removal during cleaning, but not other
            # operations.
            # TODO(JoshNang) remove node.instance_uuid when removing
            # instance_info and stop removing node.instance_uuid in the Nova
            # Ironic driver. Bug: 1436568
            LOG.debug('Removing instance uuid %(instance)s from node %(node)s',
                      {'instance': rpc_node.instance_uuid,
                       'node': rpc_node.uuid})
        elif ((rpc_node.target_power_state or rpc_node.target_provision_state)
                and rpc_node.provision_state not in
                ir_states.UPDATE_ALLOWED_STATES):
            msg = _("Node %s can not be updated while a state transition "
                    "is in progress.")
            raise wsme.exc.ClientSideError(msg % node_ident, status_code=409)

        # Verify that if we're patching 'name' that it is a valid
        name = api_utils.get_patch_value(patch, '/name')
        if name:
            if not api_utils.allow_node_logical_names():
                raise exception.NotAcceptable()
            if not api_utils.is_valid_node_name(name):
                msg = _("Node %(node)s: Cannot change name to invalid "
                        "name '%(name)s'")
                raise wsme.exc.ClientSideError(msg % {'node': node_ident,
                                                      'name': name},
                                               status_code=400)

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

        # Update only the fields that have changed
        for field in objects.Node.fields:
            try:
                patch_val = getattr(node, field)
            except AttributeError:
                # Ignore fields that aren't exposed in the API
                continue
            if patch_val == wtypes.Unset:
                patch_val = None
            if rpc_node[field] != patch_val:
                rpc_node[field] = patch_val

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
            e.code = 400
            raise e

        # NOTE(lucasagomes): If it's changing the driver and the console
        # is enabled we prevent updating it because the new driver will
        # not be able to stop a console started by the previous one.
        delta = rpc_node.obj_what_changed()
        if 'driver' in delta and rpc_node.console_enabled:
            raise wsme.exc.ClientSideError(
                _("Node %s can not update the driver while the console is "
                  "enabled. Please stop the console first.") % node_ident,
                status_code=409)

        new_node = pecan.request.rpcapi.update_node(
                         pecan.request.context, rpc_node, topic)

        return Node.convert_with_links(new_node)

    @expose.expose(None, types.uuid_or_name, status_code=204)
    def delete(self, node_ident):
        """Delete a node.

        :param node_ident: UUID or logical name of a node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = api_utils.get_rpc_node(node_ident)

        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = 400
            raise e

        pecan.request.rpcapi.destroy_node(pecan.request.context,
                                          rpc_node.uuid, topic)
