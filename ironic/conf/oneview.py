# Copyright 2016 Intel Corporation
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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
    cfg.StrOpt('manager_url',
               help=_('URL where OneView is available.')),
    cfg.StrOpt('username',
               help=_('OneView username to be used.')),
    cfg.StrOpt('password',
               secret=True,
               help=_('OneView password to be used.')),
    cfg.BoolOpt('allow_insecure_connections',
                default=False,
                help=_('Option to allow insecure connection with OneView.')),
    cfg.StrOpt('tls_cacert_file',
               help=_('Path to CA certificate.')),
    cfg.IntOpt('max_polling_attempts',
               default=12,
               help=_('Max connection retries to check changes on OneView.')),
    cfg.BoolOpt('enable_periodic_tasks',
                default=True,
                help=_('Whether to enable the periodic tasks for OneView '
                       'driver be aware when OneView hardware resources are '
                       'taken and released by Ironic or OneView users '
                       'and proactively manage nodes in clean fail state '
                       'according to Dynamic Allocation model of hardware '
                       'resources allocation in OneView.')),
    cfg.IntOpt('periodic_check_interval',
               default=300,
               help=_('Period (in seconds) for periodic tasks to be '
                      'executed when enable_periodic_tasks=True.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='oneview')
