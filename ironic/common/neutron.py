#
# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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

from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client as clientv20
from oslo.config import cfg

from ironic.api import acl
from ironic.common import exception
from ironic.common import keystone
from ironic.openstack.common import log as logging


neutron_opts = [
    cfg.StrOpt('url',
               default='http://127.0.0.1:9696',
               help='URL for connecting to neutron.'),
    cfg.IntOpt('url_timeout',
               default=30,
               help='Timeout value for connecting to neutron in seconds.'),
   ]

CONF = cfg.CONF
CONF.register_opts(neutron_opts, group='neutron')
acl.register_opts(CONF)
LOG = logging.getLogger(__name__)


class NeutronAPI(object):
    """API for communicating to neutron 2.x API."""

    def __init__(self, context):
        self.context = context
        self.client = None
        params = {
            'timeout': CONF.neutron.url_timeout,
            'insecure': CONF.keystone_authtoken.insecure,
            'ca_cert': CONF.keystone_authtoken.certfile,
            }

        if context.auth_token is None:
            params['endpoint_url'] = (CONF.neutron.url or
                                      keystone.get_service_url('neutron'))
            params['username'] = CONF.keystone_authtoken.admin_user
            params['tenant_name'] = CONF.keystone_authtoken.admin_tenant_name
            params['password'] = CONF.keystone_authtoken.admin_password
            params['auth_url'] = (CONF.keystone_authtoken.auth_uri or '')
        else:
            params['token'] = context.auth_token
            params['endpoint_url'] = CONF.neutron.url
            params['auth_strategy'] = None

        self.client = clientv20.Client(**params)

    def update_port_dhcp_opts(self, port_id, dhcp_options):
        """Update a port's attributes.

        Update one or more DHCP options on the specified port.
        For the relevant API spec, see
        http://docs.openstack.org/api/openstack-network/2.0/content/extra-dhc-opt-ext-update.html  # noqa

        :param port_id: designate which port these attributes
                        will be applied to.
        :param dhcp_options: this will be a list of dicts, e.g.
                        [{'opt_name': 'bootfile-name',
                          'opt_value': 'pxelinux.0'},
                         {'opt_name': 'server-ip-address',
                          'opt_value': '123.123.123.456'},
                         {'opt_name': 'tftp-server',
                          'opt_value': '123.123.123.123'}]

        :raises: FailedToUpdateDHCPOptOnPort
        """
        port_req_body = {'port': {'extra_dhcp_opts': dhcp_options}}
        try:
            self.client.update_port(port_id, port_req_body)
        except neutron_client_exc.NeutronClientException:
            LOG.exception(_("Failed to update Neutron port %s."), port_id)
            raise exception.FailedToUpdateDHCPOptOnPort(port_id=port_id)
