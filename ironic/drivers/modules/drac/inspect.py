#
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

"""
DRAC inspection interface
"""
from ironic.common import boot_modes
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import inspect as redfish_inspect
from ironic.drivers.modules.redfish import utils as redfish_utils
from oslo_log import log


_PXE_DEV_ENABLED_INTERFACES = [('PxeDev1EnDis', 'PxeDev1Interface'),
                               ('PxeDev2EnDis', 'PxeDev2Interface'),
                               ('PxeDev3EnDis', 'PxeDev3Interface'),
                               ('PxeDev4EnDis', 'PxeDev4Interface')]
_BIOS_ENABLED_VALUE = 'Enabled'
LOG = log.getLogger(__name__)

class DracRedfishInspect(redfish_inspect.RedfishInspect):
    """iDRAC Redfish interface for inspection-related actions."""

    def inspect_hardware(self, task):
        """Inspect hardware to get the hardware properties.

        Inspects hardware to get the essential properties.
        It fails if any of the essential properties
        are not received from the node.

        :param task: a TaskManager instance.
        :raises: HardwareInspectionFailure if essential properties
                 could not be retrieved successfully.
        :returns: The resulting state of inspection.

        """
        # Ensure we create a port for every NIC port found for consistency
        # with our previous WSMAN inspect behavior and to work around a bug
        # in some versions of the firmware where the port state is not being
        # reported correctly.

        ethernet_interfaces_mac = list(self._get_mac_address(task).values())
        inspect_utils.create_ports_if_not_exist(task, ethernet_interfaces_mac)
        return super(DracRedfishInspect, self).inspect_hardware(task)

    def _get_mac_address(self, task):
        """Get a list of MAC addresses

        :param task: a TaskManager instance.
        :returns: a mapping of interface identities to MAC addresses.
        """
        system = redfish_utils.get_system(task.node)
        # Get dictionary of ethernet interfaces
        if system.ethernet_interfaces and system.ethernet_interfaces.summary:
            ethernet_interfaces = system.ethernet_interfaces.get_members()
            ethernet_interfaces_mac = {
                interface.identity: interface.mac_address
                for interface in ethernet_interfaces}
            return ethernet_interfaces_mac
        else:
            return {}

    def _get_pxe_port_macs(self, task):
        """Get a list of PXE port MAC addresses.

        :param task: a TaskManager instance.
        :returns: Returns list of PXE port MAC addresses.
        """
        system = redfish_utils.get_system(task.node)
        ethernet_interfaces_mac = self._get_mac_address(task)
        pxe_port_macs = []

        if system.boot.mode == boot_modes.UEFI:
            # When a server is in UEFI boot mode, the PXE NIC ports are
            # stored in the PxeDevXEnDis and PxeDevXInterface BIOS
            # settings. Get the PXE NIC ports from these settings and
            # their MAC addresses.
            for param, nic in _PXE_DEV_ENABLED_INTERFACES:
                if system.bios.attributes[param] == _BIOS_ENABLED_VALUE:
                    nic_id = system.bios.attributes[nic]
                    # Get MAC address of the given nic_id
                    mac_address = ethernet_interfaces_mac[nic_id]
                    pxe_port_macs.append(mac_address)
        elif system.boot.mode == boot_modes.LEGACY_BIOS:
            # When a server is in BIOS boot mode, whether or not a
            # NIC port is set to PXE boot is stored on the NIC port
            # itself internally to the BMC. Getting this information
            # requires using an OEM extension to export the system
            # configuration, as the redfish standard does not specify
            # how to get it, and Dell does not have OEM redfish calls
            # to selectively retrieve it at this time.
            # Get instance of Sushy OEM manager object
            pxe_port_macs_list = drac_utils.execute_oem_manager_method(
                task, 'get PXE port MAC addresses',
                lambda m: m.get_pxe_port_macs_bios(ethernet_interfaces_mac))
            pxe_port_macs = [mac for mac in pxe_port_macs_list]

        return pxe_port_macs

    def _collect_lldp_data(self, task, system):
        """Collect LLDP data using Dell OEM SwitchConnection endpoints.

        Dell iDRAC provides LLDP neighbor information through OEM
        DellSwitchConnection endpoints. We return parsed LLDP data directly.

        :param task: A TaskManager instance
        :param system: Sushy system object
        :returns: Dict mapping interface names to parsed LLDP data
        """
        parsed_lldp = {}

        try:
            # Get Dell switch connection data
            switch_data = self._get_dell_switch_connections(task)

            # Convert directly to parsed LLDP format
            for connection in switch_data:
                # FQDD is Fully Qualified Device Descriptor (Dell term)
                # Example: NIC.Integrated.1-1-1
                fqdd = connection.get('FQDD')
                switch_mac = connection.get('SwitchConnectionID')
                switch_port = connection.get('SwitchPortConnectionID')

                # Skip unconnected interfaces
                if (not fqdd or not switch_mac or not switch_port
                    or switch_mac == 'No Link' or switch_port == 'No Link'):
                    continue

                parsed_lldp[fqdd] = {
                    'switch_chassis_id': switch_mac,
                    'switch_port_id': switch_port
                }

            LOG.debug("Generated parsed LLDP data for %d interfaces",
                      len(parsed_lldp))

        except Exception as e:
            LOG.debug("Dell OEM LLDP collection failed, falling back to "
                      "standard: %s", e)
            # Fallback to standard Redfish LLDP collection
            return super(DracRedfishInspect, self)._collect_lldp_data(
                task, system)

        return parsed_lldp

    def _get_dell_switch_connections(self, task):
        """Fetch Dell switch connection data via OEM.

        :param task: A TaskManager instance
        :returns: List of switch connection dictionaries
        """
        system = redfish_utils.get_system(task.node)

        # Access Sushy's private connection object
        try:
            conn = system._conn
            base_url = conn._url
        except AttributeError as e:
            LOG.debug("Failed to access Sushy connection object: %s", e)
            return []

        # Dell OEM endpoint for switch connections
        # This URL structure is specific to Dell iDRAC Redfish implementation
        switch_url = (f"{base_url}/redfish/v1/Systems/{system.identity}"
                      "/NetworkPorts/Oem/Dell/DellSwitchConnections")

        LOG.debug("Fetching Dell switch connections from: %s", switch_url)

        try:
            response = conn.get(switch_url)
            data = response.json()
            members = data.get('Members', [])
            LOG.debug("Retrieved %d Dell switch connections", len(members))
            return members
        except Exception as e:
            LOG.debug("Failed to get Dell switch connections: %s", e)
            return []
