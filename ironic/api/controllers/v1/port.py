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

import pecan
from pecan import rest

import wsme
from wsme import types as wtypes
import wsmeext.pecan as wsme_pecan

from ironic import objects

from ironic.api.controllers.v1 import base
from ironic.api.controllers.v1 import link
from ironic.common import exception
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

    extra = {wtypes.text: wtypes.text}

    node_id = int

    links = [link.Link]
    "A list containing a self link and associated port links"

    def __init__(self, **kwargs):
        self.fields = objects.Port.fields.keys()
        for k in self.fields:
            setattr(self, k, kwargs.get(k))

    @classmethod
    def convert_with_links(cls, rpc_port):
        port = Port.from_rpc_object(rpc_port)
        port.links = [link.Link.make_link('self', pecan.request.host_url,
                                          'ports', port.uuid),
                      link.Link.make_link('bookmark',
                                          pecan.request.host_url,
                                          'ports', port.uuid,
                                          bookmark=True)
                     ]
        return port


class PortsController(rest.RestController):
    """REST controller for Ports."""

    @wsme_pecan.wsexpose([Port])
    def get_all(self):
        """Retrieve a list of ports."""
        p_list = []
        for uuid in pecan.request.dbapi.get_port_list():
            rpc_port = objects.Port.get_by_uuid(pecan.request.context,
                                                uuid)
            p_list.append(Port.convert_with_links(rpc_port))
        return p_list

    @wsme_pecan.wsexpose(Port, unicode)
    def get_one(self, uuid):
        """Retrieve information about the given port."""
        rpc_port = objects.Port.get_by_uuid(pecan.request.context, uuid)
        return Port.convert_with_links(rpc_port)

    @wsme.validate(Port)
    @wsme_pecan.wsexpose(Port, body=Port)
    def post(self, port):
        """Ceate a new port."""
        try:
            new_port = pecan.request.dbapi.create_port(port.as_dict())
        except exception.IronicException as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return Port.convert_with_links(new_port)

    @wsme.validate(Port)
    @wsme_pecan.wsexpose(Port, unicode, body=Port)
    def patch(self, uuid, port_data):
        """Update an existing port."""
        # TODO(wentian): add rpc handle,
        #                  eg. if update fails because node is already locked
        port = objects.Port.get_by_uuid(pecan.request.context, uuid)
        nn_delta_p = port_data.as_terse_dict()
        for k in nn_delta_p:
            port[k] = nn_delta_p[k]
        port.save()
        return Port.convert_with_links(port)

    @wsme_pecan.wsexpose(None, unicode, status_code=204)
    def delete(self, port_id):
        """Delete a port."""
        pecan.request.dbapi.destroy_port(port_id)
