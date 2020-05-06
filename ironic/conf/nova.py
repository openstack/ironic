# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from ironic.common.i18n import _
from ironic.conf import auth

opts = [
    cfg.BoolOpt('send_power_notifications',
                default=True,
                mutable=True,
                help=_('When set to True, it will enable the support '
                       'for power state change callbacks to nova. This '
                       'option should be set to False in deployments '
                       'that do not have the openstack compute service.'))
]


def register_opts(conf):
    conf.register_opts(opts, group='nova')
    auth.register_auth_opts(conf, 'nova', service_type='compute')


def list_opts():
    return auth.add_auth_opts(opts, service_type='compute')
