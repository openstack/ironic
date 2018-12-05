# Copyright 2016 Intel Corporation
#
# Copyright 2013 International Business Machines Corporation
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

from oslo_config import cfg

from ironic.common.i18n import _

opts = [
    cfg.IntOpt('command_retry_timeout',
               default=60,
               help=_('Maximum time in seconds to retry retryable IPMI '
                      'operations. (An operation is retryable, for '
                      'example, if the requested operation fails '
                      'because the BMC is busy.) Setting this too high '
                      'can cause the sync power state '
                      'periodic task to hang when there are slow or '
                      'unresponsive BMCs.')),
    cfg.IntOpt('min_command_interval',
               default=5,
               help=_('Minimum time, in seconds, between IPMI operations '
                      'sent to a server. There is a risk with some hardware '
                      'that setting this too low may cause the BMC to crash. '
                      'Recommended setting is 5 seconds.')),
    cfg.BoolOpt('kill_on_timeout',
                default=True,
                help=_('Kill `ipmitool` process invoked by ironic to read '
                       'node power state if `ipmitool` process does not exit '
                       'after `command_retry_timeout` timeout expires. '
                       'Recommended setting is True')),
]


def register_opts(conf):
    conf.register_opts(opts, group='ipmi')
