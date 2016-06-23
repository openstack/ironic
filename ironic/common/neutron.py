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

from neutronclient.v2_0 import client as clientv20
from oslo_config import cfg
from oslo_log import log

from ironic.common.i18n import _
from ironic.common import keystone


LOG = log.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('my_ip', 'ironic.netconf')

neutron_opts = [
    cfg.StrOpt('url',
               default='http://$my_ip:9696',
               help=_('URL for connecting to neutron.')),
    cfg.IntOpt('url_timeout',
               default=30,
               help=_('Timeout value for connecting to neutron in seconds.')),
    cfg.IntOpt('port_setup_delay',
               default=0,
               min=0,
               help=_('Delay value to wait for Neutron agents to setup '
                      'sufficient DHCP configuration for port.')),
    cfg.IntOpt('retries',
               default=3,
               help=_('Client retries in the case of a failed request.')),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               choices=['keystone', 'noauth'],
               help=_('Authentication strategy to use when connecting to '
                      'neutron. Running neutron in noauth mode (related to '
                      'but not affected by this setting) is insecure and '
                      'should only be used for testing.')),
    cfg.StrOpt('cleaning_network_uuid',
               help=_('UUID of the network to create Neutron ports on, when '
                      'booting to a ramdisk for cleaning using Neutron DHCP.'))
]

CONF.register_opts(neutron_opts, group='neutron')


def get_client(token=None):
    params = {
        'timeout': CONF.neutron.url_timeout,
        'retries': CONF.neutron.retries,
        'insecure': CONF.keystone_authtoken.insecure,
        'ca_cert': CONF.keystone_authtoken.certfile,
    }

    if CONF.neutron.auth_strategy == 'noauth':
        params['endpoint_url'] = CONF.neutron.url
        params['auth_strategy'] = 'noauth'
    else:
        params['endpoint_url'] = (
            CONF.neutron.url or
            keystone.get_service_url(service_type='network'))
        params['username'] = CONF.keystone_authtoken.admin_user
        params['tenant_name'] = CONF.keystone_authtoken.admin_tenant_name
        params['password'] = CONF.keystone_authtoken.admin_password
        params['auth_url'] = (CONF.keystone_authtoken.auth_uri or '')
        if CONF.keystone.region_name:
            params['region_name'] = CONF.keystone.region_name
        params['token'] = token

    return clientv20.Client(**params)
