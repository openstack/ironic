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

from oslo_config import cfg
from oslo_db import api as db_api
import six


_BACKEND_MAPPING = {'sqlalchemy': 'ironic.db.sqlalchemy.api'}
IMPL = db_api.DBAPI.from_config(cfg.CONF, backend_mapping=_BACKEND_MAPPING,
                                lazy=True)


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
        """Get specific columns for matching nodes.

        Return a list of the specified columns for all nodes that match the
        specified filters.

        :param columns: List of column names to return.
                        Defaults to 'id' column when columns == None.
        :param filters: Filters to apply. Defaults to None.

                        :associated: True | False
                        :reserved: True | False
                        :reserved_by_any_of: [conductor1, conductor2]
                        :maintenance: True | False
                        :chassis_uuid: uuid of chassis
                        :driver: driver's name
                        :provision_state: provision state of node
                        :provisioned_before:
                            nodes with provision_updated_at field before this
                            interval in seconds
        :param limit: Maximum number of nodes to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of tuples of the specified columns.
        """

    @abc.abstractmethod
    def get_node_list(self, filters=None, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        """Return a list of nodes.

        :param filters: Filters to apply. Defaults to None.

                        :associated: True | False
                        :reserved: True | False
                        :maintenance: True | False
                        :chassis_uuid: uuid of chassis
                        :driver: driver's name
                        :provision_state: provision state of node
                        :provisioned_before:
                            nodes with provision_updated_at field before this
                            interval in seconds
        :param limit: Maximum number of nodes to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        """

    @abc.abstractmethod
    def reserve_node(self, tag, node_id):
        """Reserve a node.

        To prevent other ManagerServices from manipulating the given
        Node while a Task is performed, mark it reserved by this host.

        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id or uuid.
        :returns: A Node object.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is already reserved.
        """

    @abc.abstractmethod
    def release_node(self, tag, node_id):
        """Release the reservation on a node.

        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id or uuid.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is reserved by another host.
        :raises: NodeNotLocked if the node was found to not have a
                 reservation at all.
        """

    @abc.abstractmethod
    def create_node(self, values):
        """Create a new node.

        :param values: A dict containing several items used to identify
                       and track the node, and several dicts which are passed
                       into the Drivers when managing this node. For example:

                       ::

                        {
                         'uuid': uuidutils.generate_uuid(),
                         'instance_uuid': None,
                         'power_state': states.POWER_OFF,
                         'provision_state': states.AVAILABLE,
                         'driver': 'pxe_ipmitool',
                         'driver_info': { ... },
                         'properties': { ... },
                         'extra': { ... },
                        }
        :raises: InvalidParameterValue if create a node with tags.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_id(self, node_id):
        """Return a node.

        :param node_id: The id of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_uuid(self, node_uuid):
        """Return a node.

        :param node_uuid: The uuid of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_name(self, node_name):
        """Return a node.

        :param node_name: The logical name of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_instance(self, instance):
        """Return a node.

        :param instance: The instance uuid to search for.
        :returns: A node.
        :raises: InstanceNotFound if the instance is not found.
        :raises: InvalidUUID if the instance uuid is invalid.
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

                       ::

                        {
                         'driver_info':
                             {
                              'my-field-1': val1,
                              'my-field-2': val2,
                             }
                        }
        :returns: A node.
        :raises: NodeAssociated
        :raises: NodeNotFound
        """

    @abc.abstractmethod
    def get_port_by_id(self, port_id):
        """Return a network port representation.

        :param port_id: The id of a port.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_port_by_uuid(self, port_uuid):
        """Return a network port representation.

        :param port_uuid: The uuid of a port.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_port_by_address(self, address):
        """Return a network port representation.

        :param address: The MAC address of a port.
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
    def get_ports_by_node_id(self, node_id, limit=None, marker=None,
                             sort_key=None, sort_dir=None):
        """List all the ports for a given node.

        :param node_id: The integer node ID.
        :param limit: Maximum number of ports to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: direction in which results should be sorted
                         (asc, desc)
        :returns: A list of ports.
        """

    @abc.abstractmethod
    def get_ports_by_portgroup_id(self, portgroup_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None):
        """List all the ports for a given portgroup.

        :param portgroup_id: The integer portgroup ID.
        :param limit: Maximum number of ports to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: Direction in which results should be sorted
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
    def get_portgroup_by_id(self, portgroup_id):
        """Return a network portgroup representation.

        :param portgroup_id: The id of a portgroup.
        :returns: A portgroup.
        :raises: PortgroupNotFound
        """

    @abc.abstractmethod
    def get_portgroup_by_uuid(self, portgroup_uuid):
        """Return a network portgroup representation.

        :param portgroup_uuid: The uuid of a portgroup.
        :returns: A portgroup.
        :raises: PortgroupNotFound
        """

    @abc.abstractmethod
    def get_portgroup_by_address(self, address):
        """Return a network portgroup representation.

        :param address: The MAC address of a portgroup.
        :returns: A portgroup.
        :raises: PortgroupNotFound
        """

    @abc.abstractmethod
    def get_portgroup_by_name(self, name):
        """Return a network portgroup representation.

        :param name: The logical name of a portgroup.
        :returns: A portgroup.
        :raises: PortgroupNotFound
        """

    @abc.abstractmethod
    def get_portgroup_list(self, limit=None, marker=None,
                           sort_key=None, sort_dir=None):
        """Return a list of portgroups.

        :param limit: Maximum number of portgroups to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: Direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of portgroups.
        """

    @abc.abstractmethod
    def get_portgroups_by_node_id(self, node_id, limit=None, marker=None,
                                  sort_key=None, sort_dir=None):
        """List all the portgroups for a given node.

        :param node_id: The integer node ID.
        :param limit: Maximum number of portgroups to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: Direction in which results should be sorted
                         (asc, desc)
        :returns: A list of portgroups.
        """

    @abc.abstractmethod
    def create_portgroup(self, values):
        """Create a new portgroup.

        :param values: Dict of values with the following keys:
                       'id'
                       'uuid'
                       'name'
                       'node_id'
                       'address'
                       'extra'
                       'created_at'
                       'updated_at'
        :returns: A portgroup
        :raises: PortgroupDuplicateName
        :raises: PortgroupMACAlreadyExists
        :raises: PortgroupAlreadyExists
        """

    @abc.abstractmethod
    def update_portgroup(self, portgroup_id, values):
        """Update properties of a portgroup.

        :param portgroup_id: The UUID or MAC of a portgroup.
        :param values: Dict of values to update.
                       May contain the following keys:
                       'uuid'
                       'name'
                       'node_id'
                       'address'
                       'extra'
                       'created_at'
                       'updated_at'
        :returns: A portgroup.
        :raises: InvalidParameterValue
        :raises: PortgroupNotFound
        :raises: PortgroupDuplicateName
        :raises: PortgroupMACAlreadyExists
        """

    @abc.abstractmethod
    def destroy_portgroup(self, portgroup_id):
        """Destroy a portgroup.

        :param portgroup_id: The UUID or MAC of a portgroup.
        :raises: PortgroupNotEmpty
        :raises: PortgroupNotFound
        """

    @abc.abstractmethod
    def create_chassis(self, values):
        """Create a new chassis.

        :param values: Dict of values.
        """

    @abc.abstractmethod
    def get_chassis_by_id(self, chassis_id):
        """Return a chassis representation.

        :param chassis_id: The id of a chassis.
        :returns: A chassis.
        """

    @abc.abstractmethod
    def get_chassis_by_uuid(self, chassis_uuid):
        """Return a chassis representation.

        :param chassis_uuid: The uuid of a chassis.
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
    def register_conductor(self, values, update_existing=False):
        """Register an active conductor with the cluster.

        :param values: A dict of values which must contain the following:

                       ::

                        {
                         'hostname': the unique hostname which identifies
                                     this Conductor service.
                         'drivers': a list of supported drivers.
                        }
        :param update_existing: When false, registration will raise an
                                exception when a conflicting online record
                                is found. When true, will overwrite the
                                existing record. Default: False.
        :returns: A conductor.
        :raises: ConductorAlreadyRegistered
        """

    @abc.abstractmethod
    def get_conductor(self, hostname):
        """Retrieve a conductor's service record from the database.

        :param hostname: The hostname of the conductor service.
        :returns: A conductor.
        :raises: ConductorNotFound
        """

    @abc.abstractmethod
    def unregister_conductor(self, hostname):
        """Remove this conductor from the service registry immediately.

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
    def get_active_driver_dict(self, interval):
        """Retrieve drivers for the registered and active conductors.

        :param interval: Seconds since last check-in of a conductor.
        :returns: A dict which maps driver names to the set of hosts
                  which support them. For example:

                  ::

                    {driverA: set([host1, host2]),
                     driverB: set([host2, host3])}
        """

    @abc.abstractmethod
    def get_offline_conductors(self):
        """Get a list conductor hostnames that are offline (dead).

        :returns: A list of conductor hostnames.
        """

    @abc.abstractmethod
    def touch_node_provisioning(self, node_id):
        """Mark the node's provisioning as running.

        Mark the node's provisioning as running by updating its
        'provision_updated_at' property.

        :param node_id: The id of a node.
        :raises: NodeNotFound
        """

    @abc.abstractmethod
    def set_node_tags(self, node_id, tags):
        """Replace all of the node tags with specified list of tags.

        This ignores duplicate tags in the specified list.

        :param node_id: The id of a node.
        :param tags: List of tags.
        :returns: A list of NodeTag objects.
        :raises: NodeNotFound if the node is not found.
        """

    @abc.abstractmethod
    def unset_node_tags(self, node_id):
        """Remove all tags of the node.

        :param node_id: The id of a node.
        :raises: NodeNotFound if the node is not found.
        """

    @abc.abstractmethod
    def get_node_tags_by_node_id(self, node_id):
        """Get node tags based on its id.

        :param node_id: The id of a node.
        :returns: A list of NodeTag objects.
        :raises: NodeNotFound if the node is not found.
        """

    @abc.abstractmethod
    def add_node_tag(self, node_id, tag):
        """Add tag to the node.

        If the node_id and tag pair already exists, this should still
        succeed.

        :param node_id: The id of a node.
        :param tag: A tag string.
        :returns: the NodeTag object.
        :raises: NodeNotFound if the node is not found.
        """

    @abc.abstractmethod
    def delete_node_tag(self, node_id, tag):
        """Delete specified tag from the node.

        :param node_id: The id of a node.
        :param tag: A tag string.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeTagNotFound if the tag is not found.
        """

    @abc.abstractmethod
    def node_tag_exists(self, node_id, tag):
        """Check if the specified tag exist on the node.

        :param node_id: The id of a node.
        :param tag: A tag string.
        :returns: True if the tag exists otherwise False.
        """

    @abc.abstractmethod
    def get_node_by_port_addresses(self, addresses):
        """Find a node by any matching port address.

        :param addresses: list of port addresses (e.g. MACs).
        :returns: Node object.
        :raises: NodeNotFound if none or several nodes are found.
        """
