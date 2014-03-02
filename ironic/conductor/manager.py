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
Commands are received via RPC calls. The conductor service also performs
periodic tasks, eg.  to monitor the status of active deployments.

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

import datetime

from eventlet import greenpool

from oslo.config import cfg

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import hash_ring as hash
from ironic.common import service
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils
from ironic.db import api as dbapi
from ironic.objects import base as objects_base
from ironic.openstack.common import excutils
from ironic.openstack.common import lockutils
from ironic.openstack.common import log
from ironic.openstack.common import periodic_task
from ironic.openstack.common import timeutils

MANAGER_TOPIC = 'ironic.conductor_manager'
WORKER_SPAWN_lOCK = "conductor_worker_spawn"

LOG = log.getLogger(__name__)

conductor_opts = [
        cfg.StrOpt('api_url',
                   default=None,
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
]

CONF = cfg.CONF
CONF.register_opts(conductor_opts, 'conductor')


def _do_sync_power_state(task):
    node = task.node

    try:
        power_state = task.driver.power.get_power_state(task, node)
    except Exception as e:
        # TODO(rloo): change to IronicException, after
        #             https://bugs.launchpad.net/ironic/+bug/1267693
        LOG.warning(_("During sync_power_state, could not get power state for "
                      "node %(node)s. Error: %(err)s."),
                      {'node': node.uuid, 'err': e})
        return

    if node.power_state is None:
        LOG.info(_("During sync_power_state, node %(node)s has no previous "
                   "known state. Recording current state '%(state)s'."),
                   {'node': node.uuid, 'state': power_state})
        node.power_state = power_state
        node.save(task.context)

    if power_state == node.power_state:
        return

    if CONF.conductor.force_power_state_during_sync:
        LOG.warning(_("During sync_power_state, node %(node)s state "
                      "'%(actual)s' does not match expected state. "
                      "Changing hardware state to '%(state)s'."),
                      {'node': node.uuid, 'actual': power_state,
                       'state': node.power_state})
        try:
            # node_power_action will update the node record
            # so don't do that again here.
            utils.node_power_action(task, task.node,
                                    node.power_state)
        except Exception as e:
            # TODO(rloo): change to IronicException after
            # https://bugs.launchpad.net/ironic/+bug/1267693
            LOG.error(_("Failed to change power state of node %(node)s "
                        "to '%(state)s'."), {'node': node.uuid,
                                             'state': node.power_state})
    else:
        LOG.warning(_("During sync_power_state, node %(node)s state "
                      "does not match expected state '%(state)s'. "
                      "Updating recorded state to '%(actual)s'."),
                      {'node': node.uuid, 'actual': power_state,
                       'state': node.power_state})
        node.power_state = power_state
        node.save(task.context)


class ConductorManager(service.PeriodicService):
    """Ironic Conductor service main class."""

    RPC_API_VERSION = '1.11'

    def __init__(self, host, topic):
        serializer = objects_base.IronicObjectSerializer()
        super(ConductorManager, self).__init__(host, topic,
                                               serializer=serializer)

    def start(self):
        super(ConductorManager, self).start()
        self.dbapi = dbapi.get_instance()

        # create a DriverFactory instance, which initializes the stevedore
        # extension manager, when the service starts.
        # TODO(deva): Enable re-loading of the DriverFactory to load new
        #             extensions without restarting the whole service.
        df = driver_factory.DriverFactory()
        self.drivers = df.names
        """List of driver names which this conductor supports."""

        try:
            self.dbapi.register_conductor({'hostname': self.host,
                                           'drivers': self.drivers})
        except exception.ConductorAlreadyRegistered:
            LOG.warn(_("A conductor with hostname %(hostname)s "
                       "was previously registered. Updating registration")
                       % {'hostname': self.host})
            self.dbapi.unregister_conductor(self.host)
            self.dbapi.register_conductor({'hostname': self.host,
                                           'drivers': self.drivers})

        self.driver_rings = self._get_current_driver_rings()
        """Consistent hash ring which maps drivers to conductors."""

        self._worker_pool = greenpool.GreenPool(size=CONF.rpc_thread_pool_size)
        """GreenPool of background workers for performing tasks async."""

    # TODO(deva): add stop() to call unregister_conductor

    def initialize_service_hook(self, service):
        pass

    def process_notification(self, notification):
        LOG.debug(_('Received notification: %r') %
                        notification.get('event_type'))
        # TODO(deva)

    def periodic_tasks(self, context, raise_on_error=False):
        """Periodic tasks are run at pre-specified interval."""
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

    def update_node(self, context, node_obj):
        """Update a node with the supplied data.

        This method is the main "hub" for PUT and PATCH requests in the API.
        It ensures that the requested change is safe to perform,
        validates the parameters with the node's driver, if necessary.

        :param context: an admin context
        :param node_obj: a changed (but not saved) node object.

        """
        node_id = node_obj.uuid
        LOG.debug(_("RPC update_node called for node %s.") % node_id)

        delta = node_obj.obj_what_changed()
        if 'power_state' in delta:
            raise exception.IronicException(_(
                "Invalid method call: update_node can not change node state."))

        driver_name = node_obj.get('driver') if 'driver' in delta else None
        with task_manager.acquire(context, node_id, shared=False,
                                  driver_name=driver_name) as task:

            # TODO(deva): Determine what value will be passed by API when
            #             instance_uuid needs to be unset, and handle it.
            if 'instance_uuid' in delta:
                task.driver.power.validate(task, node_obj)
                node_obj['power_state'] = \
                        task.driver.power.get_power_state(task, node_obj)

                if node_obj['power_state'] != states.POWER_OFF:
                    raise exception.NodeInWrongPowerState(
                            node=node_id,
                            pstate=node_obj['power_state'])

            # update any remaining parameters, then save
            node_obj.save(context)

            return node_obj

    def change_node_power_state(self, context, node_id, new_state):
        """RPC method to encapsulate changes to a node's state.

        Perform actions such as power on, power off. The validation and power
        action are performed in background (async). Once the power action is
        finished and successful, it updates the power_state for the node with
        the new power state.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired power state of the node.
        :raises: NoFreeConductorWorker when there is no free worker to start
                 async task.

        """
        LOG.debug(_("RPC change_node_power_state called for node %(node)s. "
                    "The desired new state is %(state)s.")
                    % {'node': node_id, 'state': new_state})

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

    # NOTE(deva): There is a race condition in the RPC API for vendor_passthru.
    # Between the validate_vendor_action and do_vendor_action calls, it's
    # possible another conductor instance may acquire a lock, or change the
    # state of the node, such that validate() succeeds but do() fails.
    # TODO(deva): Implement an intent lock to prevent this race. Do this after
    # we have implemented intelligent RPC routing so that the do() will be
    # guaranteed to land on the same conductor instance that performed
    # validate().
    def validate_vendor_action(self, context, node_id, driver_method, info):
        """Validate driver specific info or get driver status."""

        LOG.debug(_("RPC validate_vendor_action called for node %s.")
                    % node_id)
        with task_manager.acquire(context, node_id, shared=True) as task:
            try:
                if getattr(task.driver, 'vendor', None):
                    return task.driver.vendor.validate(task, task.node,
                                                       method=driver_method,
                                                       **info)
                else:
                    raise exception.UnsupportedDriverExtension(
                                            driver=task.node.driver,
                                            extension='vendor passthru')
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    task.node.last_error = \
                        _("Failed to validate vendor info. Error: %s") % e
                    task.node.save(context)

    def do_vendor_action(self, context, node_id, driver_method, info):
        """Run driver action asynchronously."""

        with task_manager.acquire(context, node_id, shared=True) as task:
                task.driver.vendor.vendor_passthru(task, task.node,
                                                  method=driver_method, **info)

    def do_node_deploy(self, context, node_id):
        """RPC method to initiate deployment to a node.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InstanceDeployFailure

        """
        LOG.debug(_("RPC do_node_deploy called for node %s.") % node_id)

        with task_manager.acquire(context, node_id, shared=False) as task:
            node = task.node
            if node['provision_state'] is not states.NOSTATE:
                raise exception.InstanceDeployFailure(_(
                    "RPC do_node_deploy called for %(node)s, but provision "
                    "state is already %(state)s.") %
                    {'node': node_id, 'state': node['provision_state']})

            if node.maintenance:
                raise exception.NodeInMaintenance(op=_('provisioning'),
                                                  node=node.uuid)

            try:
                task.driver.deploy.validate(task, node)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    node['last_error'] = \
                        _("Failed to validate deploy info. Error: %s") % e
            else:
                # set target state to expose that work is in progress
                node['provision_state'] = states.DEPLOYING
                node['target_provision_state'] = states.DEPLOYDONE
                node['last_error'] = None
            finally:
                node.save(context)

            try:
                task.driver.deploy.prepare(task, node)
                new_state = task.driver.deploy.deploy(task, node)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    node['last_error'] = _("Failed to deploy. Error: %s") % e
                    node['provision_state'] = states.DEPLOYFAIL
                    node['target_provision_state'] = states.NOSTATE
            else:
                # NOTE(deva): Some drivers may return states.DEPLOYWAIT
                #             eg. if they are waiting for a callback
                if new_state == states.DEPLOYDONE:
                    node['target_provision_state'] = states.NOSTATE
                    node['provision_state'] = states.ACTIVE
                else:
                    node['provision_state'] = new_state
            finally:
                node.save(context)

    def do_node_tear_down(self, context, node_id):
        """RPC method to tear down an existing node deployment.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :raises: InstanceDeployFailure

        """
        LOG.debug(_("RPC do_node_tear_down called for node %s.") % node_id)

        with task_manager.acquire(context, node_id, shared=False) as task:
            node = task.node
            if node['provision_state'] not in [states.ACTIVE,
                                               states.DEPLOYFAIL,
                                               states.ERROR,
                                               states.DEPLOYWAIT]:
                raise exception.InstanceDeployFailure(_(
                    "RCP do_node_tear_down "
                    "not allowed for node %(node)s in state %(state)s")
                    % {'node': node_id, 'state': node['provision_state']})

            try:
                task.driver.deploy.validate(task, node)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    node['last_error'] = \
                        ("Failed to validate info for teardown. Error: %s") % e
            else:
                # set target state to expose that work is in progress
                node['provision_state'] = states.DELETING
                node['target_provision_state'] = states.DELETED
                node['last_error'] = None
            finally:
                node.save(context)

            try:
                task.driver.deploy.clean_up(task, node)
                new_state = task.driver.deploy.tear_down(task, node)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    node['last_error'] = \
                                      _("Failed to tear down. Error: %s") % e
                    node['provision_state'] = states.ERROR
                    node['target_provision_state'] = states.NOSTATE
            else:
                # NOTE(deva): Some drivers may return states.DELETING
                #             eg. if they are waiting for a callback
                if new_state == states.DELETED:
                    node['target_provision_state'] = states.NOSTATE
                    node['provision_state'] = states.NOSTATE
                else:
                    node['provision_state'] = new_state
            finally:
                node.save(context)

    @periodic_task.periodic_task(spacing=CONF.conductor.heartbeat_interval)
    def _conductor_service_record_keepalive(self, context):
        self.dbapi.touch_conductor(self.host)

    @periodic_task.periodic_task(
            spacing=CONF.conductor.sync_power_state_interval)
    def _sync_power_states(self, context):
        filters = {'reserved': False}
        columns = ['id', 'uuid', 'driver']
        node_list = self.dbapi.get_nodeinfo_list(columns=columns,
                                                 filters=filters)
        for (node_id, node_uuid, driver) in node_list:
            # only sync power states for nodes mapped to this conductor
            mapped_hosts = self.driver_rings[driver].get_hosts(node_uuid)
            if self.host not in mapped_hosts:
                continue

            try:
                # prevent nodes in DEPLOYWAIT state from locking
                node = self.dbapi.get_node(node_uuid)
                if node.provision_state == states.DEPLOYWAIT:
                    continue

                with task_manager.acquire(context, node_id) as task:
                    _do_sync_power_state(task)

            except exception.NodeNotFound:
                LOG.info(_("During sync_power_state, node %(node)s was not "
                           "found and presumed deleted by another process.") %
                           {'node': node_uuid})
                continue
            except exception.NodeLocked:
                LOG.info(_("During sync_power_state, node %(node)s was "
                           "already locked by another process. Skip.") %
                           {'node': node_uuid})
                continue

    @periodic_task.periodic_task(
            spacing=CONF.conductor.check_provision_state_interval)
    def _check_deploy_timeouts(self, context):
        if not CONF.conductor.deploy_callback_timeout:
            return

        filters = {'reserved': False, 'maintenance': False}
        columns = ['uuid', 'driver', 'provision_state', 'provision_updated_at']
        node_list = self.dbapi.get_nodeinfo_list(columns=columns,
                                                 filters=filters)

        for (node_uuid, driver, state, update_time) in node_list:
            mapped_hosts = self.driver_rings[driver].get_hosts(node_uuid)
            if self.host not in mapped_hosts:
                continue

            if state == states.DEPLOYWAIT:
                limit = (timeutils.utcnow() - datetime.timedelta(
                         seconds=CONF.conductor.deploy_callback_timeout))
                if timeutils.normalize_time(update_time) <= limit:
                    try:
                        task = task_manager.TaskManager(context, node_uuid)
                    except (exception.NodeLocked, exception.NodeNotFound):
                        continue

                    node = task.node
                    node.provision_state = states.DEPLOYFAIL
                    node.target_provision_state = states.NOSTATE
                    msg = (_('Timeout reached when waiting callback for '
                             'node %s') % node_uuid)
                    node.last_error = msg
                    LOG.error(msg)
                    node.save(task.context)

                    try:
                        thread = self._spawn_worker(
                                            utils.cleanup_after_timeout, task)
                        thread.link(lambda t: task.release_resources())
                    except exception.NoFreeConductorWorker:
                        task.release_resources()

    def _get_current_driver_rings(self):
        """Build the current hash ring for this ConductorManager's drivers."""

        ring = {}
        d2c = self.dbapi.get_active_driver_dict()

        for driver in self.drivers:
            ring[driver] = hash.HashRing(d2c[driver])
        return ring

    def rebalance_node_ring(self):
        """Perform any actions necessary when rebalancing the consistent hash.

        This may trigger several actions, such as calling driver.deploy.prepare
        for nodes which are now mapped to this conductor.

        """
        # TODO(deva): implement this
        pass

    def validate_driver_interfaces(self, context, node_id):
        """Validate the `core` and `standardized` interfaces for drivers.

        :param context: request context.
        :param node_id: node id or uuid.
        :returns: a dictionary containing the results of each
                  interface validation.

        """
        LOG.debug(_('RPC validate_driver_interfaces called for node %s.') %
                    node_id)
        ret_dict = {}
        with task_manager.acquire(context, node_id, shared=True) as task:
            for iface_name in (task.driver.core_interfaces +
                               task.driver.standard_interfaces):
                iface = getattr(task.driver, iface_name, None)
                result = reason = None
                if iface:
                    try:
                        iface.validate(task, task.node)
                        result = True
                    except exception.InvalidParameterValue as e:
                        result = False
                        reason = str(e)
                else:
                    reason = _('not supported')

                ret_dict[iface_name] = {}
                ret_dict[iface_name]['result'] = result
                if reason is not None:
                    ret_dict[iface_name]['reason'] = reason
        return ret_dict

    def change_node_maintenance_mode(self, context, node_id, mode):
        """Set node maintenance mode on or off.

        :param context: request context.
        :param node_id: node id or uuid.
        :param mode: True or False.
        :raises: NodeMaintenanceFailure

        """
        LOG.debug(_("RPC change_node_maintenance_mode called for node %(node)s"
                    " with maintanence mode: %(mode)s") % {'node': node_id,
                                                           'mode': mode})

        with task_manager.acquire(context, node_id, shared=True) as task:
            node = task.node
            if mode is not node.maintenance:
                node.maintenance = mode
                node.save(context)
            else:
                msg = _("The node is already in maintenance mode") if mode \
                        else _("The node is not in maintenance mode")
                raise exception.NodeMaintenanceFailure(node=node_id,
                                                       reason=msg)

            return node

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

            self.dbapi.destroy_node(node_id)

    def get_console_information(self, context, node_id):
        """Get connection information about the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: NodeConsoleNotEnabled if the console is not enabled.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        """
        LOG.debug(_('RPC get_console_information called for node %s')
                  % node_id)

        with task_manager.acquire(context, node_id, shared=True) as task:
            node = task.node

            if not getattr(task.driver, 'console', None):
                raise exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')
            if not node.console_enabled:
                raise exception.NodeConsoleNotEnabled(node=node_id)

            task.driver.console.validate(task, node)
            return task.driver.console.get_console(task, node)

    def set_console_mode(self, context, node_id, enabled):
        """Enable/Disable the console.

        :param context: request context.
        :param node_id: node id or uuid.
        :param enabled: Boolean value; whether the console is enabled or
                        disabled.
        :raises: UnsupportedDriverExtension if the node's driver doesn't
                 support console.
        :raises: InvalidParameterValue when the wrong driver info is specified.
        """
        LOG.debug(_('RPC set_console_mode called for node %(node)s with '
                    'enabled %(enabled)s') % {'node': node_id,
                                              'enabled': enabled})

        with task_manager.acquire(context, node_id) as task:
            node = task.node

            if not getattr(task.driver, 'console', None):
                exc = exception.UnsupportedDriverExtension(driver=node.driver,
                                                           extension='console')
                node.last_error = exc.format_message()
                node.save(context)
                raise exc

            try:
                task.driver.console.validate(task, node)
            except exception.InvalidParameterValue as e:
                with excutils.save_and_reraise_exception():
                    node.last_error = (_("Failed to validate console info. "
                                         "Error: %s") % e)
                    node.save(context)

            try:
                if enabled and not node.console_enabled:
                    task.driver.console.start_console(task, node)
                elif not enabled and node.console_enabled:
                    task.driver.console.stop_console(task, node)
                else:
                    op = _('enabled') if enabled else _('disabled')
                    LOG.info(_("No console action was triggered because the "
                               "console is already %s") % op)
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
                node.save(context)
