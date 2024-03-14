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

import binascii

from construct import core
import netaddr
from oslo_log import log as logging

from ironic.common import exception
from ironic.drivers.modules.inspector.hooks import base
from ironic.drivers.modules.inspector import lldp_tlvs as tlv
import ironic.objects.port as ironic_port


LOG = logging.getLogger(__name__)
PORT_ID_ITEM_NAME = "port_id"
SWITCH_ID_ITEM_NAME = "switch_id"


class LocalLinkConnectionHook(base.InspectionHook):
    """Hook to process mandatory LLDP packet fields"""

    dependencies = ['validate-interfaces']

    def _get_local_link_patch(self, lldp_data, port, node_uuid):
        local_link_connection = {}

        for tlv_type, tlv_value in lldp_data:
            try:
                data = bytearray(binascii.unhexlify(tlv_value))
            except binascii.Error:
                LOG.warning('TLV value for TLV type %d is not in correct '
                            'format. Ensure that the TLV value is in '
                            'hexadecimal format when sent to ironic. Node: %s',
                            tlv_type, node_uuid)
                return

            item = value = None
            if tlv_type == tlv.LLDP_TLV_PORT_ID:
                try:
                    port_id = tlv.PortId.parse(data)
                except (core.MappingError, netaddr.AddrFormatError) as e:
                    LOG.warning('TLV parse error for Port ID for node %s: %s',
                                node_uuid, e)
                    return

                item = PORT_ID_ITEM_NAME
                value = port_id.value.value if port_id.value else None
            elif tlv_type == tlv.LLDP_TLV_CHASSIS_ID:
                try:
                    chassis_id = tlv.ChassisId.parse(data)
                except (core.MappingError, netaddr.AddrFormatError) as e:
                    LOG.warning('TLV parse error for Chassis ID for node %s: '
                                '%s', node_uuid, e)
                    return

                # Only accept mac address for chassis ID
                if 'mac_address' in chassis_id.subtype:
                    item = SWITCH_ID_ITEM_NAME
                    value = chassis_id.value.value

            if item is None or value is None:
                continue
            if item in port.local_link_connection:
                continue
            local_link_connection[item] = value

        try:
            LOG.debug('Updating port %s for node %s', port.address, node_uuid)
            for item in local_link_connection:
                port.set_local_link_connection(item,
                                               local_link_connection[item])
            port.save()
        except exception.IronicException as e:
            LOG.warning('Failed to update port %(uuid)s for node %(node)s. '
                        'Error: %(error)s', {'uuid': port.id,
                                             'node': node_uuid,
                                             'error': e})

    def __call__(self, task, inventory, plugin_data):
        """Process LLDP data and patch Ironic port local link connection.

        Process the non-vendor-specific LLDP packet fields for each NIC found
        for a baremetal node, port ID and chassis ID. These fields, if found
        and if valid, will be saved into the local link connection information
        (port id and switch id) fields on the Ironic port that represents that
        NIC.
        """
        lldp_raw = plugin_data.get('lldp_raw') or {}

        for iface in inventory['interfaces']:
            # The all_interfaces field in plugin_data is provided by the
            # validate-interfaces hook, so it is a dependency for this hook (?)
            if iface['name'] not in plugin_data.get('all_interfaces'):
                continue

            mac_address = iface['mac_address']
            port = ironic_port.Port.get_by_address(task.context, mac_address)
            if not port:
                LOG.debug('Skipping LLDP processing for interface %s of node '
                          '%s: matching port not found in Ironic.',
                          mac_address, task.node.uuid)
                continue

            lldp_data = lldp_raw.get(iface['name']) or iface.get('lldp')
            if lldp_data is None:
                LOG.warning('No LLDP data found for interface %s of node %s',
                            mac_address, task.node.uuid)
                continue

            # Parse raw lldp data
            self._get_local_link_patch(lldp_data, port, task.node.uuid)
