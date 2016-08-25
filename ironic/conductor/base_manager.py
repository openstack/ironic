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

"""Base conductor manager functionality."""

import inspect
import threading

import eventlet
import futurist
from futurist import periodics
from futurist import rejection
from oslo_db import exception as db_exception
from oslo_log import log
from oslo_utils import excutils

from ironic.common import context as ironic_context
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import hash_ring as hash
from ironic.common.i18n import _, _LC, _LE, _LI, _LW
from ironic.common import rpc
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.db import api as dbapi
from ironic import objects


LOG = log.getLogger(__name__)


class BaseConductorManager(object):

    def __init__(self, host, topic):
        super(BaseConductorManager, self).__init__()
        if not host:
            host = CONF.host
        self.host = host
        self.topic = topic
        self.sensors_notifier = rpc.get_sensors_notifier()
        self._started = False

    def init_host(self, admin_context=None):
        """Initialize the conductor host.

        :param admin_context: the admin context to pass to periodic tasks.
        :raises: RuntimeError when conductor is already running.
        :raises: NoDriversLoaded when no drivers are enabled on the conductor.
        :raises: DriverNotFound if a driver is enabled that does not exist.
        :raises: DriverLoadError if an enabled driver cannot be loaded.
        """
        if self._started:
            raise RuntimeError(_('Attempt to start an already running '
                                 'conductor manager'))

        self.dbapi = dbapi.get_instance()

        self._keepalive_evt = threading.Event()
        """Event for the keepalive thread."""

        # TODO(dtantsur): make the threshold configurable?
        rejection_func = rejection.reject_when_reached(
            CONF.conductor.workers_pool_size)
        self._executor = futurist.GreenThreadPoolExecutor(
            max_workers=CONF.conductor.workers_pool_size,
            check_and_reject=rejection_func)
        """Executor for performing tasks async."""

        self.ring_manager = hash.HashRingManager()
        """Consistent hash ring which maps drivers to conductors."""

        # NOTE(deva): these calls may raise DriverLoadError or DriverNotFound
        # NOTE(vdrok): instantiate network interface factory on startup so that
        # all the network interfaces are loaded at the very beginning, and
        # failures prevent the conductor from starting.
        drivers = driver_factory.drivers()
        driver_factory.NetworkInterfaceFactory()
        if not drivers:
            msg = _LE("Conductor %s cannot be started because no drivers "
                      "were loaded.  This could be because no drivers were "
                      "specified in 'enabled_drivers' config option.")
            LOG.error(msg, self.host)
            raise exception.NoDriversLoaded(conductor=self.host)

        # NOTE(jroll) this is passed to the dbapi, which requires a list, not
        # a generator (which keys() returns in py3)
        driver_names = list(drivers)

        # Collect driver-specific periodic tasks.
        # Conductor periodic tasks accept context argument, driver periodic
        # tasks accept this manager and context. We have to ensure that the
        # same driver interface class is not traversed twice, otherwise
        # we'll have several instances of the same task.
        LOG.debug('Collecting periodic tasks')
        self._periodic_task_callables = []
        periodic_task_classes = set()
        self._collect_periodic_tasks(self, (admin_context,))
        for driver_obj in drivers.values():
            # TODO(dtantsur): collecting tasks from driver objects is
            # deprecated and should be removed in Ocata.
            self._collect_periodic_tasks(driver_obj, (self, admin_context))
            for iface_name in driver_obj.all_interfaces:
                iface = getattr(driver_obj, iface_name, None)
                if iface and iface.__class__ not in periodic_task_classes:
                    self._collect_periodic_tasks(iface, (self, admin_context))
                    periodic_task_classes.add(iface.__class__)

        if (len(self._periodic_task_callables) >
                CONF.conductor.workers_pool_size):
            LOG.warning(_LW('This conductor has %(tasks)d periodic tasks '
                            'enabled, but only %(workers)d task workers '
                            'allowed by [conductor]workers_pool_size option'),
                        {'tasks': len(self._periodic_task_callables),
                         'workers': CONF.conductor.workers_pool_size})

        self._periodic_tasks = periodics.PeriodicWorker(
            self._periodic_task_callables,
            executor_factory=periodics.ExistingExecutor(self._executor))

        # clear all target_power_state with locks by this conductor
        self.dbapi.clear_node_target_power_state(self.host)
        # clear all locks held by this conductor before registering
        self.dbapi.clear_node_reservations_for_conductor(self.host)
        try:
            # Register this conductor with the cluster
            self.conductor = objects.Conductor.register(
                admin_context, self.host, driver_names)
        except exception.ConductorAlreadyRegistered:
            # This conductor was already registered and did not shut down
            # properly, so log a warning and update the record.
            LOG.warning(
                _LW("A conductor with hostname %(hostname)s "
                    "was previously registered. Updating registration"),
                {'hostname': self.host})
            self.conductor = objects.Conductor.register(
                admin_context, self.host, driver_names, update_existing=True)

        # Start periodic tasks
        self._periodic_tasks_worker = self._executor.submit(
            self._periodic_tasks.start, allow_empty=True)
        self._periodic_tasks_worker.add_done_callback(
            self._on_periodic_tasks_stop)

        # NOTE(lucasagomes): If the conductor server dies abruptly
        # mid deployment (OMM Killer, power outage, etc...) we
        # can not resume the deployment even if the conductor
        # comes back online. Cleaning the reservation of the nodes
        # (dbapi.clear_node_reservations_for_conductor) is not enough to
        # unstick it, so let's gracefully fail the deployment so the node
        # can go through the steps (deleting & cleaning) to make itself
        # available again.
        filters = {'reserved': False,
                   'provision_state': states.DEPLOYING}
        last_error = (_("The deployment can't be resumed by conductor "
                        "%s. Moving to fail state.") % self.host)
        self._fail_if_in_state(ironic_context.get_admin_context(), filters,
                               states.DEPLOYING, 'provision_updated_at',
                               last_error=last_error)

        # Start consoles if it set enabled in a greenthread.
        try:
            self._spawn_worker(self._start_consoles,
                               ironic_context.get_admin_context())
        except exception.NoFreeConductorWorker:
            LOG.warning(_LW('Failed to start worker for restarting consoles.'))

        # Spawn a dedicated greenthread for the keepalive
        try:
            self._spawn_worker(self._conductor_service_record_keepalive)
            LOG.info(_LI('Successfully started conductor with hostname '
                         '%(hostname)s.'),
                     {'hostname': self.host})
        except exception.NoFreeConductorWorker:
            with excutils.save_and_reraise_exception():
                LOG.critical(_LC('Failed to start keepalive'))
                self.del_host()

        self._started = True

    def del_host(self, deregister=True):
        # Conductor deregistration fails if called on non-initialized
        # conductor (e.g. when rpc server is unreachable).
        if not hasattr(self, 'conductor'):
            return
        self._keepalive_evt.set()
        if deregister:
            try:
                # Inform the cluster that this conductor is shutting down.
                # Note that rebalancing will not occur immediately, but when
                # the periodic sync takes place.
                self.conductor.unregister()
                LOG.info(_LI('Successfully stopped conductor with hostname '
                             '%(hostname)s.'),
                         {'hostname': self.host})
            except exception.ConductorNotFound:
                pass
        else:
            LOG.info(_LI('Not deregistering conductor with hostname '
                         '%(hostname)s.'),
                     {'hostname': self.host})
        # Waiting here to give workers the chance to finish. This has the
        # benefit of releasing locks workers placed on nodes, as well as
        # having work complete normally.
        self._periodic_tasks.stop()
        self._periodic_tasks.wait()
        self._executor.shutdown(wait=True)
        self._started = False

    def _collect_periodic_tasks(self, obj, args):
        """Collect periodic tasks from a given object.

        Populates self._periodic_task_callables with tuples
        (callable, args, kwargs).

        :param obj: object containing periodic tasks as methods
        :param args: tuple with arguments to pass to every task
        """
        for name, member in inspect.getmembers(obj):
            if periodics.is_periodic(member):
                LOG.debug('Found periodic task %(owner)s.%(member)s',
                          {'owner': obj.__class__.__name__,
                           'member': name})
                self._periodic_task_callables.append((member, args, {}))

    def _on_periodic_tasks_stop(self, fut):
        try:
            fut.result()
        except Exception as exc:
            LOG.critical(_LC('Periodic tasks worker has failed: %s'), exc)
        else:
            LOG.info(_LI('Successfully shut down periodic tasks'))

    def iter_nodes(self, fields=None, **kwargs):
        """Iterate over nodes mapped to this conductor.

        Requests node set from and filters out nodes that are not
        mapped to this conductor.

        Yields tuples (node_uuid, driver, ...) where ... is derived from
        fields argument, e.g.: fields=None means yielding ('uuid', 'driver'),
        fields=['foo'] means yielding ('uuid', 'driver', 'foo').

        :param fields: list of fields to fetch in addition to uuid and driver
        :param kwargs: additional arguments to pass to dbapi when looking for
                       nodes
        :return: generator yielding tuples of requested fields
        """
        columns = ['uuid', 'driver'] + list(fields or ())
        node_list = self.dbapi.get_nodeinfo_list(columns=columns, **kwargs)
        for result in node_list:
            if self._mapped_to_this_conductor(*result[:2]):
                yield result

    def _spawn_worker(self, func, *args, **kwargs):

        """Create a greenthread to run func(*args, **kwargs).

        Spawns a greenthread if there are free slots in pool, otherwise raises
        exception. Execution control returns immediately to the caller.

        :returns: Future object.
        :raises: NoFreeConductorWorker if worker pool is currently full.

        """
        try:
            return self._executor.submit(func, *args, **kwargs)
        except futurist.RejectedSubmission:
            raise exception.NoFreeConductorWorker()

    def _conductor_service_record_keepalive(self):
        while not self._keepalive_evt.is_set():
            try:
                self.conductor.touch()
            except db_exception.DBConnectionError:
                LOG.warning(_LW('Conductor could not connect to database '
                                'while heartbeating.'))
            self._keepalive_evt.wait(CONF.conductor.heartbeat_interval)

    def _mapped_to_this_conductor(self, node_uuid, driver):
        """Check that node is mapped to this conductor.

        Note that because mappings are eventually consistent, it is possible
        for two conductors to simultaneously believe that a node is mapped to
        them. Any operation that depends on exclusive control of a node should
        take out a lock.
        """
        try:
            ring = self.ring_manager[driver]
        except exception.DriverNotFound:
            return False

        return self.host in ring.get_hosts(node_uuid)

    def _fail_if_in_state(self, context, filters, provision_state,
                          sort_key, callback_method=None,
                          err_handler=None, last_error=None,
                          keep_target_state=False):
        """Fail nodes that are in specified state.

        Retrieves nodes that satisfy the criteria in 'filters'.
        If any of these nodes is in 'provision_state', it has failed
        in whatever provisioning activity it was currently doing.
        That failure is processed here.

        :param: context: request context
        :param: filters: criteria (as a dictionary) to get the desired
                         list of nodes that satisfy the filter constraints.
                         For example, if filters['provisioned_before'] = 60,
                         this would process nodes whose provision_updated_at
                         field value was 60 or more seconds before 'now'.
        :param: provision_state: provision_state that the node is in,
                                 for the provisioning activity to have failed.
        :param: sort_key: the nodes are sorted based on this key.
        :param: callback_method: the callback method to be invoked in a
                                 spawned thread, for a failed node. This
                                 method must take a :class:`TaskManager` as
                                 the first (and only required) parameter.
        :param: err_handler: for a failed node, the error handler to invoke
                             if an error occurs trying to spawn an thread
                             to do the callback_method.
        :param: last_error: the error message to be updated in node.last_error
        :param: keep_target_state: if True, a failed node will keep the same
                                   target provision state it had before the
                                   failure. Otherwise, the node's target
                                   provision state will be determined by the
                                   fsm.

        """
        node_iter = self.iter_nodes(filters=filters,
                                    sort_key=sort_key,
                                    sort_dir='asc')

        workers_count = 0
        for node_uuid, driver in node_iter:
            try:
                with task_manager.acquire(context, node_uuid,
                                          purpose='node state check') as task:
                    if (task.node.maintenance or
                            task.node.provision_state != provision_state):
                        continue

                    target_state = (None if not keep_target_state else
                                    task.node.target_provision_state)

                    # timeout has been reached - process the event 'fail'
                    if callback_method:
                        task.process_event('fail',
                                           callback=self._spawn_worker,
                                           call_args=(callback_method, task),
                                           err_handler=err_handler,
                                           target_state=target_state)
                    else:
                        task.node.last_error = last_error
                        task.process_event('fail', target_state=target_state)
            except exception.NoFreeConductorWorker:
                break
            except (exception.NodeLocked, exception.NodeNotFound):
                continue
            workers_count += 1
            if workers_count >= CONF.conductor.periodic_max_workers:
                break

    def _start_consoles(self, context):
        """Start consoles if set enabled.

        :param: context: request context
        """
        filters = {'console_enabled': True}

        node_iter = self.iter_nodes(filters=filters)

        for node_uuid, driver in node_iter:
            try:
                with task_manager.acquire(context, node_uuid, shared=False,
                                          purpose='start console') as task:
                    try:
                        LOG.debug('Trying to start console of node %(node)s',
                                  {'node': node_uuid})
                        task.driver.console.start_console(task)
                        LOG.info(_LI('Successfully started console of node '
                                     '%(node)s'), {'node': node_uuid})
                    except Exception as err:
                        msg = (_('Failed to start console of node %(node)s '
                                 'while starting the conductor, so changing '
                                 'the console_enabled status to False, error: '
                                 '%(err)s')
                               % {'node': node_uuid, 'err': err})
                        LOG.error(msg)
                        # If starting console failed, set node console_enabled
                        # back to False and set node's last error.
                        task.node.last_error = msg
                        task.node.console_enabled = False
                        task.node.save()
            except exception.NodeLocked:
                LOG.warning(_LW('Node %(node)s is locked while trying to '
                                'start console on conductor startup'),
                            {'node': node_uuid})
                continue
            except exception.NodeNotFound:
                LOG.warning(_LW("During starting console on conductor "
                                "startup, node %(node)s was not found"),
                            {'node': node_uuid})
                continue
            finally:
                # Yield on every iteration
                eventlet.sleep(0)
