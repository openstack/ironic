# vim: tabstop=4 shiftwidth=4 softtabstop=4
# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""SQLAlchemy storage backend."""

import sys
import uuid

from oslo.config import cfg

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm.exc import MultipleResultsFound

from ironic.common import exception
from ironic.db import api
from ironic.db.sqlalchemy.models import Node, Iface
from ironic.openstack.common.db.sqlalchemy import session as db_session
from ironic.openstack.common import log
from ironic.openstack.common import uuidutils

CONF = cfg.CONF
CONF.import_opt('sql_connection',
                'ironic.openstack.common.db.sqlalchemy.session')

LOG = log.getLogger(__name__)

get_engine = db_session.get_engine
get_session = db_session.get_session

def get_backend():
     """The backend is this module itself."""
     return Connection()


#    - nodes
#      - { id: AUTO_INC INTEGER
#          uuid: node uuid
#          power_info: JSON of power mgmt information
#          task_state: current task
#          image_path: URL of associated image
#          instance_uuid: uuid of associated instance
#          instance_name: name of associated instance
#          hw_spec_id: hw specification id             (->hw_specs.id)
#          inst_spec_id: instance specification id     (->inst_specs.id)
#          extra: JSON blob of extra data
#        }
#    - ifaces
#      - { id: AUTO_INC INTEGER
#          mac: MAC address of this iface
#          node_id: associated node        (->nodes.id)
#         ?datapath_id
#         ?port_no
#         ?model
#          extra: JSON blob of extra data
#        }
#    - hw_specs
#      - { id: AUTO_INC INTEGER
#          cpu_arch:
#          n_cpu:
#          n_disk:
#          ram_mb:
#          storage_gb:
#        }
#    - inst_specs
#      - { id: AUTO_INC INTEGER
#          root_mb:
#          swap_mb:
#          image_path:
#        }


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.
    
    :param session: if present, the session to use
    """

    session = kwargs.get('session') or get_session()
    query = session.query(model, *args)
    return query


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    def get_nodes(self, columns):
        """Return a list of dicts of all nodes.

        :param columns: List of columns to return.
        """
        pass

    def get_associated_nodes(self):
        """Return a list of ids of all associated nodes."""
        pass

    def get_unassociated_nodes(self):
        """Return a list of ids of all unassociated nodes."""
        pass

    def reserve_node(self, *args, **kwargs):
        """Find a free node and associate it.

        TBD
        """
        pass

    def create_node(self, *args, **kwargs):
        """Create a new node."""
        node = Node()

    def get_node_by_id(self, node_id):
        """Return a node.

        :param node_id: The id or uuid of a node.
        """
        query = model_query(Node)
        if uuidutils.is_uuid_like(node_id):
            query.filter_by(uuid=node_id)
        else:
            query.filter_by(id=node_id)

        try:
            result = query.one()
        except NoResultFound:
            raise 
        except MultipleResultsFound:
            raise
        return result
                

    def get_node_by_instance_id(self, instance_id):
        """Return a node.

        :param instance_id: The instance id or uuid of a node.
        """
        pass

    def destroy_node(self, node_id):
        """Destroy a node.

        :param node_id: The id or uuid of a node.
        """
        pass

    def update_node(self, node_id, *args, **kwargs):
        """Update properties of a node.

        :param node_id: The id or uuid of a node.
        TBD
        """
        pass

    def get_iface(self, iface_id):
        """Return an interface.

        :param iface_id: The id or MAC of an interface.
        """
        pass

    def create_iface(self, *args, **kwargs):
        """Create a new iface."""
        pass

    def update_iface(self, iface_id, *args, **kwargs):
        """Update properties of an iface.

        :param iface_id: The id or MAC of an interface.
        TBD
        """
        pass

    def destroy_iface(self, iface_id):
        """Destroy an iface.

        :param iface_id: The id or MAC of an interface.
        """
        pass
