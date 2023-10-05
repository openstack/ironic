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

import copy
import inspect
import threading

import eventlet
import futurist
from futurist import periodics
from futurist import rejection
from ironic_lib import mdns
from oslo_db import exception as db_exception
from oslo_log import log
from oslo_utils import excutils
from oslo_utils import netutils
from oslo_utils import versionutils

from ironic.common import context as ironic_context
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import hash_ring
from ironic.common.i18n import _
from ironic.common import release_mappings as versions
from ironic.common import rpc
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import allocations
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.conf import CONF
from ironic.db import api as dbapi
from ironic.drivers.modules import deploy_utils
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic import version

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
        self._shutdown = None
        self._zeroconf = None
        self.dbapi = None

    def prepare_host(self):
        """Prepares host for initialization

        Prepares the conductor for basic operation by removing any existing
        transitory node power states and reservations which were previously
        held by this host.

        Under normal operation, this is also when the initial database
        connectivity is established for the conductor's normal operation.
        """
        # Determine the hostname to utilize/register
        if (CONF.rpc_transport == 'json-rpc'
                and CONF.json_rpc.port != 8089
                and self._use_jsonrpc_port()):
            # in the event someone configures self.host
            # as an ipv6 address...
            host = netutils.escape_ipv6(self.host)
            self.host = f'{host}:{CONF.json_rpc.port}'

        # NOTE(TheJulia) We need to clear locks early on in the process
        # of starting where the database shows we still hold them.
        # This must be done before we re-register our existence in the
        # conductors table and begin accepting new requests via RPC as
        # if we do not then we may squash our *new* locks from new work.

        if not self.dbapi:
            LOG.debug('Initializing database client for %s.', self.host)
            self.dbapi = dbapi.get_instance()
        LOG.debug('Removing stale locks from the database matching '
                  'this conductor\'s hostname: %s', self.host)
        # clear all target_power_state with locks by this conductor
        self.dbapi.clear_node_target_power_state(self.host)
        # clear all locks held by this conductor before registering
        self.dbapi.clear_node_reservations_for_conductor(self.host)

    def init_host(self, admin_context=None, start_consoles=True,
                  start_allocations=True):
        """Initialize the conductor host.

        :param admin_context: the admin context to pass to periodic tasks.
        :param start_consoles: If consoles should be started in intialization.
        :param start_allocations: If allocations should be started in
                                  initialization.
        :raises: RuntimeError when conductor is already running.
        :raises: NoDriversLoaded when no drivers are enabled on the conductor.
        :raises: DriverNotFound if a driver is enabled that does not exist.
        :raises: DriverLoadError if an enabled driver cannot be loaded.
        :raises: DriverNameConflict if a classic driver and a dynamic driver
                 are both enabled and have the same name.
        """
        if self._started:
            raise RuntimeError(_('Attempt to start an already running '
                                 'conductor manager'))
        self._shutdown = False

        if not self.dbapi:
            self.dbapi = dbapi.get_instance()

        self._keepalive_evt = threading.Event()
        """Event for the keepalive thread."""

        # NOTE(dtantsur): do not allow queuing work. Given our model, it's
        # better to reject an incoming request with HTTP 503 or reschedule
        # a periodic task that end up with hidden backlog that is hard
        # to track and debug. Using 1 instead of 0 because of how things are
        # ordered in futurist (it checks for rejection first).
        rejection_func = rejection.reject_when_reached(1)
        self._executor = futurist.GreenThreadPoolExecutor(
            max_workers=CONF.conductor.workers_pool_size,
            check_and_reject=rejection_func)
        """Executor for performing tasks async."""

        # TODO(jroll) delete the use_groups argument and use the default
        # in Stein.
        self.ring_manager = hash_ring.HashRingManager(
            use_groups=self._use_groups())
        """Consistent hash ring which maps drivers to conductors."""

        # NOTE(tenbrae): these calls may raise DriverLoadError or
        # DriverNotFound
        # NOTE(vdrok): Instantiate network and storage interface factory on
        # startup so that all the interfaces are loaded at the very
        # beginning, and failures prevent the conductor from starting.
        hardware_types = driver_factory.hardware_types()
        driver_factory.NetworkInterfaceFactory()
        driver_factory.StorageInterfaceFactory()

        # NOTE(jroll) this is passed to the dbapi, which requires a list, not
        # a generator (which keys() returns in py3)
        hardware_type_names = list(hardware_types)

        # check that at least one driver is loaded, whether classic or dynamic
        if not hardware_type_names:
            msg = ("Conductor %s cannot be started because no hardware types "
                   "were specified in the 'enabled_hardware_types' config "
                   "option.")
            LOG.error(msg, self.host)
            raise exception.NoDriversLoaded(conductor=self.host)

        self._collect_periodic_tasks(admin_context)

        try:
            # Register this conductor with the cluster
            self.conductor = objects.Conductor.register(
                admin_context, self.host, hardware_type_names,
                CONF.conductor.conductor_group)
        except exception.ConductorAlreadyRegistered:
            # This conductor was already registered and did not shut down
            # properly, so log a warning and update the record.
            LOG.warning("A conductor with hostname %(hostname)s was "
                        "previously registered. Updating registration",
                        {'hostname': self.host})
            self.conductor = objects.Conductor.register(
                admin_context, self.host, hardware_type_names,
                CONF.conductor.conductor_group, update_existing=True)

        # register hardware types and interfaces supported by this conductor
        # and validate them against other conductors
        try:
            self._register_and_validate_hardware_interfaces(hardware_types)
        except (exception.DriverLoadError, exception.DriverNotFound,
                exception.ConductorHardwareInterfacesAlreadyRegistered,
                exception.InterfaceNotFoundInEntrypoint,
                exception.NoValidDefaultForInterface) as e:
            with excutils.save_and_reraise_exception():
                LOG.error('Failed to register hardware types. %s', e)
                self.del_host()

        # Start periodic tasks
        self._periodic_tasks_worker = self._executor.submit(
            self._periodic_tasks.start, allow_empty=True)
        self._periodic_tasks_worker.add_done_callback(
            self._on_periodic_tasks_stop)

        for state in states.STUCK_STATES_TREATED_AS_FAIL:
            self._fail_transient_state(
                state,
                _("The %(state)s state can't be resumed by conductor "
                  "%(host)s. Moving to fail state.") %
                {'state': state, 'host': self.host})

        # Start consoles if it set enabled in a greenthread.
        try:
            if start_consoles:
                self._spawn_worker(self._start_consoles,
                                   ironic_context.get_admin_context())
        except exception.NoFreeConductorWorker:
            LOG.warning('Failed to start worker for restarting consoles.')

        # Spawn a dedicated greenthread for the keepalive
        try:
            self._spawn_worker(self._conductor_service_record_keepalive)
            LOG.info('Successfully started conductor with hostname '
                     '%(hostname)s.',
                     {'hostname': self.host})
        except exception.NoFreeConductorWorker:
            with excutils.save_and_reraise_exception():
                LOG.critical('Failed to start keepalive')
                self.del_host()

        # Resume allocations that started before the restart.
        try:
            if start_allocations:
                self._spawn_worker(self._resume_allocations,
                                   ironic_context.get_admin_context())
        except exception.NoFreeConductorWorker:
            LOG.warning('Failed to start worker for resuming allocations.')

        if CONF.conductor.enable_mdns:
            self._publish_endpoint()

        self._started = True
        LOG.debug('Started Ironic Conductor - %s',
                  version.version_info.release_string())

    def _use_jsonrpc_port(self):
        """Determines if the JSON-RPC port can be used."""
        release_ver = versions.RELEASE_MAPPING.get(CONF.pin_release_version)
        version_cap = (release_ver['rpc'] if release_ver
                       else self.RPC_API_VERSION)
        return versionutils.is_compatible('1.58', version_cap)

    def _use_groups(self):
        release_ver = versions.RELEASE_MAPPING.get(CONF.pin_release_version)
        # NOTE(jroll) self.RPC_API_VERSION is actually defined in a subclass,
        # but we only use this class from there.
        version_cap = (release_ver['rpc'] if release_ver
                       else self.RPC_API_VERSION)
        return versionutils.is_compatible('1.47', version_cap)

    def _fail_transient_state(self, state, last_error):
        """Apply "fail" transition to nodes in a transient state.

        If the conductor server dies abruptly mid deployment or cleaning
        (OMM Killer, power outage, etc...) we can not resume the process even
        if the conductor comes back online. Cleaning the reservation of
        the nodes (dbapi.clear_node_reservations_for_conductor) is not enough
        to unstick it, so let's gracefully fail the process.
        """
        filters = {'reserved': False, 'provision_state': state}
        self._fail_if_in_state(ironic_context.get_admin_context(), filters,
                               state, 'provision_updated_at',
                               last_error=last_error)

    def _collect_periodic_tasks(self, admin_context):
        """Collect driver-specific periodic tasks.

        Conductor periodic tasks accept context argument, driver periodic
        tasks accept this manager and context. We have to ensure that the
        same driver interface class is not traversed twice, otherwise
        we'll have several instances of the same task.

        :param admin_context: Administrator context to pass to tasks.
        """
        LOG.debug('Collecting periodic tasks')
        # collected callables
        periodic_task_callables = []
        # list of visited classes to avoid adding the same tasks twice
        periodic_task_classes = set()

        def _collect_from(obj, args):
            """Collect tasks from the given object.

            :param obj: the object to collect tasks from.
            :param args: a tuple of arguments to pass to tasks.
            """
            if obj and obj.__class__ not in periodic_task_classes:
                for name, member in inspect.getmembers(obj):
                    if periodics.is_periodic(member):
                        LOG.debug('Found periodic task %(owner)s.%(member)s',
                                  {'owner': obj.__class__.__name__,
                                   'member': name})
                        periodic_task_callables.append((member, args, {}))
                periodic_task_classes.add(obj.__class__)

        # First, collect tasks from the conductor itself
        _collect_from(self, (admin_context,))

        # Second, collect tasks from hardware interfaces
        for ifaces in driver_factory.all_interfaces().values():
            for iface in ifaces.values():
                _collect_from(iface, args=(self, admin_context))
        # TODO(dtantsur): allow periodics on hardware types themselves?

        if len(periodic_task_callables) > CONF.conductor.workers_pool_size:
            LOG.warning('This conductor has %(tasks)d periodic tasks '
                        'enabled, but only %(workers)d task workers '
                        'allowed by [conductor]workers_pool_size option',
                        {'tasks': len(periodic_task_callables),
                         'workers': CONF.conductor.workers_pool_size})

        self._periodic_tasks = periodics.PeriodicWorker(
            periodic_task_callables,
            executor_factory=periodics.ExistingExecutor(self._executor))
        # This is only used in tests currently. Delete it?
        self._periodic_task_callables = periodic_task_callables

    def keepalive_halt(self):
        if not hasattr(self, '_keepalive_evt'):
            return
        self._keepalive_evt.set()

    def del_host(self, deregister=True, clear_node_reservations=True):
        # Conductor deregistration fails if called on non-initialized
        # conductor (e.g. when rpc server is unreachable).
        if not hasattr(self, 'conductor'):
            return

        # the keepalive heartbeat greenthread will continue to run, but will
        # now be setting online=False
        self._shutdown = True

        if clear_node_reservations:
            # clear all locks held by this conductor before deregistering
            self.dbapi.clear_node_reservations_for_conductor(self.host)
        if deregister:
            try:
                # Inform the cluster that this conductor is shutting down.
                # Note that rebalancing will not occur immediately, but when
                # the periodic sync takes place.
                self.conductor.unregister()
                LOG.info('Successfully stopped conductor with hostname '
                         '%(hostname)s.',
                         {'hostname': self.host})
            except exception.ConductorNotFound:
                pass
        else:
            LOG.info('Not deregistering conductor with hostname %(hostname)s.',
                     {'hostname': self.host})
        # Waiting here to give workers the chance to finish. This has the
        # benefit of releasing locks workers placed on nodes, as well as
        # having work complete normally.
        self._periodic_tasks.stop()
        self._periodic_tasks.wait()
        self._executor.shutdown(wait=True)

        if self._zeroconf is not None:
            self._zeroconf.close()
            self._zeroconf = None

        self._started = False

    def get_online_conductor_count(self):
        """Return a count of currently online conductors"""
        return len(self.dbapi.get_online_conductors())

    def has_reserved(self):
        """Determines if this host currently has any reserved nodes

        :returns: True if this host has reserved nodes
        """
        return bool(self.dbapi.get_nodeinfo_list(
            filters={'reserved_by_any_of': [self.host]},
            limit=1))

    def _register_and_validate_hardware_interfaces(self, hardware_types):
        """Register and validate hardware interfaces for this conductor.

        Registers a row in the database for each combination of
        (hardware type, interface type, interface) that is supported and
        enabled.

        TODO: Validates against other conductors to check if the
        set of registered hardware interfaces for a given hardware type is the
        same, and warns if not (we can't error out, otherwise all conductors
        must be restarted at once to change configuration).

        :param hardware_types: Dictionary mapping hardware type name to
                               hardware type object.
        :raises: ConductorHardwareInterfacesAlreadyRegistered
        :raises: InterfaceNotFoundInEntrypoint
        :raises: NoValidDefaultForInterface if the default value cannot be
                 calculated and is not provided in the configuration
        """
        # first unregister, in case we have cruft laying around
        self.conductor.unregister_all_hardware_interfaces()

        interfaces = []
        for ht_name, ht in hardware_types.items():
            interface_map = driver_factory.enabled_supported_interfaces(ht)
            for interface_type, interface_names in interface_map.items():
                default_interface = driver_factory.default_interface(
                    ht, interface_type, driver_name=ht_name)
                interface = {}
                interface["hardware_type"] = ht_name
                interface["interface_type"] = interface_type
                for interface_name in interface_names:
                    interface["interface_name"] = interface_name
                    interface["default"] = \
                        (interface_name == default_interface)
                    interfaces.append(copy.copy(interface))
        self.conductor.register_hardware_interfaces(interfaces)

        # TODO(jroll) validate against other conductor, warn if different
        # how do we do this performantly? :|

    def _on_periodic_tasks_stop(self, fut):
        try:
            fut.result()
        except Exception as exc:
            LOG.critical('Periodic tasks worker has failed: %s', exc)
        else:
            LOG.info('Successfully shut down periodic tasks')

    def iter_nodes(self, fields=None, **kwargs):
        """Iterate over nodes mapped to this conductor.

        Requests node set from and filters out nodes that are not
        mapped to this conductor.

        Yields tuples (node_uuid, driver, conductor_group, ...) where ... is
        derived from fields argument, e.g.: fields=None means yielding ('uuid',
        'driver', 'conductor_group'), fields=['foo'] means yielding ('uuid',
        'driver', 'conductor_group', 'foo').

        :param fields: list of fields to fetch in addition to uuid, driver,
                       and conductor_group
        :param kwargs: additional arguments to pass to dbapi when looking for
                       nodes
        :return: generator yielding tuples of requested fields
        """
        columns = ['uuid', 'driver', 'conductor_group'] + list(fields or ())
        node_list = self.dbapi.get_nodeinfo_list(columns=columns, **kwargs)
        for result in node_list:
            if self._shutdown:
                break
            if self._mapped_to_this_conductor(*result[:3]):
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
        if common_utils.is_ironic_using_sqlite():
            # Exit this keepalive heartbeats are disabled and not
            # considered.
            return
        while not self._keepalive_evt.is_set():
            try:
                self.conductor.touch(online=not self._shutdown)
            except db_exception.DBConnectionError:
                LOG.warning('Conductor could not connect to database '
                            'while heartbeating.')
            except Exception as e:
                LOG.exception('Error while heartbeating. Error: %(err)s',
                              {'err': e})
            self._keepalive_evt.wait(CONF.conductor.heartbeat_interval)

    def _mapped_to_this_conductor(self, node_uuid, driver, conductor_group):
        """Check that node is mapped to this conductor.

        Note that because mappings are eventually consistent, it is possible
        for two conductors to simultaneously believe that a node is mapped to
        them. Any operation that depends on exclusive control of a node should
        take out a lock.
        """
        try:
            ring = self.ring_manager.get_ring(driver, conductor_group)
        except exception.DriverNotFound:
            return False

        return self.host in ring.get_nodes(node_uuid.encode('utf-8'))

    def _fail_if_in_state(self, context, filters, provision_state,
                          sort_key, callback_method=None,
                          err_handler=None, last_error=None,
                          keep_target_state=False):
        """Fail nodes that are in specified state.

        Retrieves nodes that satisfy the criteria in 'filters'.
        If any of these nodes is in 'provision_state', it has failed
        in whatever provisioning activity it was currently doing.
        That failure is processed here.

        :param context: request context
        :param filters: criteria (as a dictionary) to get the desired
                        list of nodes that satisfy the filter constraints.
                        For example, if filters['provisioned_before'] = 60,
                        this would process nodes whose provision_updated_at
                        field value was 60 or more seconds before 'now'.
        :param provision_state: provision_state that the node is in,
                                for the provisioning activity to have failed,
                                either one string or a set.
        :param sort_key: the nodes are sorted based on this key.
        :param callback_method: the callback method to be invoked in a
                                spawned thread, for a failed node. This
                                method must take a :class:`TaskManager` as
                                the first (and only required) parameter.
        :param err_handler: for a failed node, the error handler to invoke
                            if an error occurs trying to spawn an thread
                            to do the callback_method.
        :param last_error: the error message to be updated in node.last_error
        :param keep_target_state: if True, a failed node will keep the same
                                  target provision state it had before the
                                  failure. Otherwise, the node's target
                                  provision state will be determined by the
                                  fsm.

        """
        if isinstance(provision_state, str):
            provision_state = {provision_state}

        node_iter = self.iter_nodes(filters=filters,
                                    sort_key=sort_key,
                                    sort_dir='asc')
        desired_maintenance = filters.get('maintenance')
        workers_count = 0
        for node_uuid, driver, conductor_group in node_iter:
            try:
                with task_manager.acquire(context, node_uuid,
                                          purpose='node state check') as task:
                    # Check maintenance value since it could have changed
                    # after the filtering was done.
                    if (desired_maintenance is not None
                            and desired_maintenance != task.node.maintenance):
                        continue

                    if task.node.provision_state not in provision_state:
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
                        utils.node_history_record(
                            task.node, event=last_error,
                            error=True,
                            event_type=states.TRANSITION)
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

        :param context: request context
        """
        filters = {'console_enabled': True}

        node_iter = self.iter_nodes(filters=filters)

        for node_uuid, driver, conductor_group in node_iter:
            try:
                with task_manager.acquire(context, node_uuid, shared=False,
                                          purpose='start console') as task:

                    notify_utils.emit_console_notification(
                        task, 'console_restore',
                        obj_fields.NotificationStatus.START)
                    try:
                        LOG.debug('Trying to start console of node %(node)s',
                                  {'node': node_uuid})
                        task.driver.console.start_console(task)
                        LOG.info('Successfully started console of node '
                                 '%(node)s', {'node': node_uuid})
                        notify_utils.emit_console_notification(
                            task, 'console_restore',
                            obj_fields.NotificationStatus.END)
                    except Exception as err:
                        msg = (_('Failed to start console of node %(node)s '
                                 'while starting the conductor, so changing '
                                 'the console_enabled status to False, error: '
                                 '%(err)s')
                               % {'node': node_uuid, 'err': err})
                        LOG.error(msg)
                        # If starting console failed, set node console_enabled
                        # back to False and set node's last error.
                        utils.node_history_record(task.node, event=msg,
                                                  error=True,
                                                  event_type=states.STARTFAIL)
                        task.node.console_enabled = False
                        task.node.save()
                        notify_utils.emit_console_notification(
                            task, 'console_restore',
                            obj_fields.NotificationStatus.ERROR)
            except exception.NodeLocked:
                LOG.warning('Node %(node)s is locked while trying to '
                            'start console on conductor startup',
                            {'node': node_uuid})
                continue
            except exception.NodeNotFound:
                LOG.warning("During starting console on conductor "
                            "startup, node %(node)s was not found",
                            {'node': node_uuid})
                continue
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    def _resume_allocations(self, context):
        """Resume unfinished allocations on restart."""
        filters = {'state': states.ALLOCATING,
                   'conductor_affinity': self.conductor.id}
        for allocation in objects.Allocation.list(context, filters=filters):
            LOG.debug('Resuming unfinished allocation %s', allocation.uuid)
            allocations.do_allocate(context, allocation)

    def _publish_endpoint(self):
        params = {}
        if CONF.debug:
            params['ipa_debug'] = True
        self._zeroconf = mdns.Zeroconf()
        self._zeroconf.register_service('baremetal',
                                        deploy_utils.get_ironic_api_url(),
                                        params=params)
