#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from oslo_config import cfg
from oslo_config import types as cfg_types

from ironic.common.i18n import _


opts = [
    cfg.IntOpt('registration_attempts',
               min=1, default=5,
               help=_('Number of attempts to register a service. Currently '
                      'has to be larger than 1 because of race conditions '
                      'in the zeroconf library.')),
    cfg.IntOpt('lookup_attempts',
               min=1, default=3,
               help=_('Number of attempts to lookup a service.')),
    cfg.Opt('params',
            # This is required for values that contain commas.
            type=cfg_types.Dict(cfg_types.String(quotes=True)),
            default={},
            help=_('Additional parameters to pass for the registered '
                   'service.')),
    cfg.ListOpt('interfaces',
                help=_('List of IP addresses of interfaces to use for mDNS. '
                       'Defaults to all interfaces on the system.')),
]


def register_opts(conf):
    group = cfg.OptGroup(name='mdns', title=_('Options for multicast DNS'))
    conf.register_group(group)
    conf.register_opts(opts, group)
