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
    cfg.StrOpt('auth_strategy',
               choices=[('noauth', _('no authentication')),
                        ('keystone', _('use the Identity service for '
                                       'authentication'))],
               help=_('Authentication strategy used by JSON RPC. Defaults to '
                      'the global auth_strategy setting.')),
    cfg.HostAddressOpt('host_ip',
                       default='::',
                       help=_('The IP address or hostname on which JSON RPC '
                              'will listen.')),
    cfg.PortOpt('port',
                default=8089,
                help=_('The port to use for JSON RPC')),
    cfg.BoolOpt('use_ssl',
                default=False,
                help=_('Whether to use TLS for JSON RPC')),
]


def register_opts(conf):
    conf.register_opts(opts, group='json_rpc')
    auth.register_auth_opts(conf, 'json_rpc')


def list_opts():
    return opts + auth.add_auth_opts([])
