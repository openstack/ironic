# Copyright 2016 Intel Corporation
# Copyright 2015, Cisco Systems.
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

# NOTE: options for CIMC (Cisco Integrated Management Controller), which talks
# to UCS (Unified Computing System) in standalone mode
cimc_opts = [
    cfg.IntOpt('max_retry',
               default=6,
               help=_('Number of times a power operation needs to be '
                      'retried')),
    cfg.IntOpt('action_interval',
               default=10,
               help=_('Amount of time in seconds to wait in between power '
                      'operations')),
]

# NOTE: options for UCSM (UCS Manager), which talks to UCS via a centralized
# management controller
ucsm_opts = [
    cfg.IntOpt('max_retry',
               default=6,
               help=_('Number of times a power operation needs to be '
                      'retried')),
    cfg.IntOpt('action_interval',
               default=5,
               help=_('Amount of time in seconds to wait in between power '
                      'operations')),
]


def register_opts(conf):
    conf.register_opts(cimc_opts, group='cimc')
    conf.register_opts(ucsm_opts, group='cisco_ucs')
