# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 UnitedStack Inc.
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
from ironic.api.controllers.v1 import utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class Port(base.APIBase):
    """API representation of a port.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a port.
    """

    # NOTE: translate 'id' publicly to 'uuid' internally
    uuid = wtypes.text

    address = wtypes.text

    extra = {wtypes.text: utils.ValidTypes(wtypes.text, six.integer_types)}

    node_id = int

    links = [link.Link]
    "A list containing a self link and associated port links"

    def __init__(self, **kwargs):
        self.fields = objects.Port.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

    @classmethod
    def convert_with_links(cls, rpc_port, expand=True):
        fields = ['uuid', 'address'] if not expand else None
        port = Port.from_rpc_object(rpc_port, fields)
        port.links = [link.Link.make_link('self', pecan.request.host_url,
                                          'ports', port.uuid),
                      link.Link.make_link('bookmark',
                                          pecan.request.host_url,
                                          'ports', port.uuid,
                                          bookmark=True)
                     ]
        return port


class PortCollection(collection.Collection):
    """API representation of a collection of ports."""

    ports = [Port]
    "A list containing ports objects"

    def __init__(self, **kwargs):
        self._type = 'ports'

    @classmethod
    def convert_with_links(cls, ports, limit, url=None,
                           expand=False, **kwargs):
        collection = PortCollection()
        collection.ports = [Port.convert_with_links(p, expand) for p in ports]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection


class PortsController(rest.RestController):
    """REST controller for Ports."""

    _custom_actions = {
        'detail': ['GET'],
    }

    def __init__(self, from_nodes=False):
        self._from_nodes = from_nodes

    def _get_ports(self, node_id, marker, limit, sort_key, sort_dir):
        if self._from_nodes and not node_id:
            raise exception.InvalidParameterValue(_(
                  "Node id not specified."))

        limit = utils.validate_limit(limit)
        sort_dir = utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Port.get_by_uuid(pecan.request.context,
                                                  marker)

        if node_id:
            ports = pecan.request.dbapi.get_ports_by_node(node_id, limit,
                                                          marker_obj,
                                                          sort_key=sort_key,
                                                          sort_dir=sort_dir)
        else:
            ports = pecan.request.dbapi.get_port_list(limit, marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return ports

    @wsme_pecan.wsexpose(PortCollection, unicode, unicode, int,
                         unicode, unicode)
    def get_all(self, node_id=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports."""
        ports = self._get_ports(node_id, marker, limit, sort_key, sort_dir)
        return PortCollection.convert_with_links(ports, limit,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(PortCollection, unicode, unicode, int,
                         unicode, unicode)
    def detail(self, node_id=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports."""
        # NOTE(lucasagomes): /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "ports":
            raise exception.HTTPNotFound

        ports = self._get_ports(node_id, marker, limit, sort_key, sort_dir)
        resource_url = '/'.join(['ports', 'detail'])
        return PortCollection.convert_with_links(ports, limit,
                                                 url=resource_url,
                                                 expand=True,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(Port, unicode)
    def get_one(self, uuid):
        """Retrieve information about the given port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        rpc_port = objects.Port.get_by_uuid(pecan.request.context, uuid)
        return Port.convert_with_links(rpc_port)

    @wsme_pecan.wsexpose(Port, body=Port)
    def post(self, port):
        """Create a new port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        try:
            new_port = pecan.request.dbapi.create_port(port.as_dict())
        except exception.IronicException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return Port.convert_with_links(new_port)

    @wsme_pecan.wsexpose(Port, unicode, body=[unicode])
    def patch(self, uuid, patch):
        """Update an existing port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        port = objects.Port.get_by_uuid(pecan.request.context, uuid)
        port_dict = port.as_dict()

        utils.validate_patch(patch)
        try:
            patched_port = jsonpatch.apply_patch(port_dict,
                                                 jsonpatch.JsonPatch(patch))
        except jsonpatch.JsonPatchException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Patching Error: %s") % e)

        defaults = objects.Port.get_defaults()
        for key in defaults:
            # Internal values that shouldn't be part of the patch
            if key in ['id', 'updated_at', 'created_at']:
                continue

            # In case of a remove operation, add the missing fields back
            # to the document with their default value
            if key in port_dict and key not in patched_port:
                patched_port[key] = defaults[key]

            # Update only the fields that have changed
            if port[key] != patched_port[key]:
                port[key] = patched_port[key]

        port.save()
        return Port.convert_with_links(port)

    @wsme_pecan.wsexpose(None, unicode, status_code=204)
    def delete(self, port_id):
        """Delete a port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        pecan.request.dbapi.destroy_port(port_id)
