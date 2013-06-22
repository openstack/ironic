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

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers.v1 import base
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class Node(base.APIBase):
    """API representation of a bare metal node.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a node.
    """

    # NOTE: translate 'id' publicly to 'uuid' internally
    uuid = wtypes.text
    instance_uuid = wtypes.text

    # NOTE: task_* fields probably need to be reworked to match API spec
    task_state = wtypes.text
    task_start = wtypes.text

    # NOTE: allow arbitrary dicts for driver_info and extra so that drivers
    #       and vendors can expand on them without requiring API changes.
    # NOTE: translate 'driver_info' internally to 'management_configuration'
    driver = wtypes.text
    driver_info = {wtypes.text: wtypes.text}

    # NOTE: translate 'extra' internally to 'meta_data' externally
    extra = {wtypes.text: wtypes.text}

    # NOTE: properties should use a class to enforce required properties
    #       current list: arch, cpus, disk, ram, image
    properties = {wtypes.text: wtypes.text}

    # NOTE: translate 'chassis_id' to a link to the chassis resource
    #       and accept a chassis uuid when creating a node.
    chassis_id = int

    # NOTE: also list / link to ports associated with this node

    def __init__(self, **kwargs):
        self.fields = objects.Node.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))


class NodesController(rest.RestController):
    """REST controller for Nodes."""

    @wsme_pecan.wsexpose([unicode])
    def get(self):
        """Retrieve a list of nodes."""
        return pecan.request.dbapi.get_node_list()

    @wsme_pecan.wsexpose(Node, unicode)
    def get_one(self, uuid):
        """Retrieve information about the given node."""
        node = objects.Node.get_by_uuid(pecan.request.context, uuid)
        return node

    @wsme.validate(Node)
    @wsme_pecan.wsexpose(Node, body=Node)
    def post(self, node):
        """Ceate a new node."""
        try:
            new_node = pecan.request.dbapi.create_node(node.as_dict())
        except Exception as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return new_node

    @wsme.validate(Node)
    @wsme_pecan.wsexpose(Node, unicode, body=Node, status=200)
    def patch(self, node_id, node_data):
        """Update an existing node.

        TODO(deva): add exception handling
        """
        # NOTE: WSME is creating an api v1 Node object with all fields
        #       so we eliminate non-supplied fields by converting
        #       to a dict and stripping keys with value=None
        delta = node_data.as_terse_dict()

        # NOTE: state transitions are separate from informational changes
        #       so don't pass a task_state to update_node.
        new_state = delta.pop('task_state', None)

        response = wsme.api.Response(Node(), status_code=200)
        try:
            node = objects.Node.get_by_uuid(
                        pecan.request.context, node_id)
            for k in delta.keys():
                node[k] = delta[k]
            node = pecan.request.rpcapi.update_node(
                    pecan.request.context, node)
            response.obj = node
        except exception.InvalidParameterValue:
            response.status_code = 400
        except exception.NodeInWrongPowerState:
            response.status_code = 409
        except exception.IronicException as e:
            LOG.exception(e)
            response.status_code = 500

        if new_state:
            # NOTE: state change is async, so change the REST response
            response.status_code = 202
            pecan.request.rpcapi.start_state_change(pecan.request.context,
                                                    node, new_state)

        # TODO(deva): return the response object instead of raising
        #             after wsme 0.5b3 is released
        if response.status_code not in [200, 202]:
            raise wsme.exc.ClientSideError(_(
                    "Error updating node %s") % node_id)
        return response.obj

    @wsme_pecan.wsexpose()
    def delete(self, node_id):
        """Delete a node.

        TODO(deva): don't allow deletion of an associated node.
        """
        pecan.request.dbapi.destroy_node(node_id)
