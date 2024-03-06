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
from ironic.common import utils
from ironic.conductor import rpc_service

CONF = cfg.CONF

LOG = log.getLogger(__name__)


def warn_about_unsafe_shred_parameters(conf):
    iterations = conf.deploy.shred_random_overwrite_iterations
    overwrite_with_zeros = conf.deploy.shred_final_overwrite_with_zeros
    if iterations == 0 and overwrite_with_zeros is False:
        LOG.warning('With shred_random_overwrite_iterations set to 0 and '
                    'shred_final_overwrite_with_zeros set to False, disks '
                    'may NOT be shredded at all, unless they support ATA '
                    'Secure Erase. This is a possible SECURITY ISSUE!')


def warn_about_sqlite():
    # We are intentionally calling the helper here to ensure it caches
    # for all future calls.
    if utils.is_ironic_using_sqlite():
        LOG.warning('Ironic has been configured to utilize SQLite. '
                    'This has some restrictions and impacts. You must run '
                    'as as a single combined ironic process, and some '
                    'internal mechanisms do not execute such as the hash '
                    'ring will remain static and the conductor\'s '
                    '``last_updated`` field will also not update. This is '
                    'in order to minimize database locking issues present '
                    'as a result of SQLAlchemy 2.0 and the removal of '
                    'autocommit support.')


def warn_about_max_wait_parameters(conf):
    max_wait = conf.conductor.max_conductor_wait_step_seconds
    max_deploy_timeout = conf.conductor.deploy_callback_timeout
    max_clean_timeout = conf.conductor.clean_callback_timeout
    error_with = None
    if max_wait >= max_deploy_timeout:
        error_with = 'deploy_callback_timeout'
    if max_wait >= max_clean_timeout:
        error_with = 'clean_callback_timeout'
    if error_with:
        LOG.warning('The [conductor]max_conductor_wait_step_seconds '
                    'configuration parameter exceeds the value of '
                    '[conductor]%s, which could create a condition where '
                    'tasks may timeout. Ironic recommends a low default '
                    'value for [conductor]max_conductor_wait_step_seconds ',
                    'please re-evaluate your configuration.', error_with)


def issue_startup_warnings(conf):
    warn_about_unsafe_shred_parameters(conf)
    warn_about_sqlite()
    warn_about_max_wait_parameters(conf)


def main():
    # NOTE(lucasagomes): Safeguard to prevent 'ironic.conductor.manager'
    # from being imported prior to the configuration options being loaded.
    # If this happened, the periodic decorators would always use the
    # default values of the options instead of the configured ones. For
    # more information see: https://bugs.launchpad.net/ironic/+bug/1562258
    # and https://bugs.launchpad.net/ironic/+bug/1279774.
    assert 'ironic.conductor.manager' not in sys.modules

    # Parse config file and command line options, then start logging
    ironic_service.prepare_service('ironic_conductor', sys.argv)
    ironic_service.ensure_rpc_transport(CONF)

    mgr = rpc_service.RPCService(CONF.host,
                                 'ironic.conductor.manager',
                                 'ConductorManager')

    issue_startup_warnings(CONF)

    launcher = service.launch(CONF, mgr, restart_method='mutate')

    # NOTE(dtantsur): handling start-up failures before launcher.wait() helps
    # notify systemd about them. Otherwise the launcher will report successful
    # service start-up before checking the threads.
    mgr.wait_for_start()

    sys.exit(launcher.wait())


if __name__ == '__main__':
    sys.exit(main())
