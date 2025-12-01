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


from oslo_config import cfg
from oslo_log import log

from ironic.common import rpc_service
from ironic.networking import utils as networking_utils

LOG = log.getLogger(__name__)
CONF = cfg.CONF


class NetworkingRPCService(rpc_service.BaseRPCService):
    """RPC service for the Ironic Networking Manager."""

    def __init__(self, host, manager_module, manager_class):
        super().__init__(host, manager_module, manager_class)
        self.graceful_shutdown = False

    def _rpc_transport(self):
        return networking_utils.rpc_transport()

    def _real_start(self):
        """Start the networking service."""
        super()._real_start()
        LOG.info(
            "Started networking RPC server for service %(service)s on "
            "host %(host)s.",
            {"service": self.topic, "host": self.host},
        )

    def stop(self):
        """Stop the networking service."""
        LOG.info(
            "Stopping networking RPC server for service %(service)s on "
            "host %(host)s.",
            {"service": self.topic, "host": self.host},
        )

        try:
            if hasattr(self.manager, "del_host"):
                self.manager.del_host()
        except Exception as e:
            LOG.exception(
                "Service error occurred when cleaning up "
                "the networking RPC manager. Error: %s",
                e,
            )

        try:
            if self.rpcserver is not None:
                self.rpcserver.stop()
                self.rpcserver.wait()
        except Exception as e:
            LOG.exception(
                "Service error occurred when stopping the "
                "networking RPC server. Error: %s",
                e,
            )

        super().stop(graceful=True)
        LOG.info(
            "Stopped networking RPC server for service %(service)s on "
            "host %(host)s.",
            {"service": self.topic, "host": self.host},
        )
