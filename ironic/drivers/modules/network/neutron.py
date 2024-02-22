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


from oslo_config import cfg
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import neutron
from ironic.drivers import base
from ironic.drivers.modules.network import common

LOG = log.getLogger(__name__)

CONF = cfg.CONF


class NeutronNetwork(common.NeutronVIFPortIDMixin,
                     neutron.NeutronNetworkInterfaceMixin,
                     base.NetworkInterface):
    """Neutron v2 network interface"""

    def validate(self, task):
        """Validates the network interface.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        # NOTE(TheJulia): These are the minimal networks needed for
        # the neutron network interface to function.
        self.get_cleaning_network_uuid(task)
        self.get_provisioning_network_uuid(task)

    def _add_network(self, task, network, security_groups, process):
        # If we have left over ports from a previous process, remove them
        neutron.rollback_ports(task, network)
        LOG.info('Adding %s network to node %s', process, task.node.uuid)
        vifs = neutron.add_ports_to_network(task, network,
                                            security_groups=security_groups)
        field = '%s_vif_port_id' % process
        for port in task.ports:
            if port.uuid in vifs:
                internal_info = port.internal_info
                internal_info[field] = vifs[port.uuid]
                port.internal_info = internal_info
                port.save()
        return vifs

    def _remove_network(self, task, network, process):
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

    def add_provisioning_network(self, task):
        """Add the provisioning network to a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        self._add_network(
            task, self.get_provisioning_network_uuid(task),
            CONF.neutron.provisioning_network_security_groups,
            'provisioning')

    def remove_provisioning_network(self, task):
        """Remove the provisioning network from a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        return self._remove_network(
            task, self.get_provisioning_network_uuid(task), 'provisioning')

    def add_cleaning_network(self, task):
        """Create neutron ports for each port on task.node to boot the ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        """
        return self._add_network(
            task, self.get_cleaning_network_uuid(task),
            CONF.neutron.cleaning_network_security_groups,
            'cleaning')

    def remove_cleaning_network(self, task):
        """Deletes the neutron port created for booting the ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        """
        return self._remove_network(
            task, self.get_cleaning_network_uuid(task), 'cleaning')

    def validate_rescue(self, task):
        """Validates the network interface for rescue operation.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        self.get_rescuing_network_uuid(task)

    def add_rescuing_network(self, task):
        """Create neutron ports for each port to boot the rescue ramdisk.

        :param task: a TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        """
        return self._add_network(
            task, self.get_rescuing_network_uuid(task),
            CONF.neutron.rescuing_network_security_groups,
            'rescuing')

    def remove_rescuing_network(self, task):
        """Deletes neutron port created for booting the rescue ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        """
        return self._remove_network(
            task, self.get_rescuing_network_uuid(task), 'rescuing')

    def configure_tenant_networks(self, task):
        """Configure tenant networks for a node.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        node = task.node
        ports = task.ports
        LOG.info('Mapping instance ports to %s', node.uuid)

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

        client = neutron.get_client(context=task.context)
        pobj_without_vif = 0
        for port_like_obj in ports + portgroups:

            try:
                common.plug_port_to_tenant_network(task, port_like_obj,
                                                   client=client)
            except exception.VifNotAttached:
                pobj_without_vif += 1
                continue

        if pobj_without_vif == len(ports + portgroups):
            msg = _("No neutron ports or portgroups are associated with "
                    "node %s") % node.uuid
            LOG.error(msg)
            raise exception.NetworkError(msg)

    def unconfigure_tenant_networks(self, task):
        """Unconfigure tenant networks for a node.

        Nova takes care of port removal from tenant network, we unbind it
        here/now to avoid the possibility of the ironic port being bound to the
        tenant and cleaning networks at the same time.

        :param task: A TaskManager instance.
        :raises: NetworkError
        """
        node = task.node
        LOG.info('Unbinding instance ports from node %s', node.uuid)

        ports = [p for p in task.ports if not p.portgroup_id]
        portgroups = task.portgroups
        for port_like_obj in ports + portgroups:
            vif_port_id = (
                port_like_obj.internal_info.get(common.TENANT_VIF_KEY)
            )
            if not vif_port_id:
                continue

            is_smart_nic = neutron.is_smartnic_port(port_like_obj)
            if is_smart_nic:
                client = neutron.get_client(context=task.context)
                link_info = port_like_obj.local_link_connection
                neutron.wait_for_host_agent(client, link_info['hostname'])

            # NOTE(kaifeng) address is optional for port group, avoid to
            # regenerate mac when the address is absent.
            reset_mac = bool(port_like_obj.address)
            neutron.unbind_neutron_port(vif_port_id, context=task.context,
                                        reset_mac=reset_mac)

    def need_power_on(self, task):
        """Check if the node has any Smart NIC ports

        :param task: A TaskManager instance.
        :return: A boolean to indicate Smart NIC port presence
        """
        for port in task.ports:
            if neutron.is_smartnic_port(port):
                return True
        return False

    def add_inspection_network(self, task):
        """Add the inspection network to the node.

        :param task: A TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        :raises: NetworkError
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        """
        return self._add_network(
            task, self.get_inspection_network_uuid(task),
            CONF.neutron.inspection_network_security_groups,
            'inspection')

    def remove_inspection_network(self, task):
        """Removes the inspection network from a node.

        :param task: A TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        return self._remove_network(
            task, self.get_inspection_network_uuid(task), 'inspection')

    def validate_servicing(self, task):
        """Validates the network interface for servicing operation.

        :param task: a TaskManager instance.
        :raises: InvalidParameterValue, if the network interface configuration
            is invalid.
        :raises: MissingParameterValue, if some parameters are missing.
        """
        self.get_servicing_network_uuid(task)

    def add_servicing_network(self, task):
        """Create neutron ports for each port to boot the servicing ramdisk.

        :param task: a TaskManager instance.
        :returns: a dictionary in the form {port.uuid: neutron_port['id']}
        """
        return self._add_network(
            task, self.get_servicing_network_uuid(task),
            CONF.neutron.servicing_network_security_groups,
            'servicing')

    def remove_servicing_network(self, task):
        """Deletes neutron port created for booting the servicing ramdisk.

        :param task: a TaskManager instance.
        :raises: NetworkError
        """
        return self._remove_network(
            task, self.get_servicing_network_uuid(task), 'servicing')
