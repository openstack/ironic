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
from oslo_log import log as logging
from oslo_utils import netutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import network
from ironic.common import neutron
from ironic.conf import CONF
from ironic.dhcp import base
from ironic import objects

LOG = logging.getLogger(__name__)


class NeutronDHCPApi(base.BaseDHCP):
    """API for communicating to neutron 2.x API."""

    def update_port_dhcp_opts(self, port_id, dhcp_options, token=None,
                              context=None):
        """Update a port's attributes.

        Update one or more DHCP options on the specified port.
        For the relevant API spec, see
        https://docs.openstack.org/api-ref/network/v2/index.html#update-port

        :param port_id: designate which port these attributes
                        will be applied to.
        :param dhcp_options: this will be a list of dicts, e.g.

                             ::

                              [{'opt_name': '67',
                                'opt_value': 'pxelinux.0'},
                               {'opt_name': '66',
                                'opt_value': '123.123.123.456'}]
        :param token: optional auth token. Deprecated, use context.
        :param context: request context
        :type context: ironic.common.context.RequestContext
        :raises: FailedToUpdateDHCPOptOnPort
        """
        super(NeutronDHCPApi, self).update_port_dhcp_opts(
            port_id, dhcp_options, token=token, context=context)
        port_req_body = {'port': {'extra_dhcp_opts': dhcp_options}}
        try:
            neutron.get_client(token=token, context=context).update_port(
                port_id, port_req_body)
        except neutron_client_exc.NeutronClientException:
            LOG.exception("Failed to update Neutron port %s.", port_id)
            raise exception.FailedToUpdateDHCPOptOnPort(port_id=port_id)

    def update_dhcp_opts(self, task, options, vifs=None):
        """Send or update the DHCP BOOT options for this node.

        :param task: A TaskManager instance.
        :param options: this will be a list of dicts, e.g.

                        ::

                         [{'opt_name': '67',
                           'opt_value': 'pxelinux.0'},
                          {'opt_name': '66',
                           'opt_value': '123.123.123.456'}]
        :param vifs: a dict of Neutron port/portgroup dicts
                     to update DHCP options on. The port/portgroup dict
                     key should be Ironic port UUIDs, and the values
                     should be Neutron port UUIDs, e.g.

                     ::

                      {'ports': {'port.uuid': vif.id},
                       'portgroups': {'portgroup.uuid': vif.id}}
                      If the value is None, will get the list of
                      ports/portgroups from the Ironic port/portgroup
                      objects.
        """
        if vifs is None:
            vifs = network.get_node_vif_ids(task)
        if not (vifs['ports'] or vifs['portgroups']):
            raise exception.FailedToUpdateDHCPOptOnPort(
                _("No VIFs found for node %(node)s when attempting "
                  "to update DHCP BOOT options.") %
                {'node': task.node.uuid})

        failures = []
        vif_list = [vif for pdict in vifs.values() for vif in pdict.values()]
        for vif in vif_list:
            try:
                self.update_port_dhcp_opts(vif, options, context=task.context)
            except exception.FailedToUpdateDHCPOptOnPort:
                failures.append(vif)

        if failures:
            if len(failures) == len(vif_list):
                raise exception.FailedToUpdateDHCPOptOnPort(_(
                    "Failed to set DHCP BOOT options for any port on node %s.")
                    % task.node.uuid)
            else:
                LOG.warning("Some errors were encountered when updating "
                            "the DHCP BOOT options for node %(node)s on "
                            "the following Neutron ports: %(ports)s.",
                            {'node': task.node.uuid, 'ports': failures})

        # TODO(adam_g): Hack to workaround bug 1334447 until we have a
        # mechanism for synchronizing events with Neutron. We need to sleep
        # only if server gets to PXE faster than Neutron agents have setup
        # sufficient DHCP config for netboot. It may occur when we are using
        # VMs or hardware server with fast boot enabled.
        port_delay = CONF.neutron.port_setup_delay
        if port_delay != 0:
            LOG.debug("Waiting %d seconds for Neutron.", port_delay)
            time.sleep(port_delay)

    def _get_fixed_ip_address(self, port_uuid, client):
        """Get a Neutron port's fixed ip address.

        :param port_uuid: Neutron port id.
        :param client: Neutron client instance.
        :returns: Neutron port ip address.
        :raises: NetworkError
        :raises: InvalidIPv4Address
        :raises: FailedToGetIPAddressOnPort
        """
        ip_address = None
        try:
            neutron_port = client.show_port(port_uuid).get('port')
        except neutron_client_exc.NeutronClientException:
            raise exception.NetworkError(
                _('Could not retrieve neutron port: %s') % port_uuid)

        fixed_ips = neutron_port.get('fixed_ips')

        # NOTE(faizan) At present only the first fixed_ip assigned to this
        # neutron port will be used, since nova allocates only one fixed_ip
        # for the instance.
        if fixed_ips:
            ip_address = fixed_ips[0].get('ip_address', None)

        if ip_address:
            if netutils.is_valid_ipv4(ip_address):
                return ip_address
            else:
                LOG.error("Neutron returned invalid IPv4 "
                          "address %(ip_address)s on port %(port_uuid)s.",
                          {'ip_address': ip_address, 'port_uuid': port_uuid})
                raise exception.InvalidIPv4Address(ip_address=ip_address)
        else:
            LOG.error("No IP address assigned to Neutron port %s.",
                      port_uuid)
            raise exception.FailedToGetIPAddressOnPort(port_id=port_uuid)

    def _get_port_ip_address(self, task, p_obj, client):
        """Get ip address of ironic port/portgroup assigned by Neutron.

        :param task: a TaskManager instance.
        :param p_obj: Ironic port or portgroup object.
        :param client: Neutron client instance.
        :returns: List of Neutron vif ip address associated with
                  Node's port/portgroup.
        :raises: FailedToGetIPAddressOnPort
        :raises: InvalidIPv4Address
        """

        vif = task.driver.network.get_current_vif(task, p_obj)
        if not vif:
            obj_name = 'portgroup'
            if isinstance(p_obj, objects.Port):
                obj_name = 'port'
            LOG.warning("No VIFs found for node %(node)s when attempting "
                        "to get IP address for %(obj_name)s: %(obj_id)s.",
                        {'node': task.node.uuid, 'obj_name': obj_name,
                         'obj_id': p_obj.uuid})
            raise exception.FailedToGetIPAddressOnPort(port_id=p_obj.uuid)

        vif_ip_address = self._get_fixed_ip_address(vif, client)
        return vif_ip_address

    def _get_ip_addresses(self, task, pobj_list, client):
        """Get IP addresses for all ports/portgroups.

        :param task: a TaskManager instance.
        :param pobj_list: List of port or portgroup objects.
        :param client: Neutron client instance.
        :returns: List of IP addresses associated with
                  task's ports/portgroups.
        """
        failures = []
        ip_addresses = []
        for obj in pobj_list:
            try:
                vif_ip_address = self._get_port_ip_address(task, obj,
                                                           client)
                ip_addresses.append(vif_ip_address)
            except (exception.FailedToGetIPAddressOnPort,
                    exception.InvalidIPv4Address,
                    exception.NetworkError):
                failures.append(obj.uuid)

        if failures:
            obj_name = 'portgroups'
            if isinstance(pobj_list[0], objects.Port):
                obj_name = 'ports'

            LOG.warning(
                "Some errors were encountered on node %(node)s "
                "while retrieving IP addresses on the following "
                "%(obj_name)s: %(failures)s.",
                {'node': task.node.uuid, 'obj_name': obj_name,
                 'failures': failures})

        return ip_addresses

    def get_ip_addresses(self, task):
        """Get IP addresses for all ports/portgroups in `task`.

        :param task: a TaskManager instance.
        :returns: List of IP addresses associated with
                  task's ports/portgroups.
        """
        client = neutron.get_client(context=task.context)

        port_ip_addresses = self._get_ip_addresses(task, task.ports, client)
        portgroup_ip_addresses = self._get_ip_addresses(
            task, task.portgroups, client)

        return port_ip_addresses + portgroup_ip_addresses
