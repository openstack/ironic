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

"""
Version 1 of the Ironic API

NOTE: IN PROGRESS AND NOT FULLY IMPLEMENTED.

Should maintain feature parity with Nova Baremetal Extension.

Specification can be found at ironic/doc/api/v1.rst
"""

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.objects import node as node_obj
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class APIBase(wtypes.Base):

    def as_dict(self):
        return dict((k, getattr(self, k))
                    for k in self.fields
                    if hasattr(self, k) and
                    getattr(self, k) != wsme.Unset)


class Node(APIBase):
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
        self.fields = node_obj.Node.fields.keys()
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
        node = node_obj.Node.get_by_uuid(pecan.request.context, uuid)
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
    @wsme_pecan.wsexpose(Node, unicode, body=Node)
    def put(self, uuid, delta_node):
        """Update an existing node."""
        node = node_obj.Node.get_by_uuid(pecan.request.context, uuid)
        # NOTE: delta_node will be a full API Node instance, but only user-
        #       supplied fields will be set, so we extract those by converting
        #       the object to a dict, then scanning for non-None values, and
        #       only applying those changes to the Node object instance.
        items = delta_node.as_dict().items()
        for k, v in [(k, v) for (k, v) in items if v]:
            node[k] = v

        # TODO(deva): catch exceptions here if node_obj refuses to save.
        node.save()

        return node

    @wsme_pecan.wsexpose()
    def delete(self, node_id):
        """Delete a node."""
        pecan.request.dbapi.destroy_node(node_id)


class Controller(object):
    """Version 1 API controller root."""

    nodes = NodesController()
