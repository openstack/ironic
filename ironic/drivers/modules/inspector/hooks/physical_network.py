# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Port Physical Network Hook"""

import ipaddress

from oslo_config import cfg
from oslo_log import log as logging

from ironic.drivers.modules.inspector.hooks import base
from ironic import objects

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PhysicalNetworkHook(base.InspectionHook):
    """Hook to set the port's physical_network field.

    Set the ironic port's physical_network field based on a CIDR to physical
    network mapping in the configuration.
    """

    dependencies = ['validate-interfaces']

    def get_physical_network(self, interface):
        """Return a physical network to apply to an ironic port.

        :param interface: The interface from the inventory.
        :returns: The physical network to set, or None.
        """

        def get_interface_ips(iface):
            ips = []
            for addr_version in ['ipv4_address', 'ipv6_address']:
                try:
                    ips.append(ipaddress.ip_address(iface.get(addr_version)))
                except ValueError:
                    pass
            return ips

        # Convert list config to a dictionary with ip_networks as keys
        cidr_map = {
            ipaddress.ip_network(x.rsplit(':', 1)[0]): x.rsplit(':', 1)[1]
            for x in CONF.inspector.physical_network_cidr_map}
        ips = get_interface_ips(interface)
        for ip in ips:
            try:
                return [cidr_map[cidr] for cidr in cidr_map if ip in cidr][0]
            except IndexError:
                # This IP address is not present in the CIDR map
                pass
        # No mapping found for any of the IP addresses
        return None

    def __call__(self, task, inventory, plugin_data):
        """Process inspection data and patch the port's physical network."""

        node_ports = objects.Port.list_by_node_id(task.context, task.node.id)
        ports_dict = {p.address: p for p in node_ports}

        for interface in inventory['interfaces']:
            if interface['name'] not in plugin_data['all_interfaces']:
                continue

            mac_address = interface['mac_address']
            port = ports_dict.get(mac_address)
            if not port:
                LOG.debug("Skipping physical network processing for interface "
                          "%s on node %s - matching port not found in Ironic.",
                          mac_address, task.node.uuid)
                continue

            # Determine the physical network for this port, using the interface
            # IPs and CIDR map configuration.
            phys_network = self.get_physical_network(interface)
            if phys_network is None:
                LOG.debug("Skipping physical network processing for interface "
                          "%s on node %s - no physical network mapping.",
                          mac_address,
                          task.node.uuid)
                continue

            if getattr(port, 'physical_network', '') != phys_network:
                port.physical_network = phys_network
                port.save()
                LOG.debug('Updated physical_network of port %s to %s',
                          port.uuid, port.physical_network)
