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

from ironic.common.i18n import _
from ironic.common import keystone
from ironic.conf.api import Octal


CONF = cfg.CONF


opts = [
    cfg.StrOpt('auth_strategy',
               choices=[('noauth', _('no authentication')),
                        ('keystone', _('use the Identity service for '
                                       'authentication')),
                        ('http_basic', _('HTTP basic authentication'))],
               help=_('Authentication strategy used by JSON RPC. Defaults to '
                      'the global auth_strategy setting.')),
    cfg.StrOpt('http_basic_auth_user_file',
               default='/etc/ironic/htpasswd-json-rpc',
               help=_('Path to Apache format user authentication file used '
                      'when auth_strategy=http_basic')),
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
    cfg.StrOpt('cert_file',
               help=_("Certificate file the JSON-RPC listener will present "
                      "to clients when [json_rpc]use_ssl=True.")),
    cfg.StrOpt('key_file',
               help=_("Private key file matching cert_file.")),
    cfg.BoolOpt('client_use_ssl',
                default=False,
                help=_('Set to True to force TLS connections in the client '
                       'even if use_ssl is set to False. Only makes sense '
                       'if server-side TLS is provided outside of Ironic '
                       '(e.g. with httpd acting as a reverse proxy).')),
    cfg.StrOpt('http_basic_username',
               deprecated_for_removal=True,
               deprecated_reason=_("Use username instead"),
               help=_("Name of the user to use for HTTP Basic authentication "
                      "client requests.")),
    cfg.StrOpt('http_basic_password',
               deprecated_for_removal=True,
               deprecated_reason=_("Use password instead"),
               secret=True,
               help=_("Password to use for HTTP Basic authentication "
                      "client requests.")),
    cfg.ListOpt('allowed_roles',
                default=['admin'],
                help=_("List of roles allowed to use JSON RPC")),
    cfg.StrOpt('unix_socket',
               help=_('Unix socket to listen on. Disables host_ip and port.')),
    cfg.Opt('unix_socket_mode', type=Octal(),
            help=_('File mode (an octal number) of the unix socket to '
                   'listen on. Ignored if unix_socket is not set.')),
]


def register_opts(conf):
    conf.register_opts(opts, group='json_rpc')
    keystone.register_auth_opts(conf, 'json_rpc')
    conf.set_default('timeout', 120, group='json_rpc')


def list_opts():
    return keystone.add_auth_opts(opts)


def auth_strategy():
    return CONF.json_rpc.auth_strategy or CONF.auth_strategy
