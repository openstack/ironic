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

"""Conductor periodics."""

import collections
import functools
import inspect
import time

from futurist import periodics
from oslo_log import log

from ironic.common import exception
from ironic.common import metrics_utils
from ironic.conductor import base_manager
from ironic.conductor import task_manager
from ironic.drivers import base as driver_base


LOG = log.getLogger(__name__)


METRICS = metrics_utils.get_metrics_logger(__name__)


def refresh_periodic_attributes(func):
    """Update futurist periodic attributes from deferred CONF resolvers.

    Used for periodics whose ``enabled`` or ``spacing`` were supplied as
    callables so that values are read after configuration is loaded (for
    example in oslo.service spawn workers, which bypass the LP #1562258
    import-order guard in ``ironic.command.conductor``).
    """
    target = getattr(func, '__func__', func)
    target_dict = getattr(target, '__dict__', {})
    enabled_resolver = target_dict.get('_periodic_enabled_resolver')
    spacing_resolver = target_dict.get('_periodic_spacing_resolver')
    if not enabled_resolver and not spacing_resolver:
        return False

    spacing = target_dict.get('_periodic_spacing',
                              getattr(target, '_periodic_spacing', None))
    if spacing_resolver is not None:
        spacing = spacing_resolver()
        target._periodic_spacing = spacing

    if enabled_resolver is not None:
        target._is_periodic = bool(enabled_resolver()) and spacing > 0
    elif spacing_resolver is not None:
        target._is_periodic = spacing > 0

    return True


def refresh_class_periodic_attributes(cls):
    """Refresh lazy periodic attributes on all periodic methods of ``cls``."""
    for _name, member in inspect.getmembers(cls):
        if periodics.is_periodic(member):
            refresh_periodic_attributes(member)


def periodic(spacing, enabled=True, **kwargs):
    """A decorator to define a periodic task.

    :param spacing: how often (in seconds) to run the periodic task, or a
        callable returning the spacing in seconds.
    :param enabled: whether the task is enabled; defaults to ``spacing > 0``.
        May be a callable returning a boolean, in which case it is evaluated
        when periodic tasks are collected (and after spawn unpickling when
        configuration has been restored).
    """
    lazy_enabled = callable(enabled)
    lazy_spacing = callable(spacing)

    if not lazy_enabled and not lazy_spacing:
        return periodics.periodic(spacing=spacing,
                                  enabled=enabled and spacing > 0,
                                  **kwargs)

    def decorator(func):
        # Placeholder registration; refresh_periodic_attributes() sets real
        # spacing and _is_periodic before the PeriodicWorker is created.
        decorated = periodics.periodic(spacing=1, enabled=False,
                                       **kwargs)(func)
        if lazy_enabled:
            decorated._periodic_enabled_resolver = enabled
        if lazy_spacing:
            decorated._periodic_spacing_resolver = spacing
        return decorated

    return decorator


class Stop(Exception):
    """A signal to stop the current iteration of a periodic task."""


def node_periodic(purpose, spacing, enabled=True, filters=None,
                  predicate=None, predicate_extra_fields=(), limit=None,
                  shared_task=True, node_count_metric_name=None):
    """A decorator to define a periodic task to act on nodes.

    Defines a periodic task that fetches the list of nodes mapped to the
    current conductor which satisfy the provided filters.

    The decorated function must be a method on either the conductor manager
    or a hardware interface. The signature is:

    * for conductor manager: ``(self, task, context)``
    * for hardware interfaces: ``(self, task, manager, context)``.

    When the periodic is running on a hardware interface, only tasks
    using this interface are considered.

    ``NodeNotFound`` and ``NodeLocked`` exceptions are ignored. Raise ``Stop``
    to abort the current iteration of the task and reschedule it.

    :param purpose: a human-readable description of the activity, e.g.
        "verifying that the cat is purring".
    :param spacing: how often (in seconds) to run the periodic task.
    :param enabled: whether the task is enabled; defaults to ``spacing > 0``.
    :param filters: database-level filters for the nodes.
    :param predicate: a callable to run on the fetched nodes *before* creating
        a task for them. The only parameter will be a named tuple with fields
        ``uuid``, ``driver``, ``conductor_group`` plus everything from
        ``predicate_extra_fields``. If the callable accepts a 2nd parameter,
        it will be the conductor manager instance.
    :param predicate_extra_fields: extra fields to fetch on the initial
        request and pass into the ``predicate``. Must not contain ``uuid``,
        ``driver`` and ``conductor_group`` since they are always included.
    :param limit: how many nodes to process before stopping the current
        iteration. If ``predicate`` returns ``False``, the node is not counted.
        If the decorated function returns ``False``, the node is not counted
        either. Can be a callable, in which case it will be called on each
        iteration to determine the limit.
    :param shared_task: if ``True``, the task will have a shared lock. It is
        recommended to start with a shared lock and upgrade it only if needed.
    :param node_count_metric_name: A string value to identify a metric
        representing the count of matching nodes to be recorded upon the
        completion of the periodic.
    """
    node_type = collections.namedtuple(
        'Node',
        ['uuid', 'driver', 'conductor_group'] + list(predicate_extra_fields)
    )

    # Accepting a conductor manager is a bit of an edge case, doing a bit of
    # a signature magic to avoid passing it everywhere.
    accepts_manager = (predicate is not None
                       and len(inspect.signature(predicate).parameters) > 1)

    def decorator(func):
        @periodic(spacing=spacing, enabled=enabled)
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            # Make it work with both drivers and the conductor manager
            if isinstance(self, base_manager.BaseConductorManager):
                manager = self
                context = args[0]
            else:
                manager = args[0]
                context = args[1]

            interface_type = (getattr(self, 'interface_type', None)
                              if isinstance(self, driver_base.BaseInterface)
                              else None)

            if callable(limit):
                local_limit = limit()
            else:
                local_limit = limit
            assert local_limit is None or local_limit > 0
            node_count = 0
            nodes = manager.iter_nodes(filters=filters,
                                       fields=predicate_extra_fields)
            for (node_uuid, *other) in nodes:
                node_count += 1
                if predicate is not None:
                    node = node_type(node_uuid, *other)
                    if accepts_manager:
                        result = predicate(node, manager)
                    else:
                        result = predicate(node)
                    if not result:
                        continue

                try:
                    with task_manager.acquire(context, node_uuid,
                                              purpose=purpose,
                                              shared=shared_task) as task:
                        if interface_type is not None:
                            impl = getattr(task.driver, interface_type)
                            if not isinstance(impl, self.__class__):
                                continue

                        result = func(self, task, *args, **kwargs)
                except exception.NodeNotFound:
                    LOG.info("During %(action)s, node %(node)s was not found "
                             "and presumed deleted by another process.",
                             {'node': node_uuid, 'action': purpose})
                except exception.NodeLocked:
                    LOG.info("During %(action)s, node %(node)s was already "
                             "locked by another process. Skip.",
                             {'node': node_uuid, 'action': purpose})
                except Stop:
                    break
                finally:
                    # Yield on every iteration
                    time.sleep(0)

                if (local_limit is not None
                        and (result is None or result)):
                    local_limit -= 1
                    if not local_limit:
                        return
            if node_count_metric_name:
                # Send post-run metrics.
                METRICS.send_gauge(
                    node_count_metric_name,
                    node_count)
            LOG.debug('Completed periodic task for purpose %s.', purpose)

        return wrapper

    return decorator
