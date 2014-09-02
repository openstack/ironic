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
from oslo import messaging
from oslo.utils import importutils

from ironic.common import config
from ironic.common.i18n import _
from ironic.common import rpc
from ironic.objects import base as objects_base
from ironic.openstack.common import context
from ironic.openstack.common.gettextutils import _LI
from ironic.openstack.common import log
from ironic.openstack.common import service


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

LOG = log.getLogger(__name__)


class RPCService(service.Service):

    def __init__(self, host, manager_module, manager_class):
        super(RPCService, self).__init__()
        self.host = host
        manager_module = importutils.try_import(manager_module)
        manager_class = getattr(manager_module, manager_class)
        self.manager = manager_class(host, manager_module.MANAGER_TOPIC)
        self.topic = self.manager.topic
        self.rpcserver = None

    def start(self):
        super(RPCService, self).start()
        admin_context = context.RequestContext('admin', 'admin', is_admin=True)
        self.tg.add_dynamic_timer(
                self.manager.periodic_tasks,
                periodic_interval_max=cfg.CONF.periodic_interval,
                context=admin_context)

        self.manager.init_host()
        target = messaging.Target(topic=self.topic, server=self.host)
        endpoints = [self.manager]
        serializer = objects_base.IronicObjectSerializer()
        self.rpcserver = rpc.get_server(target, endpoints, serializer)
        self.rpcserver.start()
        LOG.info(_LI('Created RPC server for service %(service)s on host '
                     '%(host)s.'),
                 {'service': self.topic, 'host': self.host})

    def stop(self):
        super(RPCService, self).stop()
        try:
            self.rpcserver.stop()
            self.rpcserver.wait()
        except Exception as e:
            LOG.exception(_('Service error occurred when stopping the '
                            'RPC server. Error: %s'), e)
        try:
            self.manager.del_host()
        except Exception as e:
            LOG.exception(_('Service error occurred when cleaning up '
                            'the RPC manager. Error: %s'), e)
        LOG.info(_LI('Stopped RPC server for service %(service)s on host '
                     '%(host)s.'),
                 {'service': self.topic, 'host': self.host})


def prepare_service(argv=[]):
    config.parse_args(argv)
    cfg.set_defaults(log.log_opts,
                     default_log_levels=['amqp=WARN',
                                         'amqplib=WARN',
                                         'qpid.messaging=INFO',
                                         'sqlalchemy=WARN',
                                         'keystoneclient=INFO',
                                         'stevedore=INFO',
                                         'eventlet.wsgi.server=WARN',
                                         'iso8601=WARN',
                                         'paramiko=WARN',
                                         'requests=WARN',
                                         'neutronclient=WARN',
                                         'glanceclient=WARN',
                                         'ironic.openstack.common=WARN',
                                         ])
    log.setup('ironic')
