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

from eventlet import greenpool
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_context import context as ironic_context
from oslo_db import exception as db_exception
from oslo_log import log
from oslo_service import periodic_task
from oslo_utils import excutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import hash_ring as hash
from ironic.common.i18n import _
from ironic.common.i18n import _LC
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import rpc
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as dbapi


conductor_opts = [
    cfg.IntOpt('workers_pool_size',
               default=100,
               help=_('The size of the workers greenthread pool.')),
    cfg.IntOpt('heartbeat_interval',
               default=10,
               help=_('Seconds between conductor heart beats.')),
]


CONF = cfg.CONF
CONF.register_opts(conductor_opts, 'conductor')
LOG = log.getLogger(__name__)
WORKER_SPAWN_lOCK = "conductor_worker_spawn"


class BaseConductorManager(periodic_task.PeriodicTasks):

    def __init__(self, host, topic):
        super(BaseConductorManager, self).__init__(CONF)
        if not host:
            host = CONF.host
        self.host = host
        self.topic = topic
        self.notifier = rpc.get_notifier()

    def _get_driver(self, driver_name):
        """Get the driver.

        :param driver_name: name of the driver.
        :returns: the driver; an instance of a class which implements
                  :class:`ironic.drivers.base.BaseDriver`.
        :raises: DriverNotFound if the driver is not loaded.

        """
        try:
            return self._driver_factory[driver_name].obj
        except KeyError:
            raise exception.DriverNotFound(driver_name=driver_name)

    def init_host(self):
        self.dbapi = dbapi.get_instance()

        self._keepalive_evt = threading.Event()
        """Event for the keepalive thread."""

        self._worker_pool = greenpool.GreenPool(
            size=CONF.conductor.workers_pool_size)
        """GreenPool of background workers for performing tasks async."""

        self.ring_manager = hash.HashRingManager()
        """Consistent hash ring which maps drivers to conductors."""

        # NOTE(deva): instantiating DriverFactory may raise DriverLoadError
        #             or DriverNotFound
        self._driver_factory = driver_factory.DriverFactory()
        """Driver factory loads all enabled drivers."""

        self.drivers = self._driver_factory.names
        """List of driver names which this conductor supports."""

        if not self.drivers:
            msg = _LE("Conductor %s cannot be started because no drivers "
                      "were loaded.  This could be because no drivers were "
                      "specified in 'enabled_drivers' config option.")
            LOG.error(msg, self.host)
            raise exception.NoDriversLoaded(conductor=self.host)

        # Collect driver-specific periodic tasks
        for driver_obj in driver_factory.drivers().values():
            self._collect_periodic_tasks(driver_obj)
            for iface_name in (driver_obj.core_interfaces +
                               driver_obj.standard_interfaces +
                               ['vendor']):
                iface = getattr(driver_obj, iface_name, None)
                if iface:
                    self._collect_periodic_tasks(iface)

        # clear all locks held by this conductor before registering
        self.dbapi.clear_node_reservations_for_conductor(self.host)
        try:
            # Register this conductor with the cluster
            cdr = self.dbapi.register_conductor({'hostname': self.host,
                                                 'drivers': self.drivers})
        except exception.ConductorAlreadyRegistered:
            # This conductor was already registered and did not shut down
            # properly, so log a warning and update the record.
            LOG.warning(
                _LW("A conductor with hostname %(hostname)s "
                    "was previously registered. Updating registration"),
                {'hostname': self.host})
            cdr = self.dbapi.register_conductor({'hostname': self.host,
                                                 'drivers': self.drivers},
                                                update_existing=True)
        self.conductor = cdr

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

    def _collect_periodic_tasks(self, obj):
        for n, method in inspect.getmembers(obj, inspect.ismethod):
            if getattr(method, '_periodic_enabled', False):
                self.add_periodic_task(method)

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
                self.dbapi.unregister_conductor(self.host)
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
        self._worker_pool.waitall()

    def periodic_tasks(self, context, raise_on_error=False):
        """Periodic tasks are run at pre-specified interval."""
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

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

    @lockutils.synchronized(WORKER_SPAWN_lOCK, 'ironic-')
    def _spawn_worker(self, func, *args, **kwargs):

        """Create a greenthread to run func(*args, **kwargs).

        Spawns a greenthread if there are free slots in pool, otherwise raises
        exception. Execution control returns immediately to the caller.

        :returns: GreenThread object.
        :raises: NoFreeConductorWorker if worker pool is currently full.

        """
        if self._worker_pool.free():
            return self._worker_pool.spawn(func, *args, **kwargs)
        else:
            raise exception.NoFreeConductorWorker()

    def _conductor_service_record_keepalive(self):
        while not self._keepalive_evt.is_set():
            try:
                self.dbapi.touch_conductor(self.host)
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
                          err_handler=None, last_error=None):
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

                    # timeout has been reached - process the event 'fail'
                    if callback_method:
                        task.process_event('fail',
                                           callback=self._spawn_worker,
                                           call_args=(callback_method, task),
                                           err_handler=err_handler)
                    else:
                        task.node.last_error = last_error
                        task.process_event('fail')
            except exception.NoFreeConductorWorker:
                break
            except (exception.NodeLocked, exception.NodeNotFound):
                continue
            workers_count += 1
            if workers_count >= CONF.conductor.periodic_max_workers:
                break
