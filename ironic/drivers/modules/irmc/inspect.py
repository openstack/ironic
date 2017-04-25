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
from ironic_lib import metrics_utils
from oslo_log import log as logging
from oslo_utils import importutils

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common import states
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


def _inspect_hardware(node):
    """Inspect the node and get hardware information.

    :param node: node object.
    :raises: HardwareInspectionFailure, if unable to get essential
             hardware properties.
    :returns: a pair of dictionary and list, the dictionary contains
              keys as in IRMCInspect.ESSENTIAL_PROPERTIES and its inspected
              values, the list contains mac addresses.
    """
    try:
        report = irmc_common.get_irmc_report(node)
        props = scci.get_essential_properties(
            report, IRMCInspect.ESSENTIAL_PROPERTIES)
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
        (props, macs) = _inspect_hardware(node)
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
        return states.MANAGEABLE
