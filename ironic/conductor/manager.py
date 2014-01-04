# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

Drivers are loaded via entrypoints, by the
:py:class:`ironic.conductor.resource_manager.NodeManager` class. Each driver is
instantiated once and a ref to that singleton is included in each resource
manager, depending on the node's configuration. In this way, a single
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
from ironic.openstack.common import log
from ironic.openstack.common import periodic_task

MANAGER_TOPIC = 'ironic.conductor_manager'

LOG = log.getLogger(__name__)

conductor_opts = [
        cfg.StrOpt('api_url',
                   default=None,
                   help=('Url of Ironic API service. If not set Ironic can '
                         'get current value from Keystone service catalog.')),
        cfg.IntOpt('heartbeat_interval',
                   default=10,
                   help='Seconds between conductor heart beats.'),
        cfg.IntOpt('heartbeat_timeout',
                   default=60,
                   help='Maximum time since the last check-in of a conductor'),
        cfg.IntOpt('sync_power_state_interval',
                   default=60,
                   help='Interval between syncing the node power state to the '
                        'database, in seconds.'),
]

CONF = cfg.CONF
CONF.register_opts(conductor_opts, 'conductor')


class ConductorManager(service.PeriodicService):
    """Ironic Conductor service main class."""

    RPC_API_VERSION = '1.7'

    def __init__(self, host, topic):
        serializer = objects_base.IronicObjectSerializer()
        super(ConductorManager, self).__init__(host, topic,
                                               serializer=serializer)

    def start(self):
        super(ConductorManager, self).start()
        self.dbapi = dbapi.get_instance()

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

    def get_node_power_state(self, context, node_id):
        """Get and return the power state for a single node."""

        with task_manager.acquire(context, [node_id], shared=True) as task:
            node = task.resources[0].node
            driver = task.resources[0].driver
            state = driver.power.get_power_state(task, node)
            return state

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
                task.driver.power.validate(node_obj)
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

        Perform actions such as power on, power off. It waits for the power
        action to finish, then if successful, it updates the power_state for
        the node with the new power state.

        :param context: an admin context.
        :param node_id: the id or uuid of a node.
        :param new_state: the desired power state of the node.
        :raises: InvalidParameterValue when the wrong state is specified
                 or the wrong driver info is specified.
        :raises: other exceptions by the node's power driver if something
                 wrong occurred during the power action.

        """
        LOG.debug(_("RPC change_node_power_state called for node %(node)s. "
                    "The desired new state is %(state)s.")
                    % {'node': node_id, 'state': new_state})

        with task_manager.acquire(context, node_id, shared=False) as task:
            utils.node_power_action(task, task.node, new_state)

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
                    return task.driver.vendor.validate(task.node,
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

            try:
                task.driver.deploy.validate(node)
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
                # NOTE(deva): Some drivers may return states.DEPLOYING
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
                                               states.ERROR]:
                raise exception.InstanceDeployFailure(_(
                    "RCP do_node_tear_down "
                    "not allowed for node %(node)s in state %(state)s")
                    % {'node': node_id, 'state': node['provision_state']})

            try:
                task.driver.deploy.validate(node)
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
                with task_manager.acquire(context, node_id) as task:
                    node = task.node
                    power_state = task.driver.power.get_power_state(task, node)
                    if power_state != node['power_state']:
                        # NOTE(deva): don't log a warning the first time we
                        #             sync a node's power state
                        if node['power_state'] is not None:
                            LOG.warning(_("During sync_power_state, node "
                                "%(node)s out of sync. Expected: %(old)s. "
                                "Actual: %(new)s. Updating DB.") %
                                {'node': node['uuid'],
                                 'old': node['power_state'],
                                 'new': power_state})
                        node['power_state'] = power_state
                        node.save(context)

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
                        iface.validate(task.node)
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
