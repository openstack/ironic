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
"""

from ironic.common import exception
from ironic.common import service
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.objects import base as objects_base
from ironic.openstack.common import log

MANAGER_TOPIC = 'ironic.conductor_manager'

LOG = log.getLogger(__name__)


class ConductorManager(service.PeriodicService):
    """Ironic Conductor service main class."""

    RPC_API_VERSION = '1.2'

    def __init__(self, host, topic):
        serializer = objects_base.IronicObjectSerializer()
        super(ConductorManager, self).__init__(host, topic,
                                               serializer=serializer)

    def start(self):
        super(ConductorManager, self).start()
        self.dbapi = dbapi.get_instance()

    def initialize_service_hook(self, service):
        pass

    def process_notification(self, notification):
        LOG.debug(_('Received notification: %r') %
                        notification.get('event_type'))
        # TODO(deva)

    def periodic_tasks(self, context):
        # TODO(deva)
        pass

    def get_node_power_state(self, context, node_id):
        """Get and return the power state for a single node."""

        with task_manager.acquire([node_id], shared=True) as task:
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
        node_id = node_obj.get('uuid')
        LOG.debug("RPC update_node called for node %s." % node_id)

        delta = node_obj.obj_what_changed()
        if 'power_state' in delta:
            raise exception.IronicException(_(
                "Invalid method call: update_node can not change node state."))

        driver_name = node_obj.get('driver') if 'driver' in delta else None
        with task_manager.acquire(node_id,
                                  shared=False,
                                  driver_name=driver_name) as task:
            if 'driver_info' in delta:
                task.driver.deploy.validate(node_obj)
                task.driver.power.validate(node_obj)
                node_obj['power_state'] = task.driver.power.get_power_state

            # TODO(deva): Determine what value will be passed by API when
            #             instance_uuid needs to be unset, and handle it.
            if 'instance_uuid' in delta:
                if node_obj['power_state'] != states.POWER_OFF:
                    raise exception.NodeInWrongPowerState(
                            node=node_id,
                            pstate=node_obj['power_state'])

            # update any remaining parameters, then save
            node_obj.save(context)

            return node_obj

    def start_power_state_change(self, context, node_obj, new_state):
        """RPC method to encapsulate changes to a node's state.

        Perform actions such as power on, power off. It waits for the power
        action to finish, then if succesful, it updates the power_state for
        the node with the new power state.

        :param context: an admin context.
        :param node_obj: an RPC-style node object.
        :param new_state: the desired power state of the node.
        :raises: InvalidParameterValue when the wrong state is specified
                 or the wrong driver info is specified.
        :raises: NodeInWrongPowerState when the node is in the state.
                  that cannot perform and requested power action.
        :raises: other exceptins by the node's power driver if something
                  wrong during the power action.
        :
        """
        node_id = node_obj.get('uuid')
        LOG.debug("RPC start_power_state_change called for node %s."
            " The desired new state is %s." % (node_id, new_state))

        with task_manager.acquire(node_id, shared=False) as task:
            # an exception will be raised if validate fails.
            task.driver.power.validate(node_obj)
            curr_state = task.driver.power.get_power_state(task, node_obj)
            if curr_state == new_state:
                raise exception.NodeInWrongPowerState(node=node_id,
                                                      pstate=curr_state)

            # set the target_power_state.
            # This will expose to other processes and clients that the work
            # is in progress
            node_obj['target_power_state'] = new_state
            node_obj.save(context)

            #take power action, set the power_state to error if fails
            try:
                task.driver.power.set_power_state(task, node_obj, new_state)
            except exception.IronicException:
                node_obj['power_state'] = states.ERROR
                node_obj.save(context)
                raise

            # update the node power states
            node_obj['power_state'] = new_state
            node_obj['target_power_state'] = states.NOSTATE
            node_obj.save(context)

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

        LOG.debug(_("RPC call_driver called for node %s.") % node_id)
        with task_manager.acquire(node_id, shared=True) as task:
            if getattr(task.driver, 'vendor', None):
                return task.driver.vendor.validate(task.node,
                                                   method=driver_method,
                                                   **info)
            else:
                raise exception.UnsupportedDriverExtension(
                                        driver=task.node['driver'],
                                        node=node_id,
                                        extension='vendor passthru')

    def do_vendor_action(self, context, node_id, driver_method, info):
        """Run driver action asynchronously."""

        with task_manager.acquire(node_id, shared=True) as task:
                task.driver.vendor.vendor_passthru(task, task.node,
                                                  method=driver_method, **info)
