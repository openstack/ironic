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

from ironic.cmd import conductor as conductor_cmd
from ironic.common import rpc_service
from ironic.common import service as ironic_service
from ironic.common import wsgi_service

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

    launcher = service.ServiceLauncher(CONF, restart_method='mutate')

    mgr = rpc_service.RPCService(CONF.host,
                                 'ironic.conductor.manager',
                                 'ConductorManager')
    conductor_cmd.issue_startup_warnings(CONF)
    launcher.launch_service(mgr)

    wsgi = wsgi_service.WSGIService('ironic_api', CONF.api.enable_ssl_api)
    launcher.launch_service(wsgi)

    # NOTE(dtantsur): handling start-up failures before launcher.wait() helps
    # notify systemd about them. Otherwise the launcher will report successful
    # service start-up before checking the threads.
    mgr.wait_for_start()

    sys.exit(launcher.wait())
