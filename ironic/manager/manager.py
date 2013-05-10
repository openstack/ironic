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

from oslo.config import cfg

from ironic.openstack.common import context
from ironic.openstack.common import log
from ironic.openstack.common.rpc import dispatcher as rpc_dispatcher
from ironic.openstack.common import timeutils

import ironic.openstack.common.notifier.rpc_notifier

from ironic import db
from ironic.common import service
from ironic.common import extension_manager

manager_opts = [
    cfg.StrOpt('power_driver',
               default='IPMI',
               help='Power driver. [IPMI, VPD, None]'
               ),
    cfg.StrOpt('deployment_driver',
               default='PXE',
               help='Image deployment driver. [PXE]'
               ),
]

CONF = cfg.CONF
CONF.register_opts(manager_opts)

LOG = log.getLogger(__name__)


class ManagerService(service.PeriodicService):

    MANAGER_NAMESPACE = 'ironic.manager'

    def start(self):
        super(ManagerService, self).start()
        # TODO: connect with storage driver

    def initialize_(self, service):
        LOG.debug(_('Manager initializing service hooks'))

    def process_notification(self, notification):
        LOG.debug(_('Received notification %r',
                        notification.get('event_type')))

    def periodic_tasks(self, context):
        pass
