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

"""LLDP Processing Hook for basic TLVs"""

import binascii

from oslo_log import log as logging

from ironic.drivers.modules.inspector.hooks import base
from ironic.drivers.modules.inspector import lldp_parsers


LOG = logging.getLogger(__name__)


class ParseLLDPHook(base.InspectionHook):
    """Process LLDP packet fields and store them in plugin_data['parsed_lldp']

    Convert binary LLDP information into a readable form. Loop through raw
    LLDP TLVs and parse those from the basic management, 802.1, and 802.3 TLV
    sets. Store parsed data in the plugin_data as a new parsed_lldp dictionary
    with interface names as keys.
    """

    def _parse_lldp_tlvs(self, tlvs, node_uuid):
        """Parse LLDP TLVs into a dictionary of name/value pairs

        :param tlvs: List of raw TLVs
        :param node_uuid: UUID of the node being inspected
        :returns: Dictionary of name/value pairs. The LLDP user-friendly
                  names, e.g. "switch_port_id" are the keys.
        """
        # Generate name/value pairs for each TLV supported by this plugin.
        parser = lldp_parsers.LLDPBasicMgmtParser(node_uuid)

        for tlv_type, tlv_value in tlvs:
            try:
                data = bytearray(binascii.a2b_hex(tlv_value))
            except TypeError as e:
                LOG.warning(
                    'TLV value for TLV type %(tlv_type)d is not in correct '
                    'format, value must be in hexadecimal: %(msg)s. Node: '
                    '%(node)s', {'tlv_type': tlv_type, 'msg': e,
                                 'node': node_uuid})
                continue

            try:
                parsed_tlv = parser.parse_tlv(tlv_type, data)
            except UnicodeDecodeError as e:
                LOG.warning("LLDP TLV type %(tlv_type)d from Node '%(node)s' "
                            "can't be decoded: %(exc)s",
                            {'tlv_type': tlv_type, 'exc': e,
                             'node': node_uuid})
                continue

            if parsed_tlv:
                LOG.debug("Handled TLV type %d. Node: %s", tlv_type, node_uuid)
            else:
                LOG.debug("LLDP TLV type %d not handled. Node: %s", tlv_type,
                          node_uuid)
        return parser.nv_dict

    def __call__(self, task, inventory, plugin_data):
        """Process LLDP data and update plugin_data with processed data"""

        lldp_raw = plugin_data.get('lldp_raw') or {}

        for interface in inventory['interfaces']:
            if_name = interface['name']
            tlvs = lldp_raw.get(if_name) or interface.get('lldp')
            if tlvs is None:
                LOG.warning("No LLDP Data found for interface %s of node %s",
                            if_name, task.node.uuid)
                continue

            LOG.debug("Processing LLDP Data for interface %s of node %s",
                      if_name, task.node.uuid)

            # Store LLDP data per interface in plugin_data[parsed_lldp]
            nv = self._parse_lldp_tlvs(tlvs, task.node.uuid)
            if nv:
                if plugin_data.get('parsed_lldp'):
                    plugin_data['parsed_lldp'].update({if_name: nv})
                else:
                    plugin_data['parsed_lldp'] = {if_name: nv}
