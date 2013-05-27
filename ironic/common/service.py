#!/usr/bin/env python
# -*- encoding: utf-8 -*-
#
# Copyright © 2012 eNovance <licensing@enovance.com>
#
# Author: Julien Danjou <julien@danjou.info>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import socket

from oslo.config import cfg

from ironic.openstack.common import context
from ironic.openstack.common import log
from ironic.openstack.common import rpc
from ironic.openstack.common.rpc import service as rpc_service


cfg.CONF.register_opts([
    cfg.IntOpt('periodic_interval',
               default=60,
               help='seconds between running periodic tasks'),
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help='Name of this node.  This can be an opaque identifier.  '
               'It is not necessarily a hostname, FQDN, or IP address. '
               'However, the node name must be valid within '
               'an AMQP key, and if using ZeroMQ, a valid '
               'hostname, FQDN, or IP address'),
])


class PeriodicService(rpc_service.Service):

    def start(self):
        super(PeriodicService, self).start()
        admin_context = context.RequestContext('admin', 'admin', is_admin=True)
        self.tg.add_timer(cfg.CONF.periodic_interval,
                          self.manager.periodic_tasks,
                          context=admin_context)


def prepare_service(argv=[]):
    rpc.set_defaults(control_exchange='ironic')
    cfg.set_defaults(log.log_opts,
                     default_log_levels=['amqplib=WARN',
                                         'qpid.messaging=INFO',
                                         'sqlalchemy=WARN',
                                         'keystoneclient=INFO',
                                         'stevedore=INFO',
                                         'eventlet.wsgi.server=WARN'
                                         ])
    cfg.CONF(argv[1:], project='ironic')
    log.setup('ironic')
