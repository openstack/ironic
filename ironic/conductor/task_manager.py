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
locking and simplify operations across a set of :class:`NodeResource`
instances.  Each NodeResource holds the data model for a node and its
associated ports, as well as references to the driver singleton appropriate for
that node.

The :class:`TaskManager` will, by default, acquire an exclusive lock on
its resources for the duration that the TaskManager instance exists.
You may create a TaskManager instance without locking by passing
"shared=True" when creating it, but certain operations on the resources
held by such an instance of TaskManager will not be possible. Requiring
this exclusive lock guards against parallel operations interfering with
each other.

A shared lock is useful when performing non-interfering operations,
such as validating the driver interfaces or the vendor_passthru method.

An exclusive lock is stored in the database to coordinate between
:class:`ironic.conductor.manager` instances, that are typically deployed on
different hosts.

:class:`TaskManager` methods, as well as driver methods, may be decorated to
determine whether their invocation requires an exclusive lock.

If you have a task with just a single node, the TaskManager instance
exposes additional properties to access the node, driver, and ports
in a short-hand fashion. For example:

    with task_manager.acquire(node_id) as task:
        driver = task.node.driver
        driver.power.power_on(task.node)

If you need to execute task-requiring code in the background thread the
TaskManager provides the interface to manage resource locks manually. Common
approach is to use manager._spawn_worker method and release resources using
link method of the returned thread object.
For example (somewhere inside conductor manager)::

    task = task_manager.TaskManager(context, node_id, shared=False)

    try:
        # Start requested action in the background.
        thread = self._spawn_worker(utils.node_power_action,
                                    task, task.node, new_state)
        # Release node lock at the end.
        thread.link(lambda t: task.release_resources())
    except Exception:
        with excutils.save_and_reraise_exception():
            # Release node lock if error occurred.
            task.release_resources()

The linked callback will be called whenever:
    - background task finished with no errors.
    - background task has crashed with exception.
    - callback was added after the background task has finished or crashed.

"""

from oslo.config import cfg

from ironic.openstack.common import excutils

from ironic.common import driver_factory
from ironic.common import exception
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


def acquire(context, node_ids, shared=False, driver_name=None):
    """Shortcut for acquiring a lock on one or more Nodes.

    :param context: Request context.
    :param node_ids: A list of ids or uuids of nodes to lock.
    :param shared: Boolean indicating whether to take a shared or exclusive
                   lock. Default: False.
    :param driver_name: Name of Driver. Default: None.
    :returns: An instance of :class:`TaskManager`.

    """
    return TaskManager(context, node_ids, shared, driver_name)


class TaskManager(object):
    """Context manager for tasks.

    This class wraps the locking, driver loading, and acquisition
    of related resources (eg, Nodes and Ports) when beginning a unit of work.

    """

    def __init__(self, context, node_ids, shared=False, driver_name=None):
        """Create a new TaskManager.

        Acquire a lock atomically on a non-empty set of nodes. The lock
        can be either shared or exclusive. Shared locks may be used for
        read-only or non-disruptive actions only, and must be considerate
        to what other threads may be doing on the nodes at the same time.

        :param context: request context
        :param node_ids: A list of ids or uuids of nodes to lock.
        :param shared: Boolean indicating whether to take a shared or exclusive
                       lock. Default: False.
        :param driver_name: The name of the driver to load, if different
                            from the Node's current driver.
        :raises: DriverNotFound
        :raises: NodeAlreadyLocked

        """

        self.context = context
        self.resources = []
        self.shared = shared
        self.dbapi = dbapi.get_instance()

        # instead of generating an exception, DTRT and convert to a list
        if not isinstance(node_ids, list):
            node_ids = [node_ids]

        locked_node_list = []
        try:
            for id in node_ids:
                if not self.shared:
                    # NOTE(deva): Only lock one node at a time so we can ensure
                    #             that only the right nodes are unlocked.
                    #             However, reserve_nodes takes and returns a
                    #             list. This should be refactored.
                    node = self.dbapi.reserve_nodes(CONF.host, [id])[0]
                    locked_node_list.append(node.id)
                else:
                    node = self.dbapi.get_node(id)
                ports = self.dbapi.get_ports_by_node(id)
                driver = driver_factory.get_driver(driver_name or node.driver)

                self.resources.append(NodeResource(node, ports, driver))
        except Exception:
            with excutils.save_and_reraise_exception():
                if locked_node_list:
                    self.dbapi.release_nodes(CONF.host, locked_node_list)

    def release_resources(self):
        """Release any resources for which this TaskManager
        was holding an exclusive lock.
        """

        if not self.shared:
            if self.resources:
                node_ids = [r.node.id for r in self.resources]
                try:
                    self.dbapi.release_nodes(CONF.host, node_ids)
                except exception.NodeNotFound:
                    # squelch the exception if the node was deleted
                    # within the task's context.
                    pass
        self.resources = []

    @property
    def node(self):
        """Special accessor for single-node tasks."""
        if len(self.resources) == 1:
            return self.resources[0].node
        else:
            raise AttributeError(_("Multi-node TaskManager "
                                   "has no attribute 'node'"))

    @property
    def ports(self):
        """Special accessor for single-node tasks."""
        if len(self.resources) == 1:
            return self.resources[0].ports
        else:
            raise AttributeError(_("Multi-node TaskManager "
                                   "has no attribute 'ports'"))

    @property
    def driver(self):
        """Special accessor for single-node tasks."""
        if len(self.resources) == 1:
            return self.resources[0].driver
        else:
            raise AttributeError(_("Multi-node TaskManager "
                                   "has no attribute 'driver'"))

    @property
    def node_manager(self):
        """Special accessor for single-node manager."""
        if len(self.resources) == 1:
            return self.resources[0]
        else:
            raise AttributeError(_("Multi-node TaskManager "
                "can't select single node manager from the list"))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release_resources()


class NodeResource(object):
    """Wrapper to hold a Node, its associated Port(s), and its Driver."""

    def __init__(self, node, ports, driver):
        self.node = node
        self.ports = ports
        self.driver = driver
