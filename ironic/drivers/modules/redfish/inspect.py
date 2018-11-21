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

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.drivers import base
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import utils as redfish_utils

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

        if system.memory_summary and system.memory_summary.size_gib:
            inspected_properties['memory_mb'] = str(
                system.memory_summary.size_gib * units.Ki)

        if system.processors and system.processors.summary:
            cpus, arch = system.processors.summary
            if cpus:
                inspected_properties['cpus'] = cpus

            if arch:
                try:
                    inspected_properties['cpu_arch'] = CPU_ARCH_MAP[arch]

                except KeyError:
                    LOG.warning("Unknown CPU arch %(arch)s discovered "
                                "for node %(node)s", {'node': task.node.uuid,
                                                      'arch': arch})

        simple_storage_size = 0

        try:
            if (system.simple_storage and
                    system.simple_storage.disks_sizes_bytes):
                simple_storage_size = [
                    size for size in system.simple_storage.disks_sizes_bytes
                    if size >= 4 * units.Gi
                ] or [0]

                simple_storage_size = simple_storage_size[0]

        except sushy.SushyError as ex:
            LOG.debug("No simple storage information discovered "
                      "for node %(node)s: %(err)s", {'node': task.node.uuid,
                                                     'err': ex})

        storage_size = 0

        try:
            if system.storage and system.storage.volumes_sizes_bytes:
                storage_size = [
                    size for size in system.storage.volumes_sizes_bytes
                    if size >= 4 * units.Gi
                ] or [0]

                storage_size = storage_size[0]

        except sushy.SushyError as ex:
            LOG.debug("No storage volume information discovered "
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
        local_gb = max(0, int(local_gb / units.Gi - 1))

        # TODO(etingof): should we respect root device hints here?

        if local_gb:
            inspected_properties['local_gb'] = str(local_gb)

        else:
            LOG.warning("Could not provide a valid storage size configured "
                        "for node %(node)s", {'node': task.node.uuid})

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

        if (system.ethernet_interfaces and
                system.ethernet_interfaces.eth_summary):
            macs = system.ethernet_interfaces.eth_summary

            # Create ports for the nics detected.
            inspect_utils.create_ports_if_not_exist(task, macs)

        else:
            LOG.warning("No NIC information discovered "
                        "for node %(node)s", {'node': task.node.uuid})

        return states.MANAGEABLE
