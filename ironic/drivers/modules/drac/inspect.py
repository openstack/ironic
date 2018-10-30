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

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.drivers import base
from ironic.drivers.modules.drac import common as drac_common
from ironic import objects

drac_exceptions = importutils.try_import('dracclient.exceptions')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)


class DracInspect(base.InspectInterface):

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return drac_common.COMMON_PROPERTIES

    @METRICS.timer('DracInspect.validate')
    def validate(self, task):
        """Validate the driver-specific info supplied.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver to
        manage the node.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.

        """
        return drac_common.parse_driver_info(task.node)

    @METRICS.timer('DracInspect.inspect_hardware')
    def inspect_hardware(self, task):
        """Inspect hardware.

        Inspect hardware to obtain the essential & additional hardware
        properties.

        :param task: a TaskManager instance containing the node to act on.
        :raises: HardwareInspectionFailure, if unable to get essential
                 hardware properties.
        :returns: states.MANAGEABLE
        """

        node = task.node
        client = drac_common.get_drac_client(node)
        properties = {}

        try:
            properties['memory_mb'] = sum(
                [memory.size_mb for memory in client.list_memory()])
            cpus = client.list_cpus()
            if cpus:
                properties['cpus'] = sum(
                    [self._calculate_cpus(cpu) for cpu in cpus])
                properties['cpu_arch'] = 'x86_64' if cpus[0].arch64 else 'x86'

            virtual_disks = client.list_virtual_disks()
            root_disk = self._guess_root_disk(virtual_disks)
            if root_disk:
                properties['local_gb'] = int(root_disk.size_mb / units.Ki)
            else:
                physical_disks = client.list_physical_disks()
                root_disk = self._guess_root_disk(physical_disks)
                if root_disk:
                    properties['local_gb'] = int(
                        root_disk.size_mb / units.Ki)
        except drac_exceptions.BaseClientException as exc:
            LOG.error('DRAC driver failed to introspect node '
                      '%(node_uuid)s. Reason: %(error)s.',
                      {'node_uuid': node.uuid, 'error': exc})
            raise exception.HardwareInspectionFailure(error=exc)

        valid_keys = self.ESSENTIAL_PROPERTIES
        missing_keys = valid_keys - set(properties)
        if missing_keys:
            error = (_('Failed to discover the following properties: '
                       '%(missing_keys)s') %
                     {'missing_keys': ', '.join(missing_keys)})
            raise exception.HardwareInspectionFailure(error=error)

        node.properties = dict(node.properties, **properties)
        node.save()

        try:
            nics = client.list_nics()
        except drac_exceptions.BaseClientException as exc:
            LOG.error('DRAC driver failed to introspect node '
                      '%(node_uuid)s. Reason: %(error)s.',
                      {'node_uuid': node.uuid, 'error': exc})
            raise exception.HardwareInspectionFailure(error=exc)

        for nic in nics:
            try:
                port = objects.Port(task.context, address=nic.mac,
                                    node_id=node.id)
                port.create()
                LOG.info('Port created with MAC address %(mac)s '
                         'for node %(node_uuid)s during inspection',
                         {'mac': nic.mac, 'node_uuid': node.uuid})
            except exception.MACAlreadyExists:
                LOG.warning('Failed to create a port with MAC address '
                            '%(mac)s when inspecting the node '
                            '%(node_uuid)s because the address is already '
                            'registered',
                            {'mac': nic.mac, 'node_uuid': node.uuid})

        LOG.info('Node %s successfully inspected.', node.uuid)
        return states.MANAGEABLE

    def _guess_root_disk(self, disks, min_size_required_mb=4 * units.Ki):
        """Find a root disk.

        :param disks: list of disks.
        :param min_size_required_mb: minimum required size of the root disk in
                                     megabytes.
        :returns: root disk.
        """
        disks.sort(key=lambda disk: disk.size_mb)
        for disk in disks:
            if disk.size_mb >= min_size_required_mb:
                return disk

    def _calculate_cpus(self, cpu):
        """Find actual CPU count.

        :param cpu: Pass cpu.

        :returns: returns total cpu count.
        """
        if cpu.ht_enabled:
            return cpu.cores * 2
        else:
            return cpu.cores
