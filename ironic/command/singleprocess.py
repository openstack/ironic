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

import sys

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

from ironic.command import conductor as conductor_cmd
from ironic.command import utils
from ironic.common import service as ironic_service
from ironic.conductor import rpc_service
from ironic.console import novncproxy_service

CONF = cfg.CONF

LOG = log.getLogger(__name__)


def main():
    # NOTE(lucasagomes): Safeguard to prevent 'ironic.conductor.manager'
    # from being imported prior to the configuration options being loaded.
    # If this happened, the periodic decorators would always use the
    # default values of the options instead of the configured ones. For
    # more information see: https://bugs.launchpad.net/ironic/+bug/1562258
    # and https://bugs.launchpad.net/ironic/+bug/1279774.
    assert 'ironic.conductor.manager' not in sys.modules

    # Parse config file and command line options, then start logging
    ironic_service.prepare_service('ironic', sys.argv)

    # Choose the launcher based upon if vnc is enabled or not.
    # The VNC proxy has to be run in the parent process, not
    # a sub-process.
    launcher = service.ServiceLauncher(CONF, restart_method='mutate',
                                       no_fork=CONF.vnc.enabled)

    mgr = rpc_service.RPCService(CONF.host,
                                 'ironic.conductor.manager',
                                 'ConductorManager',
                                 embed_api=True)
    conductor_cmd.issue_startup_warnings(CONF)
    launcher.launch_service(mgr)

    # NOTE(TheJulia): By default, vnc is disabled, and depending on that
    # overall process behavior will change. i.e. we're not going to force
    # single process which breaks systemd process launch detection.
    # Which is because you cannot directly invoke multiple services
    # with different launchers.
    if CONF.vnc.enabled:
        # Build and start the websocket proxy
        # NOTE(TheJulia): Single-process doesn't really *need*
        # the vnc proxy per stevebaker.
        novncproxy = novncproxy_service.NoVNCProxyService()
        launcher.launch_service(novncproxy)

    # Register our signal overrides before launching the processes
    utils.handle_signal()

    # Start the processes!
    sys.exit(launcher.wait())
