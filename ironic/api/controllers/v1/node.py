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
import six

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import link
from ironic.api.controllers.v1 import port
from ironic.api.controllers.v1 import state
from ironic.api.controllers.v1 import utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import excutils
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class NodePowerState(state.State):
    @classmethod
    def convert_with_links(cls, rpc_node, expand=True):
        power_state = NodePowerState()
        # FIXME(lucasagomes): this request could potentially take a
        # while. It's dependent upon the driver talking to the hardware. At
        # least with IPMI, this often times out, and even fails after 3
        # retries at a statistically significant frequency....
        power_state.current = pecan.request.rpcapi.get_node_power_state(
                                                         pecan.request.context,
                                                         rpc_node.uuid)
        url_arg = '%s/state/power' % rpc_node.uuid
        power_state.links = [link.Link.make_link('self',
                                                 pecan.request.host_url,
                                                 'nodes', url_arg),
                             link.Link.make_link('bookmark',
                                                 pecan.request.host_url,
                                                 'nodes', url_arg,
                                                 bookmark=True)
                            ]
        if expand:
            power_state.target = rpc_node.target_power_state
            # TODO(lucasagomes): get_next_power_available_states
            power_state.available = []
        return power_state


class NodePowerStateController(rest.RestController):

    # GET nodes/<uuid>/state/power
    @wsme_pecan.wsexpose(NodePowerState, unicode)
    def get(self, node_id):
        node = objects.Node.get_by_uuid(pecan.request.context, node_id)
        return NodePowerState.convert_with_links(node)

    # PUT nodes/<uuid>/state/power
    @wsme_pecan.wsexpose(NodePowerState, unicode, unicode, status_code=202)
    def put(self, node_id, target):
        """Set the power state of the machine."""
        node = objects.Node.get_by_uuid(pecan.request.context, node_id)
        if node.target_power_state is not None:
            raise wsme.exc.ClientSideError(_("One power operation is "
                                             "already in process"))
        #TODO(lucasagomes): Test if target is a valid state and if it's able
        # to transition to the target state from the current one

        node['target_power_state'] = target
        updated_node = pecan.request.rpcapi.update_node(pecan.request.context,
                                                        node)
        pecan.request.rpcapi.change_node_power_state(pecan.request.context,
                                                      updated_node, target)
        return NodePowerState.convert_with_links(updated_node, expand=False)


class NodeProvisionState(state.State):
    @classmethod
    def convert_with_links(cls, rpc_node, expand=True):
        provision_state = NodeProvisionState()
        provision_state.current = rpc_node.provision_state
        url_arg = '%s/state/provision' % rpc_node.uuid
        provision_state.links = [link.Link.make_link('self',
                                                     pecan.request.host_url,
                                                     'nodes', url_arg),
                                 link.Link.make_link('bookmark',
                                                     pecan.request.host_url,
                                                     'nodes', url_arg,
                                                     bookmark=True)
                                ]
        if expand:
            provision_state.target = rpc_node.target_provision_state
            # TODO(lucasagomes): get_next_provision_available_states
            provision_state.available = []
        return provision_state


class NodeProvisionStateController(rest.RestController):

    # GET nodes/<uuid>/state/provision
    @wsme_pecan.wsexpose(NodeProvisionState, unicode)
    def get(self, node_id):
        node = objects.Node.get_by_uuid(pecan.request.context, node_id)
        provision_state = NodeProvisionState.convert_with_links(node)
        return provision_state

    # PUT nodes/<uuid>/state/provision
    @wsme_pecan.wsexpose(NodeProvisionState, unicode, unicode, status_code=202)
    def put(self, node_id, target):
        """Set the provision state of the machine."""
        #TODO(lucasagomes): Test if target is a valid state and if it's able
        # to transition to the target state from the current one
        # TODO(lucasagomes): rpcapi.start_provision_state_change()
        raise NotImplementedError()


class NodeStates(base.APIBase):
    """API representation of the states of a node."""

    power = NodePowerState
    "The current power state of the node"

    provision = NodeProvisionState
    "The current provision state of the node"

    @classmethod
    def convert_with_links(cls, rpc_node):
        states = NodeStates()
        states.power = NodePowerState.convert_with_links(rpc_node,
                                                         expand=False)
        states.provision = NodeProvisionState.convert_with_links(rpc_node,
                                                                 expand=False)
        return states


class NodeStatesController(rest.RestController):

    power = NodePowerStateController()
    "Expose the power controller action as a sub-element of state"

    provision = NodeProvisionStateController()
    "Expose the provision controller action as a sub-element of state"

    # GET nodes/<uuid>/state
    @wsme_pecan.wsexpose(NodeStates, unicode)
    def get(self, node_id):
        """List or update the state of a node."""
        node = objects.Node.get_by_uuid(pecan.request.context, node_id)
        state = NodeStates.convert_with_links(node)
        return state


class Node(base.APIBase):
    """API representation of a bare metal node.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a node.
    """

    # NOTE: translate 'id' publicly to 'uuid' internally
    uuid = wtypes.text
    instance_uuid = wtypes.text

    power_state = wtypes.text
    "Represent the current (not transition) power state of the node"

    target_power_state = wtypes.text
    "The user modified desired power state of the node."

    provision_state = wtypes.text
    "Represent the current (not transition) provision state of the node"

    target_provision_state = wtypes.text
    "The user modified desired provision state of the node."

    # NOTE: allow arbitrary dicts for driver_info and extra so that drivers
    #       and vendors can expand on them without requiring API changes.
    # NOTE: translate 'driver_info' internally to 'management_configuration'
    driver = wtypes.text

    driver_info = {wtypes.text: utils.ValidTypes(wtypes.text,
                                                 six.integer_types)}

    extra = {wtypes.text: utils.ValidTypes(wtypes.text, six.integer_types)}

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {wtypes.text: utils.ValidTypes(wtypes.text,
                                                six.integer_types)}

    # NOTE: translate 'chassis_id' to a link to the chassis resource
    #       and accept a chassis uuid when creating a node.
    chassis_id = utils.ValidTypes(wtypes.text, six.integer_types)

    links = [link.Link]
    "A list containing a self link and associated node links"

    ports = [link.Link]
    "Links to the collection of ports on this node"

    def __init__(self, **kwargs):
        self.fields = objects.Node.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

    @classmethod
    def convert_with_links(cls, rpc_node, expand=True):
        minimum_fields = ['uuid', 'power_state', 'target_power_state',
                          'provision_state', 'target_provision_state',
                          'instance_uuid']
        fields = minimum_fields if not expand else None
        node = Node.from_rpc_object(rpc_node, fields)

        # translate id -> uuid
        if node.chassis_id and isinstance(node.chassis_id, six.integer_types):
            chassis_obj = objects.Chassis.get_by_uuid(pecan.request.context,
                                                      node.chassis_id)
            node.chassis_id = chassis_obj.uuid

        node.links = [link.Link.make_link('self', pecan.request.host_url,
                                          'nodes', node.uuid),
                      link.Link.make_link('bookmark',
                                          pecan.request.host_url,
                                          'nodes', node.uuid,
                                          bookmark=True)
                     ]
        if expand:
            node.ports = [link.Link.make_link('self', pecan.request.host_url,
                                              'nodes', node.uuid + "/ports"),
                          link.Link.make_link('bookmark',
                                              pecan.request.host_url,
                                              'nodes', node.uuid + "/ports",
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

    @wsme_pecan.wsexpose(None, unicode, unicode, body=unicode, status_code=202)
    def _default(self, node_id, method, data):
        # Only allow POST requests
        if pecan.request.method.upper() != "POST":
            raise exception.NotFound

        # Raise an exception if node is not found
        objects.Node.get_by_uuid(pecan.request.context, node_id)

        # Raise an exception if method is not specified
        if not method:
            raise wsme.exc.ClientSideError(_("Method not specified"))

        raise NotImplementedError()


class NodesController(rest.RestController):
    """REST controller for Nodes."""

    state = NodeStatesController()
    "Expose the state controller action as a sub-element of nodes"

    vendor_passthru = NodeVendorPassthruController()
    "A resource used for vendors to expose a custom functionality in the API"

    ports = port.PortsController(from_nodes=True)
    "Expose ports as a sub-element of nodes"

    _custom_actions = {
        'detail': ['GET'],
    }

    def __init__(self, from_chassis=False):
        self._from_chassis = from_chassis

    def _get_nodes(self, chassis_id, marker, limit, sort_key, sort_dir):
        if self._from_chassis and not chassis_id:
            raise exception.InvalidParameterValue(_(
                  "Chassis id not specified."))

        limit = utils.validate_limit(limit)
        sort_dir = utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Node.get_by_uuid(pecan.request.context,
                                                  marker)

        if chassis_id:
            nodes = pecan.request.dbapi.get_nodes_by_chassis(chassis_id, limit,
                                                             marker_obj,
                                                             sort_key=sort_key,
                                                             sort_dir=sort_dir)
        else:
            nodes = pecan.request.dbapi.get_node_list(limit, marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return nodes

    def _convert_chassis_uuid_to_id(self, node_dict):
        # NOTE(lucasagomes): translate uuid -> id, used internally to
        #                    tune performance
        if node_dict['chassis_id']:
            chassis_obj = objects.Chassis.get_by_uuid(pecan.request.context,
                                                      node_dict['chassis_id'])
            node_dict['chassis_id'] = chassis_obj.id

    @wsme_pecan.wsexpose(NodeCollection, unicode, unicode, int,
                         unicode, unicode)
    def get_all(self, chassis_id=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of nodes."""
        nodes = self._get_nodes(chassis_id, marker, limit, sort_key, sort_dir)
        return NodeCollection.convert_with_links(nodes, limit,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(NodeCollection, unicode, unicode, int,
                         unicode, unicode)
    def detail(self, chassis_id=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of nodes with detail."""
        # /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "nodes":
            raise exception.HTTPNotFound

        nodes = self._get_nodes(chassis_id, marker, limit, sort_key, sort_dir)
        resource_url = '/'.join(['nodes', 'detail'])
        return NodeCollection.convert_with_links(nodes, limit,
                                                 url=resource_url,
                                                 expand=True,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(Node, unicode)
    def get_one(self, uuid):
        """Retrieve information about the given node."""
        if self._from_chassis:
            raise exception.OperationNotPermitted

        rpc_node = objects.Node.get_by_uuid(pecan.request.context, uuid)
        return Node.convert_with_links(rpc_node)

    @wsme_pecan.wsexpose(Node, body=Node)
    def post(self, node):
        """Create a new node."""
        if self._from_chassis:
            raise exception.OperationNotPermitted

        node_dict = node.as_dict()
        self._convert_chassis_uuid_to_id(node_dict)

        try:
            new_node = pecan.request.dbapi.create_node(node_dict)
        except Exception as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return Node.convert_with_links(new_node)

    @wsme_pecan.wsexpose(Node, unicode, body=[unicode])
    def patch(self, uuid, patch):
        """Update an existing node.

        TODO(yuriyz): improve exceptions handling
        """
        if self._from_chassis:
            raise exception.OperationNotPermitted

        node = objects.Node.get_by_uuid(pecan.request.context, uuid)
        node_dict = node.as_dict()

        utils.validate_patch(patch)
        patch_obj = jsonpatch.JsonPatch(patch)

        # Prevent states from being updated
        state_rel_path = ['/power_state', '/target_power_state',
                          '/provision_state', '/target_provision_state']
        if any(p['path'] in state_rel_path for p in patch_obj):
            raise wsme.exc.ClientSideError(_("Changing states is not allowed "
                                             "here; You must use the "
                                             "nodes/%s/state interface.")
                                             % uuid)

        # Prevent node from being updated when there's a state
        # change in progress
        if any(node.get(tgt) for tgt in ["target_power_state",
                                         "target_provision_state"]):
            raise wsme.exc.ClientSideError(_("Can not update node %s because "
                                             "a state change is already in "
                                             "progress.") % uuid)

        try:
            patched_node = jsonpatch.apply_patch(node_dict, patch_obj)
        except jsonpatch.JsonPatchException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Patching Error: %s") % e)

        try:
            self. _convert_chassis_uuid_to_id(patched_node)
            defaults = objects.Node.get_defaults()
            for key in defaults:
                # Internal values that shouldn't be part of the patch
                if key in ['id', 'updated_at', 'created_at']:
                    continue

                # In case of a remove operation, add the missing fields back
                # to the document with their default value
                if key in node_dict and key not in patched_node:
                    patched_node[key] = defaults[key]

                # Update only the fields that have changed
                if node[key] != patched_node[key]:
                    node[key] = patched_node[key]

            node = pecan.request.rpcapi.update_node(pecan.request.context,
                                                    node)

        except exception.IronicException as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(e)

        return Node.convert_with_links(node)

    @wsme_pecan.wsexpose(None, unicode, status_code=204)
    def delete(self, node_id):
        """Delete a node."""
        if self._from_chassis:
            raise exception.OperationNotPermitted

        pecan.request.dbapi.destroy_node(node_id)
