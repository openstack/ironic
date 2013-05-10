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
    def reserve_node(self, *args, **kwargs):
        """Find a free node and associate it.

        TBD
        """

    @abc.abstractmethod
    def create_node(self, *args, **kwargs):
        """Create a new node."""

    @abc.abstractmethod
    def get_node_by_id(self, node_id):
        """Return a node.

        :param node_id: The id or uuid of a node.
        """

    @abc.abstractmethod
    def get_node_by_instance_id(self, instance_id):
        """Return a node.

        :param instance_id: The instance id or uuid of a node.
        """

    @abc.abstractmethod
    def destroy_node(self, node_id):
        """Destroy a node.

        :param node_id: The id or uuid of a node.
        """

    @abc.abstractmethod
    def update_node(self, node_id, *args, **kwargs):
        """Update properties of a node.

        :param node_id: The id or uuid of a node.
        TBD
        """

    @abc.abstractmethod
    def get_iface(self, iface_id):
        """Return an interface.

        :param iface_id: The id or MAC of an interface.
        """

    @abc.abstractmethod
    def create_iface(self, *args, **kwargs):
        """Create a new iface."""

    @abc.abstractmethod
    def update_iface(self, iface_id, *args, **kwargs):
        """Update properties of an iface.

        :param iface_id: The id or MAC of an interface.
        TBD
        """

    @abc.abstractmethod
    def destroy_iface(self, iface_id):
        """Destroy an iface.

        :param iface_id: The id or MAC of an interface.
        """
