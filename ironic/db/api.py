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


def get_instance():
    """Return a DB API instance."""
    IMPL = db_api.DBAPI(backend_mapping=_BACKEND_MAPPING)
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
    def reserve_node(self, node, values):
        """Associate a node with an instance.

        :param node: The id or uuid of a node.
        :param values: Values to set while reserving the node.
                       Must include 'instance_uuid'.
        :return: The reserved Node.
        """

    @abc.abstractmethod
    def create_node(self, values):
        """Create a new node.

        :param values: Values to instantiate the node with.
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
