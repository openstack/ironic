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
A context manager to perform a series of tasks on a set of resources.

:class:`TaskManager` is a context manager, created on-demand to allow
synchronized access to a node and its resources.

The :class:`TaskManager` will, by default, acquire an exclusive lock on
a node for the duration that the TaskManager instance exists. You may
create a TaskManager instance without locking by passing "shared=True"
when creating it, but certain operations on the resources held by such
an instance of TaskManager will not be possible. Requiring this exclusive
lock guards against parallel operations interfering with each other.

A shared lock is useful when performing non-interfering operations,
such as validating the driver interfaces or the vendor_passthru method.

An exclusive lock is stored in the database to coordinate between
:class:`ironic.conductor.manager` instances, that are typically deployed on
different hosts.

:class:`TaskManager` methods, as well as driver methods, may be decorated to
determine whether their invocation requires an exclusive lock.

The TaskManager instance exposes certain node resources and properties as
attributes that you may access:

    task.context -- The context passed to TaskManager()
    task.shared -- False if Node is locked, True if it is not locked. (The
                   'shared' kwarg arg of TaskManager())
    task.node -- The Node object
    task.ports -- Ports belonging to the Node
    task.driver -- The Driver for the Node, or the Driver based on the
                   'driver_name' kwarg of TaskManager().

Example usage:

    with task_manager.acquire(context, node_id) as task:
        task.driver.power.power_on(task.node)

If you need to execute task-requiring code in the background thread, the
TaskManager instance provides an interface to handle this for you, making
sure to release resources when exceptions occur or when the thread finishes.
Common use of this is within the Manager like so:

    with task_manager.acquire(context, node_id) as task:
        <do some work>
        task.spawn_after(self._spawn_worker,
                         utils.node_power_action, task, task.node,
                         new_state)

All exceptions that occur in the current greenthread as part of the spawn
handling are re-raised.
"""

from oslo.config import cfg

from ironic.openstack.common import excutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.db import api as dbapi
from ironic import objects

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


def acquire(context, node_id, shared=False, driver_name=None):
    """Shortcut for acquiring a lock on a Node.

    :param context: Request context.
    :param node_id: ID or UUID of node to lock.
    :param shared: Boolean indicating whether to take a shared or exclusive
                   lock. Default: False.
    :param driver_name: Name of Driver. Default: None.
    :returns: An instance of :class:`TaskManager`.

    """
    return TaskManager(context, node_id, shared=shared,
                       driver_name=driver_name)


class TaskManager(object):
    """Context manager for tasks.

    This class wraps the locking, driver loading, and acquisition
    of related resources (eg, Node and Ports) when beginning a unit of work.

    """

    def __init__(self, context, node_id, shared=False, driver_name=None):
        """Create a new TaskManager.

        Acquire a lock on a node. The lock can be either shared or
        exclusive. Shared locks may be used for read-only or
        non-disruptive actions only, and must be considerate to what
        other threads may be doing on the same node at the same time.

        :param context: request context
        :param node_id: ID or UUID of node to lock.
        :param shared: Boolean indicating whether to take a shared or exclusive
                       lock. Default: False.
        :param driver_name: The name of the driver to load, if different
                            from the Node's current driver.
        :raises: DriverNotFound
        :raises: NodeNotFound
        :raises: NodeLocked

        """

        self._dbapi = dbapi.get_instance()
        self._spawn_method = None

        self.context = context
        self.node = None
        self.shared = shared

        try:
            if not self.shared:
                self.node = self._dbapi.reserve_node(CONF.host, node_id)
            else:
                self.node = objects.Node.get(context, node_id)
            self.ports = self._dbapi.get_ports_by_node_id(self.node.id)
            self.driver = driver_factory.get_driver(driver_name or
                                                    self.node.driver)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()

    def spawn_after(self, _spawn_method, *args, **kwargs):
        """Call this to spawn a thread to complete the task."""
        self._spawn_method = _spawn_method
        self._spawn_args = args
        self._spawn_kwargs = kwargs

    def release_resources(self):
        """Unlock a node and release resources.

        If an exclusive lock is held, unlock the node. Reset attributes
        to make it clear that this instance of TaskManager should no
        longer be accessed.
        """

        if not self.shared:
            try:
                if self.node:
                    self._dbapi.release_node(CONF.host, self.node.id)
            except exception.NodeNotFound:
                # squelch the exception if the node was deleted
                # within the task's context.
                pass
        self.node = None
        self.driver = None
        self.ports = None

    def _thread_release_resources(self, t):
        """Thread.link() callback to release resources."""
        self.release_resources()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and self._spawn_method is not None:
            # Spawn a worker to complete the task
            # The linked callback below will be called whenever:
            #   - background task finished with no errors.
            #   - background task has crashed with exception.
            #   - callback was added after the background task has
            #     finished or crashed. While eventlet currently doesn't
            #     schedule the new thread until the current thread blocks
            #     for some reason, this is true.
            # All of the above are asserted in tests such that we'll
            # catch if eventlet ever changes this behavior.
            thread = None
            try:
                thread = self._spawn_method(*self._spawn_args,
                                            **self._spawn_kwargs)

                # NOTE(comstud): Trying to use a lambda here causes
                # the callback to not occur for some reason. This
                # also makes it easier to test.
                thread.link(self._thread_release_resources)
                # Don't unlock! The unlock will occur when the
                # thread finshes.
                return
            except Exception:
                with excutils.save_and_reraise_exception():
                    if thread is not None:
                        # This means the link() failed for some
                        # reason. Nuke the thread.
                        thread.cancel()
                    self.release_resources()
        self.release_resources()
