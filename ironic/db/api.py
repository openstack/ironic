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
"""
Base classes for storage engines
"""

import abc

import six

from ironic.openstack.common.db import api as db_api

_BACKEND_MAPPING = {'sqlalchemy': 'ironic.db.sqlalchemy.api'}
IMPL = db_api.DBAPI(backend_mapping=_BACKEND_MAPPING)


def get_instance():
    """Return a DB API instance."""
    return IMPL


@six.add_metaclass(abc.ABCMeta)
class Connection(object):
    """Base class for storage system connections."""

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @abc.abstractmethod
    def get_nodeinfo_list(self, columns=None, filters=None, limit=None,
                          marker=None, sort_key=None, sort_dir=None):
        """Return a list of the specified columns for all nodes that match
        the specified filters.

        :param columns: List of column names to return.
                        Defaults to 'id' column when columns == None.
        :param filters: Filters to apply. Defaults to None.
                        'associated': True | False
                        'reserved': True | False
        :param limit: Maximum number of nodes to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of tuples of the specified columns.
        """

    @abc.abstractmethod
    def get_node_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        """Return a list of nodes.

        :param limit: Maximum number of nodes to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        """

    @abc.abstractmethod
    def get_associated_nodes(self):
        """Return a list of ids of all associated nodes."""

    @abc.abstractmethod
    def get_unassociated_nodes(self):
        """Return a list of ids of all unassociated nodes."""

    @abc.abstractmethod
    def reserve_nodes(self, tag, nodes):
        """Reserve a set of nodes atomically.

        To prevent other ManagerServices from manipulating the given
        Nodes while a Task is performed, mark them all reserved by this host.

        :param tag: A string uniquely identifying the reservation holder.
        :param nodes: A list of node id or uuid.
        :returns: A list of the reserved node refs.
        :raises: NodeNotFound if any node is not found.
        :raises: NodeAlreadyReserved if any node is already reserved.
        """

    @abc.abstractmethod
    def release_nodes(self, tag, nodes):
        """Release the reservation on a set of nodes atomically.

        :param tag: A string uniquely identifying the reservation holder.
        :param nodes: A list of node id or uuid.
        :raises: NodeNotFound if any node is not found.
        :raises: NodeAlreadyReserved if any node could not be released
                 because it was not reserved by this host.
        """

    @abc.abstractmethod
    def create_node(self, values):
        """Create a new node.

        :param values: A dict containing several items used to identify
                       and track the node, and several dicts which are passed
                       into the Drivers when managing this node. For example:

                        {
                         'uuid': utils.generate_uuid(),
                         'instance_uuid': None,
                         'power_state': states.NOSTATE,
                         'provision_state': states.NOSTATE,
                         'driver': 'pxe_ipmitool',
                         'driver_info': { ... },
                         'properties': { ... },
                         'extra': { ... },
                        }
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node(self, node_id):
        """Return a node.

        :param node_id: The id or uuid of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_instance(self, instance):
        """Return a node.

        :param instance: The instance name or uuid to search for.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_nodes_by_chassis(self, chassis_id, limit=None, marker=None,
                             sort_key=None, sort_dir=None):
        """List all the nodes for a given chassis.

        :param chassis_id: The id or uuid of a chassis.
        :param limit: Maximum number of nodes to return.
        :param marker: the last item of the previous page; we returns the next
                       results after this value.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: direction in which results should be sorted
                         (asc, desc)
        :returns: A list of nodes.
        """

    @abc.abstractmethod
    def destroy_node(self, node_id):
        """Destroy a node and all associated interfaces.

        :param node_id: The id or uuid of a node.
        """

    @abc.abstractmethod
    def update_node(self, node_id, values):
        """Update properties of a node.

        :param node_id: The id or uuid of a node.
        :param values: Dict of values to update.
                       May be a partial list, eg. when setting the
                       properties for a driver. For example:

                       {
                        'driver_info':
                            {
                             'my-field-1': val1,
                             'my-field-2': val2,
                            }
                       }
        :returns: A node.
        """

    @abc.abstractmethod
    def get_port(self, port_id):
        """Return a network port representation.

        :param port_id: The id or MAC of a port.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_port_by_vif(self, vif):
        """Return the port corresponding to this VIF.

        :param vif: The uuid of the VIF.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_port_list(self, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        """Return a list of ports.

        :param limit: Maximum number of ports to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        """

    @abc.abstractmethod
    def get_ports_by_node(self, node_id, limit=None, marker=None,
                          sort_key=None, sort_dir=None):
        """List all the ports for a given node.

        :param node_id: The id or uuid of a node.
        :param limit: Maximum number of ports to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: direction in which results should be sorted
                         (asc, desc)
        :returns: A list of ports.
        """

    @abc.abstractmethod
    def create_port(self, values):
        """Create a new port.

        :param values: Dict of values.
        """

    @abc.abstractmethod
    def update_port(self, port_id, values):
        """Update properties of an port.

        :param port_id: The id or MAC of a port.
        :param values: Dict of values to update.
        :returns: A port.
        """

    @abc.abstractmethod
    def destroy_port(self, port_id):
        """Destroy an port.

        :param port_id: The id or MAC of a port.
        """

    @abc.abstractmethod
    def create_chassis(self, values):
        """Create a new chassis.

        :param values: Dict of values.
        """

    @abc.abstractmethod
    def get_chassis(self, chassis_id):
        """Return a chassis representation.

        :param chassis_id: The id or the UUID of a chassis.
        :returns: A chassis.
        """

    @abc.abstractmethod
    def get_chassis_list(self, limit=None, marker=None,
                         sort_key=None, sort_dir=None):
        """Return a list of chassis.

        :param limit: Maximum number of chassis to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        """

    @abc.abstractmethod
    def update_chassis(self, chassis_id, values):
        """Update properties of an chassis.

        :param chassis_id: The id or the uuid of a chassis.
        :param values: Dict of values to update.
        :returns: A chassis.
        """

    @abc.abstractmethod
    def destroy_chassis(self, chassis_id):
        """Destroy a chassis.

        :param chassis_id: The id or the uuid of a chassis.
        """

    @abc.abstractmethod
    def register_conductor(self, values):
        """Register a new conductor service at the specified hostname.

        :param values: A dict of values which must contain the following:
                       {
                        'hostname': the unique hostname which identifies
                                    this Conductor service.
                        'drivers': a list of supported drivers.
                       }
        :returns: A conductor.
        :raises: ConductorAlreadyRegistered
        """

    @abc.abstractmethod
    def get_conductor(self, hostname):
        """Retrieve a conductor service record from the database.

        :param hostname: The hostname of the conductor service.
        :returns: A conductor.
        :raises: ConductorNotFound
        """

    @abc.abstractmethod
    def unregister_conductor(self, hostname):
        """Unregister this conductor with the service registry.

        :param hostname: The hostname of this conductor service.
        :raises: ConductorNotFound
        """

    @abc.abstractmethod
    def touch_conductor(self, hostname):
        """Mark a conductor as active by updating its 'updated_at' property.

        :param hostname: The hostname of this conductor service.
        :raises: ConductorNotFound
        """

    @abc.abstractmethod
    def list_active_conductor_drivers(self, interval):
        """Retrieve a list of drivers supported by the registered conductors.

        :param interval: Time since last check-in of a conductor.
        """
