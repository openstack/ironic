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
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic import objects
from ironic.openstack.common import excutils
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class Port(base.APIBase):
    """API representation of a port.

    This class enforces type checking and value constraints, and converts
    between the internal object model and the API representation of a port.
    """

    _node_uuid = None

    def _get_node_uuid(self):
        return self._node_uuid

    def _set_node_uuid(self, value):
        if value and self._node_uuid != value:
            try:
                node = objects.Node.get_by_uuid(pecan.request.context, value)
                self._node_uuid = node.uuid
                # NOTE(lucasagomes): Create the node_id attribute on-the-fly
                #                    to satisfy the api -> rpc object
                #                    conversion.
                self.node_id = node.id
            except exception.NodeNotFound as e:
                # Change error code because 404 (NotFound) is inappropriate
                # response for a POST request to create a Port
                e.code = 400  # BadRequest
                raise e
        elif value == wtypes.Unset:
            self._node_uuid = wtypes.Unset

    uuid = types.uuid
    "Unique UUID for this port"

    address = wsme.wsattr(types.macaddress, mandatory=True)
    "MAC Address for this port"

    extra = {wtypes.text: api_utils.ValidTypes(wtypes.text, six.integer_types)}
    "This port's meta data"

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid, _set_node_uuid,
                                mandatory=True)
    "The UUID of the node this port belongs to"

    links = [link.Link]
    "A list containing a self link and associated port links"

    def __init__(self, **kwargs):
        self.fields = objects.Port.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

        # NOTE(lucasagomes): node_uuid is not part of objects.Port.fields
        #                    because it's an API-only attribute
        self.fields.append('node_uuid')
        setattr(self, 'node_uuid', kwargs.get('node_id', None))

    @classmethod
    def convert_with_links(cls, rpc_port, expand=True):
        port = Port(**rpc_port.as_dict())
        if not expand:
            port.unset_fields_except(['uuid', 'address'])

        # never expose the node_id attribute
        port.node_id = wtypes.Unset

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
    def convert_with_links(cls, rpc_ports, limit, url=None,
                           expand=False, **kwargs):
        collection = PortCollection()
        collection.ports = [Port.convert_with_links(p, expand)
                            for p in rpc_ports]
        collection.next = collection.get_next(limit, url=url, **kwargs)
        return collection


class PortsController(rest.RestController):
    """REST controller for Ports."""

    _custom_actions = {
        'detail': ['GET'],
    }

    def __init__(self, from_nodes=False):
        self._from_nodes = from_nodes

    def _get_ports(self, node_uuid, marker, limit, sort_key, sort_dir):
        if self._from_nodes and not node_uuid:
            raise exception.InvalidParameterValue(_(
                  "Node id not specified."))

        limit = api_utils.validate_limit(limit)
        sort_dir = api_utils.validate_sort_dir(sort_dir)

        marker_obj = None
        if marker:
            marker_obj = objects.Port.get_by_uuid(pecan.request.context,
                                                  marker)

        if node_uuid:
            ports = pecan.request.dbapi.get_ports_by_node(node_uuid, limit,
                                                          marker_obj,
                                                          sort_key=sort_key,
                                                          sort_dir=sort_dir)
        else:
            ports = pecan.request.dbapi.get_port_list(limit, marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)
        return ports

    def _check_address(self, port_dict):
        try:
            if pecan.request.dbapi.get_port(port_dict['address']):
            # TODO(whaom) - create a custom SQLAlchemy type like
            # db.sqlalchemy.types.IPAddress in Nova for mac
            # with 'macaddr' postgres type for postgres dialect
                raise wsme.exc.ClientSideError(_("MAC address already "
                                                 "exists."))
        except exception.PortNotFound:
            pass

    @wsme_pecan.wsexpose(PortCollection, wtypes.text, wtypes.text, int,
                         wtypes.text, wtypes.text)
    def get_all(self, node_uuid=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports."""
        ports = self._get_ports(node_uuid, marker, limit, sort_key, sort_dir)
        return PortCollection.convert_with_links(ports, limit,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(PortCollection, wtypes.text, wtypes.text, int,
                         wtypes.text, wtypes.text)
    def detail(self, node_uuid=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports."""
        # NOTE(lucasagomes): /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "ports":
            raise exception.HTTPNotFound

        ports = self._get_ports(node_uuid, marker, limit, sort_key, sort_dir)
        resource_url = '/'.join(['ports', 'detail'])
        return PortCollection.convert_with_links(ports, limit,
                                                 url=resource_url,
                                                 expand=True,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    @wsme_pecan.wsexpose(Port, wtypes.text)
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
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(e)
        return Port.convert_with_links(new_port)

    @wsme_pecan.wsexpose(Port, wtypes.text, body=[wtypes.text])
    def patch(self, uuid, patch):
        """Update an existing port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        port = objects.Port.get_by_uuid(pecan.request.context, uuid)
        port_dict = port.as_dict()

        api_utils.validate_patch(patch)

        try:
            patched_port = jsonpatch.apply_patch(port_dict,
                                                 jsonpatch.JsonPatch(patch))
        except jsonpatch.JsonPatchException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Patching Error: %s") % e)

        # Required fields
        missing_attr = [attr for attr in ['address', 'node_id']
                        if attr not in patched_port]
        if missing_attr:
            msg = _("Attribute(s): %s can not be removed")
            raise wsme.exc.ClientSideError(msg % ', '.join(missing_attr))

        # FIXME(lucasagomes): This block should not exist, address should
        #                     be unique and validated at the db level.
        if port_dict['address'] != patched_port['address']:
            self._check_address(patched_port)

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

    @wsme_pecan.wsexpose(None, wtypes.text, status_code=204)
    def delete(self, port_id):
        """Delete a port."""
        if self._from_nodes:
            raise exception.OperationNotPermitted

        pecan.request.dbapi.destroy_port(port_id)
