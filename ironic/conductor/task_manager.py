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
A context manager to peform a series of tasks on a set of resources.

:class:`TaskManager` is a context manager, created on-demand to synchronize
locking and simplify operations across a set of
:class:`ironic.conductor.resource_manager.NodeManager` instances.  Each
NodeManager holds the data model for a node, as well as references to the
driver singleton appropriate for that node.

The :class:`TaskManager` will acquire either a shared or exclusive lock, as
indicated.  Multiple shared locks for the same resource may coexist with an
exclusive lock, but only one exclusive lock will be granted across a
deployment; attempting to allocate another will raise an exception.  An
exclusive lock is represented in the database to coordinate between
:class:`ironic.conductor.manager` instances, even when deployed on
different hosts.

:class:`TaskManager` methods, as well as driver methods, may be decorated to
determine whether their invocation requires an exclusive lock.

For now, you can access the drivers directly in this way::

    with task_manager.acquire(node_ids) as task:
        states = []
        for node, driver in [r.node, r.driver
                                        for r in task.resources]:
            # the driver is loaded based on that node's configuration.
            states.append(driver.power.get_power_state(task, node)

If you have a task with just a single node, the `node` property provides
a shorthand to access it. For example::

    with task_manager.acquire(node_id) as task:
        driver = task.node.driver
        driver.power.power_on(task.node)

Eventually, driver functionality may be wrapped by tasks to facilitate
multi-node tasks more easily. Once implemented, it might look like this::

    node_ids = [1, 2, 3]
    try:
        with task_manager.acquire(node_ids) as task:
            task.power_on()
            states = task.get_power_state()
    except exception.NodeLocked:
        LOG.info(_("Unable to power on nodes %s.") % node_ids)
        # Get a shared lock, just to check the power state.
        with task_manager.acquire(node_ids, shared=True) as task:
            states = task.get_power_state()

"""

import contextlib
from oslo.config import cfg

from ironic.common import exception
from ironic.conductor import resource_manager
from ironic.db import api as dbapi

CONF = cfg.CONF


def require_exclusive_lock(f):
    """Decorator to require an exclusive lock.

    Decorated functions must take a :class:`TaskManager` as the first
    parameter. Decorated class methods should take a :class:`TaskManager`
    as the first parameter after "self".

    """
    def wrapper(*args, **kwargs):
        task = args[0] if isinstance(args[0], TaskManager) else args[1]
        if task.shared:
            raise exception.ExclusiveLockRequired()
        return f(*args, **kwargs)
    return wrapper


@contextlib.contextmanager
def acquire(node_ids, shared=False):
    """Context manager for acquiring a lock on one or more Nodes.

    Acquire a lock atomically on a non-empty set of nodes. The lock
    can be either shared or exclusive. Shared locks may be used for
    read-only or non-disruptive actions only, and must be considerate
    to what other threads may be doing on the nodes at the same time.

    :param node_ids: A list of ids or uuids of nodes to lock.
    :param shared: Boolean indicating whether to take a shared or exclusive
                   lock. Default: False.
    :returns: An instance of :class:`TaskManager`.

    """

    t = TaskManager(shared)

    # instead of generating an exception, DTRT and convert to a list
    if not isinstance(node_ids, list):
        node_ids = [node_ids]

    try:
        if not shared:
            t.dbapi.reserve_nodes(CONF.host, node_ids)
        for id in node_ids:
            t.resources.append(resource_manager.NodeManager.acquire(id, t))
        yield t
    finally:
        for id in [r.id for r in t.resources]:
            resource_manager.NodeManager.release(id, t)
        if not shared:
            t.dbapi.release_nodes(CONF.host, node_ids)


class TaskManager(object):
    """Context manager for tasks."""

    def __init__(self, shared):
        self.shared = shared
        self.resources = []
        self.dbapi = dbapi.get_instance()

    @property
    def node(self):
        """Special accessor for single-node tasks."""
        if len(self.resources) == 1:
            return self.resources[0].node
        else:
            raise AttributeError(_("Multi-node TaskManager "
                                   "has no attribute 'node'"))

    @property
    def driver(self):
        """Special accessor for single-node tasks."""
        if len(self.resources) == 1:
            return self.resources[0].driver
        else:
            raise AttributeError(_("Multi-node TaskManager "
                                   "has no attribute 'driver'"))
