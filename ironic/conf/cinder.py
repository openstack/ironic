# Copyright 2016 Hewlett Packard Enterprise Development Company LP.
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
from ironic.conf import auth

opts = [
    cfg.URIOpt('url',
               schemes=('http', 'https'),
               help=_('URL for connecting to cinder. If set, the value must '
                      'start with either http:// or https://. This option is '
                      'part of boot-from-volume work, which is not currently '
                      'exposed to users.')),
    cfg.IntOpt('retries',
               default=3,
               help=_('Client retries in the case of a failed request '
                      'connection. This option is part of boot-from-volume '
                      'work, which is not currently exposed to users.')),
    cfg.IntOpt('action_retries',
               default=3,
               help=_('Number of retries in the case of a failed '
                      'action (currently only used when detaching '
                      'volumes). This option is part of boot-from-volume '
                      'work, which is not currently exposed to users.')),
    cfg.IntOpt('action_retry_interval',
               default=5,
               help=_('Retry interval in seconds in the case of a failed '
                      'action (only specific actions are retried).')),
]


def register_opts(conf):
    conf.register_opts(opts, group='cinder')
    auth.register_auth_opts(conf, 'cinder')


def list_opts():
    return auth.add_auth_opts(opts)
