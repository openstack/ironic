# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 International Business Machines Corporation
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
"""Conduct all activity related to bare-metal deployments.

A single instance of :py:class:`ironic.conductor.manager.ConductorManager` is
created within the *ironic-conductor* process, and is responsible for
performing all actions on bare metal resources (Chassis, Nodes, and Ports).
Commands are received via RPCs. The conductor service also performs periodic
tasks, eg.  to monitor the status of active deployments.

Drivers are loaded via entrypoints by the
:py:class:`ironic.common.driver_factory` class. Each driver is instantiated
only once, when the ConductorManager service starts.  In this way, a single
ConductorManager may use multiple drivers, and manage heterogeneous hardware.

When multiple :py:class:`ConductorManager` are run on different hosts, they are
all active and cooperatively manage all nodes in the deployment.  Nodes are
locked by each conductor when performing actions which change the state of that
node; these locks are represented by the
:py:class:`ironic.conductor.task_manager.TaskManager` class.

A :py:class:`ironic.common.hash_ring.HashRing` is used to distribute nodes
across the set of active conductors which support each node's driver.
Rebalancing this ring can trigger various actions by each conductor, such as
building or tearing down the TFTP environment for a node, notifying Neutron of
a change, etc.
"""

import collections
import datetime
import inspect
import tempfile
import threading

import eventlet
from eventlet import greenpool
from oslo import messaging
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_context import context as ironic_context
from oslo_db import exception as db_exception
from oslo_utils import excutils
from oslo_utils import uuidutils

from ironic.common import dhcp_factory
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils as glance_utils
from ironic.common import hash_ring as hash
from ironic.common.i18n import _
from ironic.common.i18n import _LC
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import images
from ironic.common import keystone
from ironic.common import rpc
from ironic.common import states
from ironic.common import swift
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import log
from ironic.openstack.common import periodic_task

MANAGER_TOPIC = 'ironic.conductor_manager'
WORKER_SPAWN_lOCK = "conductor_worker_spawn"

LOG = log.getLogger(__name__)

conductor_opts = [
        cfg.StrOpt('api_url',
                   help=('URL of Ironic API service. If not set ironic can '
                         'get the current value from the keystone service '
                         'catalog.')),
        cfg.IntOpt('heartbeat_interval',
                   default=10,
                   help='Seconds between conductor heart beats.'),
        cfg.IntOpt('heartbeat_timeout',
                   default=60,
                   help='Maximum time (in seconds) since the last check-in '
                        'of a conductor.'),
        cfg.IntOpt('sync_power_state_interval',
                   default=60,
                   help='Interval between syncing the node power state to the '
                        'database, in seconds.'),
        cfg.IntOpt('check_provision_state_interval',
                   default=60,
                   help='Interval between checks of provision timeouts, '
                        'in seconds.'),
        cfg.IntOpt('deploy_callback_timeout',
                   default=1800,
                   help='Timeout (seconds) for waiting callback from deploy '
                        'ramdisk. 0 - unlimited.'),
        cfg.BoolOpt('force_power_state_during_sync',
                   default=True,
                   help='During sync_power_state, should the hardware power '
                        'state be set to the state recorded in the database '
                        '(True) or should the database be updated based on '
                        'the hardware state (False).'),
        cfg.IntOpt('power_state_sync_max_retries',
                   default=3,
                   help='During sync_power_state failures, limit the '
                        'number of times Ironic should try syncing the '
                        'hardware node power state with the node power state '
                        'in DB'),
        cfg.IntOpt('periodic_max_workers',
                   default=8,
                   help='Maximum number of worker threads that can be started '
                        'simultaneously by a periodic task. Should be less '
                        'than RPC thread pool size.'),
        cfg.IntOpt('workers_pool_size',
                   default=100,
                   help='The size of the workers greenthread pool.'),
        cfg.IntOpt('node_locked_retry_attempts',
                   default=3,
                   help='Number of attempts to grab a node lock.'),
        cfg.IntOpt('node_locked_retry_interval',
                   default=1,
                   help='Seconds to sleep between node lock attempts.'),
        cfg.BoolOpt('send_sensor_data',
                   default=False,
                   help='Enable sending sensor data message via the '
                        'notification bus'),
        cfg.IntOpt('send_sensor_data_interval',
                   default=600,
                   help='Seconds between conductor sending sensor data message'
                        ' to ceilometer via the notification bus.'),
        cfg.ListOpt('send_sensor_data_types',
                   default=['ALL'],
                   help='List of comma separated metric types which need to be'
                        ' sent to Ceilometer. The default value, "ALL", is a '
                        'special value meaning send all the sensor data.'
                    ),
        cfg.IntOpt('sync_local_state_interval',
                   default=180,
                   help='When conductors join or leave the cluster, existing '
                        'conductors may need to update any persistent '
                        'local state as nodes are moved around the cluster. '
                        'This option controls how often, in seconds, each '
                        'conductor will check for nodes that it should '
                        '"take over". Set it to a negative value to disable '
                        'the check entirely.'),
        cfg.BoolOpt('configdrive_use_swift',
                    default=False,
                    help='Whether to upload the config drive to Swift.'),
        cfg.StrOpt('configdrive_swift_container',
                   default='ironic_configdrive_container',
                   help='Name of the Swift container to store config drive '
                        'data. Used when configdrive_use_swift is True.'),
        cfg.IntOpt('inspect_timeout',
                   default=1800,
                   help='Timeout (seconds) for waiting for node inspection. '
                        '0 - unlimited.'),
        cfg.BoolOpt('clean_nodes',
                    default=True,
                    help='Cleaning is a configurable set of steps, such as '
                         'erasing disk drives, that are performed on the node '
                         'to ensure it is in a baseline state and ready to be '
                         'deployed to. '
                         'This is done after instance deletion, and during '
                         'the transition from a "managed" to "available" '
                         'state. When enabled, the particular steps '
                         'performed to clean a node depend on which driver '
                         'that node is managed by; see the individual '
                         'driver\'s documentation for details. '
                         'NOTE: The introduction of the cleaning operation '
                         'causes instance deletion to take significantly '
                         'longer. In an environment where all tenants are '
                         'trusted (eg, because there is only one tenant), '
                         'this option could be safely disabled.'),
]
CONF = cfg.CONF
CONF.register_opts(conductor_opts, 'conductor')

CLEANING_INTERFACE_PRIORITY = {
    # When two clean steps have the same priority, their order is determined
    # by which interface is implementing the clean step. The clean step of the
    # interface with the highest value here, will be executed first in that
    # case.
    'power': 3,
    'management': 2,
    'deploy': 1
}


class ConductorManager(periodic_task.PeriodicTasks):
    """Ironic Conductor manager main class."""

    # NOTE(rloo): This must be in sync with rpcapi.ConductorAPI's.
    RPC_API_VERSION = '1.27'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, host, topic):
        super(ConductorManager, self).__init__()
        if not host:
            host = CONF.host
        self.host = host
        self.topic = topic
        self.power_state_sync_count = collections.defaultdict(int)
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
            LOG.warn(_LW("A conductor with hostname %(hostname)s "
                         "was previously registered. Updating registration"),
                     {'hostname': self.host})
            cdr = self.dbapi.register_conductor({'hostname': self.host,
                                                 'drivers': self.drivers},
                                                 update_existing=True)
        self.conductor = cdr

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

    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.MissingParameterValue,
                                   exception.NodeLocked)
    def update_node(self, context, node_obj):
        """Update a node with the supplied data.

        This method is the main "hub" for PUT and PATCH requests in the API.
        It ensures that the requested change is safe to perform,
        validates the parameters with the node's driver, if necessary.

        :param context: an admin context
        :param node_obj: a changed (but not saved) node object.

        """
        node_id = node_obj.uuid
        LOG.debug("RPC update_node called for node %s." % node_id)

        delta = node_obj.obj_what_changed()
        if 'power_state' in delta:
            raise exception.IronicException(_(
                "Invalid method call: update_node can not change node state."))

        # NOTE(jroll) clear maintenance_reason if node.update sets
        # maintenance to False for backwards compatibility, for tools
        # not using the maintenance endpoint.
        if 'maintenance' in delta and not node_obj.maintenance:
            node_obj.maintenance_reason = None

        driver_name = node_obj.driver if 'driver' in delta else None
        with task_manager.acquire(context, node_id, shared=False,
                                  driver_name=driver_name):
            node_obj.save()

        return node_obj

    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.MissingParameterValue,
                                   exception.NoFreeConductorWorker,
                                   exception.NodeLocked)
    def change_node_power_state(self, context, node_id, new_state):
        """RPC method to encapsulate changes to a node's state.

        Perform actions such as power on, power off. The validation is
        performed synchronously, and if successful, the power action is
        updated in the background (asynchronously). Once the power action
        is finished and successful, it updates the power_state for the
        node with the new power state.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired power state of the node.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        LOG.debug("RPC change_node_power_state called for node %(node)s. "
                  "The desired new state is %(state)s."
                  % {'node': node_id, 'state': new_state})

        with task_manager.acquire(context, node_id, shared=False) as task:
            task.driver.power.validate(task)
            # Set the target_power_state and clear any last_error, since we're
            # starting a new operation. This will expose to other processes
            # and clients that work is in progress.
            if new_state == states.REBOOT:
                task.node.target_power_state = states.POWER_ON
            else:
                task.node.target_power_state = new_state
            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(power_state_error_handler,
                                      task.node, task.node.power_state)
            task.spawn_after(self._spawn_worker, utils.node_power_action,
                             task, new_state)

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InvalidParameterValue,
                                   exception.UnsupportedDriverExtension,
                                   exception.MissingParameterValue)
    def vendor_passthru(self, context, node_id, driver_method,
                        http_method, info):
        """RPC method to encapsulate vendor action.

        Synchronously validate driver specific info or get driver status,
        and if successful invokes the vendor method. If the method mode
        is 'async' the conductor will start background worker to perform
        vendor action.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param driver_method: the name of the vendor method.
        :param http_method: the HTTP method used for the request.
        :param info: vendor method args.
        :raises: InvalidParameterValue if supplied info is not valid.
        :raises: MissingParameterValue if missing supplied info
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface or method is unsupported.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: NodeLocked if node is locked by another conductor.
        :returns: A tuple containing the response of the invoked method
                  and a boolean value indicating whether the method was
                  invoked asynchronously (True) or synchronously (False).
                  If invoked asynchronously the response field will be
                  always None.
        """
        LOG.debug("RPC vendor_passthru called for node %s." % node_id)
        # NOTE(max_lobur): Even though not all vendor_passthru calls may
        # require an exclusive lock, we need to do so to guarantee that the
        # state doesn't unexpectedly change between doing a vendor.validate
        # and vendor.vendor_passthru.
        with task_manager.acquire(context, node_id, shared=False) as task:
            if not getattr(task.driver, 'vendor', None):
                raise exception.UnsupportedDriverExtension(
                    driver=task.node.driver,
                    extension='vendor interface')

            vendor_iface = task.driver.vendor

            # NOTE(lucasagomes): Before the vendor_passthru() method was
            # a self-contained method and each driver implemented their own
            # version of it, now we have a common mechanism that drivers
            # should use to expose their vendor methods. If a driver still
            # have their own vendor_passthru() method we call it to be
            # backward compat. This code should be removed once L opens.
            if hasattr(vendor_iface, 'vendor_passthru'):
                LOG.warning(_LW("Drivers implementing their own version "
                                "of vendor_passthru() has been deprecated. "
                                "Please update the code to use the "
                                "@passthru decorator."))
                vendor_iface.validate(task, method=driver_method,
                                            **info)
                task.spawn_after(self._spawn_worker,
                                 vendor_iface.vendor_passthru, task,
                                 method=driver_method, **info)
                # NodeVendorPassthru was always async
                return (None, True)

            try:
                vendor_opts = vendor_iface.vendor_routes[driver_method]
                vendor_func = vendor_opts['func']
            except KeyError:
                raise exception.InvalidParameterValue(
                    _('No handler for method %s') % driver_method)

            http_method = http_method.upper()
            if http_method not in vendor_opts['http_methods']:
                raise exception.InvalidParameterValue(
                    _('The method %(method)s does not support HTTP %(http)s') %
                    {'method': driver_method, 'http': http_method})

            vendor_iface.validate(task, method=driver_method,
                                  http_method=http_method, **info)

            # Inform the vendor method which HTTP method it was invoked with
            info['http_method'] = http_method

            # Invoke the vendor method accordingly with the mode
            is_async = vendor_opts['async']
            ret = None
            if is_async:
                task.spawn_after(self._spawn_worker, vendor_func, task, **info)
            else:
                ret = vendor_func(task, **info)

            return (ret, is_async)

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue,
                                   exception.UnsupportedDriverExtension,
                                   exception.DriverNotFound)
    def driver_vendor_passthru(self, context, driver_name, driver_method,
                               http_method, info):
        """Handle top-level vendor actions.

        RPC method which handles driver-level vendor passthru calls. These
        calls don't require a node UUID and are executed on a random
        conductor with the specified driver. If the method mode is
        async the conductor will start background worker to perform
        vendor action.

        :param context: an admin context.
        :param driver_name: name of the driver on which to call the method.
        :param driver_method: name of the vendor method, for use by the driver.
        :param http_method: the HTTP method used for the request.
        :param info: user-supplied data to pass through to the driver.
        :raises: MissingParameterValue if missing supplied info
        :raises: InvalidParameterValue if supplied info is not valid.
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface, if the vendor interface does not implement
                 driver-level vendor passthru or if the passthru method is
                 unsupported.
        :raises: DriverNotFound if the supplied driver is not loaded.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :returns: A tuple containing the response of the invoked method
                  and a boolean value indicating whether the method was
                  invoked asynchronously (True) or synchronously (False).
                  If invoked asynchronously the response field will be
                  always None.
        """
        # Any locking in a top-level vendor action will need to be done by the
        # implementation, as there is little we could reasonably lock on here.
        LOG.debug("RPC driver_vendor_passthru for driver %s." % driver_name)
        driver = self._get_driver(driver_name)
        if not getattr(driver, 'vendor', None):
            raise exception.UnsupportedDriverExtension(
                driver=driver_name,
                extension='vendor interface')

        # NOTE(lucasagomes): Before the driver_vendor_passthru()
        # method was a self-contained method and each driver implemented
        # their own version of it, now we have a common mechanism that
        # drivers should use to expose their vendor methods. If a driver
        # still have their own driver_vendor_passthru() method we call
        # it to be backward compat. This code should be removed
        # once L opens.
        if hasattr(driver.vendor, 'driver_vendor_passthru'):
            LOG.warning(_LW("Drivers implementing their own version "
                            "of driver_vendor_passthru() has been "
                            "deprecated. Please update the code to use "
                            "the @driver_passthru decorator."))

            driver.vendor.driver_validate(method=driver_method, **info)
            ret = driver.vendor.driver_vendor_passthru(
                            context, method=driver_method, **info)
            # DriverVendorPassthru was always sync
            return (ret, False)

        try:
            vendor_opts = driver.vendor.driver_routes[driver_method]
            vendor_func = vendor_opts['func']
        except KeyError:
            raise exception.InvalidParameterValue(
                _('No handler for method %s') % driver_method)

        http_method = http_method.upper()
        if http_method not in vendor_opts['http_methods']:
            raise exception.InvalidParameterValue(
                _('The method %(method)s does not support HTTP %(http)s') %
                {'method': driver_method, 'http': http_method})

        # Inform the vendor method which HTTP method it was invoked with
        info['http_method'] = http_method

        # Invoke the vendor method accordingly with the mode
        is_async = vendor_opts['async']
        ret = None
        driver.vendor.driver_validate(method=driver_method, **info)

        if is_async:
            self._spawn_worker(vendor_func, context, **info)
        else:
            ret = vendor_func(context, **info)

        return (ret, is_async)

    @messaging.expected_exceptions(exception.UnsupportedDriverExtension)
    def get_node_vendor_passthru_methods(self, context, node_id):
        """Retrieve information about vendor methods of the given node.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        LOG.debug("RPC get_node_vendor_passthru_methods called for node %s"
                  % node_id)
        with task_manager.acquire(context, node_id, shared=True) as task:
            if not getattr(task.driver, 'vendor', None):
                raise exception.UnsupportedDriverExtension(
                    driver=task.node.driver,
                    extension='vendor interface')

            return get_vendor_passthru_metadata(
                    task.driver.vendor.vendor_routes)

    @messaging.expected_exceptions(exception.UnsupportedDriverExtension,
                                   exception.DriverNotFound)
    def get_driver_vendor_passthru_methods(self, context, driver_name):
        """Retrieve information about vendor methods of the given driver.

        :param context: an admin context.
        :param driver_name: name of the driver.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        # Any locking in a top-level vendor action will need to be done by the
        # implementation, as there is little we could reasonably lock on here.
        LOG.debug("RPC get_driver_vendor_passthru_methods for driver %s"
                  % driver_name)
        driver = self._get_driver(driver_name)
        if not getattr(driver, 'vendor', None):
            raise exception.UnsupportedDriverExtension(
                driver=driver_name,
                extension='vendor interface')

        return get_vendor_passthru_metadata(driver.vendor.driver_routes)

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.NodeInMaintenance,
                                   exception.InstanceDeployFailure,
                                   exception.InvalidStateRequested)
    def do_node_deploy(self, context, node_id, rebuild=False,
                       configdrive=None):
        """RPC method to initiate deployment to a node.

        Initiate the deployment of a node. Validations are done
        synchronously and the actual deploy work is performed in
        background (asynchronously).

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param rebuild: True if this is a rebuild request. A rebuild will
                        recreate the instance on the same node, overwriting
                        all disk. The ephemeral partition, if it exists, can
                        optionally be preserved.
        :param configdrive: Optional. A gzipped and base64 encoded configdrive.
        :raises: InstanceDeployFailure
        :raises: NodeInMaintenance if the node is in maintenance mode.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InvalidStateRequested when the requested state is not a valid
                 target from the current state.

        """
        LOG.debug("RPC do_node_deploy called for node %s." % node_id)

        # NOTE(comstud): If the _sync_power_states() periodic task happens
        # to have locked this node, we'll fail to acquire the lock. The
        # client should perhaps retry in this case unless we decide we
        # want to add retries or extra synchronization here.
        with task_manager.acquire(context, node_id, shared=False) as task:
            node = task.node
            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('provisioning'),
                                                  node=node.uuid)

            if rebuild:
                event = 'rebuild'

                # Note(gilliard) Clear these to force the driver to
                # check whether they have been changed in glance
                # NOTE(vdrok): If image_source is not from Glance we should
                # not clear kernel and ramdisk as they're input manually
                if glance_utils.is_glance_image(
                        node.instance_info.get('image_source')):
                    instance_info = node.instance_info
                    instance_info.pop('kernel', None)
                    instance_info.pop('ramdisk', None)
                    node.instance_info = instance_info
            else:
                event = 'deploy'

            driver_internal_info = node.driver_internal_info
            # Infer the image type to make sure the deploy driver
            # validates only the necessary variables for different
            # image types.
            # NOTE(sirushtim): The iwdi variable can be None. It's up to
            # the deploy driver to validate this.
            iwdi = images.is_whole_disk_image(context, node.instance_info)
            driver_internal_info['is_whole_disk_image'] = iwdi
            node.driver_internal_info = driver_internal_info
            node.save()

            try:
                task.driver.power.validate(task)
                task.driver.deploy.validate(task)
            except (exception.InvalidParameterValue,
                    exception.MissingParameterValue) as e:
                raise exception.InstanceDeployFailure(_(
                    "RPC do_node_deploy failed to validate deploy or "
                    "power info. Error: %(msg)s") % {'msg': e})

            LOG.debug("do_node_deploy Calling event: %(event)s for node: "
                      "%(node)s", {'event': event, 'node': node.uuid})
            try:
                task.process_event(event,
                                   callback=self._spawn_worker,
                                   call_args=(do_node_deploy, task,
                                              self.conductor.id,
                                              configdrive),
                                   err_handler=provisioning_error_handler)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                        action=event, node=task.node.uuid,
                        state=task.node.provision_state)

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InstanceDeployFailure,
                                   exception.InvalidStateRequested)
    def do_node_tear_down(self, context, node_id):
        """RPC method to tear down an existing node deployment.

        Validate driver specific information synchronously, and then
        spawn a background worker to tear down the node asynchronously.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InstanceDeployFailure
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: InvalidStateRequested when the requested state is not a valid
                 target from the current state.

        """
        LOG.debug("RPC do_node_tear_down called for node %s." % node_id)

        with task_manager.acquire(context, node_id, shared=False) as task:
            try:
                # NOTE(ghe): Valid power driver values are needed to perform
                # a tear-down. Deploy info is useful to purge the cache but not
                # required for this method.
                task.driver.power.validate(task)
            except (exception.InvalidParameterValue,
                    exception.MissingParameterValue) as e:
                raise exception.InstanceDeployFailure(_(
                    "Failed to validate power driver interface. "
                    "Can not delete instance. Error: %(msg)s") % {'msg': e})

            try:
                task.process_event('delete',
                                   callback=self._spawn_worker,
                                   call_args=(self._do_node_tear_down, task),
                                   err_handler=provisioning_error_handler)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                        action='delete', node=task.node.uuid,
                        state=task.node.provision_state)

    def _do_node_tear_down(self, task):
        """Internal RPC method to tear down an existing node deployment."""
        node = task.node
        try:
            task.driver.deploy.clean_up(task)
            task.driver.deploy.tear_down(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error in tear_down of node %(node)s: '
                                  '%(err)s'),
                              {'node': node.uuid, 'err': e})
                node.last_error = _("Failed to tear down. Error: %s") % e
                task.process_event('error')
        else:
            # NOTE(deva): When tear_down finishes, the deletion is done,
            # cleaning will start next
            LOG.info(_LI('Successfully unprovisioned node %(node)s with '
                         'instance %(instance)s.'),
                     {'node': node.uuid, 'instance': node.instance_uuid})
        finally:
            # NOTE(deva): there is no need to unset conductor_affinity
            # because it is a reference to the most recent conductor which
            # deployed a node, and does not limit any future actions.
            # But we do need to clear the instance_info
            node.instance_info = {}
            node.save()

        # Begin cleaning
        try:
            task.process_event('clean')
        except exception.InvalidState:
            raise exception.InvalidStateRequested(
                action='clean', node=node.uuid,
                state=node.provision_state)
        self._do_node_clean(task)

    def continue_node_clean(self, context, node_id):
        """RPC method to continue cleaning a node.

        This is useful for cleaning tasks that are async. When they complete,
        they call back via RPC, a new worker and lock are set up, and cleaning
        continues. This can also be used to resume cleaning on take_over.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InvalidStateRequested if the node is not in CLEANING state
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node no longer appears in the database

        """
        LOG.debug("RPC continue_node_clean called for node %s.", node_id)

        with task_manager.acquire(context, node_id, shared=False) as task:
            if task.node.provision_state != states.CLEANING:
                raise exception.InvalidStateRequested(_(
                    'Cannot continue cleaning on %(node)s, node is in '
                    '%(state)s state, should be %(clean_state)s') %
                    {'node': task.node.uuid,
                     'state': task.node.provision_state,
                     'clean_state': states.CLEANING})
            task.set_spawn_error_hook(cleaning_error_handler, task.node,
                                      'Failed to run next clean step')
            task.spawn_after(
                self._spawn_worker,
                self._do_next_clean_step,
                task,
                task.node.driver_internal_info.get('clean_steps', []),
                task.node.clean_step)

    def _do_node_clean(self, task):
        """Internal RPC method to perform automated cleaning of a node."""
        node = task.node
        LOG.debug('Starting cleaning for node %s', node.uuid)

        if not CONF.conductor.clean_nodes:
            # Skip cleaning, move to AVAILABLE.
            node.clean_step = None
            node.save()

            task.process_event('done')
            LOG.info(_LI('Cleaning is disabled, node %s has been successfully '
                         'moved to AVAILABLE state.'), node.uuid)
            return

        try:
            # NOTE(ghe): Valid power driver values are needed to perform
            # a cleaning.
            task.driver.power.validate(task)
        except (exception.InvalidParameterValue,
                exception.MissingParameterValue) as e:
            msg = (_('Failed to validate power driver interface. '
                     'Can not clean node %(node)s. Error: %(msg)s') %
                   {'node': node.uuid, 'msg': e})
            return cleaning_error_handler(task, msg)

        # Allow the deploy driver to set up the ramdisk again (necessary for
        # IPA cleaning/zapping)
        try:
            prepare_result = task.driver.deploy.prepare_cleaning(task)
        except Exception as e:
            msg = (_('Failed to prepare node %(node)s for cleaning: %(e)s')
                   % {'node': node.uuid, 'e': e})
            LOG.exception(msg)
            return cleaning_error_handler(task, msg)
        if prepare_result == states.CLEANING:
            # Prepare is asynchronous, the deploy driver will need to
            # set node.driver_internal_info['clean_steps'] and
            # node.clean_step and then make an RPC call to
            # continue_node_cleaning to start cleaning.
            return

        set_node_cleaning_steps(task)
        self._do_next_clean_step(task,
            node.driver_internal_info.get('clean_steps', []),
            node.clean_step)

    def _do_next_clean_step(self, task, steps, last_step):
        """Start executing cleaning/zapping steps from the last step (if any).

        :param task: a TaskManager instance with an exclusive lock
        :param steps: The complete list of steps that need to be executed
            on the node
        :param last_step: The last step that was executed. {} will start
            from the beginning
        """
        node = task.node
        # Trim already executed steps
        if last_step:
            try:
                # Trim off last_step (now finished) and all previous steps.
                steps = steps[steps.index(last_step) + 1:]
            except ValueError:
                msg = (_('Node %(node)s got an invalid last step for '
                         '%(state)s: %(step)s.') %
                       {'node': node.uuid, 'step': last_step,
                        'state': node.provision_state})
                LOG.exception(msg)
                return cleaning_error_handler(task, msg)

        LOG.info(_LI('Executing %(state)s on node %(node)s, remaining steps: '
                     '%(steps)s'), {'node': node.uuid, 'steps': steps,
                                    'state': node.provision_state})
        # Execute each step until we hit an async step or run out of steps
        for step in steps:
            # Save which step we're about to start so we can restart
            # if necessary
            node.clean_step = step
            node.save()
            interface = getattr(task.driver, step.get('interface'))
            LOG.info(_LI('Executing %(step)s on node %(node)s'),
                     {'step': step, 'node': node.uuid})
            try:
                result = interface.execute_clean_step(task, step)
            except Exception as e:
                msg = (_('Node %(node)s failed step %(step)s: '
                         '%(exc)s') %
                       {'node': node.uuid, 'exc': e,
                        'step': node.clean_step})
                LOG.exception(msg)
                cleaning_error_handler(task, msg)
                return

            # Check if the step is done or not. The step should return
            # states.CLEANING if the step is still being executed, or
            # None if the step is done.
            if result == states.CLEANING:
                # Kill this worker, the async step will make an RPC call to
                # continue_node_clean to continue cleaning
                LOG.info(_LI('Clean step %(step)s on node %(node)s being '
                             'executed asynchronously, waiting for driver.') %
                         {'node': node.uuid, 'step': step})
                return
            elif result is not None:
                msg = (_('While executing step %(step)s on node '
                         '%(node)s, step returned invalid value: %(val)s')
                       % {'step': step, 'node': node.uuid, 'val': result})
                LOG.error(msg)
                return cleaning_error_handler(task, msg)
            LOG.info(_LI('Node %(node)s finished clean step %(step)s'),
                     {'node': node.uuid, 'step': step})

        # Clear clean_step
        node.clean_step = None
        driver_info = node.driver_internal_info
        driver_info['clean_steps'] = None
        node.driver_internal_info = driver_info
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            msg = (_('Failed to tear down from cleaning for node %s')
                   % node.uuid)
            LOG.exception(msg)
            return cleaning_error_handler(task, msg)
        LOG.info(_LI('Node %s cleaning complete'), node.uuid)
        task.process_event('done')

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue,
                                   exception.InvalidStateRequested)
    def do_provisioning_action(self, context, node_id, action):
        """RPC method to initiate certain provisioning state transitions.

        Initiate a provisioning state change through the state machine,
        rather than through an RPC call to do_node_deploy / do_node_tear_down

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param action: an action. One of ironic.common.states.VERBS
        :raises: InvalidParameterValue
        :raises: InvalidStateRequested
        :raises: NoFreeConductorWorker

        """
        with task_manager.acquire(context, node_id, shared=False) as task:
            if (action == states.VERBS['provide'] and
                    task.node.provision_state == states.MANAGEABLE):
                task.process_event('provide',
                                   callback=self._spawn_worker,
                                   call_args=(self._do_node_clean, task),
                                   err_handler=provisioning_error_handler)
            else:
                try:
                    task.process_event(action)
                except exception.InvalidState:
                    raise exception.InvalidStateRequested(
                        action=action, node=task.node.uuid,
                        state=task.node.provision_state)

    @periodic_task.periodic_task(
            spacing=CONF.conductor.sync_power_state_interval)
    def _sync_power_states(self, context):
        """Periodic task to sync power states for the nodes.

        Attempt to grab a lock and sync only if the following
        conditions are met:

        1) Node is mapped to this conductor.
        2) Node is not in maintenance mode.
        3) Node is not in DEPLOYWAIT provision state.
        4) Node doesn't have a reservation

        NOTE: Grabbing a lock here can cause other methods to fail to
        grab it. We want to avoid trying to grab a lock while a
        node is in the DEPLOYWAIT state so we don't unnecessarily
        cause a deploy callback to fail. There's not much we can do
        here to avoid failing a brand new deploy to a node that we've
        locked here, though.
        """
        # FIXME(comstud): Since our initial state checks are outside
        # of the lock (to try to avoid the lock), some checks are
        # repeated after grabbing the lock so we can unlock quickly.
        # The node mapping is not re-checked because it doesn't much
        # matter if things happened to re-balance.
        #
        # This is inefficient and racey. We end up with calling DB API's
        # get_node() twice (once here, and once in acquire(). Ideally we
        # add a way to pass constraints to task_manager.acquire()
        # (through to its DB API call) so that we can eliminate our call
        # and first set of checks below.

        filters = {'reserved': False, 'maintenance': False}
        node_iter = self.iter_nodes(fields=['id'], filters=filters)
        for (node_uuid, driver, node_id) in node_iter:
            try:
                # NOTE(deva): we should not acquire a lock on a node in
                #             DEPLOYWAIT, as this could cause an error within
                #             a deploy ramdisk POSTing back at the same time.
                # TODO(deva): refactor this check, because it needs to be done
                #             in every periodic task, not just this one.
                node = objects.Node.get_by_id(context, node_id)
                if (node.provision_state == states.DEPLOYWAIT or
                        node.maintenance or node.reservation is not None):
                    continue

                with task_manager.acquire(context, node_uuid) as task:
                    if (task.node.provision_state == states.DEPLOYWAIT or
                            task.node.maintenance):
                        continue
                    count = do_sync_power_state(
                            task, self.power_state_sync_count[node_uuid])
                    if count:
                        self.power_state_sync_count[node_uuid] = count
                    else:
                        # don't bloat the dict with non-failing nodes
                        del self.power_state_sync_count[node_uuid]
            except exception.NodeNotFound:
                LOG.info(_LI("During sync_power_state, node %(node)s was not "
                             "found and presumed deleted by another process."),
                         {'node': node_uuid})
            except exception.NodeLocked:
                LOG.info(_LI("During sync_power_state, node %(node)s was "
                             "already locked by another process. Skip."),
                         {'node': node_uuid})
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    @periodic_task.periodic_task(
            spacing=CONF.conductor.check_provision_state_interval)
    def _check_deploy_timeouts(self, context):
        callback_timeout = CONF.conductor.deploy_callback_timeout
        if not callback_timeout:
            return

        filters = {'reserved': False,
                   'provision_state': states.DEPLOYWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        sort_key = 'provision_updated_at'
        callback_method = utils.cleanup_after_timeout
        err_handler = provisioning_error_handler
        self._fail_if_in_state(context, filters, states.DEPLOYWAIT,
                               sort_key, callback_method, err_handler)

    def _do_takeover(self, task):
        LOG.debug(('Conductor %(cdr)s taking over node %(node)s'),
                  {'cdr': self.host, 'node': task.node.uuid})
        task.driver.deploy.prepare(task)
        task.driver.deploy.take_over(task)
        # NOTE(lucasagomes): Set the ID of the new conductor managing
        #                    this node
        task.node.conductor_affinity = self.conductor.id
        task.node.save()

    @periodic_task.periodic_task(
            spacing=CONF.conductor.sync_local_state_interval)
    def _sync_local_state(self, context):
        """Perform any actions necessary to sync local state.

        This is called periodically to refresh the conductor's copy of the
        consistent hash ring. If any mappings have changed, this method then
        determines which, if any, nodes need to be "taken over".
        The ensuing actions could include preparing a PXE environment,
        updating the DHCP server, and so on.
        """
        self.ring_manager.reset()
        filters = {'reserved': False,
                   'maintenance': False,
                   'provision_state': states.ACTIVE}
        node_iter = self.iter_nodes(fields=['id', 'conductor_affinity'],
                                    filters=filters)

        admin_context = None
        workers_count = 0
        for node_uuid, driver, node_id, conductor_affinity in node_iter:
            if conductor_affinity == self.conductor.id:
                continue

            # NOTE(lucasagomes): The context provided by the periodic task
            # will make the glance client to fail with an 401 (Unauthorized)
            # so we have to use the admin_context with an admin auth_token
            if not admin_context:
                admin_context = ironic_context.get_admin_context()
                admin_context.auth_token = keystone.get_admin_auth_token()

            # Node is mapped here, but not updated by this conductor last
            try:
                with task_manager.acquire(admin_context, node_uuid) as task:
                    # NOTE(deva): now that we have the lock, check again to
                    # avoid racing with deletes and other state changes
                    node = task.node
                    if (node.maintenance or
                            node.conductor_affinity == self.conductor.id or
                            node.provision_state != states.ACTIVE):
                        continue

                    task.spawn_after(self._spawn_worker,
                                     self._do_takeover, task)

            except exception.NoFreeConductorWorker:
                break
            except (exception.NodeLocked, exception.NodeNotFound):
                continue
            workers_count += 1
            if workers_count == CONF.conductor.periodic_max_workers:
                break

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

    @messaging.expected_exceptions(exception.NodeLocked)
    def validate_driver_interfaces(self, context, node_id):
        """Validate the `core` and `standardized` interfaces for drivers.

        :param context: request context.
        :param node_id: node id or uuid.
        :returns: a dictionary containing the results of each
                  interface validation.

        """
        LOG.debug('RPC validate_driver_interfaces called for node %s.',
                  node_id)
        ret_dict = {}
        with task_manager.acquire(context, node_id, shared=True) as task:
            # NOTE(sirushtim): the is_whole_disk_image variable is needed by
            # deploy drivers for doing their validate(). Since the deploy
            # isn't being done yet and the driver information could change in
            # the meantime, we don't know if the is_whole_disk_image value will
            # change or not. It isn't saved to the DB, but only used with this
            # node instance for the current validations.
            iwdi = images.is_whole_disk_image(context,
                                              task.node.instance_info)
            task.node.driver_internal_info['is_whole_disk_image'] = iwdi
            for iface_name in (task.driver.core_interfaces +
                               task.driver.standard_interfaces):
                iface = getattr(task.driver, iface_name, None)
                result = reason = None
                if iface:
                    try:
                        iface.validate(task)
                        result = True
                    except (exception.InvalidParameterValue,
                            exception.UnsupportedDriverExtension,
                            exception.MissingParameterValue) as e:
                        result = False
                        reason = str(e)
                else:
                    reason = _('not supported')

                ret_dict[iface_name] = {}
                ret_dict[iface_name]['result'] = result
                if reason is not None:
                    ret_dict[iface_name]['reason'] = reason
        return ret_dict

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeAssociated,
                                   exception.NodeInWrongPowerState)
    def destroy_node(self, context, node_id):
        """Delete a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeAssociated if the node contains an instance
            associated with it.
        :raises: NodeInWrongPowerState if the node is not powered off.

        """
        with task_manager.acquire(context, node_id) as task:
            node = task.node
            if node.instance_uuid is not None:
                raise exception.NodeAssociated(node=node.uuid,
                                               instance=node.instance_uuid)
            if node.power_state not in [states.POWER_OFF, states.NOSTATE]:
                msg = (_("Node %s can't be deleted because it's not "
                         "powered off") % node.uuid)
                raise exception.NodeInWrongPowerState(msg)
            if node.console_enabled:
                try:
                    task.driver.console.stop_console(task)
                except Exception as err:
                    LOG.error(_LE('Failed to stop console while deleting '
                                  'the node %(node)s: %(err)s.'),
                              {'node': node.uuid, 'err': err})
            node.destroy()
            LOG.info(_LI('Successfully deleted node %(node)s.'),
                     {'node': node.uuid})

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound)
    def destroy_port(self, context, port):
        """Delete a port.

        :param context: request context.
        :param port: port object
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node associated with the port does not
                 exist.

        """
        LOG.debug('RPC destroy_port called for port %(port)s',
                 {'port': port.uuid})
        with task_manager.acquire(context, port.node_id) as task:
            port.destroy()
            LOG.info(_LI('Successfully deleted port %(port)s. '
                         'The node associated with the port was '
                         '%(node)s'),
                         {'port': port.uuid, 'node': task.node.uuid})

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.NodeConsoleNotEnabled,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
    def get_console_information(self, context, node_id):
        """Get connection information about the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: NodeConsoleNotEnabled if the console is not enabled.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        :raises: MissingParameterValue if missing supplied info.
        """
        LOG.debug('RPC get_console_information called for node %s' % node_id)

        with task_manager.acquire(context, node_id, shared=True) as task:
            node = task.node

            if not getattr(task.driver, 'console', None):
                raise exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')
            if not node.console_enabled:
                raise exception.NodeConsoleNotEnabled(node=node_id)

            task.driver.console.validate(task)
            return task.driver.console.get_console(task)

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
    def set_console_mode(self, context, node_id, enabled):
        """Enable/Disable the console.

        Validate driver specific information synchronously, and then
        spawn a background worker to set console mode asynchronously.

        :param context: request context.
        :param node_id: node id or uuid.
        :param enabled: Boolean value; whether the console is enabled or
                        disabled.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        :raises: MissingParameterValue if missing supplied info.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        """
        LOG.debug('RPC set_console_mode called for node %(node)s with '
                  'enabled %(enabled)s' % {'node': node_id,
                                           'enabled': enabled})

        with task_manager.acquire(context, node_id, shared=False) as task:
            node = task.node
            if not getattr(task.driver, 'console', None):
                raise exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')

            task.driver.console.validate(task)

            if enabled == node.console_enabled:
                op = _('enabled') if enabled else _('disabled')
                LOG.info(_LI("No console action was triggered because the "
                             "console is already %s"), op)
                task.release_resources()
            else:
                node.last_error = None
                node.save()
                task.spawn_after(self._spawn_worker,
                                 self._set_console_mode, task, enabled)

    def _set_console_mode(self, task, enabled):
        """Internal method to set console mode on a node."""
        node = task.node
        try:
            if enabled:
                task.driver.console.start_console(task)
                # TODO(deva): We should be updating conductor_affinity here
                # but there is no support for console sessions in
                # take_over() right now.
            else:
                task.driver.console.stop_console(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                op = _('enabling') if enabled else _('disabling')
                msg = (_('Error %(op)s the console on node %(node)s. '
                        'Reason: %(error)s') % {'op': op,
                                                'node': node.uuid,
                                                'error': e})
                node.last_error = msg
        else:
            node.console_enabled = enabled
            node.last_error = None
        finally:
            node.save()

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.FailedToUpdateMacOnPort,
                                   exception.MACAlreadyExists)
    def update_port(self, context, port_obj):
        """Update a port.

        :param context: request context.
        :param port_obj: a changed (but not saved) port object.
        :raises: DHCPNotFound if the dhcp_provider provider endpoint is invalid
        :raises: FailedToUpdateMacOnPort if MAC address changed and update
                 failed.
        :raises: MACAlreadyExists if the update is setting a MAC which is
                 registered on another port already.
        """
        port_uuid = port_obj.uuid
        LOG.debug("RPC update_port called for port %s.", port_uuid)

        with task_manager.acquire(context, port_obj.node_id) as task:
            node = task.node
            if 'address' in port_obj.obj_what_changed():
                vif = port_obj.extra.get('vif_port_id')
                if vif:
                    api = dhcp_factory.DHCPFactory()
                    api.provider.update_port_address(vif, port_obj.address,
                                                     token=context.auth_token)
                # Log warning if there is no vif_port_id and an instance
                # is associated with the node.
                elif node.instance_uuid:
                    LOG.warning(_LW("No VIF found for instance %(instance)s "
                        "port %(port)s when attempting to update port MAC "
                        "address."),
                        {'port': port_uuid, 'instance': node.instance_uuid})

            port_obj.save()

            return port_obj

    @messaging.expected_exceptions(exception.DriverNotFound)
    def get_driver_properties(self, context, driver_name):
        """Get the properties of the driver.

        :param context: request context.
        :param driver_name: name of the driver.
        :returns: a dictionary with <property name>:<property description>
                  entries.
        :raises: DriverNotFound if the driver is not loaded.

        """
        LOG.debug("RPC get_driver_properties called for driver %s.",
                  driver_name)
        driver = self._get_driver(driver_name)
        return driver.get_properties()

    @periodic_task.periodic_task(
            spacing=CONF.conductor.send_sensor_data_interval)
    def _send_sensor_data(self, context):
        # do nothing if send_sensor_data option is False
        if not CONF.conductor.send_sensor_data:
            return

        filters = {'associated': True}
        node_iter = self.iter_nodes(fields=['instance_uuid'],
                                    filters=filters)

        for (node_uuid, driver, instance_uuid) in node_iter:
            # populate the message which will be sent to ceilometer
            message = {'message_id': uuidutils.generate_uuid(),
                       'instance_uuid': instance_uuid,
                       'node_uuid': node_uuid,
                       'timestamp': datetime.datetime.utcnow(),
                       'event_type': 'hardware.ipmi.metrics.update'}

            try:
                with task_manager.acquire(context,
                                          node_uuid,
                                          shared=True) as task:
                    task.driver.management.validate(task)
                    sensors_data = task.driver.management.get_sensors_data(
                        task)
            except NotImplementedError:
                LOG.warn(_LW('get_sensors_data is not implemented for driver'
                    ' %(driver)s, node_uuid is %(node)s'),
                    {'node': node_uuid, 'driver': driver})
            except exception.FailedToParseSensorData as fps:
                LOG.warn(_LW("During get_sensors_data, could not parse "
                    "sensor data for node %(node)s. Error: %(err)s."),
                    {'node': node_uuid, 'err': str(fps)})
            except exception.FailedToGetSensorData as fgs:
                LOG.warn(_LW("During get_sensors_data, could not get "
                    "sensor data for node %(node)s. Error: %(err)s."),
                    {'node': node_uuid, 'err': str(fgs)})
            except exception.NodeNotFound:
                LOG.warn(_LW("During send_sensor_data, node %(node)s was not "
                           "found and presumed deleted by another process."),
                           {'node': node_uuid})
            except Exception as e:
                LOG.warn(_LW("Failed to get sensor data for node %(node)s. "
                    "Error: %(error)s"), {'node': node_uuid, 'error': str(e)})
            else:
                message['payload'] = self._filter_out_unsupported_types(
                                                              sensors_data)
                if message['payload']:
                    self.notifier.info(context, "hardware.ipmi.metrics",
                                       message)
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    def _filter_out_unsupported_types(self, sensors_data):
        # support the CONF.send_sensor_data_types sensor types only
        allowed = set(x.lower() for x in CONF.conductor.send_sensor_data_types)

        if 'all' in allowed:
            return sensors_data

        return dict((sensor_type, sensor_value) for (sensor_type, sensor_value)
            in sensors_data.items() if sensor_type.lower() in allowed)

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
    def set_boot_device(self, context, node_id, device, persistent=False):
        """Set the boot device for a node.

        Set the boot device to use on next reboot of the node.

        :param context: request context.
        :param node_id: node id or uuid.
        :param device: the boot device, one of
                       :mod:`ironic.common.boot_devices`.
        :param persistent: Whether to set next-boot, or make the change
                           permanent. Default: False.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.
        """
        LOG.debug('RPC set_boot_device called for node %(node)s with '
                  'device %(device)s', {'node': node_id, 'device': device})
        with task_manager.acquire(context, node_id) as task:
            node = task.node
            if not getattr(task.driver, 'management', None):
                raise exception.UnsupportedDriverExtension(
                            driver=node.driver, extension='management')
            task.driver.management.validate(task)
            task.driver.management.set_boot_device(task, device,
                                                   persistent=persistent)

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
    def get_boot_device(self, context, node_id):
        """Get the current boot device.

        Returns the current boot device of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: a dictionary containing:

            :boot_device: the boot device, one of
                :mod:`ironic.common.boot_devices` or None if it is unknown.
            :persistent: Whether the boot device will persist to all
                future boots or not, None if it is unknown.

        """
        LOG.debug('RPC get_boot_device called for node %s', node_id)
        with task_manager.acquire(context, node_id) as task:
            if not getattr(task.driver, 'management', None):
                raise exception.UnsupportedDriverExtension(
                            driver=task.node.driver, extension='management')
            task.driver.management.validate(task)
            return task.driver.management.get_boot_device(task)

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
    def get_supported_boot_devices(self, context, node_id):
        """Get the list of supported devices.

        Returns the list of supported boot devices of a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: A list with the supported boot devices defined
                  in :mod:`ironic.common.boot_devices`.

        """
        LOG.debug('RPC get_supported_boot_devices called for node %s', node_id)
        with task_manager.acquire(context, node_id, shared=True) as task:
            if not getattr(task.driver, 'management', None):
                raise exception.UnsupportedDriverExtension(
                            driver=task.node.driver, extension='management')
            return task.driver.management.get_supported_boot_devices()

    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.HardwareInspectionFailure,
                                   exception.InvalidStateRequested,
                                   exception.UnsupportedDriverExtension)
    def inspect_hardware(self, context, node_id):
        """Inspect hardware to obtain hardware properties.

        Initiate the inspection of a node. Validations are done
        synchronously and the actual inspection work is performed in
        background (asynchronously).

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support inspect.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: HardwareInspectionFailure when unable to get
                 essential scheduling properties from hardware.
        :raises: InvalidStateRequested if 'inspect' is not a
                 valid action to do in the current state.

        """
        LOG.debug('RPC inspect_hardware called for node %s', node_id)
        with task_manager.acquire(context, node_id, shared=False) as task:
            if not getattr(task.driver, 'inspect', None):
                raise exception.UnsupportedDriverExtension(
                      driver=task.node.driver, extension='inspect')

            try:
                task.driver.power.validate(task)
                task.driver.inspect.validate(task)
            except (exception.InvalidParameterValue,
                    exception.MissingParameterValue) as e:
                error = (_("RPC inspect_hardware failed to validate "
                           "inspection or power info. Error: %(msg)s")
                           % {'msg': e})
                raise exception.HardwareInspectionFailure(error=error)

            try:
                task.process_event('inspect',
                                   callback=self._spawn_worker,
                                   call_args=(_do_inspect_hardware, task),
                                   err_handler=provisioning_error_handler)

            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                        action='inspect', node=task.node.uuid,
                        state=task.node.provision_state)

    @periodic_task.periodic_task(
        spacing=CONF.conductor.check_provision_state_interval)
    def _check_inspect_timeouts(self, context):
        """Periodically checks inspect_timeout and fails upon reaching it.

        :param: context: request context

        """
        callback_timeout = CONF.conductor.inspect_timeout
        if not callback_timeout:
            return

        filters = {'reserved': False,
                   'provision_state': states.INSPECTING,
                   'inspection_started_before': callback_timeout}
        sort_key = 'inspection_started_at'
        last_error = _("timeout reached while inspecting the node")
        self._fail_if_in_state(context, filters, states.INSPECTING,
                               sort_key, last_error=last_error)

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
                with task_manager.acquire(context, node_uuid) as task:
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


def get_vendor_passthru_metadata(route_dict):
    d = {}
    for method, metadata in route_dict.iteritems():
        # 'func' is the vendor method reference, ignore it
        d[method] = {k: metadata[k] for k in metadata if k != 'func'}
    return d


def power_state_error_handler(e, node, power_state):
    """Set the node's power states if error occurs.

    This hook gets called upon an execption being raised when spawning
    the worker thread to change the power state of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param power_state: the power state to set on the node.

    """
    if isinstance(e, exception.NoFreeConductorWorker):
        node.power_state = power_state
        node.target_power_state = states.NOSTATE
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning(_LW("No free conductor workers available to perform "
                        "an action on node %(node)s, setting node's "
                        "power state back to %(power_state)s."),
                        {'node': node.uuid, 'power_state': power_state})


def provisioning_error_handler(e, node, provision_state,
                                target_provision_state):
    """Set the node's provisioning states if error occurs.

    This hook gets called upon an exception being raised when spawning
    the worker to do the deployment or tear down of a node.

    :param e: the exception object that was raised.
    :param node: an Ironic node object.
    :param provision_state: the provision state to be set on
        the node.
    :param target_provision_state: the target provision state to be
        set on the node.

    """
    if isinstance(e, exception.NoFreeConductorWorker):
        # NOTE(deva): there is no need to clear conductor_affinity
        #             because it isn't updated on a failed deploy
        node.provision_state = provision_state
        node.target_provision_state = target_provision_state
        node.last_error = (_("No free conductor workers available"))
        node.save()
        LOG.warning(_LW("No free conductor workers available to perform "
                        "an action on node %(node)s, setting node's "
                        "provision_state back to %(prov_state)s and "
                        "target_provision_state to %(tgt_prov_state)s."),
                    {'node': node.uuid, 'prov_state': provision_state,
                     'tgt_prov_state': target_provision_state})


def _get_configdrive_obj_name(node):
    """Generate the object name for the config drive."""
    return 'configdrive-%s' % node.uuid


def _store_configdrive(node, configdrive):
    """Handle the storage of the config drive.

    If configured, the config drive data are uploaded to Swift. The Node's
    instance_info is updated to include either the temporary Swift URL
    from the upload, or if no upload, the actual config drive data.

    :param node: an Ironic node object.
    :param configdrive: A gzipped and base64 encoded configdrive.
    :raises: SwiftOperationError if an error occur when uploading the
             config drive to Swift.

    """
    if CONF.conductor.configdrive_use_swift:
        # NOTE(lucasagomes): No reason to use a different timeout than
        # the one used for deploying the node
        timeout = CONF.conductor.deploy_callback_timeout
        container = CONF.conductor.configdrive_swift_container
        object_name = _get_configdrive_obj_name(node)

        object_headers = {'X-Delete-After': timeout}

        with tempfile.NamedTemporaryFile() as fileobj:
            fileobj.write(configdrive)
            fileobj.flush()

            swift_api = swift.SwiftAPI()
            swift_api.create_object(container, object_name, fileobj.name,
                                    object_headers=object_headers)
            configdrive = swift_api.get_temp_url(container, object_name,
                                                 timeout)

    i_info = node.instance_info
    i_info['configdrive'] = configdrive
    node.instance_info = i_info


def do_node_deploy(task, conductor_id, configdrive=None):
    """Prepare the environment and deploy a node."""
    node = task.node

    def handle_failure(e, task, logmsg, errmsg):
        # NOTE(deva): there is no need to clear conductor_affinity
        task.process_event('fail')
        args = {'node': task.node.uuid, 'err': e}
        LOG.warning(logmsg, args)
        node.last_error = errmsg % e

    try:
        try:
            if configdrive:
                _store_configdrive(node, configdrive)
        except exception.SwiftOperationError as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e, task,
                    _LW('Error while uploading the configdrive for '
                        '%(node)s to Swift'),
                    _('Failed to upload the configdrive to Swift. '
                      'Error: %s'))

        try:
            task.driver.deploy.prepare(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e, task,
                    _LW('Error while preparing to deploy to node %(node)s: '
                        '%(err)s'),
                    _("Failed to prepare to deploy. Error: %s"))

        try:
            new_state = task.driver.deploy.deploy(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e, task,
                    _LW('Error in deploy of node %(node)s: %(err)s'),
                    _("Failed to deploy. Error: %s"))

        # Update conductor_affinity to reference this conductor's ID
        # since there may be local persistent state
        node.conductor_affinity = conductor_id

        # NOTE(deva): Some drivers may return states.DEPLOYWAIT
        #             eg. if they are waiting for a callback
        if new_state == states.DEPLOYDONE:
            task.process_event('done')
            LOG.info(_LI('Successfully deployed node %(node)s with '
                         'instance %(instance)s.'),
                     {'node': node.uuid, 'instance': node.instance_uuid})
        elif new_state == states.DEPLOYWAIT:
            task.process_event('wait')
        else:
            LOG.error(_LE('Unexpected state %(state)s returned while '
                          'deploying node %(node)s.'),
                          {'state': new_state, 'node': node.uuid})
    finally:
        node.save()


def handle_sync_power_state_max_retries_exceeded(task,
                                                 actual_power_state):
    node = task.node
    msg = (_("During sync_power_state, max retries exceeded "
              "for node %(node)s, node state %(actual)s "
              "does not match expected state '%(state)s'. "
              "Updating DB state to '%(actual)s' "
              "Switching node to maintenance mode.") %
              {'node': node.uuid, 'actual': actual_power_state,
               'state': node.power_state})
    node.power_state = actual_power_state
    node.last_error = msg
    node.maintenance = True
    node.maintenance_reason = msg
    node.save()
    LOG.error(msg)


def do_sync_power_state(task, count):
    """Sync the power state for this node, incrementing the counter on failure.

    When the limit of power_state_sync_max_retries is reached, the node is put
    into maintenance mode and the error recorded.

    :param task: a TaskManager instance with an exclusive lock
    :param count: number of times this node has previously failed a sync
    :returns: Count of failed attempts.
              On success, the counter is set to 0.
              On failure, the count is incremented by one
    """
    node = task.node
    power_state = None
    count += 1

    # If power driver info can not be validated, and node has no prior state,
    # do not attempt to sync the node's power state.
    if node.power_state is None:
        try:
            task.driver.power.validate(task)
        except (exception.InvalidParameterValue,
                exception.MissingParameterValue):
            return 0

    try:
        # The driver may raise an exception, or may return ERROR.
        # Handle both the same way.
        power_state = task.driver.power.get_power_state(task)
        if power_state == states.ERROR:
            raise exception.PowerStateFailure(
                    _("Power driver returned ERROR state "
                      "while trying to sync power state."))
    except Exception as e:
        # Stop if any exception is raised when getting the power state
        LOG.warning(_LW("During sync_power_state, could not get power "
                        "state for node %(node)s. Error: %(err)s."),
                        {'node': node.uuid, 'err': e})
        if count > CONF.conductor.power_state_sync_max_retries:
            handle_sync_power_state_max_retries_exceeded(task, power_state)
        return count
    else:
        # If node has no prior state AND we successfully got a state,
        # simply record that.
        if node.power_state is None:
            LOG.info(_LI("During sync_power_state, node %(node)s has no "
                         "previous known state. Recording current state "
                         "'%(state)s'."),
                         {'node': node.uuid, 'state': power_state})
            node.power_state = power_state
            node.save()
            return 0

    # If the node is now in the expected state, reset the counter
    # otherwise, if we've exceeded the retry limit, stop here
    if node.power_state == power_state:
        return 0
    else:
        if count > CONF.conductor.power_state_sync_max_retries:
            handle_sync_power_state_max_retries_exceeded(task, power_state)
            return count

    if CONF.conductor.force_power_state_during_sync:
        LOG.warning(_LW("During sync_power_state, node %(node)s state "
                        "'%(actual)s' does not match expected state. "
                        "Changing hardware state to '%(state)s'."),
                        {'node': node.uuid, 'actual': power_state,
                         'state': node.power_state})
        try:
            # node_power_action will update the node record
            # so don't do that again here.
            utils.node_power_action(task, node.power_state)
        except Exception as e:
            attempts_left = (CONF.conductor.power_state_sync_max_retries -
                             count)
            LOG.error(_LE("Failed to change power state of node %(node)s "
                "to '%(state)s'. Attempts left: %(left)s."),
                {'node': node.uuid,
                 'state': node.power_state,
                 'left': attempts_left})
    else:
        LOG.warning(_LW("During sync_power_state, node %(node)s state "
                        "does not match expected state '%(state)s'. "
                        "Updating recorded state to '%(actual)s'."),
                        {'node': node.uuid, 'actual': power_state,
                         'state': node.power_state})
        node.power_state = power_state
        node.save()

    return count


def _do_inspect_hardware(task):
    """Initiates inspection.

    :param: task: a TaskManager instance with an exclusive lock
                  on its node.
    :raises: HardwareInspectionFailure if driver doesn't
             return the state as states.MANAGEABLE or
             states.INSPECTING.

    """
    node = task.node

    def handle_failure(e):
        node.last_error = e
        task.process_event('fail')
        LOG.error(_LE("Failed to inspect node %(node)s: %(err)s"),
                  {'node': node.uuid, 'err': e})

    try:
        new_state = task.driver.inspect.inspect_hardware(task)

    except Exception as e:
        with excutils.save_and_reraise_exception():
            error = str(e)
            handle_failure(error)

    if new_state == states.MANAGEABLE:
        task.process_event('done')
        LOG.info(_LI('Successfully inspected node %(node)s')
                 % {'node': node.uuid})
    elif new_state != states.INSPECTING:
        error = (_("During inspection, driver returned unexpected "
                   "state %(state)s") % {'state': new_state})
        handle_failure(error)
        raise exception.HardwareInspectionFailure(error=error)


def cleaning_error_handler(task, msg):
    """Put a failed node in CLEANFAIL or ZAPFAIL and maintenance."""
    # Reset clean step, msg should include current step
    if task.node.provision_state == states.CLEANING:
        task.node.clean_step = {}
    task.node.last_error = msg
    task.node.maintenance = True
    task.node.maintenance_reason = msg
    task.node.save()
    task.process_event('fail')


def _step_key(step):
    """Sort by priority, then interface priority in event of tie.

    :param step: cleaning step dict to get priority for.
    """
    return (step.get('priority'),
            CLEANING_INTERFACE_PRIORITY[step.get('interface')])


def _get_cleaning_steps(task, enabled=False):
    """Get sorted cleaning steps for task.node

    :param task: A TaskManager object
    :param enabled: If True, returns only enabled (priority > 0) steps. If
        False, returns all clean steps.
    :returns: A list of clean steps dictionaries, sorted with largest priority
        as the first item
    """
    # Iterate interfaces and get clean steps from each
    steps = list()
    for interface in CLEANING_INTERFACE_PRIORITY:
        interface = getattr(task.driver, interface)
        if interface:
            interface_steps = [x for x in interface.get_clean_steps(task)
                               if not enabled or x['priority'] > 0]
            steps.extend(interface_steps)
    # Sort the steps from higher priority to lower priority
    return sorted(steps, key=_step_key, reverse=True)


def set_node_cleaning_steps(task):
    """Get the list of clean steps, save them to the node."""
    # Get the prioritized steps, store them.
    node = task.node
    driver_info = node.driver_internal_info
    driver_info['clean_steps'] = _get_cleaning_steps(task, enabled=True)
    node.driver_internal_info = driver_info
    node.clean_step = {}
    node.save()
