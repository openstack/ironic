# Copyright 2016 Intel Corporation
# Copyright 2014 Red Hat, Inc.
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
    cfg.IntOpt('max_retry',
               default=3,
               help=_('Maximum retries for iBoot operations')),
    cfg.IntOpt('retry_interval',
               default=1,
               help=_('Time (in seconds) between retry attempts for iBoot '
                      'operations')),
    cfg.IntOpt('reboot_delay',
               default=5,
               min=0,
               help=_('Time (in seconds) to sleep between when rebooting '
                      '(powering off and on again).'))
]

opt_group = cfg.OptGroup(name='iboot',
                         title='Options for the iBoot power driver')


def register_opts(conf):
    conf.register_group(opt_group)
    conf.register_opts(opts, group=opt_group)
