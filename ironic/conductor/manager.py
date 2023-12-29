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

A `tooz.hashring.HashRing
<https://opendev.org/openstack/tooz/src/branch/master/tooz/hashring.py>`_
is used to distribute nodes across the set of active conductors which support
each node's driver.  Rebalancing this ring can trigger various actions by each
conductor, such as building or tearing down the TFTP environment for a node,
notifying Neutron of a change, etc.
"""

import collections
import datetime
import queue

import eventlet
from futurist import waiters
from ironic_lib import metrics_utils
from oslo_log import log
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import faults
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import nova
from ironic.common import states
from ironic.conductor import allocations
from ironic.conductor import base_manager
from ironic.conductor import cleaning
from ironic.conductor import deployments
from ironic.conductor import inspection
from ironic.conductor import notification_utils as notify_utils
from ironic.conductor import periodics
from ironic.conductor import servicing
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.conductor import verify
from ironic.conf import CONF
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import image_cache
from ironic.drivers.modules import image_utils
from ironic.drivers.modules import inspect_utils
from ironic import objects
from ironic.objects import base as objects_base
from ironic.objects import fields

LOG = log.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

SYNC_EXCLUDED_STATES = (states.DEPLOYWAIT, states.CLEANWAIT, states.ENROLL,
                        states.ADOPTFAIL)


class ConductorManager(base_manager.BaseConductorManager):
    """Ironic Conductor manager main class."""

    # NOTE(rloo): This must be in sync with rpcapi.ConductorAPI's.
    # NOTE(pas-ha): This also must be in sync with
    #               ironic.common.release_mappings.RELEASE_MAPPING['master']
    RPC_API_VERSION = '1.59'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, host, topic):
        super(ConductorManager, self).__init__(host, topic)
        # NOTE(TheJulia): This is less a metric-able count, but a means to
        # sort out nodes and prioritise a subset (of non-responding nodes).
        self.power_state_sync_count = collections.defaultdict(int)

    @METRICS.timer('ConductorManager._clean_up_caches')
    @periodics.periodic(spacing=CONF.conductor.cache_clean_up_interval,
                        enabled=CONF.conductor.cache_clean_up_interval > 0)
    def _clean_up_caches(self, context):
        image_cache.clean_up_all()

    @METRICS.timer('ConductorManager.create_node')
    # No need to add these since they are subclasses of InvalidParameterValue:
    #     InterfaceNotFoundInEntrypoint
    #     IncompatibleInterface,
    #     NoValidDefaultForInterface
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.DriverNotFound)
    def create_node(self, context, node_obj):
        """Create a node in database.

        :param context: an admin context
        :param node_obj: a created (but not saved to the database) node object.
        :returns: created node object.
        :raises: InterfaceNotFoundInEntrypoint if validation fails for any
                 dynamic interfaces (e.g. network_interface).
        :raises: IncompatibleInterface if one or more of the requested
                 interfaces are not compatible with the hardware type.
        :raises: NoValidDefaultForInterface if no default can be calculated
                 for some interfaces, and explicit values must be provided.
        :raises: InvalidParameterValue if some fields fail validation.
        :raises: DriverNotFound if the driver or hardware type is not found.
        """
        LOG.debug("RPC create_node called for node %s.", node_obj.uuid)
        driver_factory.check_and_update_node_interfaces(node_obj)
        node_obj.create()
        return node_obj

    def _check_update_protected(self, node_obj, delta):
        if 'protected' in delta:
            if not node_obj.protected:
                node_obj.protected_reason = None
            elif node_obj.provision_state not in (states.ACTIVE,
                                                  states.RESCUE):
                raise exception.InvalidState(
                    "Node %(node)s can only be made protected in provision "
                    "states 'active' or 'rescue', the current state is "
                    "'%(state)s'" %
                    {'node': node_obj.uuid, 'state': node_obj.provision_state})

        if ('protected_reason' in delta and node_obj.protected_reason and not
                node_obj.protected):
            raise exception.InvalidParameterValue(
                "The protected_reason field can only be set when "
                "protected is True")

    def _check_update_retired(self, node_obj, delta):
        if 'retired' in delta:
            if not node_obj.retired:
                node_obj.retired_reason = None
            elif node_obj.provision_state == states.AVAILABLE:
                raise exception.InvalidState(
                    "Node %(node)s can not have 'retired' set in provision "
                    "state 'available', the current state is '%(state)s'" %
                    {'node': node_obj.uuid, 'state': node_obj.provision_state})

        if ('retired_reason' in delta and node_obj.retired_reason and not
                node_obj.retired):
            raise exception.InvalidParameterValue(
                "The retired_reason field can only be set when "
                "retired is True")

    @METRICS.timer('ConductorManager.update_node')
    # No need to add these since they are subclasses of InvalidParameterValue:
    #     InterfaceNotFoundInEntrypoint
    #     IncompatibleInterface,
    #     NoValidDefaultForInterface
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NodeLocked,
                                   exception.InvalidState,
                                   exception.DriverNotFound)
    def update_node(self, context, node_obj, reset_interfaces=False):
        """Update a node with the supplied data.

        This method is the main "hub" for PUT and PATCH requests in the API.
        It ensures that the requested change is safe to perform,
        validates the parameters with the node's driver, if necessary.

        :param context: an admin context
        :param node_obj: a changed (but not saved) node object.
        :param reset_interfaces: whether to reset hardware interfaces to their
                                 defaults.
        :raises: NoValidDefaultForInterface if no default can be calculated
                 for some interfaces, and explicit values must be provided.
        """
        node_id = node_obj.uuid
        LOG.debug("RPC update_node called for node %s.", node_id)

        # NOTE(jroll) clear maintenance_reason if node.update sets
        # maintenance to False for backwards compatibility, for tools
        # not using the maintenance endpoint.
        # NOTE(kaifeng) also clear fault when out of maintenance.
        delta = node_obj.obj_what_changed()
        if 'maintenance' in delta and not node_obj.maintenance:
            node_obj.maintenance_reason = None
            node_obj.fault = None

        self._check_update_protected(node_obj, delta)
        self._check_update_retired(node_obj, delta)

        # TODO(dtantsur): reconsider allowing changing some (but not all)
        # interfaces for active nodes in the future.
        # NOTE(kaifeng): INSPECTING is allowed to keep backwards
        # compatibility, starting from API 1.39 node update is disallowed
        # in this state.
        allowed_update_states = [states.ENROLL, states.INSPECTING,
                                 states.INSPECTWAIT, states.MANAGEABLE,
                                 states.AVAILABLE]
        action = _("Node %(node)s can not have %(field)s "
                   "updated unless it is in one of allowed "
                   "(%(allowed)s) states or in maintenance mode.")
        updating_driver = 'driver' in delta
        check_interfaces = updating_driver
        for iface in drivers_base.ALL_INTERFACES:
            interface_field = '%s_interface' % iface
            if interface_field not in delta:
                if updating_driver and reset_interfaces:
                    setattr(node_obj, interface_field, None)

                continue

            if not (node_obj.provision_state in allowed_update_states
                    or node_obj.maintenance):
                raise exception.InvalidState(
                    action % {'node': node_obj.uuid,
                              'allowed': ', '.join(allowed_update_states),
                              'field': interface_field})

            check_interfaces = True

        if check_interfaces:
            driver_factory.check_and_update_node_interfaces(node_obj)

        # NOTE(dtantsur): if we're updating the driver from an invalid value,
        # loading the old driver may be impossible. Since we only need to
        # update the node record in the database, skip loading the driver
        # completely.
        with task_manager.acquire(context, node_id, shared=False,
                                  load_driver=False,
                                  purpose='node update') as task:
            # Prevent instance_uuid overwriting
            if ('instance_uuid' in delta and node_obj.instance_uuid
                and task.node.instance_uuid):
                raise exception.NodeAssociated(
                    node=node_id, instance=task.node.instance_uuid)

            # NOTE(dtantsur): if the resource class is changed for an active
            # instance, nova will not update its internal record. That will
            # result in the new resource class exposed on the node as available
            # for consumption, and nova may try to schedule on this node again.
            if ('resource_class' in delta and task.node.resource_class
                    and task.node.provision_state
                    not in allowed_update_states):
                action = _("Node %(node)s can not have resource_class "
                           "updated unless it is in one of allowed "
                           "(%(allowed)s) states.")
                raise exception.InvalidState(
                    action % {'node': node_obj.uuid,
                              'allowed': ', '.join(allowed_update_states)})

            if ('instance_uuid' in delta and task.node.allocation_id
                    and not node_obj.instance_uuid):
                if (not task.node.maintenance and task.node.provision_state
                        not in allowed_update_states):
                    action = _("Node %(node)s with an allocation can not have "
                               "instance_uuid removed unless it is in one of "
                               "allowed (%(allowed)s) states or in "
                               "maintenance mode.")
                    raise exception.InvalidState(
                        action % {'node': node_obj.uuid,
                                  'allowed': ', '.join(allowed_update_states)})

                try:
                    allocation = objects.Allocation.get_by_id(
                        context, task.node.allocation_id)
                    allocation.destroy()
                except exception.AllocationNotFound:
                    pass

            node_obj.save()

        return node_obj

    @METRICS.timer('ConductorManager.change_node_power_state')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NoFreeConductorWorker,
                                   exception.NodeLocked)
    def change_node_power_state(self, context, node_id, new_state,
                                timeout=None):
        """RPC method to encapsulate changes to a node's state.

        Perform actions such as power on, power off. The validation is
        performed synchronously, and if successful, the power action is
        updated in the background (asynchronously). Once the power action
        is finished and successful, it updates the power_state for the
        node with the new power state.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired power state of the node.
        :param timeout: timeout (in seconds) positive integer (> 0) for any
          power state. ``None`` indicates to use default timeout.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InvalidParameterValue
        :raises: MissingParameterValue

        """
        LOG.debug("RPC change_node_power_state called for node %(node)s. "
                  "The desired new state is %(state)s.",
                  {'node': node_id, 'state': new_state})

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='changing node power state') as task:
            task.driver.power.validate(task)

            if (new_state not in
                task.driver.power.get_supported_power_states(task)):
                # FIXME(naohirot):
                # After driver composition, we should print power interface
                # name here instead of driver.
                raise exception.InvalidParameterValue(
                    _('The driver %(driver)s does not support the power state,'
                      ' %(state)s') %
                    {'driver': task.node.driver, 'state': new_state})

            if new_state in (states.SOFT_REBOOT, states.SOFT_POWER_OFF):
                power_timeout = (timeout
                                 or CONF.conductor.soft_power_off_timeout)
            else:
                power_timeout = timeout

            # Set the target_power_state and clear any last_error, since we're
            # starting a new operation. This will expose to other processes
            # and clients that work is in progress.
            if new_state in (states.POWER_ON, states.REBOOT,
                             states.SOFT_REBOOT):
                task.node.target_power_state = states.POWER_ON
            else:
                task.node.target_power_state = states.POWER_OFF

            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(utils.power_state_error_handler,
                                      task.node, task.node.power_state)
            task.spawn_after(self._spawn_worker, utils.node_power_action,
                             task, new_state, timeout=power_timeout)

    @METRICS.timer('ConductorManager.change_node_boot_mode')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NoFreeConductorWorker,
                                   exception.NodeLocked)
    def change_node_boot_mode(self, context, node_id, new_state):
        """RPC method to encapsulate changes to a node's boot_mode.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired boot mode for the node.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InvalidParameterValue
        """
        LOG.debug("RPC change_node_boot_mode called for node %(node)s. "
                  "The desired new state is %(state)s.",
                  {'node': node_id, 'state': new_state})
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='changing node boot mode') as task:
            task.driver.management.validate(task)
            # Starting new operation, so clear the previous error.
            # We'll be putting an error here soon if we fail task.
            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(utils._spawn_error_handler,
                                      task.node, "changing node boot mode")
            task.spawn_after(self._spawn_worker,
                             utils.node_change_boot_mode, task, new_state)

    @METRICS.timer('ConductorManager.change_node_secure_boot')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NoFreeConductorWorker,
                                   exception.NodeLocked)
    def change_node_secure_boot(self, context, node_id, new_state):
        """RPC method to encapsulate changes to a node's secure_boot state.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired secure_boot state for the node.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InvalidParameterValue
        """
        LOG.debug("RPC change_node_secure_boot called for node %(node)s. "
                  "The desired new state is %(state)s.",
                  {'node': node_id, 'state': new_state})
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='changing node secure') as task:
            task.driver.management.validate(task)
            # Starting new operation, so clear the previous error.
            # We'll be putting an error here soon if we fail task.
            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(utils._spawn_error_handler,
                                      task.node, "changing node secure boot")
            task.spawn_after(self._spawn_worker,
                             utils.node_change_secure_boot, task, new_state)

    @METRICS.timer('ConductorManager.vendor_passthru')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InvalidParameterValue,
                                   exception.UnsupportedDriverExtension)
    def vendor_passthru(self, context, node_id, driver_method,
                        http_method, info):
        """RPC method to encapsulate vendor action.

        Synchronously validate driver specific info, and if successful invoke
        the vendor method. If the method mode is 'async' the conductor will
        start background worker to perform vendor action.

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
        :raises: NodeLocked if the vendor passthru method requires an exclusive
                 lock but the node is locked by another conductor
        :returns: A dictionary containing:

            :return: The response of the invoked vendor method
            :async: Boolean value. Whether the method was invoked
                asynchronously (True) or synchronously (False). When invoked
                asynchronously the response will be always None.
            :attach: Boolean value. Whether to attach the response of
                the invoked vendor method to the HTTP response object (True)
                or return it in the response body (False).

        """
        LOG.debug("RPC vendor_passthru called for node %s.", node_id)
        # NOTE(mariojv): Not all vendor passthru methods require an exclusive
        # lock on a node, so we acquire a shared lock initially. If a method
        # requires an exclusive lock, we'll acquire one after checking
        # vendor_opts before starting validation.
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose='calling vendor passthru') as task:
            vendor_iface = task.driver.vendor

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

            # Change shared lock to exclusive if a vendor method requires
            # it. Vendor methods default to requiring an exclusive lock.
            if vendor_opts['require_exclusive_lock']:
                task.upgrade_lock()

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

            return {'return': ret,
                    'async': is_async,
                    'attach': vendor_opts['attach']}

    @METRICS.timer('ConductorManager.driver_vendor_passthru')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.InvalidParameterValue,
                                   exception.UnsupportedDriverExtension,
                                   exception.DriverNotFound,
                                   exception.NoValidDefaultForInterface,
                                   exception.InterfaceNotFoundInEntrypoint)
    def driver_vendor_passthru(self, context, driver_name, driver_method,
                               http_method, info):
        """Handle top-level vendor actions.

        RPC method which handles driver-level vendor passthru calls. These
        calls don't require a node UUID and are executed on a random
        conductor with the specified driver. If the method mode is
        async the conductor will start background worker to perform
        vendor action.

        For dynamic drivers, the calculated default vendor interface is used.

        :param context: an admin context.
        :param driver_name: name of the driver or hardware type on which to
                            call the method.
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
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's vendor
                 interface.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :returns: A dictionary containing:

            :return: The response of the invoked vendor method
            :async: Boolean value. Whether the method was invoked
                asynchronously (True) or synchronously (False). When invoked
                asynchronously the response will be always None.
            :attach: Boolean value. Whether to attach the response of
                the invoked vendor method to the HTTP response object (True)
                or return it in the response body (False).

        """
        # Any locking in a top-level vendor action will need to be done by the
        # implementation, as there is little we could reasonably lock on here.
        LOG.debug("RPC driver_vendor_passthru for driver %s.", driver_name)
        driver = driver_factory.get_hardware_type(driver_name)
        vendor = None
        vendor_name = driver_factory.default_interface(
            driver, 'vendor', driver_name=driver_name)
        vendor = driver_factory.get_interface(driver, 'vendor',
                                              vendor_name)

        try:
            vendor_opts = vendor.driver_routes[driver_method]
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
        vendor.driver_validate(method=driver_method, **info)

        if is_async:
            self._spawn_worker(vendor_func, context, **info)
        else:
            ret = vendor_func(context, **info)

        return {'return': ret,
                'async': is_async,
                'attach': vendor_opts['attach']}

    @METRICS.timer('ConductorManager.get_node_vendor_passthru_methods')
    @messaging.expected_exceptions(exception.UnsupportedDriverExtension)
    def get_node_vendor_passthru_methods(self, context, node_id):
        """Retrieve information about vendor methods of the given node.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        LOG.debug("RPC get_node_vendor_passthru_methods called for node %s",
                  node_id)
        lock_purpose = 'listing vendor passthru methods'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            return get_vendor_passthru_metadata(
                task.driver.vendor.vendor_routes)

    @METRICS.timer('ConductorManager.get_driver_vendor_passthru_methods')
    @messaging.expected_exceptions(exception.UnsupportedDriverExtension,
                                   exception.DriverNotFound,
                                   exception.NoValidDefaultForInterface,
                                   exception.InterfaceNotFoundInEntrypoint)
    def get_driver_vendor_passthru_methods(self, context, driver_name):
        """Retrieve information about vendor methods of the given driver.

        For dynamic drivers, the default vendor interface is used.

        :param context: an admin context.
        :param driver_name: name of the driver or hardware_type
        :raises: UnsupportedDriverExtension if current driver does not have
                 vendor interface.
        :raises: DriverNotFound if the supplied driver is not loaded.
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's vendor
                 interface.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        # Any locking in a top-level vendor action will need to be done by the
        # implementation, as there is little we could reasonably lock on here.
        LOG.debug("RPC get_driver_vendor_passthru_methods for driver %s",
                  driver_name)
        driver = driver_factory.get_hardware_type(driver_name)
        vendor = None
        vendor_name = driver_factory.default_interface(
            driver, 'vendor', driver_name=driver_name)
        vendor = driver_factory.get_interface(driver, 'vendor',
                                              vendor_name)

        return get_vendor_passthru_metadata(vendor.driver_routes)

    @METRICS.timer('ConductorManager.do_node_rescue')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeInMaintenance,
                                   exception.NodeLocked,
                                   exception.InstanceRescueFailure,
                                   exception.InvalidStateRequested,
                                   exception.UnsupportedDriverExtension
                                   )
    def do_node_rescue(self, context, node_id, rescue_password):
        """RPC method to rescue an existing node deployment.

        Validate driver specific information synchronously, and then
        spawn a background worker to rescue the node asynchronously.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param rescue_password: string to be set as the password inside the
            rescue environment.
        :raises: InstanceRescueFailure if the node cannot be placed into
                 rescue mode.
        :raises: InvalidStateRequested if the state transition is not supported
                 or allowed.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: NodeLocked if the node is locked by another conductor.
        :raises: NodeInMaintenance if the node is in maintenance mode.
        :raises: UnsupportedDriverExtension if rescue interface is not
                 supported by the driver.
        """
        LOG.debug("RPC do_node_rescue called for node %s.", node_id)

        with task_manager.acquire(context,
                                  node_id, purpose='node rescue') as task:

            node = task.node
            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('rescuing'),
                                                  node=node.uuid)

            # Record of any pre-existing agent_url should be removed.
            utils.wipe_token_and_url(task)

            # driver validation may check rescue_password, so save it on the
            # node early
            i_info = node.instance_info
            i_info['rescue_password'] = rescue_password
            i_info['hashed_rescue_password'] = utils.hash_password(
                rescue_password)
            node.instance_info = i_info
            node.save()

            try:
                task.driver.power.validate(task)
                task.driver.rescue.validate(task)
                task.driver.network.validate(task)
            except (exception.InvalidParameterValue,
                    exception.UnsupportedDriverExtension,
                    exception.MissingParameterValue) as e:
                utils.remove_node_rescue_password(node, save=True)
                raise exception.InstanceRescueFailure(
                    instance=node.instance_uuid,
                    node=node.uuid,
                    reason=_("Validation failed: %s") % e)
            try:
                task.process_event(
                    'rescue',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_rescue, task),
                    err_handler=utils.spawn_rescue_error_handler)
            except exception.InvalidState:
                utils.remove_node_rescue_password(node, save=True)
                raise exception.InvalidStateRequested(
                    action='rescue', node=node.uuid,
                    state=node.provision_state)

    def _do_node_rescue(self, task):
        """Internal RPC method to rescue an existing node deployment."""
        node = task.node

        def handle_failure(e, errmsg, log_func=LOG.error):
            utils.remove_node_rescue_password(node, save=False)
            error = errmsg % e
            utils.node_history_record(task.node, event=error,
                                      event_type=states.RESCUE,
                                      error=True,
                                      user=task.context.user_id)
            task.process_event('fail')
            log_func('Error while performing rescue operation for node '
                     '%(node)s with instance %(instance)s: %(err)s',
                     {'node': node.uuid, 'instance': node.instance_uuid,
                      'err': e})

        try:
            next_state = task.driver.rescue.rescue(task)
        except exception.IronicException as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e,
                               _('Failed to rescue: %s'))
        except Exception as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e,
                               _('Failed to rescue. Exception: %s'),
                               log_func=LOG.exception)
        if next_state == states.RESCUEWAIT:
            task.process_event('wait')
        elif next_state == states.RESCUE:
            task.process_event('done')
        else:
            error = (_("Driver returned unexpected state %s") % next_state)
            handle_failure(error,
                           _('Failed to rescue: %s'))

    @METRICS.timer('ConductorManager.do_node_unrescue')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeInMaintenance,
                                   exception.NodeLocked,
                                   exception.InstanceUnrescueFailure,
                                   exception.InvalidStateRequested,
                                   exception.UnsupportedDriverExtension
                                   )
    def do_node_unrescue(self, context, node_id):
        """RPC method to unrescue a node in rescue mode.

        Validate driver specific information synchronously, and then
        spawn a background worker to unrescue the node asynchronously.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InstanceUnrescueFailure if the node fails to be unrescued
        :raises: InvalidStateRequested if the state transition is not supported
                 or allowed.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: NodeLocked if the node is locked by another conductor.
        :raises: NodeInMaintenance if the node is in maintenance mode.
        :raises: UnsupportedDriverExtension if rescue interface is not
                 supported by the driver.
        """
        LOG.debug("RPC do_node_unrescue called for node %s.", node_id)

        with task_manager.acquire(context, node_id,
                                  purpose='node unrescue') as task:
            node = task.node
            # Record of any pre-existing agent_url should be removed,
            # Not that there should be.
            utils.remove_agent_url(node)
            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('unrescuing'),
                                                  node=node.uuid)
            try:
                task.driver.power.validate(task)
            except (exception.InvalidParameterValue,
                    exception.MissingParameterValue) as e:
                raise exception.InstanceUnrescueFailure(
                    instance=node.instance_uuid,
                    node=node.uuid,
                    reason=_("Validation failed: %s") % e)

            try:
                task.process_event(
                    'unrescue',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_unrescue, task),
                    err_handler=utils.provisioning_error_handler)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='unrescue', node=node.uuid,
                    state=node.provision_state)

    def _do_node_unrescue(self, task):
        """Internal RPC method to unrescue a node in rescue mode."""
        node = task.node

        def handle_failure(e, errmsg, log_func=LOG.error):
            error = errmsg % e
            utils.node_history_record(task.node, event=error,
                                      event_type=states.RESCUE,
                                      error=True,
                                      user=task.context.user_id)
            task.process_event('fail')
            log_func('Error while performing unrescue operation for node '
                     '%(node)s with instance %(instance)s: %(err)s',
                     {'node': node.uuid, 'instance': node.instance_uuid,
                      'err': e})

        try:
            next_state = task.driver.rescue.unrescue(task)
        except exception.IronicException as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e,
                               _('Failed to unrescue: %s'))
        except Exception as e:
            with excutils.save_and_reraise_exception():
                handle_failure(e,
                               _('Failed to unrescue. Exception: %s'),
                               log_func=LOG.exception)

        utils.wipe_token_and_url(task)

        if next_state == states.ACTIVE:
            task.process_event('done')
        else:
            error = (_("Driver returned unexpected state %s") % next_state)
            handle_failure(error,
                           _('Failed to unrescue: %s'))

    @task_manager.require_exclusive_lock
    def _do_node_rescue_abort(self, task):
        """Internal method to abort an ongoing rescue operation.

        :param task: a TaskManager instance with an exclusive lock
        """
        node = task.node
        try:
            task.driver.rescue.clean_up(task)
        except Exception as e:
            LOG.exception('Failed to clean up rescue for node %(node)s '
                          'after aborting the operation: %(err)s',
                          {'node': node.uuid, 'err': e})
            error_msg = _('Failed to clean up rescue after aborting '
                          'the operation')
            node.refresh()
            utils.node_history_record(node, event=error_msg,
                                      event_type=states.RESCUE, error=True,
                                      user=task.context.user_id)
            node.maintenance = True
            node.maintenance_reason = error_msg
            node.fault = faults.RESCUE_ABORT_FAILURE
            node.save()
            return

        info_message = _('Rescue operation aborted for node %s.') % node.uuid
        # NOTE(TheJulia): This "error" is not an actual error, the operation
        # has been aborted and the node returned to normal operation.
        error = _('By request, the rescue operation was aborted.')
        utils.node_history_record(task.node, event=error,
                                  event_type=states.RESCUE,
                                  error=False,
                                  user=task.context.user_id)
        node.refresh()
        utils.remove_agent_url(node)
        node.save()
        LOG.info(info_message)

    @METRICS.timer('ConductorManager.do_node_deploy')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.NodeInMaintenance,
                                   exception.InstanceDeployFailure,
                                   exception.InvalidStateRequested,
                                   exception.NodeProtected,
                                   exception.ConcurrentActionLimit)
    def do_node_deploy(self, context, node_id, rebuild=False,
                       configdrive=None, deploy_steps=None):
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
        :param deploy_steps: Optional. Deploy steps.
        :raises: InstanceDeployFailure
        :raises: NodeInMaintenance if the node is in maintenance mode.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: InvalidStateRequested when the requested state is not a valid
                 target from the current state.
        :raises: NodeProtected if the node is protected.
        :raises: ConcurrentActionLimit if this action would exceed the maximum
                 number of configured concurrent actions of this type.
        """
        LOG.debug("RPC do_node_deploy called for node %s.", node_id)
        self._concurrent_action_limit(action='provisioning')
        event = 'rebuild' if rebuild else 'deploy'

        # NOTE(comstud): If the _sync_power_states() periodic task happens
        # to have locked this node, we'll fail to acquire the lock. The
        # client should perhaps retry in this case unless we decide we
        # want to add retries or extra synchronization here.
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node deployment') as task:
            deployments.validate_node(task, event=event)
            deployments.start_deploy(task, self, configdrive, event=event,
                                     deploy_steps=deploy_steps)

    @METRICS.timer('ConductorManager.continue_node_deploy')
    def continue_node_deploy(self, context, node_id):
        """RPC method to continue deploying a node.

        This is useful for deploying tasks that are async. When they complete,
        they call back via RPC, a new worker and lock are set up, and deploying
        continues. This can also be used to resume deploying on take_over.

        :param context: an admin context.
        :param node_id: the ID or UUID of a node.
        :raises: InvalidStateRequested if the node is not in DEPLOYWAIT state
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node no longer appears in the database

        """
        LOG.debug("RPC continue_node_deploy called for node %s.", node_id)
        with task_manager.acquire(context, node_id, shared=False, patient=True,
                                  purpose='continue node deploying') as task:
            node = task.node

            # FIXME(rloo): This should be states.DEPLOYWAIT, but we're using
            # this temporarily to get control back to the conductor, to finish
            # the deployment. Once we split up the deployment into separate
            # deploy steps and after we've crossed a rolling-upgrade boundary,
            # we should be able to check for DEPLOYWAIT only.
            expected_states = [states.DEPLOYWAIT, states.DEPLOYING]
            if node.provision_state not in expected_states:
                raise exception.InvalidStateRequested(_(
                    'Cannot continue deploying on %(node)s. Node is in '
                    '%(state)s state; should be in one of %(deploy_state)s') %
                    {'node': node.uuid,
                     'state': node.provision_state,
                     'deploy_state': ', '.join(expected_states)})

            # TODO(rloo): When deprecation period is over and node is in
            # states.DEPLOYWAIT only, delete the check and always 'resume'.
            if node.provision_state == states.DEPLOYING:
                LOG.warning('Node %(node)s was found in the state %(state)s '
                            'in the continue_node_deploy RPC call. This is '
                            'deprecated, the driver must be updated to leave '
                            'nodes in %(new)s state instead.',
                            {'node': node.uuid, 'state': states.DEPLOYING,
                             'new': states.DEPLOYWAIT})
            else:
                task.process_event('resume')

            task.set_spawn_error_hook(utils.spawn_deploying_error_handler,
                                      task.node)
            task.spawn_after(
                self._spawn_worker,
                deployments.continue_node_deploy, task)

    @METRICS.timer('ConductorManager.do_node_tear_down')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InstanceDeployFailure,
                                   exception.InvalidStateRequested,
                                   exception.NodeProtected,
                                   exception.ConcurrentActionLimit)
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
        :raises: NodeProtected if the node is protected.
        :raises: ConcurrentActionLimit if this action would exceed the maximum
                 number of configured concurrent actions of this type.
        """
        LOG.debug("RPC do_node_tear_down called for node %s.", node_id)
        self._concurrent_action_limit(action='unprovisioning')

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node tear down') as task:
            # Record of any pre-existing agent_url should be removed.
            utils.remove_agent_url(task.node)
            if task.node.protected:
                raise exception.NodeProtected(node=task.node.uuid)

            try:
                # NOTE(ghe): Valid power driver values are needed to perform
                # a tear-down. Deploy info is useful to purge the cache but not
                # required for this method.
                task.driver.power.validate(task)
            except exception.InvalidParameterValue as e:
                raise exception.InstanceDeployFailure(_(
                    "Failed to validate power driver interface. "
                    "Can not delete instance. Error: %(msg)s") % {'msg': e})

            try:
                task.process_event(
                    'delete',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_tear_down, task,
                               task.node.provision_state),
                    err_handler=utils.provisioning_error_handler)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='delete', node=task.node.uuid,
                    state=task.node.provision_state)

    @task_manager.require_exclusive_lock
    def _do_node_tear_down(self, task, initial_state):
        """Internal RPC method to tear down an existing node deployment.

        :param task: a task from TaskManager.
        :param initial_state: The initial provision state from which node
                              has moved into deleting state.
        """
        node = task.node
        try:
            if (initial_state in (states.RESCUEWAIT, states.RESCUE,
                states.UNRESCUEFAIL, states.RESCUEFAIL)):
                # Perform rescue clean up. Rescue clean up will remove
                # rescuing network as well.
                task.driver.rescue.clean_up(task)

            # stop the console
            # do it in this thread since we're already out of the main
            # conductor thread.
            if node.console_enabled:
                notify_utils.emit_console_notification(
                    task, 'console_stop', fields.NotificationStatus.START)
                try:
                    # Keep console_enabled=True for next deployment
                    task.driver.console.stop_console(task)
                except Exception as err:
                    with excutils.save_and_reraise_exception():
                        LOG.error('Failed to stop console while tearing down '
                                  'the node %(node)s: %(err)s.',
                                  {'node': node.uuid, 'err': err})
                        notify_utils.emit_console_notification(
                            task, 'console_stop',
                            fields.NotificationStatus.ERROR)
                else:
                    notify_utils.emit_console_notification(
                        task, 'console_stop', fields.NotificationStatus.END)

            task.driver.deploy.clean_up(task)
            task.driver.deploy.tear_down(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error in tear_down of node %(node)s: %(err)s',
                              {'node': node.uuid, 'err': e})
                error = _("Failed to tear down: %s") % e
                utils.node_history_record(task.node, event=error,
                                          event_type=states.UNPROVISION,
                                          error=True,
                                          user=task.context.user_id)
                task.process_event('fail')
        else:
            # NOTE(tenbrae): When tear_down finishes, the deletion is done,
            # cleaning will start next
            LOG.info('Successfully unprovisioned node %(node)s with '
                     'instance %(instance)s.',
                     {'node': node.uuid, 'instance': node.instance_uuid})
        finally:
            # NOTE(tenbrae): there is no need to unset conductor_affinity
            # because it is a reference to the most recent conductor which
            # deployed a node, and does not limit any future actions.
            # But we do need to clear the instance-related fields.
            node.instance_info = {}
            node.instance_uuid = None
            utils.wipe_deploy_internal_info(task)
            node.del_driver_internal_info('instance')
            node.del_driver_internal_info('root_uuid_or_disk_id')
            node.del_driver_internal_info('is_whole_disk_image')
            node.del_driver_internal_info('is_source_a_path')
            node.del_driver_internal_info('deploy_boot_mode')
            if node.driver_internal_info.get('automatic_lessee'):
                # Remove lessee, as it was automatically added
                node.lessee = None
                node.del_driver_internal_info('automatic_lessee')
            network.remove_vifs_from_node(task)
            node.save()
            if node.allocation_id:
                allocation = objects.Allocation.get_by_id(task.context,
                                                          node.allocation_id)
                allocation.destroy()
                # The destroy() call above removes allocation_id and
                # instance_uuid, refresh the node to get these changes.
                node.refresh()

        # Begin cleaning
        task.process_event('clean')
        cleaning.do_node_clean(task)

    @METRICS.timer('ConductorManager.do_node_clean')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.InvalidStateRequested,
                                   exception.NodeInMaintenance,
                                   exception.NodeLocked,
                                   exception.NoFreeConductorWorker,
                                   exception.ConcurrentActionLimit)
    def do_node_clean(self, context, node_id, clean_steps,
                      disable_ramdisk=False):
        """RPC method to initiate manual cleaning.

        :param context: an admin context.
        :param node_id: the ID or UUID of a node.
        :param clean_steps: an ordered list of clean steps that will be
            performed on the node. A clean step is a dictionary with required
            keys 'interface' and 'step', and optional key 'args'. If
            specified, the 'args' arguments are passed to the clean step
            method.::

              { 'interface': <driver_interface>,
                'step': <name_of_clean_step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>} }

            For example (this isn't a real example, this clean step
            doesn't exist)::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }
        :param disable_ramdisk: Optional. Whether to disable the ramdisk boot.
        :raises: InvalidParameterValue if power validation fails.
        :raises: InvalidStateRequested if the node is not in manageable state.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: ConcurrentActionLimit If this action would exceed the
                 configured limits of the deployment.
        """
        self._concurrent_action_limit(action='cleaning')
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node manual cleaning') as task:
            node = task.node
            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('cleaning'),
                                                  node=node.uuid)

            # NOTE(rloo): cleaning.do_node_clean() will also make similar calls
            # to validate power & network, but we are doing it again here so
            # that the user gets immediate feedback of any issues. This
            # behaviour (of validating) is consistent with other methods like
            # self.do_node_deploy().
            try:
                task.driver.power.validate(task)
                task.driver.network.validate(task)
            except exception.InvalidParameterValue as e:
                msg = (_('Validation of node %(node)s for cleaning '
                         'failed: %(msg)s') %
                       {'node': node.uuid, 'msg': e})
                raise exception.InvalidParameterValue(msg)

            try:
                task.process_event(
                    'clean',
                    callback=self._spawn_worker,
                    call_args=(cleaning.do_node_clean, task, clean_steps,
                               disable_ramdisk),
                    err_handler=utils.provisioning_error_handler,
                    target_state=states.MANAGEABLE)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='manual clean', node=node.uuid,
                    state=node.provision_state)

    @METRICS.timer('ConductorManager.continue_node_clean')
    def continue_node_clean(self, context, node_id):
        """RPC method to continue cleaning a node.

        This is useful for cleaning tasks that are async. When they complete,
        they call back via RPC, a new worker and lock are set up, and cleaning
        continues. This can also be used to resume cleaning on take_over.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InvalidStateRequested if the node is not in CLEANWAIT state
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node no longer appears in the database

        """
        LOG.debug("RPC continue_node_clean called for node %s.", node_id)

        with task_manager.acquire(context, node_id, shared=False, patient=True,
                                  purpose='continue node cleaning') as task:
            node = task.node

            if node.provision_state != states.CLEANWAIT:
                raise exception.InvalidStateRequested(_(
                    'Cannot continue cleaning on %(node)s, node is in '
                    '%(state)s state, should be %(clean_state)s') %
                    {'node': node.uuid,
                     'state': node.provision_state,
                     'clean_state': states.CLEANWAIT})

            task.resume_cleaning()

            task.set_spawn_error_hook(utils.spawn_cleaning_error_handler,
                                      task.node)
            task.spawn_after(
                self._spawn_worker,
                cleaning.continue_node_clean, task)

    @METRICS.timer('ConductorManager.do_provisioning_action')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InvalidParameterValue,
                                   exception.InvalidStateRequested,
                                   exception.UnsupportedDriverExtension,
                                   exception.NodeInMaintenance)
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
        :raises: NodeInMaintenance
        """
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='provision action %s'
                                  % action) as task:
            node = task.node
            if (action == states.VERBS['provide']
                    and node.provision_state == states.MANAGEABLE):
                # NOTE(dtantsur): do this early to avoid entering cleaning.
                if (not CONF.conductor.allow_provisioning_in_maintenance
                        and node.maintenance):
                    raise exception.NodeInMaintenance(op=_('providing'),
                                                      node=node.uuid)
                if node.retired:
                    raise exception.NodeIsRetired(op=_('providing'),
                                                  node=node.uuid)
                task.process_event(
                    'provide',
                    callback=self._spawn_worker,
                    call_args=(cleaning.do_node_clean, task),
                    err_handler=utils.provisioning_error_handler)
                return

            if (action == states.VERBS['manage']
                    and node.provision_state == states.ENROLL):
                task.process_event(
                    'manage',
                    callback=self._spawn_worker,
                    call_args=(verify.do_node_verify, task),
                    err_handler=utils.provisioning_error_handler)
                return

            if (action == states.VERBS['adopt']
                    and node.provision_state in (states.MANAGEABLE,
                states.ADOPTFAIL)):
                task.process_event(
                    'adopt',
                    callback=self._spawn_worker,
                    call_args=(self._do_adoption, task),
                    err_handler=utils.provisioning_error_handler)
                return

            if (action == states.VERBS['abort']
                    and node.provision_state in (states.CLEANWAIT,
                                                 states.RESCUEWAIT,
                                                 states.INSPECTWAIT,
                                                 states.CLEANHOLD,
                                                 states.DEPLOYHOLD)):
                self._do_abort(task)
                return

            if (action == states.VERBS['unhold']
                    and node.provision_state in (states.CLEANHOLD,
                                                 states.DEPLOYHOLD)):
                # NOTE(TheJulia): Release the node from the hold, which
                # allows the next heartbeat action to pick the node back
                # up and it continue it's operation.
                task.process_event('unhold')
                return

            try:
                task.process_event(action)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action=action, node=node.uuid,
                    state=node.provision_state)

    def _do_abort(self, task):
        """Handle node abort for certain states."""
        node = task.node

        if node.provision_state in (states.CLEANWAIT, states.CLEANHOLD):
            # Check if the clean step is abortable; if so abort it.
            # Otherwise, indicate in that clean step, that cleaning
            # should be aborted after that step is done.
            if (node.clean_step and not
                    node.clean_step.get('abortable')):
                LOG.info('The current clean step "%(clean_step)s" for '
                         'node %(node)s is not abortable. Adding a '
                         'flag to abort the cleaning after the clean '
                         'step is completed.',
                         {'clean_step': node.clean_step['step'],
                          'node': node.uuid})
                clean_step = node.clean_step
                if not clean_step.get('abort_after'):
                    clean_step['abort_after'] = True
                    node.clean_step = clean_step
                    node.save()
                return

            LOG.debug('Aborting the cleaning operation during clean step '
                      '"%(step)s" for node %(node)s in provision state '
                      '"%(prov)s".',
                      {'node': node.uuid,
                       'prov': node.provision_state,
                       'step': node.clean_step.get('step')})
            target_state = None
            if node.target_provision_state == states.MANAGEABLE:
                target_state = states.MANAGEABLE
            task.process_event(
                'abort',
                callback=self._spawn_worker,
                call_args=(cleaning.do_node_clean_abort, task),
                err_handler=utils.provisioning_error_handler,
                target_state=target_state,
                last_error=cleaning.get_last_error(node))
            return

        if node.provision_state == states.RESCUEWAIT:
            utils.remove_node_rescue_password(node, save=True)
            task.process_event(
                'abort',
                callback=self._spawn_worker,
                call_args=(self._do_node_rescue_abort, task),
                err_handler=utils.provisioning_error_handler)
            return

        if node.provision_state == states.INSPECTWAIT:
            return inspection.abort_inspection(task)

        if node.provision_state == states.DEPLOYHOLD:
            # Immediately break agent API interaction
            # and align with do_node_tear_down
            utils.remove_agent_url(task.node)
            # And then call the teardown
            task.process_event(
                'abort',
                callback=self._spawn_worker,
                call_args=(self._do_node_tear_down, task,
                           task.node.provision_state),
                err_handler=utils.provisioning_error_handler)

    @METRICS.timer('ConductorManager._sync_power_states')
    @periodics.periodic(spacing=CONF.conductor.sync_power_state_interval,
                        enabled=CONF.conductor.sync_power_state_interval > 0)
    def _sync_power_states(self, context):
        """Periodic task to sync power states for the nodes."""
        filters = {'maintenance': False}

        # NOTE(etingof): prioritize non-responding nodes to fail them fast
        nodes = sorted(
            self.iter_nodes(fields=['id'], filters=filters),
            key=lambda n: -self.power_state_sync_count.get(n[0], 0)
        )

        nodes_queue = queue.Queue()

        for node_info in nodes:
            nodes_queue.put(node_info)

        number_of_workers = min(CONF.conductor.sync_power_state_workers,
                                CONF.conductor.periodic_max_workers,
                                nodes_queue.qsize())
        futures = []

        for worker_number in range(max(0, number_of_workers - 1)):
            try:
                futures.append(
                    self._spawn_worker(self._sync_power_state_nodes_task,
                                       context, nodes_queue))
            except exception.NoFreeConductorWorker:
                LOG.warning("There are no more conductor workers for "
                            "power sync task. %(workers)d workers have "
                            "been already spawned.",
                            {'workers': worker_number})
                break

        try:
            self._sync_power_state_nodes_task(context, nodes_queue)

        finally:
            waiters.wait_for_all(futures)

        # report a count of the nodes
        METRICS.send_gauge(
            'ConductorManager.PowerSyncNodesCount',
            len(nodes))

    def _sync_power_state_nodes_task(self, context, nodes):
        """Invokes power state sync on nodes from synchronized queue.

        Attempt to grab a lock and sync only if the following conditions
        are met:

        1) Node is mapped to this conductor.
        2) Node is not in maintenance mode.
        3) Node is not in DEPLOYWAIT/CLEANWAIT provision state.
        4) Node doesn't have a reservation

        NOTE: Grabbing a lock here can cause other methods to fail to
        grab it. We want to avoid trying to grab a lock while a node
        is in the DEPLOYWAIT/CLEANWAIT state so we don't unnecessarily
        cause a deploy/cleaning callback to fail. There's not much we
        can do here to avoid failing a brand new deploy to a node that
        we've locked here, though.
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

        while not self._shutdown:
            try:
                (node_uuid, driver, conductor_group,
                 node_id) = nodes.get_nowait()
            except queue.Empty:
                break

            try:
                # NOTE(dtantsur): start with a shared lock, upgrade if needed
                with task_manager.acquire(context, node_uuid,
                                          purpose='power state sync',
                                          shared=True) as task:
                    # NOTE(tenbrae): we should not acquire a lock on a node in
                    #             DEPLOYWAIT/CLEANWAIT, as this could cause
                    #             an error within a deploy ramdisk POSTing back
                    #             at the same time.
                    # NOTE(dtantsur): it's also pointless (and dangerous) to
                    # sync power state when a power action is in progress
                    if (task.node.provision_state in SYNC_EXCLUDED_STATES
                            or task.node.maintenance
                            or task.node.target_power_state
                            or task.node.reservation):
                        continue
                    count = do_sync_power_state(
                        task, self.power_state_sync_count[node_uuid])
                    if count:
                        self.power_state_sync_count[node_uuid] = count
                    else:
                        # don't bloat the dict with non-failing nodes
                        del self.power_state_sync_count[node_uuid]
            except exception.NodeNotFound:
                LOG.info("During sync_power_state, node %(node)s was not "
                         "found and presumed deleted by another process.",
                         {'node': node_uuid})
                # TODO(TheJulia): The chance exists that we orphan a node
                # in power_state_sync_count, albeit it is not much data,
                # it could eventually cause the memory footprint to grow
                # on an exceptionally large ironic deployment. We should
                # make sure we clean it up at some point, but overall given
                # minimal impact, it is definite low hanging fruit.
            except exception.NodeLocked:
                LOG.info("During sync_power_state, node %(node)s was "
                         "already locked by another process. Skip.",
                         {'node': node_uuid})
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    @METRICS.timer('ConductorManager._power_failure_recovery')
    @periodics.node_periodic(
        purpose='power failure recovery',
        spacing=CONF.conductor.power_failure_recovery_interval,
        # NOTE(kaifeng) To avoid conflicts with periodic task of the
        # regular power state checking, maintenance is still a required
        # condition.
        filters={'maintenance': True, 'fault': faults.POWER_FAILURE},
        node_count_metric_name='ConductorManager.PowerSyncRecoveryNodeCount',
    )
    def _power_failure_recovery(self, task, context):
        """Periodic task to check power states for nodes in maintenance.

        Attempt to grab a lock and sync only if the following
        conditions are met:

        1) Node is mapped to this conductor.
        2) Node is in maintenance.
        3) Node's fault field is set to 'power failure'.
        4) Node is not reserved.
        5) Node is not in the ENROLL state.
        """
        def handle_recovery(task, actual_power_state):
            """Handle recovery when power sync is succeeded."""
            task.upgrade_lock()
            node = task.node
            # Update power state
            old_power_state = node.power_state
            node.power_state = actual_power_state
            # Clear maintenance related fields
            node.maintenance = False
            node.maintenance_reason = None
            node.fault = None
            node.save()
            LOG.info("Node %(node)s is recovered from power failure "
                     "with actual power state '%(state)s'.",
                     {'node': node.uuid, 'state': actual_power_state})
            if old_power_state != actual_power_state:
                if node.instance_uuid:
                    nova.power_update(
                        task.context, node.instance_uuid, node.power_state)
                notify_utils.emit_power_state_corrected_notification(
                    task, old_power_state)

        # NOTE(dtantsur): it's also pointless (and dangerous) to
        # sync power state when a power action is in progress
        if (task.node.provision_state == states.ENROLL
                or not task.node.maintenance
                or task.node.fault != faults.POWER_FAILURE
                or task.node.target_power_state
                or task.node.reservation):
            return

        try:
            # Validate driver info in case of parameter changed
            # in maintenance.
            task.driver.power.validate(task)
            # The driver may raise an exception, or may return
            # ERROR. Handle both the same way.
            power_state = task.driver.power.get_power_state(task)
            if power_state == states.ERROR:
                raise exception.PowerStateFailure(
                    _("Power driver returned ERROR state "
                      "while trying to get power state."))
        except Exception as e:
            LOG.debug("During power_failure_recovery, could "
                      "not get power state for node %(node)s: %(err)s",
                      {'node': task.node.uuid, 'err': e})
        else:
            handle_recovery(task, power_state)

    @METRICS.timer('ConductorManager._check_deploy_timeouts')
    @periodics.periodic(
        spacing=CONF.conductor.check_provision_state_interval,
        enabled=CONF.conductor.check_provision_state_interval > 0
        and CONF.conductor.deploy_callback_timeout > 0)
    def _check_deploy_timeouts(self, context):
        """Periodically checks whether a deploy RPC call has timed out.

        If a deploy call has timed out, the deploy failed and we clean up.

        :param context: request context.
        """
        callback_timeout = CONF.conductor.deploy_callback_timeout

        filters = {'reserved': False,
                   'provision_state': states.DEPLOYWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        sort_key = 'provision_updated_at'
        callback_method = utils.cleanup_after_timeout
        err_handler = utils.provisioning_error_handler
        self._fail_if_in_state(context, filters, states.DEPLOYWAIT,
                               sort_key, callback_method, err_handler)

    @METRICS.timer('ConductorManager._check_orphan_nodes')
    @periodics.periodic(
        spacing=CONF.conductor.check_provision_state_interval,
        enabled=CONF.conductor.check_provision_state_interval > 0)
    def _check_orphan_nodes(self, context):
        """Periodically checks the status of nodes that were taken over.

        Periodically checks the nodes that are managed by this conductor but
        have a reservation from a conductor that went offline.

        1. Nodes in DEPLOYING state move to DEPLOY FAIL.

        2. Nodes in CLEANING state move to CLEAN FAIL with maintenance set.

        3. Nodes in a transient power state get the power operation aborted.

        4. Reservation is removed.

        The latter operation happens even for nodes in maintenance mode,
        otherwise it's not possible to move them out of maintenance.

        :param context: request context.
        """
        offline_conductors = utils.exclude_current_conductor(
            self.host, self.dbapi.get_offline_conductors())
        if not offline_conductors:
            return

        node_iter = self.iter_nodes(
            fields=['id', 'reservation', 'maintenance', 'provision_state',
                    'target_power_state'],
            filters={'reserved_by_any_of': offline_conductors})

        state_cleanup_required = []

        for (node_uuid, driver, conductor_group, node_id, conductor_hostname,
             maintenance, provision_state, target_power_state) in node_iter:
            # NOTE(lucasagomes): Although very rare, this may lead to a
            # race condition. By the time we release the lock the conductor
            # that was previously managing the node could be back online.
            try:
                objects.Node.release(context, conductor_hostname, node_id)
            except exception.NodeNotFound:
                LOG.warning("During checking for deploying state, node "
                            "%s was not found and presumed deleted by "
                            "another process. Skipping.", node_uuid)
                continue
            except exception.NodeLocked:
                LOG.warning("During checking for deploying state, when "
                            "releasing the lock of the node %s, it was "
                            "locked by another process. Skipping.",
                            node_uuid)
                continue
            except exception.NodeNotLocked:
                LOG.warning("During checking for deploying state, when "
                            "releasing the lock of the node %s, it was "
                            "already unlocked.", node_uuid)
            else:
                LOG.warning('Forcibly removed reservation of conductor %(old)s'
                            ' on node %(node)s as that conductor went offline',
                            {'old': conductor_hostname, 'node': node_uuid})

            # TODO(dtantsur): clean up all states that are not stable and
            # are not one of WAIT states.
            if not maintenance and (provision_state in (states.DEPLOYING,
                                                        states.CLEANING)
                                    or target_power_state is not None):
                LOG.debug('Node %(node)s taken over from conductor %(old)s '
                          'requires state clean up: provision state is '
                          '%(state)s, target power state is %(pstate)s',
                          {'node': node_uuid, 'old': conductor_hostname,
                           'state': provision_state,
                           'pstate': target_power_state})
                state_cleanup_required.append(node_uuid)

        for node_uuid in state_cleanup_required:
            with task_manager.acquire(context, node_uuid,
                                      purpose='power state clean up') as task:
                if not task.node.maintenance and task.node.target_power_state:
                    old_state = task.node.target_power_state
                    task.node.target_power_state = None
                    error = _('Pending power operation was '
                              'aborted due to conductor take '
                              'over')
                    utils.node_history_record(task.node, event=error,
                                              event_type=states.TAKEOVER,
                                              error=True,
                                              user=task.context.user_id)

                    task.node.save()
                    LOG.warning('Aborted pending power operation %(op)s '
                                'on node %(node)s due to conductor take over',
                                {'op': old_state, 'node': node_uuid})

            self._fail_if_in_state(
                context, {'uuid': node_uuid},
                {states.DEPLOYING, states.CLEANING},
                'provision_updated_at',
                callback_method=utils.abort_on_conductor_take_over,
                err_handler=utils.provisioning_error_handler)

    @METRICS.timer('ConductorManager._do_adoption')
    @task_manager.require_exclusive_lock
    def _do_adoption(self, task):
        """Adopt the node.

        Similar to node takeover, adoption performs a driver boot
        validation and then triggers node takeover in order to make the
        conductor responsible for the node. Upon completion of takeover,
        the node is moved to ACTIVE state.

        The goal of this method is to set the conditions for the node to
        be managed by Ironic as an ACTIVE node without having performed
        a deployment operation.

        :param task: a TaskManager instance
        """

        node = task.node
        LOG.debug('Conductor %(cdr)s attempting to adopt node %(node)s',
                  {'cdr': self.host, 'node': node.uuid})

        try:
            # NOTE(TheJulia): A number of drivers expect to know if a
            # whole disk image was used prior to their takeover logic
            # being triggered, as such we need to populate the
            # internal info based on the configuration the user has
            # supplied.
            utils.update_image_type(task.context, task.node)
            if deploy_utils.get_boot_option(node) != 'local':
                # Calling boot validate to ensure that sufficient information
                # is supplied to allow the node to be able to boot if takeover
                # writes items such as kernel/ramdisk data to disk.
                task.driver.boot.validate(task)
            # NOTE(TheJulia): While task.driver.boot.validate() is called
            # above, and task.driver.power.validate() could be called, it
            # is called as part of the transition from ENROLL to MANAGEABLE
            # states. As such it is redundant to call here.
            self._do_takeover(task)

            LOG.info("Successfully adopted node %(node)s",
                     {'node': node.uuid})
            task.process_event('done')
        except Exception as err:
            msg = (_('Error while attempting to adopt node %(node)s: '
                     '%(err)s.') % {'node': node.uuid, 'err': err})
            LOG.error(msg)
            # Wipe power state from being preserved as it is likely invalid.
            node.power_state = states.NOSTATE
            utils.node_history_record(task.node, event=msg,
                                      event_type=states.ADOPTION,
                                      error=True,
                                      user=task.context.user_id)
            task.process_event('fail')

    @METRICS.timer('ConductorManager._do_takeover')
    def _do_takeover(self, task):
        """Take over this node.

        Prepares a node for takeover by this conductor, performs the takeover,
        and changes the conductor associated with the node. The node with the
        new conductor affiliation is saved to the DB.

        :param task: a TaskManager instance
        """
        LOG.debug('Conductor %(cdr)s taking over node %(node)s',
                  {'cdr': self.host, 'node': task.node.uuid})
        task.driver.deploy.prepare(task)
        task.driver.deploy.take_over(task)
        # NOTE(zhenguo): If console enabled, take over the console session
        # as well.
        console_error = None
        if task.node.console_enabled:
            notify_utils.emit_console_notification(
                task, 'console_restore', fields.NotificationStatus.START)
            try:
                task.driver.console.start_console(task)
            except Exception as err:
                msg = (_('Failed to start console while taking over the '
                         'node %(node)s: %(err)s.') % {'node': task.node.uuid,
                                                       'err': err})
                LOG.error(msg)
                # If taking over console failed, set node's console_enabled
                # back to False and set node's last error.
                utils.node_history_record(task.node, event=msg,
                                          event_type=states.TAKEOVER,
                                          error=True,
                                          user=task.context.user_id)
                task.node.console_enabled = False
                console_error = True
            else:
                notify_utils.emit_console_notification(
                    task, 'console_restore', fields.NotificationStatus.END)
        # NOTE(lucasagomes): Set the ID of the new conductor managing
        #                    this node
        task.node.conductor_affinity = self.conductor.id
        task.node.save()
        if console_error:
            notify_utils.emit_console_notification(
                task, 'console_restore', fields.NotificationStatus.ERROR)

    @METRICS.timer('ConductorManager._check_cleanwait_timeouts')
    @periodics.periodic(
        spacing=CONF.conductor.check_provision_state_interval,
        enabled=CONF.conductor.check_provision_state_interval > 0
        and CONF.conductor.clean_callback_timeout > 0)
    def _check_cleanwait_timeouts(self, context):
        """Periodically checks for nodes being cleaned.

        If a node doing cleaning is unresponsive (detected when it stops
        heart beating), the operation should be aborted.

        :param context: request context.
        """
        callback_timeout = CONF.conductor.clean_callback_timeout

        filters = {'reserved': False,
                   'provision_state': states.CLEANWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        self._fail_if_in_state(context, filters, states.CLEANWAIT,
                               'provision_updated_at',
                               keep_target_state=True,
                               callback_method=utils.cleanup_cleanwait_timeout)

    @METRICS.timer('ConductorManager._check_rescuewait_timeouts')
    @periodics.periodic(spacing=CONF.conductor.check_rescue_state_interval,
                        enabled=bool(CONF.conductor.rescue_callback_timeout))
    def _check_rescuewait_timeouts(self, context):
        """Periodically checks if rescue has timed out waiting for heartbeat.

        If a rescue call has timed out, fail the rescue and clean up.

        :param context: request context.
        """
        callback_timeout = CONF.conductor.rescue_callback_timeout
        filters = {'reserved': False,
                   'provision_state': states.RESCUEWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        self._fail_if_in_state(context, filters, states.RESCUEWAIT,
                               'provision_updated_at',
                               keep_target_state=True,
                               callback_method=utils.cleanup_rescuewait_timeout
                               )

    @METRICS.timer('ConductorManager._sync_local_state')
    @periodics.node_periodic(
        purpose='node take over',
        spacing=CONF.conductor.sync_local_state_interval,
        filters={'reserved': False, 'maintenance': False,
                 'provision_state': states.ACTIVE},
        predicate_extra_fields=['conductor_affinity'],
        predicate=lambda n, m: n.conductor_affinity != m.conductor.id,
        limit=lambda: CONF.conductor.periodic_max_workers,
        shared_task=False,
        node_count_metric_name='ConductorManager.SyncLocalStateNodeCount',
    )
    def _sync_local_state(self, task, context):
        """Perform any actions necessary to sync local state.

        This is called periodically to refresh the conductor's copy of the
        consistent hash ring. If any mappings have changed, this method then
        determines which, if any, nodes need to be "taken over".
        The ensuing actions could include preparing a PXE environment,
        updating the DHCP server, and so on.
        """
        # NOTE(tenbrae): now that we have the lock, check again to
        # avoid racing with deletes and other state changes
        node = task.node
        if (node.maintenance
                or node.conductor_affinity == self.conductor.id
                or node.provision_state != states.ACTIVE):
            return False

        try:
            task.spawn_after(self._spawn_worker, self._do_takeover, task)
        except exception.NoFreeConductorWorker:
            raise periodics.Stop()
        else:
            return True

    @METRICS.timer('ConductorManager.validate_driver_interfaces')
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
        lock_purpose = 'driver interface validation'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            # NOTE(sirushtim): the is_whole_disk_image variable is needed by
            # deploy drivers for doing their validate(). Since the deploy
            # isn't being done yet and the driver information could change in
            # the meantime, we don't know if the is_whole_disk_image value will
            # change or not. It isn't saved to the DB, but only used with this
            # node instance for the current validations.
            utils.update_image_type(context, task.node)
            for iface_name in task.driver.non_vendor_interfaces:
                iface = getattr(task.driver, iface_name)
                result = reason = None
                try:
                    iface.validate(task)
                    if iface_name == 'deploy':
                        utils.validate_instance_info_traits(task.node)
                        # NOTE(dtantsur): without the agent running we cannot
                        # have the complete list of steps, so skip ones that we
                        # don't know.
                        (conductor_steps
                         .validate_user_deploy_steps_and_templates(
                             task, skip_missing=True))
                    result = True
                except (exception.InvalidParameterValue,
                        exception.UnsupportedDriverExtension) as e:
                    result = False
                    reason = str(e)
                except Exception as e:
                    result = False
                    reason = (_('Unexpected exception, traceback saved '
                                'into log by ironic conductor service '
                                'that is running on %(host)s: %(error)s')
                              % {'host': self.host, 'error': e})
                    LOG.exception(
                        'Unexpected exception occurred while validating '
                        '%(iface)s driver interface for driver '
                        '%(driver)s: %(err)s on node %(node)s.',
                        {'iface': iface_name, 'driver': task.node.driver,
                         'err': e, 'node': task.node.uuid})

                ret_dict[iface_name] = {}
                ret_dict[iface_name]['result'] = result
                if reason is not None:
                    ret_dict[iface_name]['reason'] = reason
        return ret_dict

    @METRICS.timer('ConductorManager.destroy_node')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeAssociated,
                                   exception.InvalidState,
                                   exception.NodeProtected)
    def destroy_node(self, context, node_id):
        """Delete a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeAssociated if the node contains an instance
            associated with it.
        :raises: InvalidState if the node is in the wrong provision
            state to perform deletion.
        :raises: NodeProtected if the node is protected.
        """
        # NOTE(dtantsur): we allow deleting a node in maintenance mode even if
        # we would disallow it otherwise. That's done for recovering hopelessly
        # broken nodes (e.g. with broken BMC).
        with task_manager.acquire(context, node_id,
                                  load_driver=False,
                                  purpose='node deletion') as task:
            node = task.node
            if not node.maintenance and node.instance_uuid is not None:
                raise exception.NodeAssociated(node=node.uuid,
                                               instance=node.instance_uuid)

            if task.node.protected:
                raise exception.NodeProtected(node=node.uuid)

            # NOTE(lucasagomes): For the *FAIL states we users should
            # move it to a safe state prior to deletion. This is because we
            # should try to avoid deleting a node in a dirty/whacky state,
            # e.g: A node in DEPLOYFAIL, if deleted without passing through
            # tear down/cleaning may leave data from the previous tenant
            # in the disk. So nodes in *FAIL states should first be moved to:
            # CLEANFAIL -> MANAGEABLE
            # INSPECTIONFAIL -> MANAGEABLE
            # DEPLOYFAIL -> DELETING
            delete_allowed_states = states.DELETE_ALLOWED_STATES
            if CONF.conductor.allow_deleting_available_nodes:
                delete_allowed_states += (states.AVAILABLE,)
            if (not node.maintenance
                    and node.provision_state
                    not in delete_allowed_states):
                msg = (_('Can not delete node "%(node)s" while it is in '
                         'provision state "%(state)s". Valid provision states '
                         'to perform deletion are: "%(valid_states)s", '
                         'or set the node into maintenance mode') %
                       {'node': node.uuid, 'state': node.provision_state,
                        'valid_states': delete_allowed_states})
                raise exception.InvalidState(msg)
            if node.console_enabled:
                notify_utils.emit_console_notification(
                    task, 'console_set', fields.NotificationStatus.START)

                try:
                    task.load_driver()
                except Exception:
                    with excutils.save_and_reraise_exception():
                        LOG.exception('Could not load the driver for node %s '
                                      'to shut down its console', node.uuid)
                        notify_utils.emit_console_notification(
                            task, 'console_set',
                            fields.NotificationStatus.ERROR)

                try:
                    task.driver.console.stop_console(task)
                except Exception as err:
                    LOG.error('Failed to stop console while deleting '
                              'the node %(node)s: %(err)s.',
                              {'node': node.uuid, 'err': err})
                    notify_utils.emit_console_notification(
                        task, 'console_set', fields.NotificationStatus.ERROR)
                else:
                    node.console_enabled = False
                    notify_utils.emit_console_notification(
                        task, 'console_set', fields.NotificationStatus.END)
            # Destroy Swift Inventory entries for this node
            try:
                inspect_utils.clean_up_swift_entries(task)
            except exception.SwiftObjectStillExists as e:
                if node.maintenance:
                    # Maintenance -> Allow orphaning
                    LOG.warning('Swift object orphaned during destruction of '
                                'node %(node)s: %(e)s',
                                {'node': node.uuid, 'e': e})
                else:
                    LOG.error('Swift object cannot be orphaned without '
                              'maintenance mode during destruction of node '
                              '%(node)s: %(e)s', {'node': node.uuid, 'e': e})
                    raise
            except Exception as err:
                LOG.error('Failed to delete Swift entries related '
                          'to the node %(node)s: %(err)s.',
                          {'node': node.uuid, 'err': err})
                raise

            node.destroy()
            LOG.info('Successfully deleted node %(node)s.',
                     {'node': node.uuid})

    @METRICS.timer('ConductorManager.destroy_port')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound,
                                   exception.InvalidState)
    def destroy_port(self, context, port):
        """Delete a port.

        :param context: request context.
        :param port: port object
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node associated with the port does not
                 exist.
        :raises: InvalidState if a vif is still attached to the port.

        """
        LOG.debug('RPC destroy_port called for port %(port)s',
                  {'port': port.uuid})
        with task_manager.acquire(context, port.node_id,
                                  purpose='port deletion') as task:
            vif, vif_use = utils.get_attached_vif(port)
            if vif and not task.node.maintenance:
                msg = _("Cannot delete the port %(port)s as it is bound "
                        "to VIF %(vif)s for %(use)s use.")
                raise exception.InvalidState(
                    msg % {'port': port.uuid,
                           'vif': vif,
                           'use': vif_use})
            port.destroy()
            LOG.info('Successfully deleted port %(port)s. '
                     'The node associated with the port was %(node)s',
                     {'port': port.uuid, 'node': task.node.uuid})

    @METRICS.timer('ConductorManager.destroy_portgroup')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound,
                                   exception.PortgroupNotEmpty)
    def destroy_portgroup(self, context, portgroup):
        """Delete a portgroup.

        :param context: request context.
        :param portgroup: portgroup object
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node associated with the portgroup does
                 not exist.
        :raises: PortgroupNotEmpty if portgroup is not empty

        """
        LOG.debug('RPC destroy_portgroup called for portgroup %(portgroup)s',
                  {'portgroup': portgroup.uuid})
        with task_manager.acquire(context, portgroup.node_id,
                                  purpose='portgroup deletion') as task:
            portgroup.destroy()
            LOG.info('Successfully deleted portgroup %(portgroup)s. '
                     'The node associated with the portgroup was %(node)s',
                     {'portgroup': portgroup.uuid, 'node': task.node.uuid})

    @METRICS.timer('ConductorManager.destroy_volume_connector')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound,
                                   exception.VolumeConnectorNotFound,
                                   exception.InvalidStateRequested)
    def destroy_volume_connector(self, context, connector):
        """Delete a volume connector.

        :param context: request context
        :param connector: volume connector object
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the connector does
                 not exist
        :raises: VolumeConnectorNotFound if the volume connector cannot be
                 found
        :raises: InvalidStateRequested if the node associated with the
                 connector is not powered off.
        """
        LOG.debug('RPC destroy_volume_connector called for volume connector '
                  '%(connector)s',
                  {'connector': connector.uuid})
        with task_manager.acquire(context, connector.node_id,
                                  purpose='volume connector deletion') as task:
            node = task.node
            if node.power_state != states.POWER_OFF:
                raise exception.InvalidStateRequested(
                    action='volume connector deletion',
                    node=node.uuid,
                    state=node.power_state)
            connector.destroy()
            LOG.info('Successfully deleted volume connector %(connector)s. '
                     'The node associated with the connector was %(node)s',
                     {'connector': connector.uuid, 'node': task.node.uuid})

    @METRICS.timer('ConductorManager.destroy_volume_target')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound,
                                   exception.VolumeTargetNotFound,
                                   exception.InvalidStateRequested)
    def destroy_volume_target(self, context, target):
        """Delete a volume target.

        :param context: request context
        :param target: volume target object
        :raises: NodeLocked if node is locked by another conductor
        :raises: NodeNotFound if the node associated with the target does
                 not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        :raises: InvalidStateRequested if the node associated with the target
                 is not powered off.
        """
        LOG.debug('RPC destroy_volume_target called for volume target '
                  '%(target)s',
                  {'target': target.uuid})
        with task_manager.acquire(context, target.node_id,
                                  purpose='volume target deletion') as task:
            node = task.node
            if node.power_state != states.POWER_OFF:
                raise exception.InvalidStateRequested(
                    action='volume target deletion',
                    node=node.uuid,
                    state=node.power_state)
            target.destroy()
            LOG.info('Successfully deleted volume target %(target)s. '
                     'The node associated with the target was %(node)s',
                     {'target': target.uuid, 'node': task.node.uuid})

    @METRICS.timer('ConductorManager.get_console_information')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.NodeConsoleNotEnabled,
                                   exception.InvalidParameterValue)
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
        LOG.debug('RPC get_console_information called for node %s', node_id)

        lock_purpose = 'getting console information'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            node = task.node

            if not node.console_enabled:
                raise exception.NodeConsoleNotEnabled(node=node.uuid)

            task.driver.console.validate(task)
            return task.driver.console.get_console(task)

    @METRICS.timer('ConductorManager.set_console_mode')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
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
                  'enabled %(enabled)s', {'node': node_id, 'enabled': enabled})
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose='setting console mode') as task:
            node = task.node
            task.driver.console.validate(task)
            if enabled == node.console_enabled:
                op = 'enabled' if enabled else 'disabled'
                LOG.info("No console action was triggered because the "
                         "console is already %s", op)
            else:
                task.upgrade_lock()
                node.last_error = None
                node.save()
                task.spawn_after(self._spawn_worker,
                                 self._set_console_mode, task, enabled)

    @task_manager.require_exclusive_lock
    def _set_console_mode(self, task, enabled):
        """Internal method to set console mode on a node."""
        node = task.node
        notify_utils.emit_console_notification(
            task, 'console_set', fields.NotificationStatus.START)
        try:
            if enabled:
                task.driver.console.start_console(task)
                # TODO(tenbrae): We should be updating conductor_affinity here
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
                utils.node_history_record(task.node, event=msg,
                                          event_type=states.CONSOLE,
                                          error=True,
                                          user=task.context.user_id)
                LOG.error(msg)
                node.save()
                notify_utils.emit_console_notification(
                    task, 'console_set', fields.NotificationStatus.ERROR)

        node.console_enabled = enabled
        node.last_error = None
        node.save()
        notify_utils.emit_console_notification(
            task, 'console_set', fields.NotificationStatus.END)

    @METRICS.timer('ConductorManager.create_port')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.Conflict,
                                   exception.MACAlreadyExists,
                                   exception.PortgroupPhysnetInconsistent)
    def create_port(self, context, port_obj):
        """Create a port.

        :param context: request context.
        :param port_obj: a changed (but not saved) port object.
        :raises: NodeLocked if node is locked by another conductor
        :raises: MACAlreadyExists if the port has a MAC which is registered on
                 another port already.
        :raises: Conflict if the port is a member of a portgroup which is on a
                 different physical network.
        :raises: PortgroupPhysnetInconsistent if the port's portgroup has
                 ports which are not all assigned the same physical network.
        """
        port_uuid = port_obj.uuid
        LOG.debug("RPC create_port called for port %s.", port_uuid)

        with task_manager.acquire(context, port_obj.node_id,
                                  purpose='port create',
                                  shared=True) as task:
            # NOTE(TheJulia): We're creating a port, we don't need
            # an exclusive parent lock to do so.
            utils.validate_port_physnet(task, port_obj)
            port_obj.create()
        return port_obj

    @METRICS.timer('ConductorManager.update_port')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.FailedToUpdateMacOnPort,
                                   exception.MACAlreadyExists,
                                   exception.InvalidState,
                                   exception.FailedToUpdateDHCPOptOnPort,
                                   exception.Conflict,
                                   exception.InvalidParameterValue,
                                   exception.NetworkError,
                                   exception.PortgroupPhysnetInconsistent)
    def update_port(self, context, port_obj):
        """Update a port.

        :param context: request context.
        :param port_obj: a changed (but not saved) port object.
        :raises: DHCPLoadError if the dhcp_provider cannot be loaded.
        :raises: FailedToUpdateMacOnPort if MAC address changed and update
                 failed.
        :raises: MACAlreadyExists if the update is setting a MAC which is
                 registered on another port already.
        :raises: InvalidState if port connectivity attributes
                 are updated while node not in a MANAGEABLE or ENROLL or
                 INSPECTING or INSPECTWAIT state or not in MAINTENANCE mode.
        :raises: Conflict if trying to set extra/vif_port_id or
                 pxe_enabled=True on port which is a member of portgroup with
                 standalone_ports_supported=False.
        :raises: Conflict if the port is a member of a portgroup which is on a
                 different physical network.
        :raises: PortgroupPhysnetInconsistent if the port's portgroup has
                 ports which are not all assigned the same physical network.
        """
        port_uuid = port_obj.uuid
        LOG.debug("RPC update_port called for port %s.", port_uuid)

        with task_manager.acquire(context, port_obj.node_id,
                                  purpose='port update') as task:
            node = task.node
            # Only allow updating MAC addresses for active nodes if maintenance
            # mode is on.
            if ((node.provision_state == states.ACTIVE or node.instance_uuid)
                    and 'address' in port_obj.obj_what_changed()
                    and not node.maintenance):
                action = _("Cannot update hardware address for port "
                           "%(port)s as node %(node)s is active or has "
                           "instance UUID assigned")
                raise exception.InvalidState(action % {'node': node.uuid,
                                                       'port': port_uuid})

            # If port update is modifying the portgroup membership of the port
            # or modifying the local_link_connection, pxe_enabled or physical
            # network flags then node should be in MANAGEABLE/INSPECTING/ENROLL
            # provisioning state or in maintenance mode.  Otherwise
            # InvalidState exception is raised.
            connectivity_attr = {'portgroup_id',
                                 'pxe_enabled',
                                 'local_link_connection',
                                 'physical_network'}
            allowed_update_states = [states.ENROLL,
                                     states.INSPECTING,
                                     states.INSPECTWAIT,
                                     states.MANAGEABLE]
            if (set(port_obj.obj_what_changed()) & connectivity_attr
                    and not (node.provision_state in allowed_update_states
                             or node.maintenance)):
                action = _("Port %(port)s can not have any connectivity "
                           "attributes (%(connect)s) updated unless "
                           "node %(node)s is in a %(allowed)s state "
                           "or in maintenance mode. The current state is "
                           "%(state)s.")

                raise exception.InvalidState(
                    action % {'port': port_uuid,
                              'node': node.uuid,
                              'connect': ', '.join(connectivity_attr),
                              'allowed': ', '.join(allowed_update_states),
                              'state': node.provision_state})

            utils.validate_port_physnet(task, port_obj)
            task.driver.network.validate(task)
            # Handle mac_address update and VIF attach/detach stuff.
            task.driver.network.port_changed(task, port_obj)

            port_obj.save()

        return port_obj

    @METRICS.timer('ConductorManager.update_portgroup')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.FailedToUpdateMacOnPort,
                                   exception.PortgroupMACAlreadyExists,
                                   exception.PortgroupNotEmpty,
                                   exception.InvalidState,
                                   exception.Conflict,
                                   exception.InvalidParameterValue,
                                   exception.NetworkError)
    def update_portgroup(self, context, portgroup_obj):
        """Update a portgroup.

        :param context: request context.
        :param portgroup_obj: a changed (but not saved) portgroup object.
        :raises: DHCPLoadError if the dhcp_provider cannot be loaded.
        :raises: FailedToUpdateMacOnPort if MAC address changed and update
                 failed.
        :raises: PortgroupMACAlreadyExists if the update is setting a MAC which
                 is registered on another portgroup already.
        :raises: InvalidState if portgroup-node association is updated while
                 node not in a MANAGEABLE or ENROLL or INSPECTING or
                 INSPECTWAIT state or not in MAINTENANCE mode.
        :raises: PortgroupNotEmpty if there are ports associated with this
                 portgroup.
        :raises: Conflict when trying to set standalone_ports_supported=False
                 on portgroup with ports that has pxe_enabled=True and vice
                 versa.
        """
        portgroup_uuid = portgroup_obj.uuid
        LOG.debug("RPC update_portgroup called for portgroup %s.",
                  portgroup_uuid)
        lock_purpose = 'update portgroup'
        with task_manager.acquire(context,
                                  portgroup_obj.node_id,
                                  purpose=lock_purpose) as task:
            node = task.node

            if 'node_id' in portgroup_obj.obj_what_changed():
                # NOTE(zhenguo): If portgroup update is modifying the
                # portgroup-node association then node should be in
                # MANAGEABLE/INSPECTING/INSPECTWAIT/ENROLL provisioning state
                # or in maintenance mode, otherwise InvalidState is raised.
                allowed_update_states = [states.ENROLL,
                                         states.INSPECTING,
                                         states.INSPECTWAIT,
                                         states.MANAGEABLE]
                if (node.provision_state not in allowed_update_states
                    and not node.maintenance):
                    action = _("Portgroup %(portgroup)s can not be associated "
                               "to node %(node)s unless the node is in a "
                               "%(allowed)s state or in maintenance mode.")

                    raise exception.InvalidState(
                        action % {'portgroup': portgroup_uuid,
                                  'node': node.uuid,
                                  'allowed': ', '.join(allowed_update_states)})

                # NOTE(zhenguo): If portgroup update is modifying the
                # portgroup-node association then there should not be
                # any Port associated to the PortGroup, otherwise
                # PortgroupNotEmpty exception is raised.
                associated_ports = self.dbapi.get_ports_by_portgroup_id(
                    portgroup_uuid)
                if associated_ports:
                    action = _("Portgroup %(portgroup)s can not be associated "
                               "with node %(node)s because there are ports "
                               "associated with this portgroup.")
                    raise exception.PortgroupNotEmpty(
                        action % {'portgroup': portgroup_uuid,
                                  'node': node.uuid})

            task.driver.network.validate(task)
            # Handle mac_address update and VIF attach/detach stuff.
            task.driver.network.portgroup_changed(task, portgroup_obj)

            portgroup_obj.save()

        return portgroup_obj

    @METRICS.timer('ConductorManager.update_volume_connector')
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NodeLocked,
        exception.NodeNotFound,
        exception.VolumeConnectorNotFound,
        exception.VolumeConnectorTypeAndIdAlreadyExists,
        exception.InvalidStateRequested)
    def update_volume_connector(self, context, connector):
        """Update a volume connector.

        :param context: request context
        :param connector: a changed (but not saved) volume connector object
        :returns: an updated volume connector object
        :raises: InvalidParameterValue if the volume connector's UUID is being
                 changed
        :raises: NodeLocked if the node is already locked
        :raises: NodeNotFound if the node associated with the conductor does
                 not exist
        :raises: VolumeConnectorNotFound if the volume connector cannot be
                 found
        :raises: VolumeConnectorTypeAndIdAlreadyExists if another connector
                 already exists with the same values for type and connector_id
                 fields
        :raises: InvalidStateRequested if the node associated with the
                 connector is not powered off.
        """
        LOG.debug("RPC update_volume_connector called for connector "
                  "%(connector)s.",
                  {'connector': connector.uuid})

        with task_manager.acquire(context, connector.node_id,
                                  purpose='volume connector update') as task:
            node = task.node
            if node.power_state != states.POWER_OFF:
                raise exception.InvalidStateRequested(
                    action='volume connector update',
                    node=node.uuid,
                    state=node.power_state)
            connector.save()
            LOG.info("Successfully updated volume connector %(connector)s.",
                     {'connector': connector.uuid})
        return connector

    @METRICS.timer('ConductorManager.update_volume_target')
    @messaging.expected_exceptions(
        exception.InvalidParameterValue,
        exception.NodeLocked,
        exception.NodeNotFound,
        exception.VolumeTargetNotFound,
        exception.VolumeTargetBootIndexAlreadyExists,
        exception.InvalidStateRequested)
    def update_volume_target(self, context, target):
        """Update a volume target.

        :param context: request context
        :param target: a changed (but not saved) volume target object
        :returns: an updated volume target object
        :raises: InvalidParameterValue if the volume target's UUID is being
                 changed
        :raises: NodeLocked if the node is already locked
        :raises: NodeNotFound if the node associated with the volume target
                 does not exist
        :raises: VolumeTargetNotFound if the volume target cannot be found
        :raises: VolumeTargetBootIndexAlreadyExists if a volume target already
                 exists with the same node ID and boot index values
        :raises: InvalidStateRequested if the node associated with the target
                 is not powered off.
        """
        LOG.debug("RPC update_volume_target called for target %(target)s.",
                  {'target': target.uuid})

        with task_manager.acquire(context, target.node_id,
                                  purpose='volume target update') as task:
            node = task.node
            if node.power_state != states.POWER_OFF:
                raise exception.InvalidStateRequested(
                    action='volume target update',
                    node=node.uuid,
                    state=node.power_state)
            target.save()
            LOG.info("Successfully updated volume target %(target)s.",
                     {'target': target.uuid})
        return target

    @METRICS.timer('ConductorManager.get_driver_properties')
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
        driver = driver_factory.get_hardware_type(driver_name)
        return driver.get_properties()

    @METRICS.timer('ConductorManager._sensors_nodes_task')
    def _sensors_nodes_task(self, context, nodes):
        """Sends sensors data for nodes from synchronized queue."""
        while not self._shutdown:
            try:
                (node_uuid, driver, conductor_group,
                 instance_uuid) = nodes.get_nowait()
            except queue.Empty:
                break
            # populate the message which will be sent to ceilometer
            message = {'message_id': uuidutils.generate_uuid(),
                       'instance_uuid': instance_uuid,
                       'node_uuid': node_uuid,
                       'timestamp': datetime.datetime.utcnow()}

            try:
                lock_purpose = 'getting sensors data'
                with task_manager.acquire(context,
                                          node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    if task.node.maintenance:
                        LOG.debug('Skipping sending sensors data for node '
                                  '%s as it is in maintenance mode',
                                  task.node.uuid)
                        continue
                    # Add the node name, as the name would be hand for other
                    # notifier plugins
                    message['node_name'] = task.node.name
                    # We should convey the proper hardware type,
                    # which previously was hard coded to ipmi, but other
                    # drivers were transmitting other values under the
                    # guise of ipmi.
                    ev_type = 'hardware.{driver}.metrics'.format(
                        driver=task.node.driver)
                    message['event_type'] = ev_type + '.update'

                    task.driver.management.validate(task)
                    sensors_data = task.driver.management.get_sensors_data(
                        task)
            except NotImplementedError:
                # NOTE(JayF): In mixed deployments with some nodes supporting
                # sensor data and others not, logging this at warning level
                # creates unreasonable levels of logging noise.
                # See https://bugs.launchpad.net/ironic/+bug/2047709
                LOG.debug(
                    'get_sensors_data is not implemented for driver'
                    ' %(driver)s, node_uuid is %(node)s',
                    {'node': node_uuid, 'driver': driver})
            except exception.FailedToParseSensorData as fps:
                LOG.warning(
                    "During get_sensors_data, could not parse "
                    "sensor data for node %(node)s. Error: %(err)s.",
                    {'node': node_uuid, 'err': str(fps)})
            except exception.FailedToGetSensorData as fgs:
                LOG.warning(
                    "During get_sensors_data, could not get "
                    "sensor data for node %(node)s. Error: %(err)s.",
                    {'node': node_uuid, 'err': str(fgs)})
            except exception.NodeNotFound:
                LOG.warning(
                    "During send_sensor_data, node %(node)s was not "
                    "found and presumed deleted by another process.",
                    {'node': node_uuid})
            except Exception as e:
                LOG.warning(
                    "Failed to get sensor data for node %(node)s. "
                    "Error: %(error)s", {'node': node_uuid, 'error': e})
            else:
                message['payload'] = (
                    self._filter_out_unsupported_types(sensors_data))
                if message['payload']:
                    self.sensors_notifier.info(
                        context, ev_type, message)
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    def _sensors_conductor(self, context):
        """Called to collect and send metrics "sensors" for the conductor."""
        # populate the message which will be sent to ceilometer
        # or other data consumer
        message = {'message_id': uuidutils.generate_uuid(),
                   'timestamp': datetime.datetime.utcnow(),
                   'hostname': self.host}

        try:
            ev_type = 'ironic.metrics'
            message['event_type'] = ev_type + '.update'
            sensors_data = METRICS.get_metrics_data()
        except AttributeError:
            # TODO(TheJulia): Remove this at some point, but right now
            # don't inherently break on version mismatches when people
            # disregard requriements.
            LOG.warning(
                'get_sensors_data has been configured to collect '
                'conductor metrics, however the installed ironic-lib '
                'library lacks the functionality. Please update '
                'ironic-lib to a minimum of version 5.4.0.')
        except Exception as e:
            LOG.exception(
                "An unknown error occured while attempting to collect "
                "sensor data from within the conductor. Error: %(error)s",
                {'error': e})
        else:
            message['payload'] = (
                self._filter_out_unsupported_types(sensors_data))
            if message['payload']:
                self.sensors_notifier.info(
                    context, ev_type, message)

    @METRICS.timer('ConductorManager._send_sensor_data')
    @periodics.periodic(spacing=CONF.sensor_data.interval,
                        enabled=CONF.sensor_data.send_sensor_data)
    def _send_sensor_data(self, context):
        """Periodically collects and transmits sensor data notifications."""

        if CONF.sensor_data.enable_for_conductor:
            if CONF.sensor_data.workers == 1:
                # Directly call the sensors_conductor when only one
                # worker is permitted, so we collect data serially
                # instead.
                self._sensors_conductor(context)
            else:
                # Also, do not apply the general threshold limit to
                # the self collection of "sensor" data from the conductor,
                # as were not launching external processes, we're just reading
                # from an internal data structure, if we can.
                self._spawn_worker(self._sensors_conductor, context)
        if not CONF.sensor_data.enable_for_nodes:
            # NOTE(TheJulia): If node sensor data is not required, then
            # skip the rest of this method.
            return
        filters = {}
        if not CONF.sensor_data.enable_for_undeployed_nodes:
            filters['provision_state'] = states.ACTIVE

        nodes = queue.Queue()
        for node_info in self.iter_nodes(fields=['instance_uuid'],
                                         filters=filters):
            nodes.put_nowait(node_info)

        number_of_threads = min(CONF.sensor_data.workers,
                                nodes.qsize())
        futures = []
        for thread_number in range(number_of_threads):
            try:
                futures.append(
                    self._spawn_worker(self._sensors_nodes_task,
                                       context, nodes))
            except exception.NoFreeConductorWorker:
                LOG.warning("There is no more conductor workers for "
                            "task of sending sensors data. %(workers)d "
                            "workers has been already spawned.",
                            {'workers': thread_number})
                break

        done, not_done = waiters.wait_for_all(
            futures, timeout=CONF.sensor_data.wait_timeout)
        if not_done:
            LOG.warning("%d workers for send sensors data did not complete",
                        len(not_done))

    def _filter_out_unsupported_types(self, sensors_data):
        """Filters out sensor data types that aren't specified in the config.

        Removes sensor data types that aren't specified in
        CONF.sensor_data.data_types.

        :param sensors_data: dict containing sensor types and the associated
               data
        :returns: dict with unsupported sensor types removed
        """
        allowed = set(x.lower() for x in
                      CONF.sensor_data.data_types)

        if 'all' in allowed:
            return sensors_data

        return dict((sensor_type, sensor_value) for (sensor_type, sensor_value)
                    in sensors_data.items() if sensor_type.lower() in allowed)

    @METRICS.timer('ConductorManager.set_boot_device')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
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
        with task_manager.acquire(context, node_id,
                                  purpose='setting boot device') as task:
            task.driver.management.validate(task)
            task.driver.management.set_boot_device(task, device,
                                                   persistent=persistent)

    @METRICS.timer('ConductorManager.get_boot_device')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
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
        with task_manager.acquire(context, node_id,
                                  purpose='getting boot device') as task:
            task.driver.management.validate(task)
            return task.driver.management.get_boot_device(task)

    @METRICS.timer('ConductorManager.inject_nmi')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
    def inject_nmi(self, context, node_id):
        """Inject NMI for a node.

        Inject NMI (Non Maskable Interrupt) for a node immediately.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management or management.inject_nmi.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.
        """
        LOG.debug('RPC inject_nmi called for node %s', node_id)

        with task_manager.acquire(context, node_id,
                                  purpose='inject nmi') as task:
            task.driver.management.validate(task)
            task.driver.management.inject_nmi(task)

    @METRICS.timer('ConductorManager.get_supported_boot_devices')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
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
        lock_purpose = 'getting supported boot devices'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            return task.driver.management.get_supported_boot_devices(task)

    @METRICS.timer('ConductorManager.set_indicator_state')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
    def set_indicator_state(self, context, node_id, component,
                            indicator, state):
        """Set node hardware components indicator to the desired state.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator IDs, as
            reported by `get_supported_indicators`)
        :param state: Indicator state, one of
            mod:`ironic.common.indicator_states`.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified or an invalid boot device is specified.
        :raises: MissingParameterValue if missing supplied info.

        """
        LOG.debug('RPC set_indicator_state called for node %(node)s with '
                  'component %(component)s, indicator %(indicator)s and state '
                  '%(state)s', {'node': node_id, 'component': component,
                                'indicator': indicator, 'state': state})
        with task_manager.acquire(context, node_id,
                                  purpose='setting indicator state') as task:
            task.driver.management.validate(task)
            task.driver.management.set_indicator_state(
                task, component, indicator, state)

    @METRICS.timer('ConductorManager.get_indicator_states')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
    def get_indicator_state(self, context, node_id, component, indicator):
        """Get node hardware component indicator state.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: The hardware component, one of
            :mod:`ironic.common.components`.
        :param indicator: Indicator IDs, as
            reported by `get_supported_indicators`)
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: Indicator state, one of
            mod:`ironic.common.indicator_states`.

        """
        LOG.debug('RPC get_indicator_states called for node %s', node_id)
        with task_manager.acquire(context, node_id,
                                  purpose='getting indicators states') as task:
            task.driver.management.validate(task)
            return task.driver.management.get_indicator_state(
                task, component, indicator)

    @METRICS.timer('ConductorManager.get_supported_indicators')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
    def get_supported_indicators(self, context, node_id, component=None):
        """Get node hardware components and their indicators.

        :param context: request context.
        :param node_id: node id or uuid.
        :param component: If not `None`, return indicator information
            for just this component, otherwise return indicators for
            all existing components.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support management.
        :raises: InvalidParameterValue when the wrong driver info is
                 specified.
        :raises: MissingParameterValue if missing supplied info.
        :returns: A dictionary of hardware components
            (:mod:`ironic.common.components`) as keys with indicator IDs
            as values.

            ::

                {
                    'chassis': {
                        'enclosure-0': {
                            "readonly": true,
                            "states": [
                                "OFF",
                                "ON"
                            ]
                        }
                    },
                    'system':
                        'blade-A': {
                            "readonly": true,
                            "states": [
                                "OFF",
                                "ON"
                            ]
                        }
                    },
                    'drive':
                        'ssd0': {
                            "readonly": true,
                            "states": [
                                "OFF",
                                "ON"
                            ]
                        }
                    }
                }

        """
        LOG.debug('RPC get_supported_indicators called for node %s', node_id)
        lock_purpose = 'getting supported indicators'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            return task.driver.management.get_supported_indicators(
                task, component)

    @METRICS.timer('ConductorManager.inspect_hardware')
    @messaging.expected_exceptions(exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.InvalidParameterValue,
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
        :raises: InvalidParameterValue when unable to get
                 essential scheduling properties from hardware.
        :raises: MissingParameterValue when required
                 information is not found.
        :raises: InvalidStateRequested if 'inspect' is not a
                 valid action to do in the current state.

        """
        LOG.debug('RPC inspect_hardware called for node %s', node_id)
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='hardware inspection') as task:
            task.driver.power.validate(task)
            task.driver.inspect.validate(task)

            try:
                task.process_event(
                    'inspect',
                    callback=self._spawn_worker,
                    call_args=(inspection.inspect_hardware, task),
                    err_handler=utils.provisioning_error_handler)

            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='inspect', node=task.node.uuid,
                    state=task.node.provision_state)

    @METRICS.timer('ConductorManager._check_inspect_wait_timeouts')
    @periodics.periodic(
        spacing=CONF.conductor.check_provision_state_interval,
        enabled=CONF.conductor.check_provision_state_interval > 0
        and CONF.conductor.inspect_wait_timeout > 0)
    def _check_inspect_wait_timeouts(self, context):
        """Periodically checks inspect_wait_timeout and fails upon reaching it.

        :param context: request context

        """
        callback_timeout = CONF.conductor.inspect_wait_timeout

        filters = {'reserved': False,
                   'maintenance': False,
                   'provision_state': states.INSPECTWAIT,
                   'inspection_started_before': callback_timeout}
        sort_key = 'inspection_started_at'
        last_error = _("timeout reached while inspecting the node")
        self._fail_if_in_state(context, filters, states.INSPECTWAIT,
                               sort_key, last_error=last_error)

    @METRICS.timer('ConductorManager.set_target_raid_config')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue)
    def set_target_raid_config(self, context, node_id, target_raid_config):
        """Stores the target RAID configuration on the node.

        Stores the target RAID configuration on node.target_raid_config

        :param context: request context.
        :param node_id: node id or uuid.
        :param target_raid_config: Dictionary containing the target RAID
            configuration. It may be an empty dictionary as well.
        :raises: UnsupportedDriverExtension, if the node's driver doesn't
            support RAID configuration.
        :raises: InvalidParameterValue, if validation of target raid config
            fails.
        :raises: MissingParameterValue, if some required parameters are
            missing.
        :raises: NodeLocked if node is locked by another conductor.
        """
        LOG.debug('RPC set_target_raid_config called for node %(node)s with '
                  'RAID configuration %(target_raid_config)s',
                  {'node': node_id, 'target_raid_config': target_raid_config})

        with task_manager.acquire(
                context, node_id,
                purpose='setting target RAID config') as task:
            node = task.node
            # Operator may try to unset node.target_raid_config.  So, try to
            # validate only if it is not empty.
            if target_raid_config:
                task.driver.raid.validate_raid_config(task, target_raid_config)
            node.target_raid_config = target_raid_config
            node.save()

    @METRICS.timer('ConductorManager.get_raid_logical_disk_properties')
    @messaging.expected_exceptions(exception.UnsupportedDriverExtension,
                                   exception.NoValidDefaultForInterface,
                                   exception.InterfaceNotFoundInEntrypoint)
    def get_raid_logical_disk_properties(self, context, driver_name):
        """Get the logical disk properties for RAID configuration.

        Gets the information about logical disk properties which can
        be specified in the input RAID configuration. For dynamic drivers,
        the default vendor interface is used.

        :param context: request context.
        :param driver_name: name of the driver
        :raises: UnsupportedDriverExtension, if the driver doesn't
            support RAID configuration.
        :raises: NoValidDefaultForInterface if no default interface
                 implementation can be found for this driver's RAID
                 interface.
        :raises: InterfaceNotFoundInEntrypoint if the default interface for a
                 hardware type is invalid.
        :returns: A dictionary containing the properties and a textual
            description for them.
        """
        LOG.debug("RPC get_raid_logical_disk_properties "
                  "called for driver %s", driver_name)

        driver = driver_factory.get_hardware_type(driver_name)
        raid_iface = None
        raid_iface_name = driver_factory.default_interface(
            driver, 'raid', driver_name=driver_name)
        raid_iface = driver_factory.get_interface(driver, 'raid',
                                                  raid_iface_name)

        return raid_iface.get_logical_disk_properties()

    @METRICS.timer('ConductorManager.heartbeat')
    @messaging.expected_exceptions(exception.InvalidParameterValue)
    @messaging.expected_exceptions(exception.NoFreeConductorWorker)
    def heartbeat(self, context, node_id, callback_url, agent_version=None,
                  agent_token=None, agent_verify_ca=None, agent_status=None,
                  agent_status_message=None):
        """Process a heartbeat from the ramdisk.

        :param context: request context.
        :param node_id: node id or uuid.
        :param callback_url: URL to reach back to the ramdisk.
        :param agent_version: The version of the agent that is heartbeating. If
            not provided it either indicates that the agent that is
            heartbeating is a version before sending agent_version was
            introduced or that we're in the middle of a rolling upgrade and the
            RPC version is pinned so the API isn't passing us the
            agent_version, in these cases assume agent v3.0.0 (the last release
            before sending agent_version was introduced).
        :param agent_token: randomly generated validation token.
        :param agent_status: Status of the heartbeating agent. Agent status is
            one of 'start', 'end', error'
        :param agent_status_message: Message describing agent's status
        :param agent_verify_ca: TLS certificate for the agent.
        :raises: NoFreeConductorWorker if there are no conductors to process
            this heartbeat request.
        """
        LOG.debug('RPC heartbeat called for node %s', node_id)

        # Do not raise exception if version is missing when agent is
        # anaconda ramdisk.
        if agent_version is None and agent_status is None:
            LOG.error('Node %s transmitted no version information which '
                      'indicates the agent is incompatible with the ironic '
                      'services and must be upgraded.', node_id)
            raise exception.InvalidParameterValue(
                _('Agent did not transmit a version, and a version is '
                  'required. Please update the agent being used.'))

        # NOTE(dtantsur): we acquire a shared lock to begin with, drivers are
        # free to promote it to an exclusive one.
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose='heartbeat') as task:

            # NOTE(TheJulia): The "token" line of defense.
            # either tokens are required and they are present,
            # or a token is present in general and needs to be
            # validated.
            if not utils.is_agent_token_valid(task.node, agent_token):
                LOG.error('Invalid or missing agent_token received for '
                          'node %(node)s', {'node': node_id})
                raise exception.InvalidParameterValue(
                    'Invalid or missing agent token received.')

            if (CONF.agent.require_tls and callback_url
                    and not callback_url.startswith('https://')):
                LOG.error('Rejecting callback_url %(url)s for node '
                          '%(node)s because it does not use TLS',
                          {'url': callback_url, 'node': task.node.uuid})
                raise exception.InvalidParameterValue(
                    _('TLS is required by configuration'))

            if agent_verify_ca:
                agent_verify_ca = utils.store_agent_certificate(
                    task.node, agent_verify_ca)

            task.spawn_after(
                self._spawn_worker, task.driver.deploy.heartbeat,
                task, callback_url, agent_version, agent_verify_ca,
                agent_status, agent_status_message)

    @METRICS.timer('ConductorManager.vif_list')
    @messaging.expected_exceptions(exception.NetworkError,
                                   exception.InvalidParameterValue)
    def vif_list(self, context, node_id):
        """List attached VIFs for a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :returns: List of VIF dictionaries, each dictionary will have an
            'id' entry with the ID of the VIF.
        :raises: NetworkError, if something goes wrong during list the VIFs.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF list is wrong/missing.
        """
        LOG.debug("RPC vif_list called for the node %s", node_id)
        with task_manager.acquire(context, node_id,
                                  purpose='list vifs',
                                  shared=True) as task:
            task.driver.network.validate(task)
            return task.driver.network.vif_list(task)

    @METRICS.timer('ConductorManager.vif_attach')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NetworkError,
                                   exception.VifAlreadyAttached,
                                   exception.NoFreePhysicalPorts,
                                   exception.PortgroupPhysnetInconsistent,
                                   exception.VifInvalidForAttach,
                                   exception.InvalidParameterValue)
    def vif_attach(self, context, node_id, vif_info):
        """Attach a VIF to a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :param vif_info: a dictionary representing VIF object.
             It must have an 'id' key, whose value is a unique
             identifier for that VIF.
        :raises: VifAlreadyAttached, if VIF is already attached to node
        :raises: NoFreePhysicalPorts, if no free physical ports left to attach
        :raises: NodeLocked, if node has an exclusive lock held on it
        :raises: NetworkError, if an error occurs during attaching the VIF.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF attach is wrong/missing.
        :raises: PortgroupPhysnetInconsistent if one of the node's portgroups
                 has ports which are not all assigned the same physical
                 network.
        :raises: VifInvalidForAttach if the VIF is not valid for attachment to
                 the node.
        """
        LOG.debug("RPC vif_attach called for the node %(node_id)s with "
                  "vif_info %(vif_info)s", {'node_id': node_id,
                                            'vif_info': vif_info})
        with task_manager.acquire(context, node_id,
                                  purpose='attach vif') as task:
            task.driver.network.validate(task)
            task.driver.network.vif_attach(task, vif_info)
        LOG.info("VIF %(vif_id)s successfully attached to node %(node_id)s",
                 {'vif_id': vif_info['id'], 'node_id': node_id})

    @METRICS.timer('ConductorManager.vif_detach')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NetworkError,
                                   exception.VifNotAttached,
                                   exception.InvalidParameterValue)
    def vif_detach(self, context, node_id, vif_id):
        """Detach a VIF from a node

        :param context: request context.
        :param node_id: node ID or UUID.
        :param vif_id: A VIF ID.
        :raises: VifNotAttached, if VIF not attached to node
        :raises: NodeLocked, if node has an exclusive lock held on it
        :raises: NetworkError, if an error occurs during detaching the VIF.
        :raises: InvalidParameterValue, if a parameter that's required for
            VIF detach is wrong/missing.
        """
        LOG.debug("RPC vif_detach called for the node %(node_id)s with "
                  "vif_id %(vif_id)s", {'node_id': node_id, 'vif_id': vif_id})
        with task_manager.acquire(context, node_id,
                                  purpose='detach vif') as task:
            task.driver.network.validate(task)
            task.driver.network.vif_detach(task, vif_id)
        LOG.info("VIF %(vif_id)s successfully detached from node %(node_id)s",
                 {'vif_id': vif_id, 'node_id': node_id})

    def _object_dispatch(self, target, method, context, args, kwargs):
        """Dispatch a call to an object method.

        This ensures that object methods get called and any exception
        that is raised gets wrapped in an ExpectedException for forwarding
        back to the caller (without spamming the conductor logs).
        """
        try:
            # NOTE(danms): Keep the getattr inside the try block since
            # a missing method is really a client problem
            return getattr(target, method)(context, *args, **kwargs)
        except Exception:
            # NOTE(danms): This is oslo.messaging fu. ExpectedException()
            # grabs sys.exc_info here and forwards it along. This allows the
            # caller to see the exception information, but causes us *not* to
            # log it as such in this service. This is something that is quite
            # critical so that things that conductor does on behalf of another
            # node are not logged as exceptions in conductor logs. Otherwise,
            # you'd have the same thing logged in both places, even though an
            # exception here *always* means that the caller screwed up, so
            # there's no reason to log it here.
            raise messaging.ExpectedException()

    @METRICS.timer('ConductorManager.object_class_action_versions')
    def object_class_action_versions(self, context, objname, objmethod,
                                     object_versions, args, kwargs):
        """Perform an action on a VersionedObject class.

        :param context: The context within which to perform the action
        :param objname: The registry name of the object
        :param objmethod: The name of the action method to call
        :param object_versions: A dict of {objname: version} mappings
        :param args: The positional arguments to the action method
        :param kwargs: The keyword arguments to the action method
        :returns: The result of the action method, which may (or may not)
                  be an instance of the implementing VersionedObject class.
        """
        objclass = objects_base.IronicObject.obj_class_from_name(
            objname, object_versions[objname])
        result = self._object_dispatch(objclass, objmethod, context,
                                       args, kwargs)
        # NOTE(danms): The RPC layer will convert to primitives for us,
        # but in this case, we need to honor the version the client is
        # asking for, so we do it before returning here.
        if isinstance(result, objects_base.IronicObject):
            result = result.obj_to_primitive(
                target_version=object_versions[objname],
                version_manifest=object_versions)
        return result

    @METRICS.timer('ConductorManager.object_action')
    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on a VersionedObject instance.

        :param context: The context within which to perform the action
        :param objinst: The object instance on which to perform the action
        :param objmethod: The name of the action method to call
        :param args: The positional arguments to the action method
        :param kwargs: The keyword arguments to the action method
        :returns: A tuple with the updates made to the object and
                  the result of the action method
        """

        oldobj = objinst.obj_clone()
        result = self._object_dispatch(objinst, objmethod, context,
                                       args, kwargs)
        updates = dict()
        # NOTE(danms): Diff the object with the one passed to us and
        # generate a list of changes to forward back
        for name, field in objinst.fields.items():
            if not objinst.obj_attr_is_set(name):
                # Avoid demand-loading anything
                continue
            if (not oldobj.obj_attr_is_set(name)
                    or getattr(oldobj, name) != getattr(objinst, name)):
                updates[name] = field.to_primitive(objinst, name,
                                                   getattr(objinst, name))
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    @METRICS.timer('ConductorManager.object_backport_versions')
    def object_backport_versions(self, context, objinst, object_versions):
        """Perform a backport of an object instance.

        The default behavior of the base VersionedObjectSerializer, upon
        receiving an object with a version newer than what is in the local
        registry, is to call this method to request a backport of the object.

        :param context: The context within which to perform the backport
        :param objinst: An instance of a VersionedObject to be backported
        :param object_versions: A dict of {objname: version} mappings
        :returns: The downgraded instance of objinst
        """
        target = object_versions[objinst.obj_name()]
        LOG.debug('Backporting %(obj)s to %(ver)s with versions %(manifest)s',
                  {'obj': objinst.obj_name(),
                   'ver': target,
                   'manifest': ','.join(
                       ['%s=%s' % (name, ver)
                        for name, ver in object_versions.items()])})
        return objinst.obj_to_primitive(target_version=target,
                                        version_manifest=object_versions)

    @METRICS.timer('ConductorManager.add_node_traits')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NodeLocked,
                                   exception.NodeNotFound)
    def add_node_traits(self, context, node_id, traits, replace=False):
        """Add or replace traits for a node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param traits: a list of traits to add to the node.
        :param replace: True to replace all of the node's traits.
        :raises: InvalidParameterValue if adding the traits would exceed the
            per-node traits limit. Traits added prior to reaching the limit
            will not be removed.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node does not exist.
        """
        LOG.debug("RPC add_node_traits called for the node %(node_id)s with "
                  "traits %(traits)s", {'node_id': node_id, 'traits': traits})
        with task_manager.acquire(context, node_id,
                                  purpose='add node traits'):
            if replace:
                objects.TraitList.create(context, node_id=node_id,
                                         traits=traits)
            else:
                for trait in traits:
                    trait = objects.Trait(context, node_id=node_id,
                                          trait=trait)
                    trait.create()

    @METRICS.timer('ConductorManager.remove_node_traits')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NodeNotFound,
                                   exception.NodeTraitNotFound)
    def remove_node_traits(self, context, node_id, traits):
        """Remove some or all traits from a node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param traits: a list of traits to remove from the node, or None. If
            None, all traits will be removed from the node.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeNotFound if the node does not exist.
        :raises: NodeTraitNotFound if one of the traits is not found. Traits
            removed prior to the non-existent trait will not be replaced.
        """
        LOG.debug("RPC remove_node_traits called for the node %(node_id)s "
                  "with traits %(traits)s",
                  {'node_id': node_id, 'traits': traits})
        with task_manager.acquire(context, node_id,
                                  purpose='remove node traits'):
            if traits is None:
                objects.TraitList.destroy(context, node_id=node_id)
            else:
                for trait in traits:
                    objects.Trait.destroy(context, node_id=node_id,
                                          trait=trait)

    @METRICS.timer('ConductorManager.create_allocation')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NodeAssociated,
                                   exception.InstanceAssociated,
                                   exception.NodeNotFound)
    def create_allocation(self, context, allocation):
        """Create an allocation in database.

        :param context: an admin context
        :param allocation: a created (but not saved to the database)
                           allocation object.
        :returns: created allocation object.
        :raises: InvalidParameterValue if some fields fail validation.
        :raises: NodeAssociated if allocation backfill is requested for a node
            that is associated with another instance.
        :raises: InstanceAssociated if allocation backfill is requested, but
            the allocation UUID is already used as instance_uuid on another
            node.
        :raises: NodeNotFound if allocation backfill is requested for a node
            that cannot be found.
        """
        LOG.debug("RPC create_allocation called for allocation %s.",
                  allocation.uuid)
        allocation.conductor_affinity = self.conductor.id
        # Allocation backfilling is handled separately, remove node_id for now.
        # Cannot use plain getattr here since oslo.versionedobjects raise
        # NotImplementedError instead of AttributeError (because life is pain).
        if 'node_id' in allocation and allocation.node_id:
            node_id = allocation.node_id
            allocation.node_id = None
        else:
            node_id = None
        allocation.create()

        if node_id:
            # This is a fast operation and should be done synchronously
            allocations.backfill_allocation(context, allocation, node_id)
        else:
            # Spawn an asynchronous worker to process the allocation. Copy it
            # to avoid data races.
            self._spawn_worker(allocations.do_allocate,
                               context, allocation.obj_clone())

        # Return the current status of the allocation
        return allocation

    @METRICS.timer('ConductorManager.destroy_allocation')
    @messaging.expected_exceptions(exception.InvalidState)
    def destroy_allocation(self, context, allocation):
        """Delete an allocation.

        :param context: request context.
        :param allocation: allocation object.
        :raises: InvalidState if the associated node is in the wrong provision
            state to perform deallocation.
        """
        if allocation.node_id:
            with task_manager.acquire(context, allocation.node_id,
                                      purpose='allocation deletion',
                                      shared=False) as task:
                allocations.verify_node_for_deallocation(task.node, allocation)
                # NOTE(dtantsur): remove the allocation while still holding
                # the node lock to avoid races.
                allocation.destroy()
        else:
            allocation.destroy()

        LOG.info('Successfully deleted allocation %s', allocation.uuid)

    @METRICS.timer('ConductorManager._check_orphan_allocations')
    @periodics.periodic(
        spacing=CONF.conductor.check_allocations_interval,
        enabled=CONF.conductor.check_allocations_interval > 0)
    def _check_orphan_allocations(self, context):
        """Periodically checks the status of allocations that were taken over.

        Periodically checks the allocations assigned to a conductor that
        went offline, tries to take them over and finish.

        :param context: request context.
        """
        offline_conductors = utils.exclude_current_conductor(
            self.conductor.id, self.dbapi.get_offline_conductors(field='id'))
        for conductor_id in offline_conductors:
            filters = {'state': states.ALLOCATING,
                       'conductor_affinity': conductor_id}
            for allocation in objects.Allocation.list(context,
                                                      filters=filters):
                try:
                    if not self.dbapi.take_over_allocation(allocation.id,
                                                           conductor_id,
                                                           self.conductor.id):
                        # Another conductor has taken over, skipping
                        continue
                    LOG.debug('Taking over allocation %s', allocation.uuid)
                    allocations.do_allocate(context, allocation)
                except Exception:
                    LOG.exception('Unexpected exception when taking over '
                                  'allocation %s', allocation.uuid)

    @METRICS.timer('ConductorManager.get_node_with_token')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.Invalid)
    def get_node_with_token(self, context, node_id):
        """Add secret agent token to node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :returns: Secret token set for the node.
        :raises: NodeLocked, if node has an exclusive lock held on it
        :raises: Invalid, if the node already has a token set.
        """
        LOG.debug("RPC get_node_with_token called for the node %(node_id)s",
                  {'node_id': node_id})
        with task_manager.acquire(context, node_id,
                                  purpose='generate_token',
                                  shared=True) as task:
            node = task.node
            if utils.is_agent_token_present(task.node):
                LOG.warning('An agent token generation request is being '
                            'refused as one is already present for '
                            'node %(node)s',
                            {'node': node_id})
                # Allow lookup to work by returning a value, it is just an
                # unusable value that can't be verified against.
                # This is important if the agent lookup has occured with
                # pre-generation of tokens with virtual media usage.
                node.set_driver_internal_info('agent_secret_token', "******")
                return node
            # Do not retry the lock, fail immediately otherwise
            # we can cause these requests to stack up on the API,
            # all thinking they can process the node.
            task.upgrade_lock(retry=False)
            LOG.debug('Generating agent token for node %(node)s',
                      {'node': task.node.uuid})
            utils.add_secret_token(task.node)
            task.node.save()
        return objects.Node.get(context, node_id)

    @METRICS.timer('ConductorManager.manage_node_history')
    @periodics.periodic(
        spacing=CONF.conductor.node_history_cleanup_interval,
        enabled=(
            CONF.conductor.node_history_cleanup_batch_count > 0
            and CONF.conductor.node_history_max_entries != 0
        )
    )
    def manage_node_history(self, context):
        try:
            self._manage_node_history(context)
        except Exception as e:
            LOG.error('Encountered error while cleaning node '
                      'history records: %s', e)

    def _manage_node_history(self, context):
        """Periodic task to keep the node history tidy."""
        max_batch = CONF.conductor.node_history_cleanup_batch_count
        # NOTE(TheJulia): Asks the db for the list. Presently just gets
        # the node id and the count. If we incorporate by date constraint
        # or handling, then it will need to be something like the method
        # needs to identify the explicit ID values to delete, and then
        # the deletion process needs to erase in logical chunks.
        entries_to_clean = self.dbapi.query_node_history_records_for_purge(
            conductor_id=self.conductor.id)
        count = 0
        for node_id in entries_to_clean:
            if count < max_batch:
                # If we have not hit our total limit, proceed
                if entries_to_clean[node_id]:
                    # if we have work to do on this node, proceed.
                    self.dbapi.bulk_delete_node_history_records(
                        entries_to_clean[node_id])
            else:
                LOG.warning('While cleaning up node history records, '
                            'we reached the maximum number of records '
                            'permitted in a single batch. If this error '
                            'is repeated, consider tuning node history '
                            'configuration options to be more aggressive '
                            'by increasing frequency and lowering the '
                            'number of entries to be deleted to not '
                            'negatively impact performance.')
                break
            count = count + len(entries_to_clean[node_id])
            # Yield to other threads, since we also don't want to be
            # looping tightly deleting rows as that will negatively
            # impact DB access if done in excess.
            eventlet.sleep(0)

    def _concurrent_action_limit(self, action):
        """Check Concurrency limits and block operations if needed.

        This method is used to serve as a central place for the logic
        for checks on concurrency limits. If a limit is reached, then
        an appropriate exception is raised.

        :raises: ConcurrentActionLimit If the system configuration
                 is exceeded.
        """
        # NOTE(TheJulia): Keeping this all in one place for simplicity.
        if action == 'provisioning':
            node_count = self.dbapi.count_nodes_in_provision_state([
                states.DEPLOYING,
                states.DEPLOYWAIT
            ])
            if node_count >= CONF.conductor.max_concurrent_deploy:
                raise exception.ConcurrentActionLimit(
                    task_type=action)

        if action == 'unprovisioning' or action == 'cleaning':
            # NOTE(TheJulia): This also checks for the deleting state
            # which is super transitory, *but* you can get a node into
            # the state. So in order to guard against a DoS attack, we
            # need to check even the super transitory node state.
            node_count = self.dbapi.count_nodes_in_provision_state([
                states.DELETING,
                states.CLEANING,
                states.CLEANWAIT
            ])
            if node_count >= CONF.conductor.max_concurrent_clean:
                raise exception.ConcurrentActionLimit(
                    task_type=action)

    @METRICS.timer('ConductorManager.continue_inspection')
    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.NotFound,
                                   exception.Invalid)
    def continue_inspection(self, context, node_id, inventory,
                            plugin_data=None):
        """Continue in-band inspection.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param inventory: hardware inventory from the node.
        :param plugin_data: optional plugin-specific data.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NotFound if node is in invalid state.
        """
        LOG.debug("RPC continue_inspection called for the node %(node_id)s",
                  {'node_id': node_id})
        with task_manager.acquire(context, node_id,
                                  purpose='continue inspection',
                                  shared=False) as task:
            # TODO(dtantsur): support active state (re-)inspection
            if task.node.provision_state != states.INSPECTWAIT:
                LOG.error('Refusing to process inspection data for node '
                          '%(node)s in invalid state %(state)s',
                          {'node': task.node.uuid,
                           'state': task.node.provision_state})
                raise exception.NotFound()

            task.process_event(
                'resume',
                callback=self._spawn_worker,
                call_args=(inspection.continue_inspection,
                           task, inventory, plugin_data),
                err_handler=utils.provisioning_error_handler)

    @METRICS.timer('ConductorManager.do_node_service')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.InvalidStateRequested,
                                   exception.NodeInMaintenance,
                                   exception.NodeLocked,
                                   exception.NoFreeConductorWorker,
                                   exception.ConcurrentActionLimit)
    def do_node_service(self, context, node_id, service_steps,
                        disable_ramdisk=False):
        """RPC method to initiate node service.

        :param context: an admin context.
        :param node_id: the ID or UUID of a node.
        :param service_steps: an ordered list of steps that will be
            performed on the node. A step is a dictionary with required
            keys 'interface' and 'step', and optional key 'args'. If
            specified, the 'args' arguments are passed to the clean step
            method.::

              { 'interface': <driver_interface>,
                'step': <name_of__step>,
                'args': {<arg1>: <value1>, ..., <argn>: <valuen>} }

            For example (this isn't a real example, this service step
            doesn't exist)::

              { 'interface': deploy',
                'step': 'upgrade_firmware',
                'args': {'force': True} }
        :param disable_ramdisk: Optional. Whether to disable the ramdisk boot.
        :raises: InvalidParameterValue if power validation fails.
        :raises: InvalidStateRequested if the node is not in manageable state.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        :raises: ConcurrentActionLimit If this action would exceed the
                 configured limits of the deployment.
        """
        self._concurrent_action_limit(action='service')
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node service') as task:
            node = task.node
            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('service'),
                                                  node=node.uuid)
            # NOTE(TheJulia): service.do_node_service() will also make similar
            # calls to validate power & network, but we are doing it again
            # here so that the user gets immediate feedback of any issues.
            # This behaviour (of validating) is consistent with other methods
            # like self.do_node_deploy().
            try:
                task.driver.power.validate(task)
                task.driver.network.validate(task)
            except exception.InvalidParameterValue as e:
                msg = (_('Validation of node %(node)s for servicing '
                         'failed: %(msg)s') %
                       {'node': node.uuid, 'msg': e})
                raise exception.InvalidParameterValue(msg)
            try:
                task.process_event(
                    'service',
                    callback=self._spawn_worker,
                    call_args=(servicing.do_node_service, task, service_steps,
                               disable_ramdisk),
                    err_handler=utils.provisioning_error_handler,
                    target_state=states.ACTIVE)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='service', node=node.uuid,
                    state=node.provision_state)

    @METRICS.timer('ConductorManager.attach_virtual_media')
    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.NoFreeConductorWorker,
                                   exception.NodeLocked,
                                   exception.UnsupportedDriverExtension)
    def attach_virtual_media(self, context, node_id, device_type, image_url,
                             image_download_source='local'):
        """Attach a virtual media device to the node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param image_url: URL of the image to attach, HTTP or HTTPS.
        :param image_download_source: Which way to serve the image to the BMC:
            "http" to serve it from the provided location, "local" to serve
            it from the local web server.
        :raises: UnsupportedDriverExtension if the driver does not support
                 this call.
        :raises: InvalidParameterValue if validation of management driver
                 interface failed.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        LOG.debug("RPC attach_virtual_media called for node %(node)s "
                  "for device type %(type)s",
                  {'node': node_id, 'type': device_type})
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='attaching virtual media') as task:
            task.driver.management.validate(task)
            # Starting new operation, so clear the previous error.
            # We'll be putting an error here soon if we fail task.
            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(utils._spawn_error_handler,
                                      task.node, "attaching virtual media")
            task.spawn_after(self._spawn_worker,
                             do_attach_virtual_media, task,
                             device_type=device_type,
                             image_url=image_url,
                             image_download_source=image_download_source)

    def detach_virtual_media(self, context, node_id, device_types=None):
        """Detach some or all virtual media devices from the node.

        :param context: request context.
        :param node_id: node ID or UUID.
        :param device_types: A collection of device type, ones from
            :data:`ironic.common.boot_devices.VMEDIA_DEVICES`.
            If not provided, all devices are detached.
        :raises: UnsupportedDriverExtension if the driver does not support
                 this call.
        :raises: InvalidParameterValue if validation of management driver
                 interface failed.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        LOG.debug("RPC detach_virtual_media called for node %(node)s "
                  "for device types %(type)s",
                  {'node': node_id, 'type': device_types})
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='detaching virtual media') as task:
            task.driver.management.validate(task)
            # Starting new operation, so clear the previous error.
            # We'll be putting an error here soon if we fail task.
            task.node.last_error = None
            task.node.save()
            task.set_spawn_error_hook(utils._spawn_error_handler,
                                      task.node, "detaching virtual media")
            task.spawn_after(self._spawn_worker,
                             utils.run_node_action,
                             task, task.driver.management.detach_virtual_media,
                             success_msg="Device(s) %(device_types)s detached "
                             "from node %(node)s",
                             error_msg="Could not detach device(s) "
                             "%(device_types)s from node %(node)s: %(exc)s",
                             device_types=device_types)


# NOTE(TheJulia): This is the end of the class definition for the
# conductor manager. Methods for RPC and stuffs should go above this
# point in the File. Everything below is a helper or periodic.

@METRICS.timer('get_vendor_passthru_metadata')
def get_vendor_passthru_metadata(route_dict):
    d = {}
    for method, metadata in route_dict.items():
        # 'func' is the vendor method reference, ignore it
        d[method] = {k: metadata[k] for k in metadata if k != 'func'}
    return d


@task_manager.require_exclusive_lock
def handle_sync_power_state_max_retries_exceeded(task, actual_power_state,
                                                 exception=None):
    """Handles power state sync exceeding the max retries.

    When synchronizing the power state between a node and the DB has exceeded
    the maximum number of retries, change the DB power state to be the actual
    node power state and place the node in maintenance.

    :param task: a TaskManager instance with an exclusive lock
    :param actual_power_state: the actual power state of the node; a power
           state from ironic.common.states
    :param exception: the exception object that caused the sync power state
           to fail, if present.
    """
    node = task.node
    msg = (_("During sync_power_state, max retries exceeded "
             "for node %(node)s, node state %(actual)s "
             "does not match expected state '%(state)s'. "
             "Updating DB state to '%(actual)s' "
             "Switching node to maintenance mode.") %
           {'node': node.uuid, 'actual': actual_power_state,
            'state': node.power_state})

    if exception is not None:
        msg += _(" Error: %s") % exception

    old_power_state = node.power_state
    node.power_state = actual_power_state
    utils.node_history_record(task.node, event=msg,
                              event_type=states.MONITORING,
                              error=True)
    node.maintenance = True
    node.maintenance_reason = msg
    node.fault = faults.POWER_FAILURE
    node.save()
    if old_power_state != actual_power_state:
        if node.instance_uuid:
            nova.power_update(
                task.context, node.instance_uuid, node.power_state)
        notify_utils.emit_power_state_corrected_notification(
            task, old_power_state)
    LOG.error(msg)


@METRICS.timer('do_sync_power_state')
def do_sync_power_state(task, count):
    """Sync the power state for this node, incrementing the counter on failure.

    When the limit of power_state_sync_max_retries is reached, the node is put
    into maintenance mode and the error recorded.

    :param task: a TaskManager instance
    :param count: number of times this node has previously failed a sync
    :raises: NodeLocked if unable to upgrade task lock to an exclusive one
    :returns: Count of failed attempts.
              On success, the counter is set to 0.
              On failure, the count is incremented by one
    """
    node = task.node
    old_power_state = node.power_state
    power_state = None
    count += 1

    max_retries = CONF.conductor.power_state_sync_max_retries
    # If power driver info can not be validated, and node has no prior state,
    # do not attempt to sync the node's power state.
    if node.power_state is None:
        try:
            task.driver.power.validate(task)
        except exception.InvalidParameterValue:
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
        if count > max_retries:
            task.upgrade_lock()
            handle_sync_power_state_max_retries_exceeded(task, power_state,
                                                         exception=e)
        else:
            LOG.warning("During sync_power_state, could not get power "
                        "state for node %(node)s, attempt %(attempt)s of "
                        "%(retries)s. Error: %(err)s.",
                        {'node': node.uuid, 'attempt': count,
                         'retries': max_retries, 'err': e})
        return count

    # Make sure we have the vendor cached (if for some reason it failed during
    # the transition to manageable or a really old API version was used).
    utils.node_cache_vendor(task)
    # Also make sure to cache the current boot_mode and secure_boot states
    utils.node_cache_boot_mode(task)

    if ((node.power_state and node.power_state == power_state)
            or (node.power_state is None and power_state is None)):
        # No action is needed
        return 0

    # We will modify a node, so upgrade our lock and use reloaded node.
    # This call may raise NodeLocked that will be caught on upper level.
    task.upgrade_lock()
    node = task.node

    # Repeat all checks with exclusive lock to avoid races
    if ((node.power_state and node.power_state == power_state)
            or (node.power_state is None and power_state is None)):
        # Node power state was updated to the correct value
        return 0
    elif node.provision_state in SYNC_EXCLUDED_STATES or node.maintenance:
        # Something was done to a node while a shared lock was held
        return 0
    elif node.power_state is None:
        # If node has no prior state AND we successfully got a state,
        # simply record that and send a notification.
        LOG.info("During sync_power_state, node %(node)s has no "
                 "previous known state. Recording current state '%(state)s'.",
                 {'node': node.uuid, 'state': power_state})
        node.power_state = power_state
        node.save()
        if node.instance_uuid:
            nova.power_update(
                task.context, node.instance_uuid, node.power_state)
        notify_utils.emit_power_state_corrected_notification(
            task, None)
        return 0

    if count > max_retries:
        handle_sync_power_state_max_retries_exceeded(task, power_state)
        return count

    if (CONF.conductor.force_power_state_during_sync
            and task.driver.power.supports_power_sync(task)):
        LOG.warning("During sync_power_state, node %(node)s state "
                    "'%(actual)s' does not match expected state. "
                    "Changing hardware state to '%(state)s'.",
                    {'node': node.uuid, 'actual': power_state,
                     'state': node.power_state})
        try:
            # node_power_action will update the node record
            # so don't do that again here.
            utils.node_power_action(task, node.power_state)
        except Exception:
            LOG.error(
                "Failed to change power state of node %(node)s "
                "to '%(state)s', attempt %(attempt)s of %(retries)s.",
                {'node': node.uuid,
                 'state': node.power_state,
                 'attempt': count,
                 'retries': max_retries})
    else:
        LOG.warning("During sync_power_state, node %(node)s state "
                    "does not match expected state '%(state)s'. "
                    "Updating recorded state to '%(actual)s'.",
                    {'node': node.uuid, 'actual': power_state,
                     'state': node.power_state})
        node.power_state = power_state
        node.save()
        if node.instance_uuid:
            nova.power_update(
                task.context, node.instance_uuid, node.power_state)
        notify_utils.emit_power_state_corrected_notification(
            task, old_power_state)

    return count


def do_attach_virtual_media(task, device_type, image_url,
                            image_download_source):
    assert device_type in boot_devices.VMEDIA_DEVICES
    file_name = "%s.%s" % (
        device_type.lower(),
        'iso' if device_type == boot_devices.CDROM else 'img'
    )
    image_url = image_utils.prepare_remote_image(
        task, image_url, file_name=file_name,
        download_source=image_download_source)
    utils.run_node_action(
        task, task.driver.management.attach_virtual_media,
        success_msg="Device %(device_type)s attached to node %(node)s",
        error_msg="Could not attach device %(device_type)s "
        "to node %(node)s: %(exc)s",
        device_type=device_type,
        image_url=image_url)


def do_detach_virtual_media(task, device_types):
    utils.run_node_action(task, task.driver.management.detach_virtual_media,
                          success_msg="Device(s) %(device_types)s detached "
                          "from node %(node)s",
                          error_msg="Could not detach device(s) "
                          "%(device_types)s from node %(node)s: %(exc)s",
                          device_types=device_types)
    for device_type in device_types:
        suffix = '.iso' if device_type == boot_devices.CDROM else '.img'
        image_utils.ImageHandler.unpublish_image_for_node(
            task.node, prefix=device_type.lower(), suffix=suffix)
