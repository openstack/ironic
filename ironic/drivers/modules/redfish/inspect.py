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
Redfish Inspect Interface
"""

from oslo_log import log
from oslo_utils import importutils
from oslo_utils import units

from ironic.common import boot_modes
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.drivers import base
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.drivers import utils as drivers_utils
from ironic import objects

LOG = log.getLogger(__name__)

sushy = importutils.try_import('sushy')

if sushy:
    CPU_ARCH_MAP = {
        sushy.PROCESSOR_ARCH_x86: 'x86_64',
        sushy.PROCESSOR_ARCH_IA_64: 'ia64',
        sushy.PROCESSOR_ARCH_ARM: 'arm',
        sushy.PROCESSOR_ARCH_MIPS: 'mips',
        sushy.PROCESSOR_ARCH_OEM: 'oem'
    }

    PROCESSOR_INSTRUCTION_SET_MAP = {
        sushy.InstructionSet.ARM_A32: 'arm',
        sushy.InstructionSet.ARM_A64: 'aarch64',
        sushy.InstructionSet.IA_64: 'ia64',
        sushy.InstructionSet.MIPS32: 'mips',
        sushy.InstructionSet.MIPS64: 'mips64',
        sushy.InstructionSet.OEM: None,
        sushy.InstructionSet.X86: 'i686',
        sushy.InstructionSet.X86_64: 'x86_64'
    }

    BOOT_MODE_MAP = {
        sushy.BOOT_SOURCE_MODE_UEFI: boot_modes.UEFI,
        sushy.BOOT_SOURCE_MODE_BIOS: boot_modes.LEGACY_BIOS
    }


class RedfishInspect(base.InspectInterface):

    def __init__(self):
        """Initialize the Redfish inspection interface.

        :raises: DriverLoadError if the driver can't be loaded due to
            missing dependencies
        """
        super(RedfishInspect, self).__init__()
        if not sushy:
            raise exception.DriverLoadError(
                driver='redfish',
                reason=_('Unable to import the sushy library'))

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return redfish_utils.COMMON_PROPERTIES.copy()

    def validate(self, task):
        """Validate the driver-specific Node deployment info.

        This method validates whether the 'driver_info' properties of
        the task's node contains the required information for this
        interface to function.

        This method is often executed synchronously in API requests, so it
        should not conduct long-running checks.

        :param task: A TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue on malformed parameter(s)
        :raises: MissingParameterValue on missing parameter(s)
        """
        redfish_utils.parse_driver_info(task.node)

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
        system = redfish_utils.get_system(task.node)

        # get the essential properties and update the node properties
        # with it.
        inspected_properties = task.node.properties
        inventory = {}

        if system.memory_summary and system.memory_summary.size_gib:
            memory = system.memory_summary.size_gib * units.Ki
            inspected_properties['memory_mb'] = memory
            inventory['memory'] = {'physical_mb': memory}

        self._get_processor_info(task, system, inspected_properties, inventory)

        # TODO(etingof): should we respect root device hints here?
        local_gb = self._detect_local_gb(task, system)

        if local_gb:
            inspected_properties['local_gb'] = str(local_gb)

        else:
            LOG.warning("Could not provide a valid storage size configured "
                        "for node %(node)s. Assuming this is a disk-less node",
                        {'node': task.node.uuid})
            inspected_properties['local_gb'] = '0'

        if storages := system.storage or system.simple_storage:
            disks = list()
            for storage in storages.get_members():
                drives = storage.drives if hasattr(
                    storage, 'drives') else storage.devices
                for drive in drives:
                    disk = {}
                    disk['name'] = drive.name
                    disk['size'] = drive.capacity_bytes
                    disks.append(disk)

            inventory['disks'] = disks

        if system.ethernet_interfaces and system.ethernet_interfaces.summary:
            inventory['interfaces'] = []
            mac_addresses = list(system.ethernet_interfaces.summary.keys())
            for mac_address in mac_addresses:
                inventory['interfaces'].append({'mac_address': mac_address})

        system_vendor = {}
        if system.name:
            system_vendor['product_name'] = str(system.name)

        if system.serial_number:
            system_vendor['serial_number'] = str(system.serial_number)

        if system.manufacturer:
            system_vendor['manufacturer'] = str(system.manufacturer)

        if system_vendor:
            inventory['system_vendor'] = system_vendor

        if system.boot.mode:
            if not drivers_utils.get_node_capability(task.node, 'boot_mode'):
                capabilities = utils.get_updated_capabilities(
                    inspected_properties.get('capabilities', ''),
                    {'boot_mode': BOOT_MODE_MAP[system.boot.mode]})

                inspected_properties['capabilities'] = capabilities
            inventory['boot'] = {'current_boot_mode':
                                 BOOT_MODE_MAP[system.boot.mode]}

        valid_keys = self.ESSENTIAL_PROPERTIES
        missing_keys = valid_keys - set(inspected_properties)
        if missing_keys:
            error = (_('Failed to discover the following properties: '
                       '%(missing_keys)s on node %(node)s'),
                     {'missing_keys': ', '.join(missing_keys),
                      'node': task.node.uuid})
            raise exception.HardwareInspectionFailure(error=error)

        task.node.properties = inspected_properties
        task.node.save()

        LOG.debug("Node properties for %(node)s are updated as "
                  "%(properties)s", {'properties': inspected_properties,
                                     'node': task.node.uuid})

        self._create_ports(task, system)

        pxe_port_macs = self._get_pxe_port_macs(task)
        if pxe_port_macs is None:
            LOG.warning("No PXE enabled NIC was found for node "
                        "%(node_uuid)s.", {'node_uuid': task.node.uuid})
        else:
            pxe_port_macs = [macs.lower() for macs in pxe_port_macs]

            ports = objects.Port.list_by_node_id(task.context, task.node.id)
            if ports:
                for port in ports:
                    is_baremetal_pxe_port = (port.address.lower()
                                             in pxe_port_macs)
                    if port.pxe_enabled != is_baremetal_pxe_port:
                        port.pxe_enabled = is_baremetal_pxe_port
                        port.save()
                        LOG.info('Port %(port)s having %(mac_address)s '
                                 'updated with pxe_enabled %(pxe)s for '
                                 'node %(node_uuid)s during inspection',
                                 {'port': port.uuid,
                                  'mac_address': port.address,
                                  'pxe': port.pxe_enabled,
                                  'node_uuid': task.node.uuid})
            else:
                LOG.warning("No port information discovered "
                            "for node %(node)s", {'node': task.node.uuid})

        inspect_utils.store_inspection_data(task.node,
                                            inventory, None, task.context)
        return states.MANAGEABLE

    def _create_ports(self, task, system):
        enabled_macs = redfish_utils.get_enabled_macs(task, system)
        if enabled_macs:
            inspect_utils.create_ports_if_not_exist(task, list(enabled_macs))
        else:
            LOG.warning("Not attempting to create any port as no NICs "
                        "were discovered in 'enabled' state for node "
                        "%(node)s: %(mac_data)s",
                        {'mac_data': enabled_macs, 'node': task.node.uuid})

    def _detect_local_gb(self, task, system):
        simple_storage_size = 0

        try:
            LOG.debug("Attempting to discover system simple storage size for "
                      "node %(node)s", {'node': task.node.uuid})
            if (system.simple_storage
                    and system.simple_storage.disks_sizes_bytes):
                simple_storage_size = [
                    size for size in system.simple_storage.disks_sizes_bytes
                    if size >= 4 * units.Gi
                ] or [0]

                simple_storage_size = simple_storage_size[0]

        except sushy.exceptions.SushyError as ex:
            LOG.debug("No simple storage information discovered "
                      "for node %(node)s: %(err)s", {'node': task.node.uuid,
                                                     'err': ex})

        storage_size = 0

        try:
            LOG.debug("Attempting to discover system storage volume size for "
                      "node %(node)s", {'node': task.node.uuid})
            if system.storage and system.storage.volumes_sizes_bytes:
                storage_size = [
                    size for size in system.storage.volumes_sizes_bytes
                    if size >= 4 * units.Gi
                ] or [0]

                storage_size = storage_size[0]

        except sushy.exceptions.SushyError as ex:
            LOG.debug("No storage volume information discovered "
                      "for node %(node)s: %(err)s", {'node': task.node.uuid,
                                                     'err': ex})

        try:
            if not storage_size:
                LOG.debug("Attempting to discover system storage drive size "
                          "for node %(node)s", {'node': task.node.uuid})
                if system.storage and system.storage.drives_sizes_bytes:
                    storage_size = [
                        size for size in system.storage.drives_sizes_bytes
                        if size >= 4 * units.Gi
                    ] or [0]

                    storage_size = storage_size[0]

        except sushy.exceptions.SushyError as ex:
            LOG.debug("No storage drive information discovered "
                      "for node %(node)s: %(err)s", {'node': task.node.uuid,
                                                     'err': ex})

        # NOTE(etingof): pick the smallest disk larger than 4G among available
        if simple_storage_size and storage_size:
            local_gb = min(simple_storage_size, storage_size)

        else:
            local_gb = max(simple_storage_size, storage_size)

        # Note(deray): Convert the received size to GiB and reduce the
        # value by 1 GB as consumers like Ironic requires the ``local_gb``
        # to be returned 1 less than actual size.
        return max(0, int(local_gb / units.Gi - 1))

    def _get_pxe_port_macs(self, task):
        """Get a list of PXE port MAC addresses.

        :param task: a TaskManager instance.
        :returns: Returns list of PXE port MAC addresses.
                  If cannot be determined, returns None.
        """
        return None

    def _get_processor_info(self, task, system, inspected_properties,
                            inventory):
        if system.processors is None:
            return

        cpu = {}
        if system.processors.summary:
            cpus, arch = system.processors.summary
            if cpus:
                inspected_properties['cpus'] = cpus
                cpu['count'] = cpus
            if arch:
                try:
                    inspected_properties['cpu_arch'] = CPU_ARCH_MAP[arch]
                except KeyError:
                    LOG.warning("Unknown CPU arch %(arch)s discovered "
                                "for node %(node)s", {'node': task.node.uuid,
                                                      'arch': arch})

        processor = system.processors.get_members()[0]

        if processor.model is not None:
            cpu['model_name'] = str(processor.model)
        if processor.max_speed_mhz is not None:
            cpu['frequency'] = processor.max_speed_mhz
        if processor.instruction_set is not None:
            cpu['architecture'] = PROCESSOR_INSTRUCTION_SET_MAP[
                processor.instruction_set]

        inventory['cpu'] = cpu
