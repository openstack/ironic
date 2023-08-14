# Copyright 2016 Intel Corporation
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
    cfg.StrOpt('mysql_engine',
               default='InnoDB',
               help=_('MySQL engine to use.')),
    cfg.BoolOpt('sqlite_retries',
                default=True,
                help=_('If SQLite database operation retry logic is enabled '
                       'or not. Enabled by default.')),
    cfg.IntOpt('sqlite_max_wait_for_retry',
               default=10,
               help=_('Maximum number of seconds to retry SQLite database '
                      'locks, after which the original exception will be '
                      'returned to the caller. This does not presently apply '
                      'to internal node lock release actions and DB actions '
                      'centered around the completion of tasks.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='database')
