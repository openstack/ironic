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

from ironic.common import service
from ironic.manager import task_manager
from ironic.openstack.common import log

LOG = log.getLogger(__name__)


class ManagerService(service.PeriodicService):
    """Ironic Manager Service.

    A single instance of this class is created within the ironic-manager
    process. It is responsible for performing all actions on Chassis, Nodes,
    and Ports, and tracks these actions via Trackers.

    Tracker instances are created on-demand and destroyed when the
    operation(s) are complete. Persistent state is stored in a database,
    which is also used to coordinate locks between ManagerServices.
    """

    def __init__(self, host, topic):
        super(ManagerService, self).__init__(host, topic)

    def start(self):
        super(ManagerService, self).start()
        # TODO(deva): connect with storage driver

    def initialize(self, service):
        LOG.debug(_('Manager initializing service hooks'))
        # TODO(deva)

    def process_notification(self, notification):
        LOG.debug(_('Received notification: %r') %
                        notification.get('event_type'))
        # TODO(deva)

    def periodic_tasks(self, context):
        # TODO(deva)
        pass

    def get_node_power_state(self, id):
        """Get and return the power state for a single node."""

        with task_manager.acquire([id], shared=True) as task:
            node = task.resources[0].node
            driver = task.resources[0].controller
            state = driver.get_power_state(task, node)
            return state

    # TODO(deva)
