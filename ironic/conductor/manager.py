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
import tempfile

import eventlet
from futurist import periodics
from oslo_config import cfg
from oslo_log import log
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import uuidutils

from ironic.common import dhcp_factory
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common.glance_service import service_utils as glance_utils
from ironic.common.i18n import _
from ironic.common.i18n import _LE
from ironic.common.i18n import _LI
from ironic.common.i18n import _LW
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.conductor import base_manager
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic import objects
from ironic.objects import base as objects_base

MANAGER_TOPIC = 'ironic.conductor_manager'

LOG = log.getLogger(__name__)

conductor_opts = [
    cfg.StrOpt('api_url',
               help=_('URL of Ironic API service. If not set ironic can '
                      'get the current value from the keystone service '
                      'catalog.')),
    cfg.IntOpt('heartbeat_timeout',
               default=60,
               help=_('Maximum time (in seconds) since the last check-in '
                      'of a conductor. A conductor is considered inactive '
                      'when this time has been exceeded.')),
    cfg.IntOpt('sync_power_state_interval',
               default=60,
               help=_('Interval between syncing the node power state to the '
                      'database, in seconds.')),
    cfg.IntOpt('check_provision_state_interval',
               default=60,
               help=_('Interval between checks of provision timeouts, '
                      'in seconds.')),
    cfg.IntOpt('deploy_callback_timeout',
               default=1800,
               help=_('Timeout (seconds) to wait for a callback from '
                      'a deploy ramdisk. Set to 0 to disable timeout.')),
    cfg.BoolOpt('force_power_state_during_sync',
                default=True,
                help=_('During sync_power_state, should the hardware power '
                       'state be set to the state recorded in the database '
                       '(True) or should the database be updated based on '
                       'the hardware state (False).')),
    cfg.IntOpt('power_state_sync_max_retries',
               default=3,
               help=_('During sync_power_state failures, limit the '
                      'number of times Ironic should try syncing the '
                      'hardware node power state with the node power state '
                      'in DB')),
    cfg.IntOpt('periodic_max_workers',
               default=8,
               help=_('Maximum number of worker threads that can be started '
                      'simultaneously by a periodic task. Should be less '
                      'than RPC thread pool size.')),
    cfg.IntOpt('node_locked_retry_attempts',
               default=3,
               help=_('Number of attempts to grab a node lock.')),
    cfg.IntOpt('node_locked_retry_interval',
               default=1,
               help=_('Seconds to sleep between node lock attempts.')),
    cfg.BoolOpt('send_sensor_data',
                default=False,
                help=_('Enable sending sensor data message via the '
                       'notification bus')),
    cfg.IntOpt('send_sensor_data_interval',
               default=600,
               help=_('Seconds between conductor sending sensor data message'
                      ' to ceilometer via the notification bus.')),
    cfg.ListOpt('send_sensor_data_types',
                default=['ALL'],
                help=_('List of comma separated meter types which need to be'
                       ' sent to Ceilometer. The default value, "ALL", is a '
                       'special value meaning send all the sensor data.')),
    cfg.IntOpt('sync_local_state_interval',
               default=180,
               help=_('When conductors join or leave the cluster, existing '
                      'conductors may need to update any persistent '
                      'local state as nodes are moved around the cluster. '
                      'This option controls how often, in seconds, each '
                      'conductor will check for nodes that it should '
                      '"take over". Set it to a negative value to disable '
                      'the check entirely.')),
    cfg.BoolOpt('configdrive_use_swift',
                default=False,
                help=_('Whether to upload the config drive to Swift.')),
    cfg.StrOpt('configdrive_swift_container',
               default='ironic_configdrive_container',
               help=_('Name of the Swift container to store config drive '
                      'data. Used when configdrive_use_swift is True.')),
    cfg.IntOpt('inspect_timeout',
               default=1800,
               help=_('Timeout (seconds) for waiting for node inspection. '
                      '0 - unlimited.')),
    # TODO(rloo): Remove support for deprecated name 'clean_nodes' in Newton
    #             cycle.
    cfg.BoolOpt('automated_clean',
                default=True,
                deprecated_name='clean_nodes',
                help=_('Enables or disables automated cleaning. Automated '
                       'cleaning is a configurable set of steps, '
                       'such as erasing disk drives, that are performed on '
                       'the node to ensure it is in a baseline state and '
                       'ready to be deployed to. This is '
                       'done after instance deletion as well as during '
                       'the transition from a "manageable" to "available" '
                       'state. When enabled, the particular steps '
                       'performed to clean a node depend on which driver '
                       'that node is managed by; see the individual '
                       'driver\'s documentation for details. '
                       'NOTE: The introduction of the cleaning operation '
                       'causes instance deletion to take significantly '
                       'longer. In an environment where all tenants are '
                       'trusted (eg, because there is only one tenant), '
                       'this option could be safely disabled.')),
    cfg.IntOpt('clean_callback_timeout',
               default=1800,
               help=_('Timeout (seconds) to wait for a callback from the '
                      'ramdisk doing the cleaning. If the timeout is reached '
                      'the node will be put in the "clean failed" provision '
                      'state. Set to 0 to disable timeout.')),
]
CONF = cfg.CONF
CONF.register_opts(conductor_opts, 'conductor')
SYNC_EXCLUDED_STATES = (states.DEPLOYWAIT, states.CLEANWAIT, states.ENROLL)


class ConductorManager(base_manager.BaseConductorManager):
    """Ironic Conductor manager main class."""

    # NOTE(rloo): This must be in sync with rpcapi.ConductorAPI's.
    RPC_API_VERSION = '1.33'

    target = messaging.Target(version=RPC_API_VERSION)

    def __init__(self, host, topic):
        super(ConductorManager, self).__init__(host, topic)
        self.power_state_sync_count = collections.defaultdict(int)

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

        # NOTE(jroll) clear maintenance_reason if node.update sets
        # maintenance to False for backwards compatibility, for tools
        # not using the maintenance endpoint.
        delta = node_obj.obj_what_changed()
        if 'maintenance' in delta and not node_obj.maintenance:
            node_obj.maintenance_reason = None

        driver_name = node_obj.driver if 'driver' in delta else None
        with task_manager.acquire(context, node_id, shared=False,
                                  driver_name=driver_name,
                                  purpose='node update'):
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

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='changing node power state') as task:
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
            task.set_spawn_error_hook(utils.power_state_error_handler,
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
        :returns: A dictionary containing:

            :return: The response of the invoked vendor method
            :async: Boolean value. Whether the method was invoked
                asynchronously (True) or synchronously (False). When invoked
                asynchronously the response will be always None.
            :attach: Boolean value. Whether to attach the response of
                the invoked vendor method to the HTTP response object (True)
                or return it in the response body (False).

        """
        LOG.debug("RPC vendor_passthru called for node %s." % node_id)
        # NOTE(max_lobur): Even though not all vendor_passthru calls may
        # require an exclusive lock, we need to do so to guarantee that the
        # state doesn't unexpectedly change between doing a vendor.validate
        # and vendor.vendor_passthru.
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='calling vendor passthru') as task:
            if not getattr(task.driver, 'vendor', None):
                raise exception.UnsupportedDriverExtension(
                    driver=task.node.driver,
                    extension='vendor interface')

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
        LOG.debug("RPC driver_vendor_passthru for driver %s." % driver_name)
        driver = driver_factory.get_driver(driver_name)
        if not getattr(driver, 'vendor', None):
            raise exception.UnsupportedDriverExtension(
                driver=driver_name,
                extension='vendor interface')

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

        return {'return': ret,
                'async': is_async,
                'attach': vendor_opts['attach']}

    @messaging.expected_exceptions(exception.UnsupportedDriverExtension)
    def get_node_vendor_passthru_methods(self, context, node_id):
        """Retrieve information about vendor methods of the given node.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :returns: dictionary of <method name>:<method metadata> entries.

        """
        LOG.debug("RPC get_node_vendor_passthru_methods called for node %s"
                  % node_id)
        lock_purpose = 'listing vendor passthru methods'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
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
        driver = driver_factory.get_driver(driver_name)
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
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node deployment') as task:
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
                raise exception.InstanceDeployFailure(
                    _("RPC do_node_deploy failed to validate deploy or "
                      "power info for node %(node_uuid)s. Error: %(msg)s") %
                    {'node_uuid': node.uuid, 'msg': e})

            LOG.debug("do_node_deploy Calling event: %(event)s for node: "
                      "%(node)s", {'event': event, 'node': node.uuid})
            try:
                task.process_event(
                    event,
                    callback=self._spawn_worker,
                    call_args=(do_node_deploy, task, self.conductor.id,
                               configdrive),
                    err_handler=utils.provisioning_error_handler)
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

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node tear down') as task:
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
                task.process_event(
                    'delete',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_tear_down, task),
                    err_handler=utils.provisioning_error_handler)
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
            # But we do need to clear the instance-related fields.
            node.instance_info = {}
            node.instance_uuid = None
            driver_internal_info = node.driver_internal_info
            driver_internal_info.pop('instance', None)
            node.driver_internal_info = driver_internal_info
            node.save()

        # Begin cleaning
        try:
            task.process_event('clean')
        except exception.InvalidState:
            raise exception.InvalidStateRequested(
                action='clean', node=node.uuid,
                state=node.provision_state)
        self._do_node_clean(task)

    def _get_node_next_clean_steps(self, task, skip_current_step=True):
        """Get the task's node's next clean steps.

        This determines what the next (remaining) clean steps are, and
        returns the index into the clean steps list that corresponds to the
        next clean step. The remaining clean steps are determined as follows:

        * If no clean steps have been started yet, all the clean steps
          must be executed
        * If skip_current_step is False, the remaining clean steps start
          with the current clean step. Otherwise, the remaining clean steps
          start with the clean step after the current one.

        All the clean steps for an automated or manual cleaning are in
        node.driver_internal_info['clean_steps']. node.clean_step is the
        current clean step that was just executed (or None, {} if no steps
        have been executed yet). node.driver_internal_info['clean_step_index']
        is the index into the clean steps list (or None, doesn't exist if no
        steps have been executed yet) and corresponds to node.clean_step.

        :param task: A TaskManager object
        :param skip_current_step: True to skip the current clean step; False to
                                  include it.
        :raises: NodeCleaningFailure if an internal error occurred when
                 getting the next clean steps
        :returns: index of the next clean step; None if there are no clean
                  steps to execute.

        """
        node = task.node
        if not node.clean_step:
            # first time through, all steps need to be done. Return the
            # index of the first step in the list.
            return 0

        ind = None
        if 'clean_step_index' in node.driver_internal_info:
            ind = node.driver_internal_info['clean_step_index']
        else:
            # TODO(rloo). driver_internal_info['clean_step_index'] was
            # added in Mitaka. We need to maintain backwards compatibility
            # so this uses the original code to get the index of the current
            # step. This will be deleted in the Newton cycle.
            try:
                next_steps = node.driver_internal_info['clean_steps']
                ind = next_steps.index(node.clean_step)
            except (KeyError, ValueError):
                msg = (_('Node %(node)s got an invalid last step for '
                         '%(state)s: %(step)s.') %
                       {'node': node.uuid, 'step': node.clean_step,
                        'state': node.provision_state})
                LOG.exception(msg)
                utils.cleaning_error_handler(task, msg)
                raise exception.NodeCleaningFailure(node=node.uuid,
                                                    reason=msg)
        if ind is None:
            return None

        if skip_current_step:
            ind += 1
        if ind >= len(node.driver_internal_info['clean_steps']):
            # no steps left to do
            ind = None
        return ind

    @messaging.expected_exceptions(exception.InvalidParameterValue,
                                   exception.InvalidStateRequested,
                                   exception.NodeInMaintenance,
                                   exception.NodeLocked,
                                   exception.NoFreeConductorWorker)
    def do_node_clean(self, context, node_id, clean_steps):
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
        :raises: InvalidParameterValue if power validation fails.
        :raises: InvalidStateRequested if the node is not in manageable state.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.
        """
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='node manual cleaning') as task:
            node = task.node

            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('cleaning'),
                                                  node=node.uuid)

            # NOTE(rloo): _do_node_clean() will also make a similar call
            # to validate the power, but we are doing it again here so that
            # the user gets immediate feedback of any issues. This behaviour
            # (of validating) is consistent with other methods like
            # self.do_node_deploy().
            try:
                task.driver.power.validate(task)
            except exception.InvalidParameterValue as e:
                msg = (_('RPC do_node_clean failed to validate power info.'
                         ' Cannot clean node %(node)s. Error: %(msg)s') %
                       {'node': node.uuid, 'msg': e})
                raise exception.InvalidParameterValue(msg)

            try:
                task.process_event(
                    'clean',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_clean, task, clean_steps),
                    err_handler=utils.provisioning_error_handler,
                    target_state=states.MANAGEABLE)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='manual clean', node=node.uuid,
                    state=node.provision_state)

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
        :raises: NodeCleaningFailure if an internal error occurred when
                 getting the next clean steps

        """
        LOG.debug("RPC continue_node_clean called for node %s.", node_id)

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='continue node cleaning') as task:
            node = task.node
            if node.target_provision_state == states.MANAGEABLE:
                target_state = states.MANAGEABLE
            else:
                target_state = None

            # TODO(lucasagomes): CLEANING here for backwards compat
            # with previous code, otherwise nodes in CLEANING when this
            # is deployed would fail. Should be removed once the Mitaka
            # release starts.
            if node.provision_state not in (states.CLEANWAIT,
                                            states.CLEANING):
                raise exception.InvalidStateRequested(_(
                    'Cannot continue cleaning on %(node)s, node is in '
                    '%(state)s state, should be %(clean_state)s') %
                    {'node': node.uuid,
                     'state': node.provision_state,
                     'clean_state': states.CLEANWAIT})

            info = node.driver_internal_info
            try:
                skip_current_step = info.pop('skip_current_clean_step')
            except KeyError:
                skip_current_step = True
            else:
                node.driver_internal_info = info
                node.save()

            next_step_index = self._get_node_next_clean_steps(
                task, skip_current_step=skip_current_step)

            # If this isn't the final clean step in the cleaning operation
            # and it is flagged to abort after the clean step that just
            # finished, we abort the cleaning operation.
            if node.clean_step.get('abort_after'):
                step_name = node.clean_step['step']
                if next_step_index is not None:
                    LOG.debug('The cleaning operation for node %(node)s was '
                              'marked to be aborted after step "%(step)s '
                              'completed. Aborting now that it has completed.',
                              {'node': task.node.uuid, 'step': step_name})
                    task.process_event(
                        'abort',
                        callback=self._spawn_worker,
                        call_args=(self._do_node_clean_abort,
                                   task, step_name),
                        err_handler=utils.provisioning_error_handler,
                        target_state=target_state)
                    return

                LOG.debug('The cleaning operation for node %(node)s was '
                          'marked to be aborted after step "%(step)s" '
                          'completed. However, since there are no more '
                          'clean steps after this, the abort is not going '
                          'to be done.', {'node': node.uuid,
                                          'step': step_name})

            # TODO(lucasagomes): This conditional is here for backwards
            # compat with previous code. Should be removed once the Mitaka
            # release starts.
            if node.provision_state == states.CLEANWAIT:
                task.process_event('resume', target_state=target_state)

            task.set_spawn_error_hook(utils.spawn_cleaning_error_handler,
                                      task.node)
            task.spawn_after(
                self._spawn_worker,
                self._do_next_clean_step,
                task, next_step_index)

    def _do_node_clean(self, task, clean_steps=None):
        """Internal RPC method to perform cleaning of a node.

        :param task: a TaskManager instance with an exclusive lock on its node
        :param clean_steps: For a manual clean, the list of clean steps to
                            perform. Is None For automated cleaning (default).
                            For more information, see the clean_steps parameter
                            of :func:`ConductorManager.do_node_clean`.
        """
        node = task.node
        manual_clean = clean_steps is not None
        clean_type = 'manual' if manual_clean else 'automated'
        LOG.debug('Starting %(type)s cleaning for node %(node)s',
                  {'type': clean_type, 'node': node.uuid})

        if not manual_clean and not CONF.conductor.automated_clean:
            # Skip cleaning, move to AVAILABLE.
            node.clean_step = None
            node.save()

            task.process_event('done')
            LOG.info(_LI('Automated cleaning is disabled, node %s has been '
                         'successfully moved to AVAILABLE state.'), node.uuid)
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
            return utils.cleaning_error_handler(task, msg)

        if manual_clean:
            info = node.driver_internal_info
            info['clean_steps'] = clean_steps
            node.driver_internal_info = info
            node.save()

        # Allow the deploy driver to set up the ramdisk again (necessary for
        # IPA cleaning)
        try:
            prepare_result = task.driver.deploy.prepare_cleaning(task)
        except Exception as e:
            msg = (_('Failed to prepare node %(node)s for cleaning: %(e)s')
                   % {'node': node.uuid, 'e': e})
            LOG.exception(msg)
            return utils.cleaning_error_handler(task, msg)

        # TODO(lucasagomes): Should be removed once the Mitaka release starts
        if prepare_result == states.CLEANING:
            LOG.warning(_LW('Returning CLEANING for asynchronous prepare '
                            'cleaning has been deprecated. Please use '
                            'CLEANWAIT instead.'))
            prepare_result = states.CLEANWAIT

        if prepare_result == states.CLEANWAIT:
            # Prepare is asynchronous, the deploy driver will need to
            # set node.driver_internal_info['clean_steps'] and
            # node.clean_step and then make an RPC call to
            # continue_node_cleaning to start cleaning.

            # For manual cleaning, the target provision state is MANAGEABLE,
            # whereas for automated cleaning, it is AVAILABLE (the default).
            target_state = states.MANAGEABLE if manual_clean else None
            task.process_event('wait', target_state=target_state)
            return

        try:
            utils.set_node_cleaning_steps(task)
        except (exception.InvalidParameterValue,
                exception.NodeCleaningFailure) as e:
            msg = (_('Cannot clean node %(node)s. Error: %(msg)s')
                   % {'node': node.uuid, 'msg': e})
            return utils.cleaning_error_handler(task, msg)

        steps = node.driver_internal_info.get('clean_steps', [])
        step_index = 0 if steps else None
        self._do_next_clean_step(task, step_index)

    def _do_next_clean_step(self, task, step_index):
        """Do cleaning, starting from the specified clean step.

        :param task: a TaskManager instance with an exclusive lock
        :param step_index: The first clean step in the list to execute. This
            is the index (from 0) into the list of clean steps in the node's
            driver_internal_info['clean_steps']. Is None if there are no steps
            to execute.
        """
        node = task.node
        # For manual cleaning, the target provision state is MANAGEABLE,
        # whereas for automated cleaning, it is AVAILABLE.
        manual_clean = node.target_provision_state == states.MANAGEABLE

        driver_internal_info = node.driver_internal_info
        if step_index is None:
            steps = []
        else:
            steps = driver_internal_info['clean_steps'][step_index:]

        LOG.info(_LI('Executing %(state)s on node %(node)s, remaining steps: '
                     '%(steps)s'), {'node': node.uuid, 'steps': steps,
                                    'state': node.provision_state})

        # Execute each step until we hit an async step or run out of steps
        for ind, step in enumerate(steps):
            # Save which step we're about to start so we can restart
            # if necessary
            node.clean_step = step
            driver_internal_info['clean_step_index'] = step_index + ind
            node.driver_internal_info = driver_internal_info
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
                utils.cleaning_error_handler(task, msg)
                return

            # TODO(lucasagomes): Should be removed once the Mitaka
            # release starts
            if result == states.CLEANING:
                LOG.warning(_LW('Returning CLEANING for asynchronous clean '
                                'steps has been deprecated. Please use '
                                'CLEANWAIT instead.'))
                result = states.CLEANWAIT

            # Check if the step is done or not. The step should return
            # states.CLEANWAIT if the step is still being executed, or
            # None if the step is done.
            if result == states.CLEANWAIT:
                # Kill this worker, the async step will make an RPC call to
                # continue_node_clean to continue cleaning
                LOG.info(_LI('Clean step %(step)s on node %(node)s being '
                             'executed asynchronously, waiting for driver.') %
                         {'node': node.uuid, 'step': step})
                target_state = states.MANAGEABLE if manual_clean else None
                task.process_event('wait', target_state=target_state)
                return
            elif result is not None:
                msg = (_('While executing step %(step)s on node '
                         '%(node)s, step returned invalid value: %(val)s')
                       % {'step': step, 'node': node.uuid, 'val': result})
                LOG.error(msg)
                return utils.cleaning_error_handler(task, msg)
            LOG.info(_LI('Node %(node)s finished clean step %(step)s'),
                     {'node': node.uuid, 'step': step})

        # Clear clean_step
        node.clean_step = None
        driver_internal_info['clean_steps'] = None
        driver_internal_info.pop('clean_step_index', None)
        node.driver_internal_info = driver_internal_info
        node.save()
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
	    #raise ValueError("Exception called")
            msg = (_('Node %s Failed to tear down from cleaning for node')
                   % node.uuid)  # change1
            LOG.exception(msg)
            return utils.cleaning_error_handler(task, msg,
                                                tear_down_cleaning=False)

        LOG.info(_LI('Node %s cleaning complete'), node.uuid)
        event = 'manage' if manual_clean else 'done'
        # NOTE(rloo): No need to specify target prov. state; we're done
        task.process_event(event)

    def _do_node_verify(self, task):
        """Internal method to perform power credentials verification."""
        node = task.node
        LOG.debug('Starting power credentials verification for node %s',
                  node.uuid)

        error = None
        try:
            task.driver.power.validate(task)
        except Exception as e:
            error = (_('Failed to validate power driver interface for node '
                       '%(node)s. Error: %(msg)s') %
                     {'node': node.uuid, 'msg': e})
        else:
            try:
                power_state = task.driver.power.get_power_state(task)
            except Exception as e:
                error = (_('Failed to get power state for node '
                           '%(node)s. Error: %(msg)s') %
                         {'node': node.uuid, 'msg': e})

        if error is None:
            node.power_state = power_state
            task.process_event('done')
        else:
            LOG.error(error)
            node.last_error = error
            task.process_event('fail')
            node.target_provision_state = None
            node.save()

    def _do_node_clean_abort(self, task, step_name=None):
        """Internal method to abort an ongoing operation.

        :param task: a TaskManager instance with an exclusive lock
        :param step_name: The name of the clean step.
        """
        node = task.node
        try:
            task.driver.deploy.tear_down_cleaning(task)
        except Exception as e:
            LOG.exception(_LE('Failed to tear down cleaning for node %(node)s '
                              'after aborting the operation. Error: %(err)s'),
                          {'node': node.uuid, 'err': e})
            error_msg = _('Failed to tear down cleaning after aborting '
                          'the operation')
            utils.cleaning_error_handler(task, error_msg,
                                         tear_down_cleaning=False,
                                         set_fail_state=False)
            return

        info_message = _('Clean operation aborted for node %s') % node.uuid
        last_error = _('By request, the clean operation was aborted')
        if step_name:
            msg = _(' after the completion of step "%s"') % step_name
            last_error += msg
            info_message += msg

        node.last_error = last_error
        node.clean_step = None
        node.save()
        LOG.info(info_message)

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
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='provision action %s'
                                  % action) as task:
            node = task.node
            if (action == states.VERBS['provide'] and
                    node.provision_state == states.MANAGEABLE):
                task.process_event(
                    'provide',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_clean, task),
                    err_handler=utils.provisioning_error_handler)
                return

            if (action == states.VERBS['manage'] and
                    node.provision_state == states.ENROLL):
                task.process_event(
                    'manage',
                    callback=self._spawn_worker,
                    call_args=(self._do_node_verify, task),
                    err_handler=utils.provisioning_error_handler)
                return

            if (action == states.VERBS['abort'] and
                    node.provision_state == states.CLEANWAIT):

                # Check if the clean step is abortable; if so abort it.
                # Otherwise, indicate in that clean step, that cleaning
                # should be aborted after that step is done.
                if (node.clean_step and not
                    node.clean_step.get('abortable')):
                    LOG.info(_LI('The current clean step "%(clean_step)s" for '
                                 'node %(node)s is not abortable. Adding a '
                                 'flag to abort the cleaning after the clean '
                                 'step is completed.'),
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
                    call_args=(self._do_node_clean_abort, task),
                    err_handler=utils.provisioning_error_handler,
                    target_state=target_state)
                return

            try:
                task.process_event(action)
            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action=action, node=node.uuid,
                    state=node.provision_state)

    @periodics.periodic(spacing=CONF.conductor.sync_power_state_interval)
    def _sync_power_states(self, context):
        """Periodic task to sync power states for the nodes.

        Attempt to grab a lock and sync only if the following
        conditions are met:

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

        filters = {'reserved': False, 'maintenance': False}
        node_iter = self.iter_nodes(fields=['id'], filters=filters)
        for (node_uuid, driver, node_id) in node_iter:
            try:
                # NOTE(dtantsur): start with a shared lock, upgrade if needed
                with task_manager.acquire(context, node_uuid,
                                          purpose='power state sync',
                                          shared=True) as task:
                    # NOTE(deva): we should not acquire a lock on a node in
                    #             DEPLOYWAIT/CLEANWAIT, as this could cause
                    #             an error within a deploy ramdisk POSTing back
                    #             at the same time.
                    # NOTE(dtantsur): it's also pointless (and dangerous) to
                    # sync power state when a power action is in progress
                    if (task.node.provision_state in SYNC_EXCLUDED_STATES or
                            task.node.maintenance or
                            task.node.target_power_state):
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

    @periodics.periodic(spacing=CONF.conductor.check_provision_state_interval)
    def _check_deploy_timeouts(self, context):
        """Periodically checks whether a deploy RPC call has timed out.

        If a deploy call has timed out, the deploy failed and we clean up.

        :param context: request context.
        """
        callback_timeout = CONF.conductor.deploy_callback_timeout
        if not callback_timeout:
            return

        filters = {'reserved': False,
                   'provision_state': states.DEPLOYWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        sort_key = 'provision_updated_at'
        callback_method = utils.cleanup_after_timeout
        err_handler = utils.provisioning_error_handler
        self._fail_if_in_state(context, filters, states.DEPLOYWAIT,
                               sort_key, callback_method, err_handler)

    @periodics.periodic(spacing=CONF.conductor.check_provision_state_interval)
    def _check_deploying_status(self, context):
        """Periodically checks the status of nodes in DEPLOYING state.

        Periodically checks the nodes in DEPLOYING and the state of the
        conductor deploying them. If we find out that a conductor that
        was provisioning the node has died we then break release the
        node and gracefully mark the deployment as failed.

        :param context: request context.
        """
        offline_conductors = self.dbapi.get_offline_conductors()
        if not offline_conductors:
            return

        node_iter = self.iter_nodes(
            fields=['id', 'reservation'],
            filters={'provision_state': states.DEPLOYING,
                     'maintenance': False,
                     'reserved_by_any_of': offline_conductors})
        if not node_iter:
            return

        for node_uuid, driver, node_id, conductor_hostname in node_iter:
            # NOTE(lucasagomes): Although very rare, this may lead to a
            # race condition. By the time we release the lock the conductor
            # that was previously managing the node could be back online.
            try:
                objects.Node.release(context, conductor_hostname, node_id)
            except exception.NodeNotFound:
                LOG.warning(_LW("During checking for deploying state, node "
                                "%s was not found and presumed deleted by "
                                "another process. Skipping."), node_uuid)
                continue
            except exception.NodeLocked:
                LOG.warning(_LW("During checking for deploying state, when "
                                "releasing the lock of the node %s, it was "
                                "locked by another process. Skipping."),
                            node_uuid)
                continue
            except exception.NodeNotLocked:
                LOG.warning(_LW("During checking for deploying state, when "
                                "releasing the lock of the node %s, it was "
                                "already unlocked."), node_uuid)

            self._fail_if_in_state(
                context, {'id': node_id}, states.DEPLOYING,
                'provision_updated_at',
                callback_method=utils.cleanup_after_timeout,
                err_handler=utils.provisioning_error_handler)

    def _do_takeover(self, task):
        """Take over this node.

        Prepares a node for takeover by this conductor, performs the takeover,
        and changes the conductor associated with the node. The node with the
        new conductor affiliation is saved to the DB.

        :param task: a TaskManager instance
        """
        LOG.debug(('Conductor %(cdr)s taking over node %(node)s'),
                  {'cdr': self.host, 'node': task.node.uuid})
        task.driver.deploy.prepare(task)
        task.driver.deploy.take_over(task)
        # NOTE(zhenguo): If console enabled, take over the console session
        # as well.
        if task.node.console_enabled:
            try:
                task.driver.console.start_console(task)
            except Exception as err:
                msg = (_('Failed to start console while taking over the '
                         'node %(node)s: %(err)s.') % {'node': task.node.uuid,
                                                       'err': err})
                LOG.error(msg)
                # If taking over console failed, set node's console_enabled
                # back to False and set node's last error.
                task.node.last_error = msg
                task.node.console_enabled = False
        # NOTE(lucasagomes): Set the ID of the new conductor managing
        #                    this node
        task.node.conductor_affinity = self.conductor.id
        task.node.save()

    @periodics.periodic(spacing=CONF.conductor.check_provision_state_interval)
    def _check_cleanwait_timeouts(self, context):
        """Periodically checks for nodes being cleaned.

        If a node doing cleaning is unresponsive (detected when it stops
        heart beating), the operation should be aborted.

        :param context: request context.
        """
        callback_timeout = CONF.conductor.clean_callback_timeout
        if not callback_timeout:
            return

        filters = {'reserved': False,
                   'provision_state': states.CLEANWAIT,
                   'maintenance': False,
                   'provisioned_before': callback_timeout}
        last_error = _("Timeout reached while cleaning the node. Please "
                       "check if the ramdisk responsible for the cleaning is "
                       "running on the node.")
        self._fail_if_in_state(context, filters, states.CLEANWAIT,
                               'provision_updated_at',
                               last_error=last_error,
                               keep_target_state=True)

    @periodics.periodic(spacing=CONF.conductor.sync_local_state_interval)
    def _sync_local_state(self, context):
        """Perform any actions necessary to sync local state.

        This is called periodically to refresh the conductor's copy of the
        consistent hash ring. If any mappings have changed, this method then
        determines which, if any, nodes need to be "taken over".
        The ensuing actions could include preparing a PXE environment,
        updating the DHCP server, and so on.
        """
        filters = {'reserved': False,
                   'maintenance': False,
                   'provision_state': states.ACTIVE}
        node_iter = self.iter_nodes(fields=['id', 'conductor_affinity'],
                                    filters=filters)

        workers_count = 0
        for node_uuid, driver, node_id, conductor_affinity in node_iter:
            if conductor_affinity == self.conductor.id:
                continue

            # Node is mapped here, but not updated by this conductor last
            try:
                with task_manager.acquire(context, node_uuid,
                                          purpose='node take over') as task:
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
            iwdi = images.is_whole_disk_image(context,
                                              task.node.instance_info)
            task.node.driver_internal_info['is_whole_disk_image'] = iwdi
            for iface_name in task.driver.non_vendor_interfaces:
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
                                   exception.InvalidState)
    def destroy_node(self, context, node_id):
        """Delete a node.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: NodeLocked if node is locked by another conductor.
        :raises: NodeAssociated if the node contains an instance
            associated with it.
        :raises: InvalidState if the node is in the wrong provision
            state to perform deletion.

        """
        # NOTE(dtantsur): we allow deleting a node in maintenance mode even if
        # we would disallow it otherwise. That's done for recovering hopelessly
        # broken nodes (e.g. with broken BMC).
        with task_manager.acquire(context, node_id,
                                  purpose='node deletion') as task:
            node = task.node
            if not node.maintenance and node.instance_uuid is not None:
                raise exception.NodeAssociated(node=node.uuid,
                                               instance=node.instance_uuid)

            # NOTE(lucasagomes): For the *FAIL states we users should
            # move it to a safe state prior to deletion. This is because we
            # should try to avoid deleting a node in a dirty/whacky state,
            # e.g: A node in DEPLOYFAIL, if deleted without passing through
            # tear down/cleaning may leave data from the previous tenant
            # in the disk. So nodes in *FAIL states should first be moved to:
            # CLEANFAIL -> MANAGEABLE
            # INSPECTIONFAIL -> MANAGEABLE
            # DEPLOYFAIL -> DELETING
            if (not node.maintenance and
                    node.provision_state not in states.DELETE_ALLOWED_STATES):
                msg = (_('Can not delete node "%(node)s" while it is in '
                         'provision state "%(state)s". Valid provision states '
                         'to perform deletion are: "%(valid_states)s"') %
                       {'node': node.uuid, 'state': node.provision_state,
                        'valid_states': states.DELETE_ALLOWED_STATES})
                raise exception.InvalidState(msg)
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
        with task_manager.acquire(context, port.node_id,
                                  purpose='port deletion') as task:
            port.destroy()
            LOG.info(_LI('Successfully deleted port %(port)s. '
                         'The node associated with the port was '
                         '%(node)s'),
                     {'port': port.uuid, 'node': task.node.uuid})

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
            LOG.info(_LI('Successfully deleted portgroup %(portgroup)s. '
                         'The node associated with the portgroup was '
                         '%(node)s'),
                     {'portgroup': portgroup.uuid, 'node': task.node.uuid})

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

        lock_purpose = 'getting console information'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            node = task.node

            if not getattr(task.driver, 'console', None):
                raise exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')
            if not node.console_enabled:
                raise exception.NodeConsoleNotEnabled(node=node.uuid)

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

        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='setting console mode') as task:
            node = task.node
            if not getattr(task.driver, 'console', None):
                raise exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')

            task.driver.console.validate(task)

            if enabled == node.console_enabled:
                op = _('enabled') if enabled else _('disabled')
                LOG.info(_LI("No console action was triggered because the "
                             "console is already %s"), op)
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
            op = _('enabling') if enabled else _('disabling')
            msg = (_('Error %(op)s the console on node %(node)s. '
                     'Reason: %(error)s') % {'op': op,
                                             'node': node.uuid,
                                             'error': e})
            node.last_error = msg
            LOG.error(msg)
        else:
            node.console_enabled = enabled
            node.last_error = None
        finally:
            node.save()

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.FailedToUpdateMacOnPort,
                                   exception.MACAlreadyExists,
                                   exception.InvalidState)
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
                 INSPECTING state or not in MAINTENANCE mode.
        """
        port_uuid = port_obj.uuid
        LOG.debug("RPC update_port called for port %s.", port_uuid)

        with task_manager.acquire(context, port_obj.node_id,
                                  purpose='port update') as task:
            node = task.node

            # If port update is modifying the portgroup membership of the port
            # or modifying the local_link_connection or pxe_enabled flags then
            # node should be in MANAGEABLE/INSPECTING/ENROLL provisioning state
            # or in maintenance mode.
            # Otherwise InvalidState exception is raised.
            connectivity_attr = {'portgroup_uuid',
                                 'pxe_enabled',
                                 'local_link_connection'}
            allowed_update_states = [states.ENROLL,
                                     states.INSPECTING,
                                     states.MANAGEABLE]
            if (set(port_obj.obj_what_changed()) & connectivity_attr
                    and not (node.provision_state in allowed_update_states
                             or node.maintenance)):
                action = _("Port %(port)s can not have any connectivity "
                           "attributes (%(connect)s) updated unless "
                           "node %(node)s is in a %(allowed)s state "
                           "or in maintenance mode.")

                raise exception.InvalidState(
                    action % {'port': port_uuid,
                              'node': node.uuid,
                              'connect': ', '.join(connectivity_attr),
                              'allowed': ', '.join(allowed_update_states)})

            if 'address' in port_obj.obj_what_changed():
                vif = port_obj.extra.get('vif_port_id')
                if vif:
                    api = dhcp_factory.DHCPFactory()
                    api.provider.update_port_address(vif, port_obj.address,
                                                     token=context.auth_token)
                # Log warning if there is no vif_port_id and an instance
                # is associated with the node.
                elif node.instance_uuid:
                    LOG.warning(_LW(
                        "No VIF found for instance %(instance)s "
                        "port %(port)s when attempting to update port MAC "
                        "address."),
                        {'port': port_uuid, 'instance': node.instance_uuid})

            port_obj.save()

            return port_obj

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.FailedToUpdateMacOnPort,
                                   exception.PortgroupMACAlreadyExists)
    def update_portgroup(self, context, portgroup_obj):
        """Update a portgroup.

        :param context: request context.
        :param portgroup_obj: a changed (but not saved) portgroup object.
        :raises: DHCPLoadError if the dhcp_provider cannot be loaded.
        :raises: FailedToUpdateMacOnPort if MAC address changed and update
                 failed.
        :raises: PortgroupMACAlreadyExists if the update is setting a MAC which
                 is registered on another portgroup already.
        """
        portgroup_uuid = portgroup_obj.uuid
        LOG.debug("RPC update_portgroup called for portgroup %s.",
                  portgroup_uuid)
        lock_purpose = 'update portgroup'
        with task_manager.acquire(context,
                                  portgroup_obj.node_id,
                                  purpose=lock_purpose) as task:
            node = task.node
            if 'address' in portgroup_obj.obj_what_changed():
                vif = portgroup_obj.extra.get('vif_portgroup_id')
                if vif:
                    api = dhcp_factory.DHCPFactory()
                    api.provider.update_port_address(
                        vif,
                        portgroup_obj.address,
                        token=context.auth_token)
                # Log warning if there is no vif_portgroup_id and an instance
                # is associated with the node.
                elif node.instance_uuid:
                    LOG.warning(_LW(
                        "No VIF was found for instance %(instance)s "
                        "on node %(node)s, when attempting to update "
                        "portgroup %(portgroup)s MAC address."),
                        {'portgroup': portgroup_uuid,
                         'instance': node.instance_uuid,
                         'node': node.uuid})

            portgroup_obj.save()

            return portgroup_obj

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
        driver = driver_factory.get_driver(driver_name)
        return driver.get_properties()

    @periodics.periodic(spacing=CONF.conductor.send_sensor_data_interval)
    def _send_sensor_data(self, context):
        """Periodically sends sensor data to Ceilometer."""
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
                lock_purpose = 'getting sensors data'
                with task_manager.acquire(context,
                                          node_uuid,
                                          shared=True,
                                          purpose=lock_purpose) as task:
                    if not getattr(task.driver, 'management', None):
                        continue
                    task.driver.management.validate(task)
                    sensors_data = task.driver.management.get_sensors_data(
                        task)
            except NotImplementedError:
                LOG.warning(_LW(
                    'get_sensors_data is not implemented for driver'
                    ' %(driver)s, node_uuid is %(node)s'),
                    {'node': node_uuid, 'driver': driver})
            except exception.FailedToParseSensorData as fps:
                LOG.warning(_LW(
                    "During get_sensors_data, could not parse "
                    "sensor data for node %(node)s. Error: %(err)s."),
                    {'node': node_uuid, 'err': str(fps)})
            except exception.FailedToGetSensorData as fgs:
                LOG.warning(_LW(
                    "During get_sensors_data, could not get "
                    "sensor data for node %(node)s. Error: %(err)s."),
                    {'node': node_uuid, 'err': str(fgs)})
            except exception.NodeNotFound:
                LOG.warning(_LW(
                    "During send_sensor_data, node %(node)s was not "
                    "found and presumed deleted by another process."),
                    {'node': node_uuid})
            except Exception as e:
                LOG.warning(_LW(
                    "Failed to get sensor data for node %(node)s. "
                    "Error: %(error)s"), {'node': node_uuid, 'error': str(e)})
            else:
                message['payload'] = (
                    self._filter_out_unsupported_types(sensors_data))
                if message['payload']:
                    self.notifier.info(context, "hardware.ipmi.metrics",
                                       message)
            finally:
                # Yield on every iteration
                eventlet.sleep(0)

    def _filter_out_unsupported_types(self, sensors_data):
        """Filters out sensor data types that aren't specified in the config.

        Removes sensor data types that aren't specified in
        CONF.conductor.send_sensor_data_types.

        :param sensors_data: dict containing sensor types and the associated
               data
        :returns: dict with unsupported sensor types removed
        """
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
        with task_manager.acquire(context, node_id,
                                  purpose='setting boot device') as task:
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
        with task_manager.acquire(context, node_id,
                                  purpose='getting boot device') as task:
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
        lock_purpose = 'getting supported boot devices'
        with task_manager.acquire(context, node_id, shared=True,
                                  purpose=lock_purpose) as task:
            if not getattr(task.driver, 'management', None):
                raise exception.UnsupportedDriverExtension(
                    driver=task.node.driver, extension='management')
            return task.driver.management.get_supported_boot_devices(task)

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
        with task_manager.acquire(context, node_id, shared=False,
                                  purpose='hardware inspection') as task:
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
                task.process_event(
                    'inspect',
                    callback=self._spawn_worker,
                    call_args=(_do_inspect_hardware, task),
                    err_handler=utils.provisioning_error_handler)

            except exception.InvalidState:
                raise exception.InvalidStateRequested(
                    action='inspect', node=task.node.uuid,
                    state=task.node.provision_state)

    @periodics.periodic(spacing=CONF.conductor.check_provision_state_interval)
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

    @messaging.expected_exceptions(exception.NodeLocked,
                                   exception.UnsupportedDriverExtension,
                                   exception.InvalidParameterValue,
                                   exception.MissingParameterValue)
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
            if not getattr(task.driver, 'raid', None):
                raise exception.UnsupportedDriverExtension(
                    driver=task.driver, extension='raid')
            # Operator may try to unset node.target_raid_config.  So, try to
            # validate only if it is not empty.
            if target_raid_config:
                task.driver.raid.validate_raid_config(task, target_raid_config)
            node.target_raid_config = target_raid_config
            node.save()

    @messaging.expected_exceptions(exception.UnsupportedDriverExtension)
    def get_raid_logical_disk_properties(self, context, driver_name):
        """Get the logical disk properties for RAID configuration.

        Gets the information about logical disk properties which can
        be specified in the input RAID configuration.

        :param context: request context.
        :param driver_name: name of the driver
        :raises: UnsupportedDriverExtension, if the driver doesn't
            support RAID configuration.
        :returns: A dictionary containing the properties and a textual
            description for them.
        """
        LOG.debug("RPC get_raid_logical_disk_properties "
                  "called for driver %s" % driver_name)

        driver = driver_factory.get_driver(driver_name)
        if not getattr(driver, 'raid', None):
            raise exception.UnsupportedDriverExtension(
                driver=driver_name, extension='raid')

        return driver.raid.get_logical_disk_properties()

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
            if (not oldobj.obj_attr_is_set(name) or
                    getattr(oldobj, name) != getattr(objinst, name)):
                updates[name] = field.to_primitive(objinst, name,
                                                   getattr(objinst, name))
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

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


def get_vendor_passthru_metadata(route_dict):
    d = {}
    for method, metadata in route_dict.items():
        # 'func' is the vendor method reference, ignore it
        d[method] = {k: metadata[k] for k in metadata if k != 'func'}
    return d


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

        with tempfile.NamedTemporaryFile(dir=CONF.tempdir) as fileobj:
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
        LOG.error(logmsg, args)
        node.last_error = logmsg + errmsg % e

    try:
        try:
            if configdrive:
                _store_configdrive(node, configdrive)
        except exception.SwiftOperationError as e:
            with excutils.save_and_reraise_exception():
                handle_failure(
                    e, task,
                    _LE('Error while uploading the configdrive for '
                        '%(node)s to Swift'),
                    _('Failed to upload the configdrive to Swift. '
                      'Error: %s'))

        try:
            task.driver.deploy.prepare(task)
        except Exception as e:
	# change 2 here
            # raise ValueError("Anup!!")
            with excutils.save_and_reraise_exception():
                handle_failure(
                    e, task,
                    _LE('Error while preparing to deploy to node %(node)s: '
                        '%(err)s') % {'node': node.uuid, 'err': str(e)},  
                    _("Failed to prepare to deploy. Error: %s"))

        try:
            new_state = task.driver.deploy.deploy(task)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                handle_failure(
                    e, task,
                    _LE('Error in deploy of node %(node)s: %(err)s'),
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

    :param task: a TaskManager instance
    :param count: number of times this node has previously failed a sync
    :raises: NodeLocked if unable to upgrade task lock to an exclusive one
    :returns: Count of failed attempts.
              On success, the counter is set to 0.
              On failure, the count is incremented by one
    """
    node = task.node
    power_state = None
    count += 1

    max_retries = CONF.conductor.power_state_sync_max_retries
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
        if count > max_retries:
            task.upgrade_lock()
            handle_sync_power_state_max_retries_exceeded(task, power_state,
                                                         exception=e)
        else:
            LOG.warning(_LW("During sync_power_state, could not get power "
                            "state for node %(node)s, attempt %(attempt)s of "
                            "%(retries)s. Error: %(err)s."),
                        {'node': node.uuid, 'attempt': count,
                         'retries': max_retries, 'err': e})
        return count

    if node.power_state and node.power_state == power_state:
        # No action is needed
        return 0

    # We will modify a node, so upgrade our lock and use reloaded node.
    # This call may raise NodeLocked that will be caught on upper level.
    task.upgrade_lock()
    node = task.node

    # Repeat all checks with exclusive lock to avoid races
    if node.power_state and node.power_state == power_state:
        # Node power state was updated to the correct value
        return 0
    elif node.provision_state in SYNC_EXCLUDED_STATES or node.maintenance:
        # Something was done to a node while a shared lock was held
        return 0
    elif node.power_state is None:
        # If node has no prior state AND we successfully got a state,
        # simply record that.
        LOG.info(_LI("During sync_power_state, node %(node)s has no "
                     "previous known state. Recording current state "
                     "'%(state)s'."),
                 {'node': node.uuid, 'state': power_state})
        node.power_state = power_state
        node.save()
        return 0

    if count > max_retries:
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
            LOG.error(_LE(
                "Failed to change power state of node %(node)s "
                "to '%(state)s', attempt %(attempt)s of %(retries)s."),
                {'node': node.uuid,
                 'state': node.power_state,
                 'attempt': count,
                 'retries': max_retries})
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
	# change 3 here
        # raise ValueError("Anup!!!")
        error = (_("During inspection, driver returned unexpected "
			"state %(state)s to node %(node)s") % {'state': new_state, 'node': node.uuid})
        handle_failure(error)
        raise exception.HardwareInspectionFailure(error=error)
