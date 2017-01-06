# Copyright 2015 FUJITSU LIMITED
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
iRMC Inspect Interface
"""
import re

from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
from ironic.common import utils
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules.irmc import common as irmc_common
from ironic.drivers.modules import snmp
from ironic import objects

scci = importutils.try_import('scciclient.irmc.scci')

LOG = logging.getLogger(__name__)

METRICS = metrics_utils.get_metrics_logger(__name__)

"""
SC2.mib: sc2UnitNodeClass returns NIC type.

sc2UnitNodeClass OBJECT-TYPE
 SYNTAX       INTEGER
 {
 unknown(1),
 primary(2),
 secondary(3),
 management-blade(4),
 secondary-remote(5),
 secondary-remote-backup(6),
 baseboard-controller(7)
 }
 ACCESS       read-only
 STATUS       mandatory
 DESCRIPTION  "Management node class:
 primary:                 local operating system interface
 secondary:               local management controller LAN interface
 management-blade:        management blade interface (in a blade server
 chassis)
 secondary-remote:        remote management controller (in an RSB
 concentrator environment)
 secondary-remote-backup: backup remote management controller
 baseboard-controller:    local baseboard management controller (BMC)"
 ::= { sc2ManagementNodes 8 }
"""

NODE_CLASS_OID_VALUE = {
    'unknown': 1,
    'primary': 2,
    'secondary': 3,
    'management-blade': 4,
    'secondary-remote': 5,
    'secondary-remote-backup': 6,
    'baseboard-controller': 7
}

NODE_CLASS_OID = '1.3.6.1.4.1.231.2.10.2.2.10.3.1.1.8.1'

"""
SC2.mib: sc2UnitNodeMacAddress returns NIC MAC address

sc2UnitNodeMacAddress OBJECT-TYPE
 SYNTAX       PhysAddress
 ACCESS       read-only
 STATUS       mandatory
 DESCRIPTION  "Management node hardware (MAC) address"
 ::= { sc2ManagementNodes 9 }
"""

MAC_ADDRESS_OID = '1.3.6.1.4.1.231.2.10.2.2.10.3.1.1.9.1'
CAPABILITIES_PROPERTIES = {'trusted_boot', 'irmc_firmware_version',
                           'rom_firmware_version', 'server_model',
                           'pci_gpu_devices'}


def _get_mac_addresses(node):
    """Get mac addresses of the node.

    :param node: node object.
    :raises: SNMPFailure if SNMP operation failed.
    :returns: a list of mac addresses.
    """
    d_info = irmc_common.parse_driver_info(node)
    snmp_client = snmp.SNMPClient(d_info['irmc_address'],
                                  d_info['irmc_snmp_port'],
                                  d_info['irmc_snmp_version'],
                                  d_info['irmc_snmp_community'],
                                  d_info['irmc_snmp_security'])

    node_classes = snmp_client.get_next(NODE_CLASS_OID)
    mac_addresses = [':'.join(['%02x' % ord(x) for x in mac])
                     for mac in snmp_client.get_next(MAC_ADDRESS_OID)]

    return [a for c, a in zip(node_classes, mac_addresses)
            if c == NODE_CLASS_OID_VALUE['primary']]


def _inspect_hardware(node, **kwargs):
    """Inspect the node and get hardware information.

    :param node: node object.
    :param kwargs: the dictionary of additional parameters.
    :raises: HardwareInspectionFailure, if unable to get essential
             hardware properties.
    :returns: a pair of dictionary and list, the dictionary contains
              keys as in IRMCInspect.ESSENTIAL_PROPERTIES and its inspected
              values, the list contains mac addresses.
    """
    capabilities_props = set(CAPABILITIES_PROPERTIES)

    # Remove all capabilities item which will be inspected in the existing
    # capabilities of node
    if 'capabilities' in node.properties:
        existing_cap = node.properties['capabilities'].split(',')
        for item in capabilities_props:
            for prop in existing_cap:
                if item == prop.split(':')[0]:
                    existing_cap.remove(prop)
        node.properties['capabilities'] = ",".join(existing_cap)

    # get gpu_ids in ironic configuration
    values = [gpu_id.lower() for gpu_id in CONF.irmc.gpu_ids]

    # if gpu_ids = [], pci_gpu_devices will not be inspected
    if len(values) == 0:
        capabilities_props.remove('pci_gpu_devices')

    try:
        report = irmc_common.get_irmc_report(node)
        props = scci.get_essential_properties(
            report, IRMCInspect.ESSENTIAL_PROPERTIES)
        d_info = irmc_common.parse_driver_info(node)
        capabilities = scci.get_capabilities_properties(
            d_info,
            capabilities_props,
            values,
            **kwargs)
        if capabilities:
            if capabilities.get('pci_gpu_devices') == 0:
                capabilities.pop('pci_gpu_devices')
            if capabilities.get('trusted_boot') is False:
                capabilities.pop('trusted_boot')
            capabilities = utils.get_updated_capabilities(
                node.properties.get('capabilities'), capabilities)
            if capabilities:
                props['capabilities'] = capabilities
        macs = _get_mac_addresses(node)
    except (scci.SCCIInvalidInputError,
            scci.SCCIClientError,
            exception.SNMPFailure) as e:
        error = (_("Inspection failed for node %(node_id)s "
                   "with the following error: %(error)s") %
                 {'node_id': node.uuid, 'error': e})
        raise exception.HardwareInspectionFailure(error=error)

    return (props, macs)


class IRMCInspect(base.InspectInterface):
    """Interface for out of band inspection."""

    def __init__(self):
        """Validate the driver-specific inspection information.

        This action will validate gpu_ids value along with starting
        ironic-conductor service.
        """
        for gpu_id in CONF.irmc.gpu_ids:
            if not re.match('^0x[0-9a-f]{4}/0x[0-9a-f]{4}$', gpu_id.lower()):
                raise exception.InvalidParameterValue(_(
                    "Invalid [irmc]/gpu_ids configuration option."))

        super(IRMCInspect, self).__init__()

    def get_properties(self):
        """Return the properties of the interface.

        :returns: dictionary of <property name>:<property description> entries.
        """
        return irmc_common.COMMON_PROPERTIES

    @METRICS.timer('IRMCInspect.validate')
    def validate(self, task):
        """Validate the driver-specific inspection information.

        This method validates whether the 'driver_info' property of the
        supplied node contains the required information for this driver.

        :param task: a TaskManager instance containing the node to act on.
        :raises: InvalidParameterValue if required driver_info attribute
                 is missing or invalid on the node.
        :raises: MissingParameterValue if a required parameter is missing.
        """
        irmc_common.parse_driver_info(task.node)

    @METRICS.timer('IRMCInspect.inspect_hardware')
    def inspect_hardware(self, task):
        """Inspect hardware.

        Inspect hardware to obtain the essential hardware properties and
        mac addresses.

        :param task: a task from TaskManager.
        :raises: HardwareInspectionFailure, if hardware inspection failed.
        :returns: states.MANAGEABLE, if hardware inspection succeeded.
        """
        node = task.node
        kwargs = {}
        # Inspect additional capabilities task requires node with power on
        # status
        old_power_state = task.driver.power.get_power_state(task)
        if old_power_state == states.POWER_OFF:
            manager_utils.node_set_boot_device(task, boot_devices.BIOS, False)
            manager_utils.node_power_action(task, states.POWER_ON)

            LOG.info("The Node %(node_uuid)s being powered on for inspection",
                     {'node_uuid': task.node.uuid})

            kwargs['sleep_flag'] = True

        (props, macs) = _inspect_hardware(node, **kwargs)
        node.properties = dict(node.properties, **props)
        node.save()

        for mac in macs:
            try:
                new_port = objects.Port(task.context,
                                        address=mac, node_id=node.id)
                new_port.create()
                LOG.info("Port created for MAC address %(address)s "
                         "for node %(node_uuid)s during inspection",
                         {'address': mac, 'node_uuid': node.uuid})
            except exception.MACAlreadyExists:
                LOG.warning("Port already existed for MAC address "
                            "%(address)s for node %(node_uuid)s "
                            "during inspection",
                            {'address': mac, 'node_uuid': node.uuid})

        LOG.info("Node %s inspected", node.uuid)
        # restore old power state
        if old_power_state == states.POWER_OFF:
            manager_utils.node_power_action(task, states.POWER_OFF)

            LOG.info("The Node %(node_uuid)s being powered off after "
                     "inspection",
                     {'node_uuid': task.node.uuid})

        return states.MANAGEABLE
