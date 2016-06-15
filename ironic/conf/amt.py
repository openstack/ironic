# Copyright 2016 Intel Corporation
# Copyright (c) 2012 NTT DOCOMO, INC.
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
    cfg.StrOpt('protocol',
               default='http',
               choices=['http', 'https'],
               help=_('Protocol used for AMT endpoint')),
    cfg.IntOpt('awake_interval',
               default=60,
               min=0,
               help=_('Time interval (in seconds) for successive awake call '
                      'to AMT interface, this depends on the IdleTimeout '
                      'setting on AMT interface. AMT Interface will go to '
                      'sleep after 60 seconds of inactivity by default. '
                      'IdleTimeout=0 means AMT will not go to sleep at all. '
                      'Setting awake_interval=0 will disable awake call.')),
    cfg.IntOpt('max_attempts',
               default=3,
               help=_('Maximum number of times to attempt an AMT operation, '
                      'before failing')),
    cfg.IntOpt('action_wait',
               default=10,
               help=_('Amount of time (in seconds) to wait, before retrying '
                      'an AMT operation'))
]


def register_opts(conf):
    conf.register_opts(opts, group='amt')
