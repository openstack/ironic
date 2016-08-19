# Copyright 2015 Rackspace, Inc.
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


from neutronclient.common import exceptions as neutron_exceptions
from oslo_config import cfg
from oslo_log import log
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common.i18n import _, _LI, _LW
from ironic.common import neutron
from ironic.drivers import base
from ironic import objects

LOG = log.getLogger(__name__)

CONF = cfg.CONF


class NeutronNetwork(base.NetworkInterface):
    """Neutron v2 network interface"""

    def __init__(self):
        failures = []
        cleaning_net = CONF.neutron.cleaning_network_uuid
        if not uuidutils.is_uuid_like(cleaning_net):
            failures.append('cleaning_network_uuid=%s' % cleaning_net)

        provisioning_net = CONF.neutron.provisioning_network_uuid
        if not uuidutils.is_uuid_like(provisioning_net):
            failures.append('provisioning_network_uuid=%s' % provisioning_net)

        if failures:
            raise exception.DriverLoadError(
                driver=self.__class__.__name__,
                reason=(_('The following [neutron] group configuration '
                          'options are incorrect, they must be valid UUIDs: '
                          '%s') % ', '.join(failures)))

    def add_provisioning_network(self, task):
        """Add the provisioning network to a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        LOG.info(_LI('Adding provisioning network to node %s'),
                 task.node.uuid)
        vifs = neutron.add_ports_to_network(
            task, CONF.neutron.provisioning_network_uuid)
        for port in task.ports:
            if port.uuid in vifs:
                internal_info = port.internal_info
                internal_info['provisioning_vif_port_id'] = vifs[port.uuid]
                port.internal_info = internal_info
                port.save()

    def remove_provisioning_network(self, task):
        """Remove the provisioning network from a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        LOG.info(_LI('Removing provisioning network from node %s'),
                 task.node.uuid)
        neutron.remove_ports_from_network(
            task, CONF.neutron.provisioning_network_uuid)
        for port in task.ports:
            if 'provisioning_vif_port_id' in port.internal_info:
                internal_info = port.internal_info
                del internal_info['provisioning_vif_port_id']
                port.internal_info = internal_info
                port.save()

    def add_cleaning_network(self, task):
        """Create neutron ports for each port on task.node to boot the ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        """
        # If we have left over ports from a previous cleaning, remove them
        neutron.rollback_ports(task, CONF.neutron.cleaning_network_uuid)
        LOG.info(_LI('Adding cleaning network to node %s'), task.node.uuid)
        vifs = neutron.add_ports_to_network(task,
                                            CONF.neutron.cleaning_network_uuid)
        for port in task.ports:
            if port.uuid in vifs:
                internal_info = port.internal_info
                internal_info['cleaning_vif_port_id'] = vifs[port.uuid]
                port.internal_info = internal_info
                port.save()
        return vifs

    def remove_cleaning_network(self, task):
        """Deletes the neutron port created for booting the ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        """
        LOG.info(_LI('Removing cleaning network from node %s'),
                 task.node.uuid)
        neutron.remove_ports_from_network(
            task, CONF.neutron.cleaning_network_uuid)
        for port in task.ports:
            if 'cleaning_vif_port_id' in port.internal_info:
                internal_info = port.internal_info
                del internal_info['cleaning_vif_port_id']
                port.internal_info = internal_info
                port.save()

    def configure_tenant_networks(self, task):
        """Configure tenant networks for a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        node = task.node
        ports = task.ports
        LOG.info(_LI('Mapping instance ports to %s'), node.uuid)

        # TODO(russell_h): this is based on the broken assumption that the
        # number of Neutron ports will match the number of physical ports.
        # Instead, we should probably list ports for this instance in
        # Neutron and update all of those with the appropriate portmap.
        if not ports:
            msg = _("No ports are associated with node %s") % node.uuid
            LOG.error(msg)
            raise exception.NetworkError(msg)
        ports = [p for p in ports if not p.portgroup_id]
        portgroups = task.portgroups

        portmap = neutron.get_node_portmap(task)

        client = neutron.get_client(task.context.auth_token)
        for port_like_obj in ports + portgroups:
            vif_port_id = port_like_obj.extra.get('vif_port_id')

            if not vif_port_id:
                LOG.warning(
                    _LW('%(port_like_object)s %(pobj_uuid)s in node %(node)s '
                        'has no vif_port_id value in extra field.'),
                    {'port_like_object': port_like_obj.__class__.__name__,
                     'pobj_uuid': port_like_obj.uuid, 'node': node.uuid})
                continue

            LOG.debug('Mapping tenant port %(vif_port_id)s to node '
                      '%(node_id)s',
                      {'vif_port_id': vif_port_id, 'node_id': node.uuid})
            local_link_info = []
            client_id_opt = None
            if isinstance(port_like_obj, objects.Portgroup):
                pg_ports = [p for p in task.ports
                            if p.portgroup_id == port_like_obj.id]
                for port in pg_ports:
                    local_link_info.append(portmap[port.uuid])
            else:
                # We iterate only on ports or portgroups, no need to check
                # that it is a port
                local_link_info.append(portmap[port_like_obj.uuid])
                client_id = port_like_obj.extra.get('client-id')
                if client_id:
                    client_id_opt = (
                        {'opt_name': 'client-id', 'opt_value': client_id})
            body = {
                'port': {
                    'device_owner': 'baremetal:none',
                    'device_id': node.instance_uuid or node.uuid,
                    'admin_state_up': True,
                    'binding:vnic_type': 'baremetal',
                    'binding:host_id': node.uuid,
                    'binding:profile': {
                        'local_link_information': local_link_info,
                    },
                }
            }
            if client_id_opt:
                body['port']['extra_dhcp_opts'] = [client_id_opt]

            try:
                client.update_port(vif_port_id, body)
            except neutron_exceptions.ConnectionFailed as e:
                msg = (_('Could not add public network VIF %(vif)s '
                         'to node %(node)s, possible network issue. %(exc)s') %
                       {'vif': vif_port_id,
                        'node': node.uuid,
                        'exc': e})
                LOG.error(msg)
                raise exception.NetworkError(msg)

    def unconfigure_tenant_networks(self, task):
        """Unconfigure tenant networks for a node.

        Even though nova takes care of port removal from tenant network, we
        remove it here/now to avoid the possibility of the ironic port being
        bound to the tenant and cleaning networks at the same time.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        node = task.node
        LOG.info(_LI('Unmapping instance ports from node %s'), node.uuid)
        params = {'device_id': node.instance_uuid or node.uuid}

        neutron.remove_neutron_ports(task, params)
