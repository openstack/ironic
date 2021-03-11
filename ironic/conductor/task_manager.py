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
such as validating the driver interfaces.

An exclusive lock is stored in the database to coordinate between
:class:`ironic.conductor.manager` instances, that are typically deployed on
different hosts.

:class:`TaskManager` methods, as well as driver methods, may be decorated to
determine whether their invocation requires an exclusive lock.

The TaskManager instance exposes certain node resources and properties as
attributes that you may access:

    task.context
        The context passed to TaskManager()
    task.shared
        False if Node is locked, True if it is not locked. (The
        'shared' kwarg arg of TaskManager())
    task.node
        The Node object
    task.ports
        Ports belonging to the Node
    task.portgroups
        Portgroups belonging to the Node
    task.volume_connectors
        Storage connectors belonging to the Node
    task.volume_targets
        Storage targets assigned to the Node
    task.driver
        The Driver for the Node, or the Driver based on the
        'driver_name' kwarg of TaskManager().

Example usage:

::

    with task_manager.acquire(context, node_id, purpose='power on') as task:
        task.driver.power.power_on(task.node)

If you need to execute task-requiring code in a background thread, the
TaskManager instance provides an interface to handle this for you, making
sure to release resources when the thread finishes (successfully or if
an exception occurs). Common use of this is within the Manager like so:

::

    with task_manager.acquire(context, node_id, purpose='some work') as task:
        <do some work>
        task.spawn_after(self._spawn_worker,
                         utils.node_power_action, task, new_state)

All exceptions that occur in the current GreenThread as part of the
spawn handling are re-raised. You can specify a hook to execute custom
code when such exceptions occur. For example, the hook is a more elegant
solution than wrapping the "with task_manager.acquire()" with a
try..exception block. (Note that this hook does not handle exceptions
raised in the background thread.):

::

    def on_error(e):
        if isinstance(e, Exception):
            ...

    with task_manager.acquire(context, node_id, purpose='some work') as task:
        <do some work>
        task.set_spawn_error_hook(on_error)
        task.spawn_after(self._spawn_worker,
                         utils.node_power_action, task, new_state)

"""

import copy
import functools

import futurist
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils
import tenacity

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.conductor import notification_utils as notify
from ironic import objects
from ironic.objects import fields

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


def require_exclusive_lock(f):
    """Decorator to require an exclusive lock.

    Decorated functions must take a :class:`TaskManager` as the first
    parameter. Decorated class methods should take a :class:`TaskManager`
    as the first parameter after "self".

    """
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        # NOTE(dtantsur): this code could be written simpler, but then unit
        # testing decorated functions is pretty hard, as we usually pass a Mock
        # object instead of TaskManager there.
        if len(args) > 1:
            task = args[1] if isinstance(args[1], TaskManager) else args[0]
        else:
            task = args[0]
        if task.shared:
            raise exception.ExclusiveLockRequired()
        # NOTE(lintan): This is a workaround to set the context of async tasks,
        # which should contain an exclusive lock.
        task.context.ensure_thread_contain_context()
        return f(*args, **kwargs)
    return wrapper


def acquire(context, *args, **kwargs):
    """Shortcut for acquiring a lock on a Node.

    :param context: Request context.
    :returns: An instance of :class:`TaskManager`.

    """
    # NOTE(lintan): This is a workaround to set the context of periodic tasks.
    context.ensure_thread_contain_context()
    return TaskManager(context, *args, **kwargs)


class TaskManager(object):
    """Context manager for tasks.

    This class wraps the locking, driver loading, and acquisition
    of related resources (eg, Node and Ports) when beginning a unit of work.

    """

    def __init__(self, context, node_id, shared=False,
                 purpose='unspecified action', retry=True, patient=False,
                 load_driver=True):
        """Create a new TaskManager.

        Acquire a lock on a node. The lock can be either shared or
        exclusive. Shared locks may be used for read-only or
        non-disruptive actions only, and must be considerate to what
        other threads may be doing on the same node at the same time.

        :param context: request context
        :param node_id: ID or UUID of node to lock.
        :param shared: Boolean indicating whether to take a shared or exclusive
                       lock. Default: False.
        :param purpose: human-readable purpose to put to debug logs.
        :param retry: whether to retry locking if it fails. Default: True.
        :param patient: whether to indefinitely retry locking if it fails.
                        Set this to True if there is an operation that does not
                        have any fallback or built-in retry mechanism, such as
                        finalizing a state transition during deploy/clean.
                        The default retry behavior is to retry a configured
                        number of times and then give up. Default: False.
        :param load_driver: whether to load the ``driver`` object. Set this to
                            False if loading the driver is undesired or
                            impossible.
        :raises: DriverNotFound
        :raises: InterfaceNotFoundInEntrypoint
        :raises: NodeNotFound
        :raises: NodeLocked

        """

        self._spawn_method = None
        self._on_error_method = None

        self.context = context
        self._node = None
        self._ports = None
        self._portgroups = None
        self._volume_connectors = None
        self._volume_targets = None
        self.node_id = node_id
        self.shared = shared
        self._retry = retry
        self._patient = patient

        self.fsm = states.machine.copy()
        self._purpose = purpose
        self._debug_timer = timeutils.StopWatch()

        # states and event for notification
        self._prev_provision_state = None
        self._prev_target_provision_state = None
        self._event = None
        self._saved_node = None

        try:
            node = objects.Node.get(context, node_id)
            LOG.debug("Attempting to get %(type)s lock on node %(node)s (for "
                      "%(purpose)s)",
                      {'type': 'shared' if shared else 'exclusive',
                       'node': node.uuid, 'purpose': purpose})
            if not self.shared:
                self._lock()
            else:
                self._debug_timer.restart()
                self.node = node

            if load_driver:
                self.driver = driver_factory.build_driver_for_task(self)
            else:
                self.driver = None

        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()

    @property
    def node(self):
        return self._node

    @node.setter
    def node(self, node):
        self._node = node
        if node is not None:
            self.fsm.initialize(start_state=self.node.provision_state,
                                target_state=self.node.target_provision_state)

    @property
    def ports(self):
        try:
            if self._ports is None:
                self._ports = objects.Port.list_by_node_id(self.context,
                                                           self.node.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()
        return self._ports

    @ports.setter
    def ports(self, ports):
        self._ports = ports

    @property
    def portgroups(self):
        try:
            if self._portgroups is None:
                self._portgroups = objects.Portgroup.list_by_node_id(
                    self.context, self.node.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()
        return self._portgroups

    @portgroups.setter
    def portgroups(self, portgroups):
        self._portgroups = portgroups

    @property
    def volume_connectors(self):
        try:
            if self._volume_connectors is None:
                self._volume_connectors = \
                    objects.VolumeConnector.list_by_node_id(
                        self.context, self.node.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()
        return self._volume_connectors

    @volume_connectors.setter
    def volume_connectors(self, volume_connectors):
        self._volume_connectors = volume_connectors

    @property
    def volume_targets(self):
        try:
            if self._volume_targets is None:
                self._volume_targets = objects.VolumeTarget.list_by_node_id(
                    self.context, self.node.id)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.release_resources()
        return self._volume_targets

    @volume_targets.setter
    def volume_targets(self, volume_targets):
        self._volume_targets = volume_targets

    def load_driver(self):
        if self.driver is None:
            self.driver = driver_factory.build_driver_for_task(self)

    def _lock(self):
        self._debug_timer.restart()

        if self._patient:
            stop_after = tenacity.stop_never
        elif self._retry:
            stop_after = tenacity.stop_after_attempt(
                CONF.conductor.node_locked_retry_attempts)
        else:
            stop_after = tenacity.stop_after_attempt(1)

        # NodeLocked exceptions can be annoying. Let's try to alleviate
        # some of that pain by retrying our lock attempts.
        @tenacity.retry(
            retry=tenacity.retry_if_exception_type(exception.NodeLocked),
            stop=stop_after,
            wait=tenacity.wait_fixed(
                CONF.conductor.node_locked_retry_interval),
            reraise=True)
        def reserve_node():
            self.node = objects.Node.reserve(self.context, CONF.host,
                                             self.node_id)
            LOG.debug("Node %(node)s successfully reserved for %(purpose)s "
                      "(took %(time).2f seconds)",
                      {'node': self.node.uuid, 'purpose': self._purpose,
                       'time': self._debug_timer.elapsed()})
            self._debug_timer.restart()

        reserve_node()

    def upgrade_lock(self, purpose=None, retry=None):
        """Upgrade a shared lock to an exclusive lock.

        Also reloads node object from the database.
        If lock is already exclusive only changes the lock purpose
        when provided with one.

        :param purpose: optionally change the purpose of the lock
        :param retry: whether to retry locking if it fails, the
            class-level value is used by default
        :raises: NodeLocked if an exclusive lock remains on the node after
                            "node_locked_retry_attempts"
        """
        if purpose is not None:
            self._purpose = purpose
        if retry is not None:
            self._retry = retry

        if self.shared:
            LOG.debug('Upgrading shared lock on node %(uuid)s for %(purpose)s '
                      'to an exclusive one (shared lock was held %(time).2f '
                      'seconds)',
                      {'uuid': self.node.uuid, 'purpose': self._purpose,
                       'time': self._debug_timer.elapsed()})
            self._lock()
            self.shared = False

    def spawn_after(self, _spawn_method, *args, **kwargs):
        """Call this to spawn a thread to complete the task.

        The specified method will be called when the TaskManager instance
        exits.

        :param _spawn_method: a method that returns a GreenThread object
        :param args: args passed to the method.
        :param kwargs: additional kwargs passed to the method.

        """
        self._spawn_method = _spawn_method
        self._spawn_args = args
        self._spawn_kwargs = kwargs

    def set_spawn_error_hook(self, _on_error_method, *args, **kwargs):
        """Create a hook to handle exceptions when spawning a task.

        Create a hook that gets called upon an exception being raised
        from spawning a background thread to do a task.

        :param _on_error_method: a callable object, it's first parameter
            should accept the Exception object that was raised.
        :param args: additional args passed to the callable object.
        :param kwargs: additional kwargs passed to the callable object.

        """
        self._on_error_method = _on_error_method
        self._on_error_args = args
        self._on_error_kwargs = kwargs

    def downgrade_lock(self):
        """Downgrade the lock to a shared one."""
        if self.node is None:
            raise RuntimeError("Cannot downgrade an already released lock")

        if not self.shared:
            objects.Node.release(self.context, CONF.host, self.node.id)
            self.shared = True
            self.node.refresh()
            LOG.debug("Successfully downgraded lock for %(purpose)s "
                      "on node %(node)s",
                      {'purpose': self._purpose, 'node': self.node.uuid})

    def release_resources(self):
        """Unlock a node and release resources.

        If an exclusive lock is held, unlock the node. Reset attributes
        to make it clear that this instance of TaskManager should no
        longer be accessed.
        """

        if not self.shared:
            try:
                if self.node:
                    objects.Node.release(self.context, CONF.host, self.node.id)
            except exception.NodeNotFound:
                # squelch the exception if the node was deleted
                # within the task's context.
                pass
        if self.node:
            LOG.debug("Successfully released %(type)s lock for %(purpose)s "
                      "on node %(node)s (lock was held %(time).2f sec)",
                      {'type': 'shared' if self.shared else 'exclusive',
                       'purpose': self._purpose, 'node': self.node.uuid,
                       'time': self._debug_timer.elapsed()})
        self.node = None
        self.driver = None
        self.ports = None
        self.portgroups = None
        self.volume_connectors = None
        self.volume_targets = None
        self.fsm = None

    def _write_exception(self, future):
        """Set node last_error if exception raised in thread."""
        node = self.node
        # do not rewrite existing error
        if node and node.last_error is None:
            method = self._spawn_args[0].__name__
            try:
                exc = future.exception()
            except futurist.CancelledError:
                LOG.exception("Execution of %(method)s for node %(node)s "
                              "was canceled.", {'method': method,
                                                'node': node.uuid})
            else:
                if exc is not None:
                    msg = _("Async execution of %(method)s failed with error: "
                            "%(error)s") % {'method': method,
                                            'error': str(exc)}
                    node.last_error = msg
                    try:
                        node.save()
                    except exception.NodeNotFound:
                        pass

    def _notify_provision_state_change(self):
        """Emit notification about change of the node provision state."""
        if self._event is None:
            return

        if self.node is None:
            # Rare case if resource released before notification
            task = copy.copy(self)
            task.fsm = states.machine.copy()
            task.node = self._saved_node
        else:
            task = self

        node = task.node

        state = node.provision_state
        prev_state = self._prev_provision_state
        new_unstable = state in states.UNSTABLE_STATES
        prev_unstable = prev_state in states.UNSTABLE_STATES
        level = fields.NotificationLevel.INFO

        if self._event in ('fail', 'error'):
            status = fields.NotificationStatus.ERROR
            level = fields.NotificationLevel.ERROR
        elif (prev_unstable, new_unstable) == (False, True):
            status = fields.NotificationStatus.START
        elif (prev_unstable, new_unstable) == (True, False):
            status = fields.NotificationStatus.END
        else:
            status = fields.NotificationStatus.SUCCESS

        notify.emit_provision_set_notification(
            task, level, status, self._prev_provision_state,
            self._prev_target_provision_state, self._event)

        # reset saved event, avoiding duplicate notification
        self._event = None

    def _thread_release_resources(self, fut):
        """Thread callback to release resources."""
        try:
            self._write_exception(fut)
        finally:
            self.release_resources()

    def process_event(self, event, callback=None, call_args=None,
                      call_kwargs=None, err_handler=None, target_state=None):
        """Process the given event for the task's current state.

        :param event: the name of the event to process
        :param callback: optional callback to invoke upon event transition
        :param call_args: optional args to pass to the callback method
        :param call_kwargs: optional kwargs to pass to the callback method
        :param err_handler: optional error handler to invoke if the
                callback fails, eg. because there are no workers available
                (err_handler should accept arguments node, prev_prov_state, and
                prev_target_state)
        :param target_state: if specified, the target provision state for the
               node. Otherwise, use the target state from the fsm
        :raises: InvalidState if the event is not allowed by the associated
                 state machine
        """
        # save previous states and event
        self._prev_provision_state = self.node.provision_state
        self._prev_target_provision_state = self.node.target_provision_state
        self._event = event

        # Advance the state model for the given event. Note that this doesn't
        # alter the node in any way. This may raise InvalidState, if this event
        # is not allowed in the current state.
        self.fsm.process_event(event, target_state=target_state)

        # stash current states in the error handler if callback is set,
        # in case we fail to get a worker from the pool
        if err_handler and callback:
            self.set_spawn_error_hook(err_handler, self.node,
                                      self.node.provision_state,
                                      self.node.target_provision_state)

        self.node.provision_state = self.fsm.current_state

        # NOTE(lucasagomes): If there's no extra processing
        # (callback) and we've moved to a stable state, make sure the
        # target_provision_state is cleared
        if not callback and self.fsm.is_stable(self.node.provision_state):
            self.node.target_provision_state = states.NOSTATE
        else:
            self.node.target_provision_state = self.fsm.target_state

        # set up the async worker
        if callback:
            # clear the error if we're going to start work in a callback
            self.node.last_error = None
            if call_args is None:
                call_args = ()
            if call_kwargs is None:
                call_kwargs = {}
            self.spawn_after(callback, *call_args, **call_kwargs)

        # publish the state transition by saving the Node
        self.node.save()

        log_message = ('Node %(node)s moved to provision state "%(state)s" '
                       'from state "%(previous)s"; target provision state is '
                       '"%(target)s"' %
                       {'node': self.node.uuid,
                        'state': self.node.provision_state,
                        'target': self.node.target_provision_state,
                        'previous': self._prev_provision_state})

        if (self.node.provision_state.endswith('failed')
                or self.node.provision_state == 'error'):
            LOG.error(log_message)
        else:
            LOG.info(log_message)

        if callback is None:
            self._notify_provision_state_change()
        else:
            # save the node, in case it is released before a notification is
            # emitted at __exit__().
            self._saved_node = self.node

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
            fut = None
            try:
                fut = self._spawn_method(*self._spawn_args,
                                         **self._spawn_kwargs)

                # NOTE(comstud): Trying to use a lambda here causes
                # the callback to not occur for some reason. This
                # also makes it easier to test.
                fut.add_done_callback(self._thread_release_resources)
                # Don't unlock! The unlock will occur when the
                # thread finishes.
                # NOTE(yuriyz): A race condition with process_event()
                # in callback is possible here if eventlet changes behavior.
                # E.g., if the execution of the new thread (that handles the
                # event processing) finishes before we get here, that new
                # thread may emit the "end" notification before we emit the
                # following "start" notification.
                self._notify_provision_state_change()
                return
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    try:
                        # Execute the on_error hook if set
                        if self._on_error_method:
                            self._on_error_method(e, *self._on_error_args,
                                                  **self._on_error_kwargs)
                    except Exception:
                        LOG.warning("Task's on_error hook failed to "
                                    "call %(method)s on node %(node)s",
                                    {'method': self._on_error_method.__name__,
                                     'node': self.node.uuid})

                    if fut is not None:
                        # This means the add_done_callback() failed for some
                        # reason. Nuke the thread.
                        fut.cancel()
                    self.release_resources()
        self.release_resources()
