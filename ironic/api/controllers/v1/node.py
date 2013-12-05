# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import jsonpatch
from oslo.config import cfg
import pecan
from pecan import rest
import six
import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import link
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import excutils
from ironic.openstack.common import log

CONF = cfg.CONF
CONF.import_opt('heartbeat_timeout', 'ironic.conductor.manager',
                group='conductor')

LOG = log.getLogger(__name__)


class NodePatchType(types.JsonPatchType):

    @staticmethod
    def internal_attrs():
        defaults = types.JsonPatchType.internal_attrs()
        return defaults + ['/last_error', '/power_state', '/provision_state',
                           '/target_power_state', '/target_provision_state']

    @staticmethod
    def mandatory_attrs():
        return ['/chassis_uuid', '/driver']


class NodeStates(base.APIBase):
    """API representation of the states of a node."""

    power_state = wtypes.text

    provision_state = wtypes.text

    target_power_state = wtypes.text

    target_provision_state = wtypes.text

    last_error = wtypes.text

    @classmethod
    def convert(cls, rpc_node):
        attr_list = ['last_error', 'power_state', 'provision_state',
                     'target_power_state', 'target_provision_state']
        states = NodeStates()
        for attr in attr_list:
            setattr(states, attr, getattr(rpc_node, attr))
        return states


class NodeStatesController(rest.RestController):

    _custom_actions = {
        'power': ['PUT'],
    }

    @wsme_pecan.wsexpose(NodeStates, wtypes.text)
    def get(self, node_id):
        """List the states of the node.

        :param node_id: UUID of a node.
        """
        # NOTE(lucasagomes): All these state values come from the
        # DB. Ironic counts with a periodic task that verify the current
        # power states of the nodes and update the DB accordingly.
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_id)
        return NodeStates.convert(rpc_node)

    @wsme_pecan.wsexpose(NodeStates, wtypes.text, wtypes.text, status_code=202)
    def power(self, node_uuid, target):
        """Set the power state of the node.

        :param node_uuid: UUID of a node.
        :param target: The desired power state of the node.
        """
        # TODO(lucasagomes): Test if target is a valid state and if it's able
        # to transition to the target state from the current one
        rpc_node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        if rpc_node.target_power_state is not None:
            raise wsme.exc.ClientSideError(_("Power operation for node %s is "
                                             "already in progress.") %
                                              rpc_node['uuid'],
                                              status_code=409)
        # Note that there is a race condition. The node state(s) could change
        # by the time the RPC call is made and the TaskManager manager gets a
        # lock.
        pecan.request.rpcapi.change_node_power_state(pecan.request.context,
                                                     rpc_node, target)
        return NodeStates.convert(rpc_node)

    @wsme_pecan.wsexpose(NodeStates, wtypes.text, wtypes.text, status_code=202)
    def provision(self, node_uuid, target):
        """Set the provision state of the node.

        :param node_uuid: UUID of a node.
        :param target: The desired power state of the node.
        """
        # TODO(lucasagomes): Test if target is a valid state and if it's able
        # to transition to the target state from the current one
        raise NotImplementedError()


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
                chassis = objects.Chassis.get_by_uuid(pecan.request.context,
                                                      value)
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
    "Unique UUID for this node"

    instance_uuid = types.uuid
    "The UUID of the instance in nova-compute"

    power_state = wtypes.text
    "Represent the current (not transition) power state of the node"

    target_power_state = wtypes.text
    "The user modified desired power state of the node."

    last_error = wtypes.text
    "Any error from the most recent (last) asynchronous transaction that"
    "started but failed to finish."

    provision_state = wtypes.text
    "Represent the current (not transition) provision state of the node"

    target_provision_state = wtypes.text
    "The user modified desired provision state of the node."

    driver = wsme.wsattr(wtypes.text, mandatory=True)
    "The driver responsible for controlling the node"

    driver_info = {wtypes.text: api_utils.ValidTypes(wtypes.text,
                                                 six.integer_types)}
    "This node's driver configuration"

    extra = {wtypes.text: api_utils.ValidTypes(wtypes.text, six.integer_types)}
    "This node's meta data"

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {wtypes.text: api_utils.ValidTypes(wtypes.text,
                                                six.integer_types)}
    "The physical characteristics of this node"

    chassis_uuid = wsme.wsproperty(types.uuid, _get_chassis_uuid,
                                   _set_chassis_uuid, mandatory=True)
    "The UUID of the chassis this node belongs"

    links = [link.Link]
    "A list containing a self link and associated node links"

    ports = [link.Link]
    "Links to the collection of ports on this node"

    def __init__(self, **kwargs):
        self.fields = objects.Node.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

        # NOTE(lucasagomes): chassis_uuid is not part of objects.Node.fields
        #                    because it's an API-only attribute
        self.fields.append('chassis_uuid')
        setattr(self, 'chassis_uuid', kwargs.get('chassis_id', None))

    @classmethod
    def convert_with_links(cls, rpc_node, expand=True):
        node = Node(**rpc_node.as_dict())
        if not expand:
            except_list = ['instance_uuid', 'power_state',
                           'provision_state', 'uuid']
            node.unset_fields_except(except_list)
        else:
            node.ports = [link.Link.make_link('self', pecan.request.host_url,
                                              'nodes', node.uuid + "/ports"),
                          link.Link.make_link('bookmark',
                                              pecan.request.host_url,
                                              'nodes', node.uuid + "/ports",
                                              bookmark=True)
                         ]

        # NOTE(lucasagomes): The numeric ID should not be exposed to
        #                    the user, it's internal only.
        node.chassis_id = wtypes.Unset

        node.links = [link.Link.make_link('self', pecan.request.host_url,
                                          'nodes', node.uuid),
                      link.Link.make_link('bookmark',
                                          pecan.request.host_url,
                                          'nodes', node.uuid,
                                          bookmark=True)
                     ]
        return node


class NodeCollection(collection.Collection):
    """API representation of a collection of nodes."""

    nodes = [Node]
    "A list containing nodes objects"

    def __init__(self, **kwargs):
        self._type = 'nodes'

    @classmethod
    def convert_with_links(cls, nodes, limit, url=None,
                           expand=False, **kwargs):
        collection = NodeCollection()
        collection.nodes = [Node.convert_with_links(n, expand) for n in nodes]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection


class NodeVendorPassthruController(rest.RestController):
    """REST controller for VendorPassthru.

    This controller allow vendors to expose a custom functionality in
    the Ironic API. Ironic will merely relay the message from here to the
    appropriate driver, no introspection will be made in the message body.
    """

    @wsme_pecan.wsexpose(wtypes.text, wtypes.text, wtypes.text,
                         body=wtypes.text,
                         status_code=202)
    def post(self, node_id, method, data):
        """Call a vendor extension.

        :param node_id: UUID of the node.
        :param method: name of the method in vendor driver.
        :param data: body of data to supply to the specified method.
        """
        # Raise an exception if node is not found
        objects.Node.get_by_uuid(pecan.request.context, node_id)

        # Raise an exception if method is not specified
        if not method:
            raise wsme.exc.ClientSideError(_("Method not specified"))

        return pecan.request.rpcapi.vendor_passthru(
                pecan.request.context, node_id, method, data)


class NodesController(rest.RestController):
    """REST controller for Nodes."""

    states = NodeStatesController()
    "Expose the state controller action as a sub-element of nodes"

    vendor_passthru = NodeVendorPassthruController()
    "A resource used for vendors to expose a custom functionality in the API"

    ports = port.PortsController(from_nodes=True)
    "Expose ports as a sub-element of nodes"

    _custom_actions = {
        'detail': ['GET'],
        'validate': ['GET'],
    }

    def __init__(self, from_chassis=False):
        self._from_chassis = from_chassis

    def _get_nodes(self, chassis_uuid, instance_uuid, associated, marker,
                   limit, sort_key, sort_dir):
        if self._from_chassis and not chassis_uuid:
            raise exception.InvalidParameterValue(_(
                  "Chassis id not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(pecan.request.context,
                                                  marker)

        if chassis_uuid:
            nodes = pecan.request.dbapi.get_nodes_by_chassis(chassis_uuid,
                                                             limit, marker_obj,
                                                             sort_key=sort_key,
                                                             sort_dir=sort_dir)
        elif instance_uuid:
            nodes = self._get_nodes_by_instance(instance_uuid)
        elif associated:
            nodes = self._get_nodes_by_instance_association(associated,
                                                   limit, marker_obj,
                                                   sort_key, sort_dir)
        else:
            nodes = pecan.request.dbapi.get_node_list(limit, marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return nodes

    def _get_nodes_by_instance(self, instance_uuid):
        """Retrieve a node by its instance uuid.

        It returns a list with the node, or an empty list if no node is found.
        """
        try:
            node = pecan.request.dbapi.get_node_by_instance(instance_uuid)
            return [node]
        except exception.InstanceNotFound:
            return []

    def _get_nodes_by_instance_association(self, associated, limit, marker_obj,
                                           sort_key, sort_dir):
        """Retrieve nodes by instance association."""
        if associated.lower() == 'true':
            nodes = pecan.request.dbapi.get_associated_nodes(limit,
                        marker_obj, sort_key=sort_key, sort_dir=sort_dir)
        elif associated.lower() == 'false':
            nodes = pecan.request.dbapi.get_unassociated_nodes(limit,
                        marker_obj, sort_key=sort_key, sort_dir=sort_dir)
        else:
            raise wsme.exc.ClientSideError(_(
                    "Invalid parameter value: %s, 'associated' "
                    "can only be true or false.") % associated)
        return nodes

    @wsme_pecan.wsexpose(NodeCollection, wtypes.text, wtypes.text,
               wtypes.text, wtypes.text, int, wtypes.text, wtypes.text)
    def get_all(self, chassis_id=None, instance_uuid=None, associated=None,
                marker=None, limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of nodes.

        :param chassis_id: Optional UUID of a chassis, to get only nodes for
                           that chassis.
        :param instance_uuid: Optional UUID of an instance, to find the node
                              associated with that instance.
        :param associated: Optional boolean whether to return a list of
                           associated or unassociated nodes. May be combined
                           with other parameters.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        nodes = self._get_nodes(chassis_id, instance_uuid, associated, marker,
                                limit, sort_key, sort_dir)
        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}
        if associated:
            parameters['associated'] = associated.lower()
        return NodeCollection.convert_with_links(nodes, limit, **parameters)

    @wsme_pecan.wsexpose(NodeCollection, wtypes.text, wtypes.text,
            wtypes.text, wtypes.text, int, wtypes.text, wtypes.text)
    def detail(self, chassis_id=None, instance_uuid=None, associated=None,
               marker=None, limit=None, sort_key='id', sort_dir='asc'):
        """Retrieve a list of nodes with detail.

        :param chassis_id: Optional UUID of a chassis, to get only nodes for
                           that chassis.
        :param instance_uuid: Optional UUID of an instance, to find the node
                              associated with that instance.
        :param associated: Optional boolean whether to return a list of
                           associated or unassociated nodes. May be combined
                           with other parameters.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        # /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound

        nodes = self._get_nodes(chassis_id, instance_uuid, associated,
                                marker, limit, sort_key, sort_dir)
        resource_url = '/'.join(['nodes', 'detail'])

        parameters = {'sort_key': sort_key, 'sort_dir': sort_dir}
        if associated:
            parameters['associated'] = associated.lower()
        return NodeCollection.convert_with_links(nodes, limit,
                                                 url=resource_url,
                                                 expand=True,
                                                 **parameters)

    @wsme_pecan.wsexpose(wtypes.text, wtypes.text)
    def validate(self, node_uuid):
        """Validate the driver interfaces."""
        # check if node exists
        node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
        return pecan.request.rpcapi.validate_driver_interfaces(
                                        pecan.request.context, node.uuid)

    @wsme_pecan.wsexpose(Node, wtypes.text)
    def get_one(self, uuid):
        """Retrieve information about the given node.

        :param uuid: UUID of a node.
        """
        if self._from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, uuid)
        return Node.convert_with_links(rpc_node)

    @wsme_pecan.wsexpose(Node, body=Node)
    def post(self, node):
        """Create a new node.

        :param node: a node within the request body.
        """
        if self._from_chassis:
            raise exception.OperationNotPermitted

        try:
            new_node = pecan.request.dbapi.create_node(node.as_dict())
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(e)
        return Node.convert_with_links(new_node)

    @wsme.validate(wtypes.text, [NodePatchType])
    @wsme_pecan.wsexpose(Node, wtypes.text, body=[NodePatchType])
    def patch(self, uuid, patch):
        """Update an existing node.

        :param uuid: UUID of a node.
        :param patch: a json PATCH document to apply to this node.
        """
        if self._from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, uuid)

        # Check if node is transitioning state
        if rpc_node['target_power_state'] or \
             rpc_node['target_provision_state']:
            msg = _("Node %s can not be updated while a state transition"
                    "is in progress.")
            raise wsme.exc.ClientSideError(msg % uuid, status_code=409)

        try:
            node = Node(**jsonpatch.apply_patch(rpc_node.as_dict(),
                                                jsonpatch.JsonPatch(patch)))
        except jsonpatch.JsonPatchException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Patching Error: %s") % e)

        # Update only the fields that have changed
        for field in objects.Node.fields:
            if rpc_node[field] != getattr(node, field):
                rpc_node[field] = getattr(node, field)

        try:
            new_node = pecan.request.rpcapi.update_node(pecan.request.context,
                                                        rpc_node)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(e)

        return Node.convert_with_links(new_node)

    @wsme_pecan.wsexpose(None, wtypes.text, status_code=204)
    def delete(self, node_id):
        """Delete a node.

        :param node_id: UUID of the node.
        """
        if self._from_chassis:
            raise exception.OperationNotPermitted

        pecan.request.dbapi.destroy_node(node_id)
