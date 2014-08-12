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

import time

from neutronclient.common import exceptions as neutron_client_exc
from neutronclient.v2_0 import client as clientv20
from oslo.config import cfg

from ironic.common import exception
from ironic.common import keystone
from ironic.drivers.modules import ssh
from ironic.openstack.common import log as logging


neutron_opts = [
    cfg.StrOpt('url',
               default='http://$my_ip:9696',
               help='URL for connecting to neutron.'),
    cfg.IntOpt('url_timeout',
               default=30,
               help='Timeout value for connecting to neutron in seconds.'),
    cfg.StrOpt('auth_strategy',
               default='keystone',
               help='Default authentication strategy to use when connecting '
                    'to neutron. Can be either "keystone" or "noauth". '
                    'Running neutron in noauth mode (related to but not '
                    'affected by this setting) is insecure and should only be '
                    'used for testing.')
   ]

CONF = cfg.CONF
CONF.import_opt('my_ip', 'ironic.netconf')
CONF.register_opts(neutron_opts, group='neutron')
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

        if CONF.neutron.auth_strategy not in ['noauth', 'keystone']:
            raise exception.ConfigInvalid(_('Neutron auth_strategy should be '
                                            'either "noauth" or "keystone".'))

        if CONF.neutron.auth_strategy == 'noauth':
            params['endpoint_url'] = CONF.neutron.url
            params['auth_strategy'] = 'noauth'
        elif (CONF.neutron.auth_strategy == 'keystone' and
                context.auth_token is None):
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

    def update_port_address(self, port_id, address):
        """Update a port's mac address.

        :param port_id: Neutron port id.
        :param address: new MAC address.
        :raises: FailedToUpdateMacOnPort
        """
        port_req_body = {'port': {'mac_address': address}}
        try:
            self.client.update_port(port_id, port_req_body)
        except neutron_client_exc.NeutronClientException:
            LOG.exception(_("Failed to update MAC address on Neutron port %s."
                           ), port_id)
            raise exception.FailedToUpdateMacOnPort(port_id=port_id)


def get_node_vif_ids(task):
    """Get all Neutron VIF ids for a node.

    This function does not handle multi node operations.

    :param task: a TaskManager instance.
    :returns: A dict of the Node's port UUIDs and their associated VIFs

    """
    port_vifs = {}
    for port in task.ports:
        vif = port.extra.get('vif_port_id')
        if vif:
            port_vifs[port.uuid] = vif
    return port_vifs


def update_neutron(task, options):
    """Send or update the DHCP BOOT options to Neutron for this node."""
    vifs = get_node_vif_ids(task)
    if not vifs:
        LOG.warning(_("No VIFs found for node %(node)s when attempting to "
                      "update Neutron DHCP BOOT options."),
                      {'node': task.node.uuid})
        return

    # TODO(deva): decouple instantiation of NeutronAPI from task.context.
    #             Try to use the user's task.context.auth_token, but if it
    #             is not present, fall back to a server-generated context.
    #             We don't need to recreate this in every method call.
    api = NeutronAPI(task.context)
    failures = []
    for port_id, port_vif in vifs.iteritems():
        try:
            api.update_port_dhcp_opts(port_vif, options)
        except exception.FailedToUpdateDHCPOptOnPort:
            failures.append(port_id)

    if failures:
        if len(failures) == len(vifs):
            raise exception.FailedToUpdateDHCPOptOnPort(_(
                "Failed to set DHCP BOOT options for any port on node %s.") %
                task.node.uuid)
        else:
            LOG.warning(_("Some errors were encountered when updating the "
                          "DHCP BOOT options for node %(node)s on the "
                          "following ports: %(ports)s."),
                          {'node': task.node.uuid, 'ports': failures})

    _wait_for_neutron_update(task)


def _wait_for_neutron_update(task):
    """Wait for Neutron agents to process all requested changes if required."""
    # TODO(adam_g): Hack to workaround bug 1334447 until we have a mechanism
    # for synchronizing events with Neutron.  We need to sleep only if we are
    # booting VMs, which is implied by SSHPower, to ensure they do not boot
    # before Neutron agents have setup sufficent DHCP config for netboot.
    if isinstance(task.driver.power, ssh.SSHPower):
        LOG.debug(_("Waiting 15 seconds for Neutron."))
        time.sleep(15)
