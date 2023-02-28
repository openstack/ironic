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

import datetime
import signal
import sys
import time

from ironic_lib.json_rpc import server as json_rpc
from oslo_config import cfg
from oslo_log import log
import oslo_messaging as messaging
from oslo_service import service
from oslo_utils import importutils
from oslo_utils import timeutils

from ironic.common import context
from ironic.common import rpc
from ironic.objects import base as objects_base

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class RPCService(service.Service):

    def __init__(self, host, manager_module, manager_class):
        super(RPCService, self).__init__()
        self.host = host
        manager_module = importutils.try_import(manager_module)
        manager_class = getattr(manager_module, manager_class)
        self.manager = manager_class(host, rpc.MANAGER_TOPIC)
        self.topic = self.manager.topic
        self.rpcserver = None
        self.deregister = True
        self._failure = None
        self._started = False

    def wait_for_start(self):
        while not self._started and not self._failure:
            time.sleep(0.1)
        if self._failure:
            LOG.critical(self._failure)
            sys.exit(self._failure)

    def start(self):
        self._failure = None
        self._started = False
        super(RPCService, self).start()
        try:
            self._real_start()
        except Exception as exc:
            self._failure = f"{exc.__class__.__name__}: {exc}"
            raise
        else:
            self._started = True

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
        rpc.set_global_manager(self.manager)

        LOG.info('Created RPC server with %(transport)s transport for service '
                 '%(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host,
                  'transport': CONF.rpc_transport})

    def stop(self):
        initial_time = timeutils.utcnow()
        extend_time = initial_time + datetime.timedelta(
            seconds=CONF.hash_ring_reset_interval)

        try:
            self.manager.del_host(deregister=self.deregister)
        except Exception as e:
            LOG.exception('Service error occurred when cleaning up '
                          'the RPC manager. Error: %s', e)

        if self.manager.get_online_conductor_count() > 1:
            # Delay stopping the server until the hash ring has been
            # reset on the cluster
            stop_time = timeutils.utcnow()
            if stop_time < extend_time:
                stop_wait = max(0, (extend_time - stop_time).seconds)
                LOG.info('Waiting %(stop_wait)s seconds for hash ring reset.',
                         {'stop_wait': stop_wait})
                time.sleep(stop_wait)

        try:
            if self.rpcserver is not None:
                self.rpcserver.stop()
                self.rpcserver.wait()
        except Exception as e:
            LOG.exception('Service error occurred when stopping the '
                          'RPC server. Error: %s', e)

        super(RPCService, self).stop(graceful=True)
        LOG.info('Stopped RPC server for service %(service)s on host '
                 '%(host)s.',
                 {'service': self.topic, 'host': self.host})
        rpc.set_global_manager(None)

    def _handle_signal(self, signo, frame):
        LOG.info('Got signal SIGUSR1. Not deregistering on next shutdown '
                 'of service %(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host})
        self.deregister = False

    def handle_signal(self):
        """Add a signal handler for SIGUSR1.

        The handler ensures that the manager is not deregistered when it is
        shutdown.
        """
        signal.signal(signal.SIGUSR1, self._handle_signal)
