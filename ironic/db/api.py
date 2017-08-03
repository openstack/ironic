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
        """Destroy a node and its associated resources.

        Destroy a node, including any associated ports, port groups,
        tags, volume connectors, and volume targets.

        :param node_id: The ID or UUID of a node.
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
    def get_active_hardware_type_dict(self):
        """Retrieve hardware types for the registered and active conductors.

        :returns: A dict which maps hardware type names to the set of hosts
                  which support them. For example:

                  ::

                    {hardware-type-a: set([host1, host2]),
                     hardware-type-b: set([host2, host3])}
        """

    @abc.abstractmethod
    def get_offline_conductors(self):
        """Get a list conductor hostnames that are offline (dead).

        :returns: A list of conductor hostnames.
        """

    @abc.abstractmethod
    def list_conductor_hardware_interfaces(self, conductor_id):
        """List all registered hardware interfaces for a conductor.

        :param conductor_id: Database ID of conductor.
        :returns: List of ``ConductorHardwareInterfaces`` objects.
        """

    @abc.abstractmethod
    def list_hardware_type_interfaces(self, hardware_types):
        """List registered hardware interfaces for given hardware types.

        This is restricted to only active conductors.
        :param hardware_types: list of hardware types to filter by.
        :returns: list of ``ConductorHardwareInterfaces`` objects.
        """

    @abc.abstractmethod
    def register_conductor_hardware_interfaces(self, conductor_id,
                                               hardware_type, interface_type,
                                               interfaces, default_interface):
        """Registers hardware interfaces for a conductor.

        :param conductor_id: Database ID of conductor to register for.
        :param hardware_type: Name of hardware type for the interfaces.
        :param interface_type: Type of interfaces, e.g. 'deploy' or 'boot'.
        :param interfaces: List of interface names to register.
        :param default_interface: String, the default interface for this
                                  hardware type and interface type.
        :raises: ConductorHardwareInterfacesAlreadyRegistered if at least one
                 of the interfaces in the combination of all parameters is
                 already registered.
        """

    @abc.abstractmethod
    def unregister_conductor_hardware_interfaces(self, conductor_id):
        """Unregisters all hardware interfaces for a conductor.

        :param conductor_id: Database ID of conductor to unregister for.
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

    @abc.abstractmethod
    def get_volume_connector_list(self, limit=None, marker=None,
                                  sort_key=None, sort_dir=None):
        """Return a list of volume connectors.

        :param limit: Maximum number of volume connectors to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: Direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of volume connectors.
        :raises: InvalidParameterValue If sort_key does not exist.
        """

    @abc.abstractmethod
    def get_volume_connector_by_id(self, db_id):
        """Return a volume connector representation.

        :param db_id: The integer database ID of a volume connector.
        :returns: A volume connector with the specified ID.
        :raises: VolumeConnectorNotFound If a volume connector
                 with the specified ID is not found.
        """

    @abc.abstractmethod
    def get_volume_connector_by_uuid(self, connector_uuid):
        """Return a volume connector representation.

        :param connector_uuid: The UUID of a connector.
        :returns: A volume connector with the specified UUID.
        :raises: VolumeConnectorNotFound If a volume connector
                 with the specified UUID is not found.
        """

    @abc.abstractmethod
    def get_volume_connectors_by_node_id(self, node_id, limit=None,
                                         marker=None, sort_key=None,
                                         sort_dir=None):
        """List all the volume connectors for a given node.

        :param node_id: The integer node ID.
        :param limit: Maximum number of volume connectors to return.
        :param marker: The last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: Direction in which results should be sorted
                         (asc, desc)
        :returns: A list of volume connectors.
        :raises: InvalidParameterValue If sort_key does not exist.
        """

    @abc.abstractmethod
    def create_volume_connector(self, connector_info):
        """Create a new volume connector.

        :param connector_info: Dictionary containing information about the
                               connector. Example::

                                   {
                                       'uuid': '000000-..',
                                       'type': 'wwnn',
                                       'connector_id': '00:01:02:03:04:05:06',
                                       'node_id': 2
                                   }

        :returns: A volume connector.
        :raises: VolumeConnectorTypeAndIdAlreadyExists If a connector
                 already exists with a matching type and connector_id.
        :raises: VolumeConnectorAlreadyExists If a volume connector with
                 the same UUID already exists.
        """

    @abc.abstractmethod
    def update_volume_connector(self, ident, connector_info):
        """Update properties of a volume connector.

        :param ident: The UUID or integer ID of a volume connector.
        :param connector_info: Dictionary containing the information about
                               connector to update.
        :returns: A volume connector.
        :raises: VolumeConnectorTypeAndIdAlreadyExists If another
                 connector already exists with a matching type and
                 connector_id field.
        :raises: VolumeConnectorNotFound If a volume connector
                 with the specified ident does not exist.
        :raises: InvalidParameterValue When a UUID is included in
                 connector_info.
        """

    @abc.abstractmethod
    def destroy_volume_connector(self, ident):
        """Destroy a volume connector.

        :param ident: The UUID or integer ID of a volume connector.
        :raises: VolumeConnectorNotFound If a volume connector
                 with the specified ident does not exist.
        """

    @abc.abstractmethod
    def get_volume_target_list(self, limit=None, marker=None,
                               sort_key=None, sort_dir=None):
        """Return a list of volume targets.

        :param limit: Maximum number of volume targets to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of volume targets.
        :raises: InvalidParameterValue if sort_key does not exist.
        """

    @abc.abstractmethod
    def get_volume_target_by_id(self, db_id):
        """Return a volume target representation.

        :param db_id: The database primary key (integer) ID of a volume target.
        :returns: A volume target.
        :raises: VolumeTargetNotFound if no volume target with this ID
                 exists.
        """

    @abc.abstractmethod
    def get_volume_target_by_uuid(self, uuid):
        """Return a volume target representation.

        :param uuid: The UUID of a volume target.
        :returns: A volume target.
        :raises: VolumeTargetNotFound if no volume target with this UUID
                 exists.
        """

    @abc.abstractmethod
    def get_volume_targets_by_node_id(self, node_id, limit=None,
                                      marker=None, sort_key=None,
                                      sort_dir=None):
        """List all the volume targets for a given node.

        :param node_id: The integer node ID.
        :param limit: Maximum number of volume targets to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: direction in which results should be sorted
                         (asc, desc)
        :returns: A list of volume targets.
        :raises: InvalidParameterValue if sort_key does not exist.
        """

    @abc.abstractmethod
    def get_volume_targets_by_volume_id(self, volume_id, limit=None,
                                        marker=None, sort_key=None,
                                        sort_dir=None):
        """List all the volume targets for a given volume id.

        :param volume_id: The UUID of the volume.
        :param limit: Maximum number of volume targets to return.
        :param marker: the last item of the previous page; we return the next
                       result set.
        :param sort_key: Attribute by which results should be sorted
        :param sort_dir: direction in which results should be sorted
                         (asc, desc)
        :returns: A list of volume targets.
        :raises: InvalidParameterValue if sort_key does not exist.
        """

    @abc.abstractmethod
    def create_volume_target(self, target_info):
        """Create a new volume target.

        :param target_info: Dictionary containing the information about the
                            volume target. Example::

                                   {
                                       'uuid': '000000-..',
                                       'node_id': 2,
                                       'boot_index': 0,
                                       'volume_id': '12345678-...'
                                       'volume_type': 'some type',
                                   }
        :returns: A volume target.
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same boot index and node ID.
        :raises: VolumeTargetAlreadyExists if a volume target with the same
                 UUID exists.
        """

    @abc.abstractmethod
    def update_volume_target(self, ident, target_info):
        """Update information for a volume target.

        :param ident: The UUID or integer ID of a volume target.
        :param target_info: Dictionary containing the information about
                            volume target to update.
        :returns: A volume target.
        :raises: InvalidParameterValue if a UUID is included in target_info.
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same boot index and node ID.
        :raises: VolumeTargetNotFound if no volume target with this ident
                 exists.
        """

    @abc.abstractmethod
    def destroy_volume_target(self, ident):
        """Destroy a volume target.

        :param ident: The UUID or integer ID of a volume target.
        :raises: VolumeTargetNotFound if a volume target with the specified
                 ident does not exist.
        """

    @abc.abstractmethod
    def check_versions(self):
        """Checks the whole database for incompatible objects.

        This scans all the tables in search of objects that are not supported;
        i.e., those that are not specified in
        `ironic.common.release_mappings.RELEASE_MAPPING`.

        :returns: A Boolean. True if all the objects have supported versions;
                  False otherwise.
        """

    @abc.abstractmethod
    def backfill_version_column(self, max_count):
        """Backfill the version column with Ocata versions.

        The version column was added to all the resource tables in this Pike
        release (via 'ironic-dbsync upgrade'). After upgrading (from Ocata to
        Pike), the 'ironic-dbsync online_data_migrations' command will invoke
        this method to populate (backfill) the version columns. The version
        used will be the object version from the pinning set in config (i.e.
        prior to this column being added).

        :param max_count: The maximum number of objects to migrate. Must be
                          >= 0. If zero, all the objects will be migrated.
        :returns: A 2-tuple, 1. the total number of objects that need to be
                  migrated (at the beginning of this call) and 2. the number
                  of migrated objects.
        """
        # TODO(rloo) Delete this in Queens cycle.
