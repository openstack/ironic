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

from oslo_config import cfg
from oslo_log import log
import oslo_messaging as messaging
from oslo_service import service
from oslo_service import threadgroup
from oslo_utils import importutils

from ironic.common import context
from ironic.common.json_rpc import server as json_rpc
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

    def __getstate__(self):
        """Exclude unpicklable threading objects for spawn safety.

        oslo.service checks if the service is picklable to determine
        whether to use the spawn or fork multiprocessing context. The
        parent oslo.service.Service creates a ThreadGroup containing
        threading objects that cannot be pickled.
        """
        state = self.__dict__.copy()
        # ThreadGroup from oslo.service.Service contains threads/locks
        state.pop('tg', None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        # Recreate ThreadGroup; start() will use it for managing threads
        self.tg = threadgroup.ThreadGroup()

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

    def _rpc_transport(self):
        return CONF.rpc_transport

    def _real_start(self):
        admin_context = context.get_admin_context()

        serializer = objects_base.IronicObjectSerializer(is_server=True)
        # Perform preparatory actions before starting the RPC listener
        self.manager.prepare_host()
        if self._rpc_transport() == 'json-rpc':
            conf_group = getattr(self.manager, 'json_rpc_conf_group',
                                 'json_rpc')
            self.rpcserver = json_rpc.WSGIService(
                self.manager, serializer, context.RequestContext.from_dict,
                conf_group=conf_group)
        elif self._rpc_transport() != 'none':
            target = messaging.Target(topic=self.topic, server=self.host)
            endpoints = [self.manager]
            self.rpcserver = rpc.get_server(target, endpoints, serializer)

        if self.rpcserver is not None:
            self.rpcserver.start()

        self.manager.init_host(admin_context)

        LOG.info('Created RPC server with %(transport)s transport for service '
                 '%(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host,
                  'transport': self._rpc_transport()})
