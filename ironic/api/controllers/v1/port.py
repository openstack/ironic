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

import datetime

import pecan
from pecan import rest
import six
import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic.api.controllers import base
from ironic.api.controllers import link
from ironic.api.controllers.v1 import collection
from ironic.api.controllers.v1 import types
from ironic.api.controllers.v1 import utils as api_utils
from ironic.common import exception
from ironic import objects


class PortPatchType(types.JsonPatchType):

    @staticmethod
    def mandatory_attrs():
        return ['/address', '/node_uuid']


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
                # FIXME(comstud): One should only allow UUID here, but
                # there seems to be a bug in that tests are passing an
                # ID. See bug #1301046 for more details.
                node = objects.Node.get(pecan.request.context, value)
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

    extra = {wtypes.text: types.MultiType(wtypes.text, six.integer_types)}
    "This port's meta data"

    node_uuid = wsme.wsproperty(types.uuid, _get_node_uuid, _set_node_uuid,
                                mandatory=True)
    "The UUID of the node this port belongs to"

    links = wsme.wsattr([link.Link], readonly=True)
    "A list containing a self link and associated port links"

    def __init__(self, **kwargs):
        self.fields = objects.Port.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

        # NOTE(lucasagomes): node_uuid is not part of objects.Port.fields
        #                    because it's an API-only attribute
        self.fields.append('node_uuid')
        setattr(self, 'node_uuid', kwargs.get('node_id'))

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

    @classmethod
    def sample(cls):
        sample = cls(uuid='27e3153e-d5bf-4b7e-b517-fb518e17f34c',
                     address='fe:54:00:77:07:d9',
                     extra={'foo': 'bar'},
                     created_at=datetime.datetime.utcnow(),
                     updated_at=datetime.datetime.utcnow())
        # NOTE(lucasagomes): node_uuid getter() method look at the
        # _node_uuid variable
        sample._node_uuid = '7ae81bb3-dec3-4289-8d6c-da80bd8001ae'
        return sample


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

    @classmethod
    def sample(cls):
        sample = cls()
        sample.ports = [Port.sample()]
        return sample


class PortsController(rest.RestController):
    """REST controller for Ports."""

    _custom_actions = {
        'detail': ['GET'],
    }

    def __init__(self, from_nodes=False):
        self._from_nodes = from_nodes

    def _get_ports_collection(self, node_uuid, address, marker, limit,
                              sort_key, sort_dir, expand=False,
                              resource_url=None):
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
            # FIXME(comstud): Since all we need is the node ID, we can
            #                 make this more efficient by only querying
            #                 for that column. This will get cleaned up
            #                 as we move to the object interface.
            node = objects.Node.get_by_uuid(pecan.request.context, node_uuid)
            ports = pecan.request.dbapi.get_ports_by_node_id(node.id, limit,
                                                             marker_obj,
                                                             sort_key=sort_key,
                                                             sort_dir=sort_dir)
        elif address:
            ports = self._get_ports_by_address(address)
        else:
            ports = pecan.request.dbapi.get_port_list(limit, marker_obj,
                                                      sort_key=sort_key,
                                                      sort_dir=sort_dir)

        return PortCollection.convert_with_links(ports, limit,
                                                 url=resource_url,
                                                 expand=expand,
                                                 sort_key=sort_key,
                                                 sort_dir=sort_dir)

    def _get_ports_by_address(self, address):
        """Retrieve a port by its address.

        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :returns: a list with the port, or an empty list if no port is found.

        """
        try:
            port = pecan.request.dbapi.get_port(address)
            return [port]
        except exception.PortNotFound:
            return []

    @wsme_pecan.wsexpose(PortCollection, types.uuid, types.macaddress,
                         types.uuid, int, wtypes.text, wtypes.text)
    def get_all(self, node_uuid=None, address=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports.

        :param node_uuid: UUID of a node, to get only ports for that node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        return self._get_ports_collection(node_uuid, address, marker, limit,
                                          sort_key, sort_dir)

    @wsme_pecan.wsexpose(PortCollection, types.uuid, types.macaddress,
                         types.uuid, int, wtypes.text, wtypes.text)
    def detail(self, node_uuid=None, address=None, marker=None, limit=None,
                sort_key='id', sort_dir='asc'):
        """Retrieve a list of ports with detail.

        :param node_uuid: UUID of a node, to get only ports for that node.
        :param address: MAC address of a port, to get the port which has
                        this MAC address.
        :param marker: pagination marker for large data sets.
        :param limit: maximum number of resources to return in a single result.
        :param sort_key: column to sort results by. Default: id.
        :param sort_dir: direction to sort. "asc" or "desc". Default: asc.
        """
        # NOTE(lucasagomes): /detail should only work agaist collections
        parent = pecan.request.path.split('/')[:-1][-1]
        if parent != "ports":
            raise exception.HTTPNotFound

        expand = True
        resource_url = '/'.join(['ports', 'detail'])
        return self._get_ports_collection(node_uuid, address, marker, limit,
                                          sort_key, sort_dir, expand,
                                          resource_url)

    @wsme_pecan.wsexpose(Port, types.uuid)
    def get_one(self, port_uuid):
        """Retrieve information about the given port.

        :param port_uuid: UUID of a port.
        """
        if self._from_nodes:
            raise exception.OperationNotPermitted

        rpc_port = objects.Port.get_by_uuid(pecan.request.context, port_uuid)
        return Port.convert_with_links(rpc_port)

    @wsme_pecan.wsexpose(Port, body=Port, status_code=201)
    def post(self, port):
        """Create a new port.

        :param port: a port within the request body.
        """
        if self._from_nodes:
            raise exception.OperationNotPermitted

        new_port = pecan.request.dbapi.create_port(port.as_dict())
        # Set the HTTP Location Header
        pecan.response.location = link.build_url('ports', new_port.uuid)
        return Port.convert_with_links(new_port)

    @wsme.validate(types.uuid, [PortPatchType])
    @wsme_pecan.wsexpose(Port, types.uuid, body=[PortPatchType])
    def patch(self, port_uuid, patch):
        """Update an existing port.

        :param port_uuid: UUID of a port.
        :param patch: a json PATCH document to apply to this port.
        """
        if self._from_nodes:
            raise exception.OperationNotPermitted

        rpc_port = objects.Port.get_by_uuid(pecan.request.context, port_uuid)
        try:
            port = Port(**api_utils.apply_jsonpatch(rpc_port.as_dict(), patch))
        except api_utils.JSONPATCH_EXCEPTIONS as e:
            raise exception.PatchError(patch=patch, reason=e)

        # Update only the fields that have changed
        for field in objects.Port.fields:
            if rpc_port[field] != getattr(port, field):
                rpc_port[field] = getattr(port, field)

        rpc_node = objects.Node.get_by_id(pecan.request.context,
                                          rpc_port.node_id)
        topic = pecan.request.rpcapi.get_topic_for(rpc_node)

        new_port = pecan.request.rpcapi.update_port(
                                        pecan.request.context, rpc_port, topic)

        return Port.convert_with_links(new_port)

    @wsme_pecan.wsexpose(None, types.uuid, status_code=204)
    def delete(self, port_uuid):
        """Delete a port.

        :param port_uuid: UUID of a port.
        """
        if self._from_nodes:
            raise exception.OperationNotPermitted

        pecan.request.dbapi.destroy_port(port_uuid)
