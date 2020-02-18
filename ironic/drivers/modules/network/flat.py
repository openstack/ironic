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

"""
Flat network interface. Useful for shared, flat networks.
"""

from neutronclient.common import exceptions as neutron_exceptions
from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import neutron
from ironic.drivers import base
from ironic.drivers.modules.network import common


LOG = log.getLogger(__name__)

CONF = cfg.CONF


class FlatNetwork(common.NeutronVIFPortIDMixin,
                  neutron.NeutronNetworkInterfaceMixin, base.NetworkInterface):
    """Flat network interface."""

    def __init__(self):
        cleaning_net = CONF.neutron.cleaning_network
        if not cleaning_net:
            LOG.warning(
                'Please specify a valid UUID or name for '
                '[neutron]/cleaning_network configuration option so that '
                'this interface is able to perform cleaning. Otherwise, '
                'cleaning operations will fail to start.')

    def validate(self, task):
        """Validates the network interface.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        self.get_cleaning_network_uuid(task)

    def _bind_flat_ports(self, task):
        LOG.debug("Binding flat network ports")
        for port_like_obj in task.ports + task.portgroups:
            vif_port_id = (
                port_like_obj.internal_info.get(common.TENANT_VIF_KEY)
                or port_like_obj.extra.get('vif_port_id')
            )
            if not vif_port_id:
                continue
            body = {
                'port': {
                    'binding:host_id': task.node.uuid,
                    'binding:vnic_type': neutron.VNIC_BAREMETAL,
                    'mac_address': port_like_obj.address
                }
            }
            try:
                neutron.update_neutron_port(task.context,
                                            vif_port_id, body)
            except neutron_exceptions.NeutronClientException as e:
                msg = (_('Unable to set binding:host_id for '
                         'neutron port %(port_id)s. Error: '
                         '%(err)s') % {'port_id': vif_port_id, 'err': e})
                LOG.exception(msg)
                raise exception.NetworkError(msg)

    def _unbind_flat_ports(self, task):
        node = task.node
        LOG.info('Unbinding instance ports from node %s', node.uuid)

        ports = [p for p in task.ports if not p.portgroup_id]
        portgroups = task.portgroups
        for port_like_obj in ports + portgroups:
            vif_port_id = (
                port_like_obj.internal_info.get(common.TENANT_VIF_KEY)
                or port_like_obj.extra.get('vif_port_id'))
            if not vif_port_id:
                continue
            neutron.unbind_neutron_port(vif_port_id, context=task.context)

    def add_provisioning_network(self, task):
        """Add the provisioning network to a node.

        :param task: A TaskManager instance.
        :raises: NetworkError when failed to set binding:host_id
        """
        self._bind_flat_ports(task)

    def remove_provisioning_network(self, task):
        """Remove the provisioning network from a node.

        :param task: A TaskManager instance.
        """
        self._unbind_flat_ports(task)

    def configure_tenant_networks(self, task):
        """Configure tenant networks for a node.

        :param task: A TaskManager instance.
        """
        self._bind_flat_ports(task)

    def unconfigure_tenant_networks(self, task):
        """Unconfigure tenant networks for a node.

        Unbind the port here/now to avoid the possibility of the ironic port
        being bound to the tenant and cleaning networks at the same time.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        self._unbind_flat_ports(task)

    def _add_service_network(self, task, network, process):
        # If we have left over ports from a previous process, remove them
        neutron.rollback_ports(task, network)
        LOG.info('Adding %s network to node %s', process, task.node.uuid)
        vifs = neutron.add_ports_to_network(task, network)
        field = '%s_vif_port_id' % process
        for port in task.ports:
            if port.uuid in vifs:
                internal_info = port.internal_info
                internal_info[field] = vifs[port.uuid]
                port.internal_info = internal_info
                port.save()
        return vifs

    def _remove_service_network(self, task, network, process):
        LOG.info('Removing ports from %s network for node %s',
                 process, task.node.uuid)
        neutron.remove_ports_from_network(task, network)
        field = '%s_vif_port_id' % process
        for port in task.ports:
            if field in port.internal_info:
                internal_info = port.internal_info
                del internal_info[field]
                port.internal_info = internal_info
                port.save()

    def add_cleaning_network(self, task):
        """Add the cleaning network to a node.

        :param task: A TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        :raises: NetworkError, InvalidParameterValue
        """
        return self._add_service_network(
            task, self.get_cleaning_network_uuid(task), 'cleaning')

    def remove_cleaning_network(self, task):
        """Remove the cleaning network from a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        return self._remove_service_network(
            task, self.get_cleaning_network_uuid(task), 'cleaning')

    def add_rescuing_network(self, task):
        """Add the rescuing network to a node.

        Flat network does not use the rescuing network.
        Bind the port again since unconfigure_tenant_network() unbound it.

        :param task: A TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        :raises: NetworkError, InvalidParameterValue
        """
        LOG.info('Bind ports for rescuing node %s', task.node.uuid)
        self._bind_flat_ports(task)

    def remove_rescuing_network(self, task):
        """Remove the rescuing network from a node.

        Flat network does not use the rescuing network.
        Unbind the port again since add_rescuing_network() bound it.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        LOG.info('Unbind ports for rescuing node %s', task.node.uuid)
        self._unbind_flat_ports(task)

    def add_inspection_network(self, task):
        """Add the inspection network to the node.

        :param task: A TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        :raises: NetworkError
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        """
        return self._add_service_network(
            task, self.get_inspection_network_uuid(task), 'inspection')

    def remove_inspection_network(self, task):
        """Removes the inspection network from a node.

        :param task: A TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        return self._remove_service_network(
            task, self.get_inspection_network_uuid(task), 'inspection')
