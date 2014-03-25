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

from ironic.common import config
from ironic.openstack.common import context
from ironic.openstack.common import importutils
from ironic.openstack.common import log
from ironic.openstack.common import periodic_task
from ironic.openstack.common.rpc import service as rpc_service


service_opts = [
    cfg.IntOpt('periodic_interval',
               default=60,
               help='Seconds between running periodic tasks.'),
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help='Name of this node.  This can be an opaque identifier.  '
               'It is not necessarily a hostname, FQDN, or IP address. '
               'However, the node name must be valid within '
               'an AMQP key, and if using ZeroMQ, a valid '
               'hostname, FQDN, or IP address.'),
]

cfg.CONF.register_opts(service_opts)


class PeriodicService(rpc_service.Service, periodic_task.PeriodicTasks):

    def start(self):
        super(PeriodicService, self).start()
        admin_context = context.RequestContext('admin', 'admin', is_admin=True)
        self.tg.add_dynamic_timer(
                self.manager.periodic_tasks,
                periodic_interval_max=cfg.CONF.periodic_interval,
                context=admin_context)


def prepare_service(argv=[]):
    config.parse_args(argv)
    cfg.set_defaults(log.log_opts,
                     default_log_levels=['amqplib=WARN',
                                         'qpid.messaging=INFO',
                                         'sqlalchemy=WARN',
                                         'keystoneclient=INFO',
                                         'stevedore=INFO',
                                         'eventlet.wsgi.server=WARN',
                                         'iso8601=WARN',
                                         'paramiko=WARN',
                                         ])
    log.setup('ironic')


def load_manager(manager_modulename, manager_classname, host):
    manager_module = importutils.import_module(manager_modulename)
    manager_class = getattr(manager_module, manager_classname)
    return manager_class(host, manager_module.MANAGER_TOPIC)
