# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
"""Handles all activity related to bare-metal deployments.

A single instance of :py:class:`ironic.manager.manager.ManagerService` is
created within the *ironic-manager* process, and is responsible for performing
all actions on bare metal resources (Chassis, Nodes, and Ports). Commands are
received via RPC calls. The manager service also performs periodic tasks, eg.
to monitor the status of active deployments.

Drivers are loaded via entrypoints, by the
:py:class:`ironic.manager.resource_manager.NodeManager` class. Each driver is
instantiated once and a ref to that singleton is included in each resource
manager, depending on the node's configuration. In this way, a single
ManagerService may use multiple drivers, and manage heterogeneous hardware.

When multiple :py:class:`ManagerService` are run on different hosts, they are
all active and cooperatively manage all nodes in the deplyment.  Nodes are
locked by each manager when performing actions which change the state of that
node; these locks are represented by the
:py:class:`ironic.manager.task_manager.TaskManager` class.
"""

from ironic.common import service
from ironic.db import api as dbapi
from ironic.manager import task_manager
from ironic.openstack.common import log

MANAGER_TOPIC = 'ironic.manager'

LOG = log.getLogger(__name__)


class ManagerService(service.PeriodicService):
    """Ironic Manager service main class."""

    RPC_API_VERSION = '1.0'

    def __init__(self, host, topic):
        super(ManagerService, self).__init__(host, topic)

    def start(self):
        super(ManagerService, self).start()
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
            driver = task.resources[0].controller
            state = driver.get_power_state(task, node)
            return state

    # TODO(deva)
