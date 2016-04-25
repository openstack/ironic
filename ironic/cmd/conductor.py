# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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
The Ironic Management Service
"""

import sys

from oslo_config import cfg
from oslo_log import log
from oslo_service import service

from ironic.common import service as ironic_service

CONF = cfg.CONF


def main():
    # Parse config file and command line options, then start logging
    ironic_service.prepare_service(sys.argv)

    mgr = ironic_service.RPCService(CONF.host,
                                    'ironic.conductor.manager',
                                    'ConductorManager')

    LOG = log.getLogger(__name__)
    LOG.debug("Configuration:")
    CONF.log_opt_values(LOG, log.DEBUG)

    launcher = service.launch(CONF, mgr)
    launcher.wait()


if __name__ == '__main__':
    sys.exit(main())
