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

from ironic.common.i18n import _LW
from ironic.common import rpc_service
from ironic.common import service as ironic_service
from ironic.conf import auth

CONF = cfg.CONF

LOG = log.getLogger(__name__)

SECTIONS_WITH_AUTH = (
    'service_catalog', 'neutron', 'glance', 'swift', 'inspector')


# TODO(pas-ha) remove this check after deprecation period
def _check_auth_options(conf):
    missing = []
    for section in SECTIONS_WITH_AUTH:
        if not auth.load_auth(conf, section):
            missing.append('[%s]' % section)
    if missing:
        link = "http://docs.openstack.org/releasenotes/ironic/newton.html"
        LOG.warning(_LW("Failed to load authentification credentials from "
                        "%(missing)s config sections. "
                        "The corresponding service users' credentials "
                        "will be loaded from [%(old)s] config section, "
                        "which is deprecated for this purpose. "
                        "Please update the config file. "
                        "For more info see %(link)s."),
                    dict(missing=", ".join(missing),
                         old=auth.LEGACY_SECTION,
                         link=link))


def main():
    # NOTE(lucasagomes): Safeguard to prevent 'ironic.conductor.manager'
    # from being imported prior to the configuration options being loaded.
    # If this happened, the periodic decorators would always use the
    # default values of the options instead of the configured ones. For
    # more information see: https://bugs.launchpad.net/ironic/+bug/1562258
    # and https://bugs.launchpad.net/ironic/+bug/1279774.
    assert 'ironic.conductor.manager' not in sys.modules

    # Parse config file and command line options, then start logging
    ironic_service.prepare_service(sys.argv)

    mgr = rpc_service.RPCService(CONF.host,
                                 'ironic.conductor.manager',
                                 'ConductorManager')

    _check_auth_options(CONF)

    launcher = service.launch(CONF, mgr)
    launcher.wait()


if __name__ == '__main__':
    sys.exit(main())
