# Copyright 2016 Intel Corporation
# Copyright 2013,2014 Cray Inc
#
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
    cfg.IntOpt('power_timeout',
               default=10,
               help=_('Seconds to wait for power action to be completed')),
    # NOTE(yuriyz): some of SNMP-enabled hardware have own options for pause
    # between off and on. This option guarantees minimal value.
    cfg.IntOpt('reboot_delay',
               default=0,
               min=0,
               help=_('Time (in seconds) to sleep between when rebooting '
                      '(powering off and on again)')),
    cfg.IntOpt('power_action_delay',
               default=0,
               min=0,
               help=_('Time (in seconds) to sleep before power on and '
                      'after powering off. Which may be needed with some '
                      'PDUs as they may not honor toggling a specific power '
                      'port in rapid succession without a delay. This option '
                      'may be useful if the attached physical machine has a '
                      'substantial power supply to hold it over in the event '
                      'of a brownout.')),
    cfg.FloatOpt('udp_transport_timeout',
                 default=1.0,
                 min=0.0,
                 help=_('Response timeout in seconds used for UDP transport. '
                        'Timeout should be a multiple of 0.5 seconds and '
                        'is applicable to each retry.')),
    cfg.IntOpt('udp_transport_retries',
               default=5,
               min=0,
               help=_('Maximum number of UDP request retries, '
                      '0 means no retries.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='snmp')
