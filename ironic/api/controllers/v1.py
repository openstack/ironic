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

Should maintain feature parity with Nova Baremetal Extension.
Specification in ironic/doc/api/v1.rst
"""


import pecan
from pecan import rest

import wsme
import wsmeext.pecan as wsme_pecan
from wsme import types as wtypes

from ironic import db


class Base(wtypes.Base):
    # TODO: all the db bindings

    @classmethod
    def from_db_model(cls, m):
        return cls(**(m.as_dict()))

    @classmethod
    def from_db_and_links(cls, m, links):
        return cls(links=links, **(m.as_dict()))

    def as_dict(self, db_model):
        valid_keys = inspect.getargspec(db_model.__init__)[0]
        if 'self' in valid_keys:
            valid_keys.remove('self')

        return dict((k, getattr(self, k))
                    for k in valid_keys
                    if hasattr(self, k) and
                    getattr(self, k) != wsme.Unset)


class Interface(Base):
    """A representation of a network interface for a baremetal node"""

    node_id = int
    address = wtypes.text

    def __init__(self, **kwargs):
        self.fields = list(kwargs)
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

    @classmethod
    def sample(cls):
        return cls(node_id=1,
                   address='52:54:00:cf:2d:31',
                   )


class InterfacesController(rest.RestController):
    """REST controller for Interfaces"""

    @wsme_pecan.wsexpose(Interface, unicode) 
    def post(self, iface):
        """Ceate a new interface."""
        return Interface.sample()

    @wsme_pecan.wsexpose()
    def get_all(self):
        """Retrieve a list of all interfaces."""
        ifaces = [Interface.sample()]
        return [(i.node_id, i.address) for i in ifaces]

    @wsme_pecan.wsexpose(Interface, unicode)
    def get_one(self, address):
        """Retrieve information about the given interface."""
        one = Interface.sample()
        one.address = address
        return one

    @wsme_pecan.wsexpose()
    def delete(self, iface_id):
        """Delete an interface"""
        pass

    @wsme_pecan.wsexpose()
    def put(self, iface_id):
        """Update an interface"""
        pass


class Node(Base):
    """A representation of a bare metal node"""

    uuid = wtypes.text
    cpu_arch = wtypes.text
    cpu_num = int
    memory = int
    local_storage_max = int
    task_state = wtypes.text
    image_path = wtypes.text
    instance_uuid = wtypes.text
    instance_name = wtypes.text
    power_info = wtypes.text
    extra = wtypes.text

    def __init__(self, **kwargs):
        self.fields = list(kwargs)
        for k, v in kwargs.iteritems():
            setattr(self, k, v)

    @classmethod
    def sample(cls):
        power_info = "{'driver': 'ipmi', 'user': 'fake', " \
                   + "'password': 'password', 'address': '1.2.3.4'}"
        return cls(uuid='1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                   cpu_arch='x86_64',
                   cpu_num=4,
                   memory=16384,
                   local_storage_max=1000,
                   task_state='NOSTATE',
                   image_path='/fake/image/path',
                   instance_uuid='8227348d-5f1d-4488-aad1-7c92b2d42504',
                   power_info=power_info,
                   extra='{}',
                   )

 
class NodesController(rest.RestController):
    """REST controller for Nodes"""

    @wsme_pecan.wsexpose(Node, body=Node)
    def post(self, data):
        """Ceate a new node."""
        try:
            node = pecan.request.dbapi.create_node(
                        data.as_dict(db.models.Node))
        except Exception as e:
            LOG.exception(e)
            raise wsme.exc.ClientSideError(_("Invalid data"))
        return node
        

    @wsme_pecan.wsexpose()
    def get_all(self):
        """Retrieve a list of all nodes."""
        nodes = [Node.sample()]
        return [n.uuid for n in nodes]

    @wsme_pecan.wsexpose(Node, unicode)
    def get_one(self, node_id):
        """Retrieve information about the given node."""
        r = pecan.request.dbapi.get_node_by_id(node_id)
        return Node.from_db_model(r)

    @wsme_pecan.wsexpose()
    def delete(self, node_id):
        """Delete a node"""
        pass

    @wsme_pecan.wsexpose()
    def put(self, node_id):
        """Update a node"""
        pass


class Controller(object):
    """Version 1 API controller root."""

    # TODO: _default and index

    nodes = NodesController()
    interfaces = InterfacesController()
