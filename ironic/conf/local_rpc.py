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


CONF = cfg.CONF

opts = [
    cfg.StrOpt('temp_dir',
               help=_('When local RPC is used (rpc_transport=None), this is '
                      'the name of the directory to create temporary files '
                      'in. Must not be readable by any other processes. '
                      'If not provided, a temporary directory is used.')),
    cfg.BoolOpt('use_ssl',
                default=True,
                help=_('Whether to use TLS on the local RPC bus. Only set to '
                       'False if you experience issues with TLS and if all '
                       'local processes are trusted!')),
]


def register_opts(conf):
    conf.register_opts(opts, group='local_rpc')


def list_opts():
    return opts
