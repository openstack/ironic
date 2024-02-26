# -*- encoding: utf-8 -*-
#
# Copyright © 2012 eNovance <licensing@enovance.com>
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

import sys
import time

from ironic_lib.json_rpc import server as json_rpc
from oslo_config import cfg
from oslo_log import log
import oslo_messaging as messaging
from oslo_service import service
from oslo_utils import importutils

from ironic.common import context
from ironic.common import rpc
from ironic.objects import base as objects_base

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class BaseRPCService(service.Service):

    def __init__(self, host, manager_module, manager_class):
        super().__init__()
        self.host = host
        manager_module = importutils.try_import(manager_module)
        manager_class = getattr(manager_module, manager_class)
        self.manager = manager_class(host)
        self.topic = self.manager.topic
        self.rpcserver = None
        self._started = False
        self._failure = None

    def wait_for_start(self):
        while not self._started and not self._failure:
            time.sleep(0.1)
        if self._failure:
            LOG.critical(self._failure)
            sys.exit(self._failure)

    def start(self):
        self._failure = None
        self._started = False
        super().start()
        try:
            self._real_start()
        except Exception as exc:
            self._failure = f"{exc.__class__.__name__}: {exc}"
            raise
        else:
            self._started = True

    def handle_signal(self):
        pass

    def _real_start(self):
        admin_context = context.get_admin_context()

        serializer = objects_base.IronicObjectSerializer(is_server=True)
        # Perform preparatory actions before starting the RPC listener
        self.manager.prepare_host()
        if CONF.rpc_transport == 'json-rpc':
            self.rpcserver = json_rpc.WSGIService(
                self.manager, serializer, context.RequestContext.from_dict)
        elif CONF.rpc_transport != 'none':
            target = messaging.Target(topic=self.topic, server=self.host)
            endpoints = [self.manager]
            self.rpcserver = rpc.get_server(target, endpoints, serializer)

        if self.rpcserver is not None:
            self.rpcserver.start()

        self.handle_signal()
        self.manager.init_host(admin_context)

        LOG.info('Created RPC server with %(transport)s transport for service '
                 '%(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host,
                  'transport': CONF.rpc_transport})
