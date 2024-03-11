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

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

from ironic.common import rpc_service
from ironic.common import service as ironic_service

CONF = cfg.CONF
LOG = log.getLogger(__name__)


class RPCService(rpc_service.BaseRPCService):

    def stop(self):
        try:
            self.manager.del_host()
        except Exception as e:
            LOG.exception('Service error occurred when cleaning up '
                          'the RPC manager. Error: %s', e)

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


def main():
    assert 'ironic.pxe_filter.service' not in sys.modules

    # Parse config file and command line options, then start logging
    ironic_service.prepare_service('ironic_pxe_filter', sys.argv)
    if CONF.rpc_transport == 'json-rpc':
        raise RuntimeError("This service is not designed to work with "
                           "rpc_transport = json-rpc. Please use another "
                           "RPC transport.")

    mgr = RPCService(
        CONF.host, 'ironic.pxe_filter.service', 'PXEFilterManager')

    launcher = service.launch(CONF, mgr, restart_method='mutate')

    # NOTE(dtantsur): handling start-up failures before launcher.wait() helps
    # notify systemd about them. Otherwise the launcher will report successful
    # service start-up before checking the threads.
    mgr.wait_for_start()

    sys.exit(launcher.wait())


if __name__ == '__main__':
    sys.exit(main())
