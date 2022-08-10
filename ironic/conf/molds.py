# Copyright (c) 2021 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from ironic.common.i18n import _

opts = [
    cfg.StrOpt('storage',
               default='swift',
               help=_('Configuration mold storage location. Supports "swift" '
                      'and "http". By default "swift".')),
    cfg.StrOpt('user',
               help=_('User for "http" Basic auth. By default set empty.')),
    cfg.StrOpt('password',
               help=_('Password for "http" Basic auth. By default set '
                      'empty.')),
    cfg.IntOpt('retry_attempts',
               default=3,
               help=_('Retry attempts for saving or getting configuration '
                      'molds.')),
    cfg.IntOpt('retry_interval',
               default=3,
               help=_('Retry interval for saving or getting configuration '
                      'molds.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='molds')
