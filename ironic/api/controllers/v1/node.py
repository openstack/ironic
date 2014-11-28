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

from oslo.config import cfg
import pecan
from pecan import rest
import six
import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states as ir_states
from ironic.common import utils
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


class NodePatchType(types.JsonPatchType):

    @staticmethod
    def internal_attrs():
        defaults = types.JsonPatchType.internal_attrs()
        # TODO(lucasagomes): Include maintenance once the endpoint
        # v1/nodes/<uuid>/maintenance do more things than updating the DB.
        return defaults + ['/console_enabled', '/last_error',
                           '/power_state', '/provision_state', '/reservation',
                           '/target_power_state', '/target_provision_state',
                           '/provision_updated_at', '/maintenance_reason']

    @staticmethod
    def mandatory_attrs():
        return ['/chassis_uuid', '/driver']


class BootDeviceController(rest.RestController):

    _custom_actions = {
        'supported': ['GET'],
    }

    def _get_boot_device(self, node_uuid, supported=False):
        """Get the current boot device or a list of supported devices.

        :param node_uuid: UUID of a node.
        :param supported: Boolean value. If true return a list of
                          supported boot devices, if false return the
                          current boot device. Default: False.
        :returns: The current boot device or a list of the supported
                  boot devices.

        """
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        if supported:
            return pecan.request.rpcapi.get_supported_boot_devices(
                                       pecan.request.context, node_uuid, topic)
        else:
            return pecan.request.rpcapi.get_boot_device(pecan.request.context,
                                                        node_uuid, topic)

    @wsme_pecan.wsexpose(None, types.uuid, wtypes.text, types.boolean,
                         status_code=204)
    def put(self, node_uuid, boot_device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param node_uuid: UUID of a node.
        :param boot_device: the boot device, one of
                            :mod:`ironic.common.boot_devices`.
        :param persistent: Boolean value. True if the boot device will
                           persist to all future boots, False if not.
                           Default: False.

        """
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.set_boot_device(pecan.request.context, node_uuid,
                                             boot_device,
                                             persistent=persistent,
                                             topic=topic)

    @wsme_pecan.wsexpose(wtypes.text, types.uuid)
    def get(self, node_uuid):
        """Get the current boot device for a node.

        :param node_uuid: UUID of a node.
        :returns: a json object containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        return self._get_boot_device(node_uuid)

    @wsme_pecan.wsexpose(wtypes.text, types.uuid)
    def supported(self, node_uuid):
        """Get a list of the supported boot devices.

        :param node_uuid: UUID of a node.
        :returns: A json object with the list of supported boot
                  devices.

        """
        boot_devices = self._get_boot_device(node_uuid, supported=True)
        return {'supported_boot_devices': boot_devices}


class NodeManagementController(rest.RestController):

    boot_device = BootDeviceController()
    """Expose boot_device as a sub-element of management"""


class ConsoleInfo(base.APIBase):
    """API representation of the console information for a node."""

    console_enabled = types.boolean
    """The console state: if the console is enabled or not."""

    console_info = {wtypes.text: types.MultiType(wtypes.text,
                                                 six.integer_types)}
    """The console information. It typically includes the url to access the
    console and the type of the application that hosts the console."""

    @classmethod
    def sample(cls):
        console = {'type': 'shellinabox', 'url': 'http://<hostname>:4201'}
        return cls(console_enabled=True, console_info=console)


class NodeConsoleController(rest.RestController):

    @wsme_pecan.wsexpose(ConsoleInfo, types.uuid)
    def get(self, node_uuid):
        """Get connection information about the console.

        :param node_uuid: UUID of a node.
        """
        rpc_node = objects.Node.get_by_uuid(pecan.request.context,
                                            node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        try:
            console = pecan.request.rpcapi.get_console_information(
                pecan.request.context, node_uuid, topic)
            console_state = True
        except exception.NodeConsoleNotEnabled:
            console = None
            console_state = False

        return ConsoleInfo(console_enabled=console_state, console_info=console)

    @wsme_pecan.wsexpose(None, types.uuid, types.boolean, status_code=202)
    def put(self, node_uuid, enabled):
        """Start and stop the node console.

        :param node_uuid: UUID of a node.
        :param enabled: Boolean value; whether to enable or disable the
                console.
        """
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        pecan.request.rpcapi.set_console_mode(pecan.request.context, node_uuid,
                                              enabled, topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_uuid, 'states', 'console'])
        pecan.response.location = link.build_url('nodes', url_args)


class NodeStates(base.APIBase):
    """API representation of the states of a node."""

    console_enabled = types.boolean

    power_state = wtypes.text

    provision_state = wtypes.text

    provision_updated_at = datetime.datetime

    target_power_state = wtypes.text

    target_provision_state = wtypes.text

    last_error = wtypes.text

    @staticmethod
    def convert(rpc_node):
        attr_list = ['console_enabled', 'last_error', 'power_state',
                     'provision_state', 'target_power_state',
                     'target_provision_state', 'provision_updated_at']
        states = NodeStates()
        for attr in attr_list:
            setattr(states, attr, getattr(rpc_node, attr))
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

    @wsme_pecan.wsexpose(NodeStates, types.uuid)
    def get(self, node_uuid):
        """List the states of the node.

        :param node_uuid: UUID of a node.
        """
        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        return NodeStates.convert(rpc_node)

    @wsme_pecan.wsexpose(None, types.uuid, wtypes.text, status_code=202)
    def power(self, node_uuid, target):
        """Set the power state of the node.

        :param node_uuid: UUID of a node.
        :param target: The desired power state of the node.
        :raises: ClientSideError (HTTP 409) if a power operation is
                 already in progress.
        :raises: InvalidStateRequested (HTTP 400) if the requested target
                 state is not valid.

        """
        # TODO(lucasagomes): Test if it's able to transition to the
        #                    target state from the current one
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        if target not in [ir_states.POWER_ON,
                          ir_states.POWER_OFF,
                          ir_states.REBOOT]:
            raise exception.InvalidStateRequested(state=target, node=node_uuid)

        pecan.request.rpcapi.change_node_power_state(pecan.request.context,
                                                     node_uuid, target, topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_uuid, 'states'])
        pecan.response.location = link.build_url('nodes', url_args)

    @wsme_pecan.wsexpose(None, types.uuid, wtypes.text, status_code=202)
    def provision(self, node_uuid, target):
        """Asynchronous trigger the provisioning of the node.

        This will set the target provision state of the node, and a
        background task will begin which actually applies the state
        change. This call will return a 202 (Accepted) indicating the
        request was accepted and is in progress; the client should
        continue to GET the status of this node to observe the status
        of the requested action.

        :param node_uuid: UUID of a node.
        :param target: The desired provision state of the node.
        :raises: ClientSideError (HTTP 409) if the node is already being
                 provisioned.
        :raises: ClientSideError (HTTP 400) if the node is already in
                 the requested state.
        :raises: InvalidStateRequested (HTTP 400) if the requested target
                 state is not valid.
        """
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        if target == rpc_node.provision_state:
            msg = (_("Node %(node)s is already in the '%(state)s' state.") %
                   {'node': rpc_node['uuid'], 'state': target})
            raise wsme.exc.ClientSideError(msg, status_code=400)

        if target in (ir_states.ACTIVE, ir_states.REBUILD):
            processing = rpc_node.target_provision_state is not None
        elif target == ir_states.DELETED:
            processing = (rpc_node.target_provision_state is not None and
                        rpc_node.provision_state != ir_states.DEPLOYWAIT)
        else:
            raise exception.InvalidStateRequested(state=target, node=node_uuid)

        if processing:
            msg = (_('Node %s is already being provisioned or decommissioned.')
                   % rpc_node.uuid)
            raise wsme.exc.ClientSideError(msg, status_code=409)  # Conflict

        # Note that there is a race condition. The node state(s) could change
        # by the time the RPC call is made and the TaskManager manager gets a
        # lock.

        if target in (ir_states.ACTIVE, ir_states.REBUILD):
            rebuild = (target == ir_states.REBUILD)
            pecan.request.rpcapi.do_node_deploy(
                    pecan.request.context, node_uuid, rebuild, topic)
        elif target == ir_states.DELETED:
            pecan.request.rpcapi.do_node_tear_down(
                    pecan.request.context, node_uuid, topic)
        # Set the HTTP Location Header
        url_args = '/'.join([node_uuid, 'states'])
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

    maintenance = types.boolean
    """Indicates whether the node is in maintenance mode."""

    maintenance_reason = wsme.wsattr(wtypes.text, readonly=True)
    """Indicates reason for putting a node in maintenance mode."""

    target_provision_state = wsme.wsattr(wtypes.text, readonly=True)
    """The user modified desired provision state of the node."""

    console_enabled = types.boolean
    """Indicates whether the console access is enabled or disabled on
    the node."""

    instance_info = {wtypes.text: types.MultiType(wtypes.text,
                                                  six.integer_types)}
    """This node's instance info."""

    driver = wsme.wsattr(wtypes.text, mandatory=True)
    """The driver responsible for controlling the node"""

    driver_info = {wtypes.text: types.MultiType(wtypes.text,
                                                six.integer_types)}
    """This node's driver configuration"""

    extra = {wtypes.text: types.MultiType(wtypes.text, six.integer_types)}
    """This node's meta data"""

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {wtypes.text: types.MultiType(wtypes.text,
                                               six.integer_types)}
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
    def _convert_with_links(node, url, expand=True):
        if not expand:
            except_list = ['instance_uuid', 'maintenance', 'power_state',
                           'provision_state', 'uuid']
            node.unset_fields_except(except_list)
        else:
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
        return cls._convert_with_links(node, pecan.request.host_url,
                                       expand)

    @classmethod
    def sample(cls, expand=True):
        time = datetime.datetime(2000, 1, 1, 12, 0, 0)
        node_uuid = '1be26c0b-03f2-4d2e-ae87-c02d7f33c123'
        instance_uuid = 'dcf1fbc5-93fc-4596-9395-b80572f6267b'
        sample = cls(uuid=node_uuid, instance_uuid=instance_uuid,
                     power_state=ir_states.POWER_ON,
                     target_power_state=ir_states.NOSTATE,
                     last_error=None, provision_state=ir_states.ACTIVE,
                     target_provision_state=ir_states.NOSTATE,
                     reservation=None, driver='fake', driver_info={}, extra={},
                     properties={'memory_mb': '1024', 'local_gb': '10',
                     'cpus': '1'}, updated_at=time, created_at=time,
                     provision_updated_at=time, instance_info={},
                     maintenance=False, maintenance_reason=None,
                     console_enabled=False)
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

    @wsme_pecan.wsexpose(wtypes.text, types.uuid)
    def methods(self, node_uuid):
        """Retrieve information about vendor methods of the given node.

        :param node_uuid: UUID of a node.
        :returns: dictionary with <vendor method name>:<method metadata>
                  entries.
        :raises: NodeNotFound if the node is not found.
        """
        # Raise an exception if node is not found
        rpc_node = objects.Node.get_by_uuid(pecan.request.context,
                                            node_uuid)

        if rpc_node.driver not in _VENDOR_METHODS:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
            ret = pecan.request.rpcapi.get_node_vendor_passthru_methods(
                        pecan.request.context, node_uuid, topic=topic)
            _VENDOR_METHODS[rpc_node.driver] = ret

        return _VENDOR_METHODS[rpc_node.driver]

    @wsme_pecan.wsexpose(wtypes.text, types.uuid, wtypes.text,
                         body=wtypes.text)
    def _default(self, node_uuid, method, data=None):
        """Call a vendor extension.

        :param node_uuid: UUID of a node.
        :param method: name of the method in vendor driver.
        :param data: body of data to supply to the specified method.
        """
        # Raise an exception if node is not found
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        # Raise an exception if method is not specified
        if not method:
            raise wsme.exc.ClientSideError(_("Method not specified"))

        if data is None:
            data = {}

        http_method = pecan.request.method.upper()
        ret, is_async = pecan.request.rpcapi.vendor_passthru(
                            pecan.request.context, node_uuid, method,
                            http_method, data, topic)
        status_code = 202 if is_async else 200
        return wsme.api.Response(ret, status_code=status_code)


class NodeMaintenanceController(rest.RestController):

    def _set_maintenance(self, node_uuid, maintenance_mode, reason=None):
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        rpc_node.maintenance = maintenance_mode
        rpc_node.maintenance_reason = reason

        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = 400
            raise e
        pecan.request.rpcapi.update_node(pecan.request.context,
                                         rpc_node, topic=topic)

    @wsme_pecan.wsexpose(None, types.uuid, wtypes.text, status_code=202)
    def put(self, node_uuid, reason=None):
        """Put the node in maintenance mode.

        :param node_uuid: UUID of a node.
        :param reason: Optional, the reason why it's in maintenance.

        """
        self._set_maintenance(node_uuid, True, reason=reason)

    @wsme_pecan.wsexpose(None, types.uuid, status_code=202)
    def delete(self, node_uuid):
        """Remove the node from maintenance mode.

        :param node_uuid: UUID of a node.

        """
        self._set_maintenance(node_uuid, False)


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

    @wsme_pecan.wsexpose(NodeCollection, types.uuid, types.uuid,
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

    @wsme_pecan.wsexpose(NodeCollection, types.uuid, types.uuid,
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
        # /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['nodes', 'detail'])
        return self._get_nodes_collection(chassis_uuid, instance_uuid,
                                          associated, maintenance, marker,
                                          limit, sort_key, sort_dir, expand,
                                          resource_url)

    @wsme_pecan.wsexpose(wtypes.text, types.uuid)
    def validate(self, node_uuid):
        """Validate the driver interfaces.

        :param node_uuid: UUID of a node.
        """
        # check if node exists
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        return pecan.request.rpcapi.validate_driver_interfaces(
                pecan.request.context, rpc_node.uuid, topic)

    @wsme_pecan.wsexpose(Node, types.uuid)
    def get_one(self, node_uuid):
        """Retrieve information about the given node.

        :param node_uuid: UUID of a node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        return Node.convert_with_links(rpc_node)

    @wsme_pecan.wsexpose(Node, body=Node, status_code=201)
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
            node.uuid = utils.generate_uuid()

        try:
            pecan.request.rpcapi.get_topic_for(node)
        except exception.NoValidHost as e:
            # NOTE(deva): convert from 404 to 400 because client can see
            #             list of available drivers and shouldn't request
            #             one that doesn't exist.
            e.code = 400
            raise e

        new_node = objects.Node(pecan.request.context,
                                **node.as_dict())
        new_node.create()
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('nodes', new_node.uuid)
        return Node.convert_with_links(new_node)

    @wsme.validate(types.uuid, [NodePatchType])
    @wsme_pecan.wsexpose(Node, types.uuid, body=[NodePatchType])
    def patch(self, node_uuid, patch):
        """Update an existing node.

        :param node_uuid: UUID of a node.
        :param patch: a json PATCH document to apply to this node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)

        # Check if node is transitioning state
        if (rpc_node['target_power_state'] or
                rpc_node['target_provision_state']):
            msg = _("Node %s can not be updated while a state transition "
                    "is in progress.")
            raise wsme.exc.ClientSideError(msg % node_uuid, status_code=409)

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

        new_node = pecan.request.rpcapi.update_node(
                         pecan.request.context, rpc_node, topic)

        return Node.convert_with_links(new_node)

    @wsme_pecan.wsexpose(None, types.uuid, status_code=204)
    def delete(self, node_uuid):
        """Delete a node.

        :param node_uuid: UUID of a node.
        """
        if self.from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        try:
            topic = pecan.request.rpcapi.get_topic_for(rpc_node)
        except exception.NoValidHost as e:
            e.code = 400
            raise e

        pecan.request.rpcapi.destroy_node(pecan.request.context,
                                          node_uuid, topic)
