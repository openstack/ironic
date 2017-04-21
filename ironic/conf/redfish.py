# Copyright 2017 Red Hat, Inc.
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
    cfg.IntOpt('connection_attempts',
               min=1,
               default=5,
               help=_('Maximum number of attempts to try to connect '
                      'to Redfish')),
    cfg.IntOpt('connection_retry_interval',
               min=1,
               default=4,
               help=_('Number of seconds to wait between attempts to '
                      'connect to Redfish'))
]


def register_opts(conf):
    conf.register_opts(opts, group='redfish')
