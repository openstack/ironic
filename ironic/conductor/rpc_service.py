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
import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import timeutils

from ironic.common import rpc
from ironic.common import rpc_service

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class RPCService(rpc_service.BaseRPCService):

    def __init__(self, host, manager_module, manager_class):
        super().__init__(host, manager_module, manager_class)
        self.deregister = True
        self.draining = False

    def _real_start(self):
        super()._real_start()
        rpc.set_global_manager(self.manager)

    def stop(self):
        initial_time = timeutils.utcnow()
        extend_time = initial_time + datetime.timedelta(
            seconds=CONF.hash_ring_reset_interval)

        try:
            self.manager.del_host(deregister=self.deregister,
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

    def _shutdown_timeout_reached(self, initial_time):
        if self.draining:
            shutdown_timeout = CONF.drain_shutdown_timeout
        else:
            shutdown_timeout = CONF.graceful_shutdown_timeout
        if shutdown_timeout == 0:
            # No timeout, run until no nodes are reserved
            return False
        shutdown_time = initial_time + datetime.timedelta(
            seconds=shutdown_timeout)
        return shutdown_time < timeutils.utcnow()

    def _handle_no_deregister(self, signo, frame):
        LOG.info('Got signal SIGUSR1. Not deregistering on next shutdown '
                 'of service %(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host})
        self.deregister = False

    def _handle_drain(self, signo, frame):
        LOG.info('Got signal SIGUSR2. Starting drain shutdown'
                 'of service %(service)s on host %(host)s.',
                 {'service': self.topic, 'host': self.host})
        self.draining = True
        self.stop()

    def handle_signal(self):
        """Add a signal handler for SIGUSR1, SIGUSR2.

        The SIGUSR1 handler ensures that the manager is not deregistered when
        it is shutdown.

        The SIGUSR2 handler starts a drain shutdown.
        """
        signal.signal(signal.SIGUSR1, self._handle_no_deregister)
        signal.signal(signal.SIGUSR2, self._handle_drain)
