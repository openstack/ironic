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

from ironic.openstack.common.db import api as db_api

_BACKEND_MAPPING = {'sqlalchemy': 'ironic.db.sqlalchemy.api'}
IMPL = db_api.DBAPI(backend_mapping=_BACKEND_MAPPING)


def get_instance():
    """Return a DB API instance."""
    return IMPL


class Connection(object):
    """Base class for storage system connections."""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @abc.abstractmethod
    def get_nodes(self, columns):
        """Return a list of dicts of all nodes.

        :param columns: List of columns to return.
        """

    @abc.abstractmethod
    def get_associated_nodes(self):
        """Return a list of ids of all associated nodes."""

    @abc.abstractmethod
    def get_unassociated_nodes(self):
        """Return a list of ids of all unassociated nodes."""

    @abc.abstractmethod
    def reserve_nodes(self, nodes):
        """Reserve a set of nodes atomically.

        To prevent other ManagerServices from manipulating the given
        Nodes while a Task is performed, mark them all reserved by this host.

        :param nodes: A list of node id or uuid.
        :returns: A list of the reserved node refs.
        :raises: NodeNotFound if any node is not found.
        :raises: NodeAlreadyReserved if any node is already reserved.
        """

    @abc.abstractmethod
    def release_nodes(self, nodes):
        """Release the reservation on a set of nodes atomically.

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
                         'uuid': uuidutils.generate_uuid(),
                         'instance_uuid': None,
                         'task_state': states.NOSTATE,
                         'control_driver': 'ipmi',
                         'control_info': { ... },
                         'deploy_driver': 'pxe',
                         'deploy_info': { ... },
                         'properties': { ... },
                        }
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node(self, node):
        """Return a node.

        :param node: The id or uuid of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_instance(self, instance):
        """Return a node.

        :param instance: The instance name or uuid to search for.
        :returns: A node.
        """

    @abc.abstractmethod
    def destroy_node(self, node):
        """Destroy a node and all associated interfaces.

        :param node: The id or uuid of a node.
        """

    @abc.abstractmethod
    def update_node(self, node, values):
        """Update properties of a node.

        :param node: The id or uuid of a node.
        :param values: Dict of values to update.
                       May be a partial list, eg. when setting the
                       properties for a single driver. For example:

                       {
                        'deploy_driver': 'my-vendor-driver',
                        'deploy_info':
                            {
                             'my-field-1': val1,
                             'my-field-2': val2,
                            }
                       }
        :returns: A node.
        """

    @abc.abstractmethod
    def get_port(self, port):
        """Return a network port representation.

        :param port: The id or MAC of a port.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_port_by_vif(self, vif):
        """Return the port corresponding to this VIF.

        :param vif: The uuid of the VIF.
        :returns: A port.
        """

    @abc.abstractmethod
    def get_ports_by_node(self, node):
        """List all the ports for a given node.

        :param node: The id or uuid of a node.
        :returns: A list of ports.
        """

    @abc.abstractmethod
    def create_port(self, values):
        """Create a new port.

        :param values: Dict of values.
        """

    @abc.abstractmethod
    def update_port(self, port, values):
        """Update properties of an port.

        :param port: The id or MAC of a port.
        :param values: Dict of values to update.
        :returns: A port.
        """

    @abc.abstractmethod
    def destroy_port(self, port):
        """Destroy an port.

        :param port: The id or MAC of a port.
        """
