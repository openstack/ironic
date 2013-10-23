# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

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
Hold the data and drivers for a distinct node within a given context.

Each :py:class:`ironic.conductor.resource_manager.NodeManager` instance is a
semi-singleton, keyed by the node id. It contains references to all
:py:class:`ironic.conductor.task_manager.TaskManager` which called it.  When no
more TaskManagers reference a given NodeManager, it is automatically destroyed.

Do not request a NodeManager directly; instead, you should use a TaskManager to
manage the resource in a given context. See the documentation on TaskManager
for an example.
"""

from ironic.openstack.common import lockutils
from ironic.openstack.common import log

from ironic.common import driver_factory
from ironic.common import exception
from ironic.db import api as dbapi

LOG = log.getLogger(__name__)

RESOURCE_MANAGER_SEMAPHORE = "node_resource"


class NodeManager(object):
    """The data model, state, and drivers to manage a Node."""

    _nodes = {}

    def __init__(self, id, t, driver_name=None):
        self._driver_factory = driver_factory.DriverFactory()
        self.id = id
        self.task_refs = [t]

        db = dbapi.get_instance()
        self.node = db.get_node(id)
        self.ports = db.get_ports_by_node(id)

        # Select new driver's name if defined or select already defined in db.
        driver_name = driver_name or self.node.get('driver')
        self.driver = self.load_driver(driver_name)

    @classmethod
    @lockutils.synchronized(RESOURCE_MANAGER_SEMAPHORE, 'ironic-')
    def acquire(cls, id, t, new_driver=None):
        """Acquire a NodeManager and associate to a TaskManager."""
        n = cls._nodes.get(id)
        if n:
            n.task_refs.append(t)
        else:
            n = cls(id, t, new_driver)
            cls._nodes[id] = n
        return n

    @classmethod
    @lockutils.synchronized(RESOURCE_MANAGER_SEMAPHORE, 'ironic-')
    def release(cls, id, t):
        """Release a NodeManager previously acquired."""

        n = cls._nodes.get(id)
        if not n:
            raise exception.IronicException(_(
                "Release called on node %s for which no lock "
                "has been acquired.") % id)

        try:
            n.task_refs.remove(t)
        except ValueError:
            raise exception.IronicException(_(
                "Can not release node %s because it was not "
                "reserved by this tracker.") % id)

        # Delete the resource when no TaskManager references it.
        if len(n.task_refs) == 0:
            del(cls._nodes[id])

    def load_driver(self, driver_name):
        """Find a driver based on driver_name and return a driver object.

        :param driver_name: The name of the driver.
        :returns: A driver object.
        :raises: DriverNotFound if any driver is not found.
        """
        try:
            driver = self._driver_factory[driver_name]
        except KeyError:
            raise exception.DriverNotFound(driver_name=driver_name)

        return driver.obj
