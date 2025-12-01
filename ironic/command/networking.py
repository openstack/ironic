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

"""
The Ironic Networking Service
"""

import sys

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

from ironic.command import utils as command_utils
from ironic.common import service as ironic_service
from ironic.networking import rpc_service

CONF = cfg.CONF

LOG = log.getLogger(__name__)


def issue_startup_warnings(conf):
    """Issue any startup warnings for the networking service."""
    # Add any networking-specific startup warnings here
    LOG.info("Starting Ironic Networking Service")


def main():
    # NOTE(alegacy): Safeguard to prevent 'ironic.networking.manager'
    # from being imported prior to the configuration options being loaded.
    assert 'ironic.networking.manager' not in sys.modules

    # Parse config file and command line options, then start logging
    ironic_service.prepare_service('ironic_networking', sys.argv)
    ironic_service.ensure_rpc_transport(CONF)

    mgr = rpc_service.NetworkingRPCService(CONF.host,
                                           'ironic.networking.manager',
                                           'NetworkingManager')

    issue_startup_warnings(CONF)

    launcher = service.launch(CONF, mgr, restart_method='mutate')

    # Set override signals.
    command_utils.handle_signal()

    # Start the processes!
    sys.exit(launcher.wait())


if __name__ == '__main__':
    sys.exit(main())
