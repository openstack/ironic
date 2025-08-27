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
import multiprocessing
import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import timeutils

from ironic.common import console_factory
from ironic.common import rpc
from ironic.common import rpc_service
from ironic.common import wsgi_service

LOG = log.getLogger(__name__)
CONF = cfg.CONF

# NOTE(TheJulia): We set the following flags as it relates to process
# shutdown. Because in the post-eventlet model we now consist of a primary
# process and an application process with then threads, we *must* use
# multiprocessing because this needs to cross the process boundary where
# multiprocessing was invoked to launch new processes.

# Always set a flag for deregistering, when shutting down the primary
# process will clear the flag.
DEREGISTER_ON_SHUTDOWN = multiprocessing.Event()
DEREGISTER_ON_SHUTDOWN.set()
# Flag which can be set to indicate if we need to drain the conductor
# workload, or not. Set by the primary process when shutdown has been
# requested.
DRAIN = multiprocessing.Event()


class RPCService(rpc_service.BaseRPCService):

    def __init__(self, host, manager_module, manager_class,
                 embed_api=False):
        super().__init__(host, manager_module, manager_class)
        self.apiserver = None
        self._embed_api = embed_api

    @property
    def deregister_on_shutdown(self):
        return DEREGISTER_ON_SHUTDOWN.is_set()

    def is_draining(self):
        return DRAIN.is_set()

    def _real_start(self):
        super()._real_start()
        rpc.set_global_manager(self.manager)

        if self._embed_api:
            self.apiserver = wsgi_service.WSGIService(
                'ironic_api', CONF.api.enable_ssl_api)
            self.apiserver.start()

        # Start in a known state of no console containers running.
        # Any enabled console managed by this conductor will be started
        # after this
        self._stop_console_containers()

    def stop(self):
        initial_time = timeutils.utcnow()
        extend_time = initial_time + datetime.timedelta(
            seconds=CONF.hash_ring_reset_interval)

        # Stop serving the embedded API first to avoid any new requests
        try:
            if self.apiserver is not None:
                self.apiserver.stop()
                self.apiserver.wait()
        except Exception:
            LOG.exception('Service error occurred when stopping the API')

        try:
            self.manager.del_host(
                deregister=self.deregister_on_shutdown,
                clear_node_reservations=False)
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

        super().stop(graceful=True)
        LOG.info('Stopped RPC server for service %(service)s on host '
                 '%(host)s.',
                 {'service': self.topic, 'host': self.host})

        # Stop all running console containers
        self._stop_console_containers()

        # Wait for reservation locks held by this conductor.
        # The conductor process will end when one of the following occurs:
        # - All reservations for this conductor are released
        # - shutdown_timeout has elapsed
        # - The process manager (systemd, kubernetes) sends SIGKILL after the
        #   configured timeout period
        while (self.manager.has_reserved()
               and not self._shutdown_timeout_reached(initial_time)):
            LOG.info('Waiting for reserved nodes to clear on host %(host)s',
                     {'host': self.host})
            time.sleep(1)

        # Stop the keepalive heartbeat greenthread sending touch(online=False)
        self.manager.keepalive_halt()

        rpc.set_global_manager(None)

    def _stop_console_containers(self):
        # the default provider is fake, so this can be called even when
        # CONF.vnc.enabled is false
        provider = console_factory.ConsoleContainerFactory().provider
        provider.stop_all_containers()

    def _shutdown_timeout_reached(self, initial_time):
        if self.is_draining():
            shutdown_timeout = CONF.drain_shutdown_timeout
        else:
            shutdown_timeout = CONF.conductor.graceful_shutdown_timeout
        if shutdown_timeout == 0:
            # No timeout, run until no nodes are reserved
            return False
        shutdown_time = initial_time + datetime.timedelta(
            seconds=shutdown_timeout)
        return shutdown_time < timeutils.utcnow()
