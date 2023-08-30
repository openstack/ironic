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

""" Names and mapping functions used to map LLDP TLVs to name/value pairs """

import binascii

from construct import core
import netaddr
from oslo_log import log as logging

from ironic.common.i18n import _
from ironic.drivers.modules.inspector import lldp_tlvs as tlv

LOG = logging.getLogger(__name__)


# Names used in name/value pair from parsed TLVs
LLDP_CHASSIS_ID_NM = 'switch_chassis_id'
LLDP_PORT_ID_NM = 'switch_port_id'
LLDP_PORT_DESC_NM = 'switch_port_description'
LLDP_SYS_NAME_NM = 'switch_system_name'
LLDP_SYS_DESC_NM = 'switch_system_description'
LLDP_SWITCH_CAP_NM = 'switch_capabilities'
LLDP_CAP_SUPPORT_NM = 'switch_capabilities_support'
LLDP_CAP_ENABLED_NM = 'switch_capabilities_enabled'
LLDP_MGMT_ADDRESSES_NM = 'switch_mgmt_addresses'
LLDP_PORT_VLANID_NM = 'switch_port_untagged_vlan_id'
LLDP_PORT_PROT_NM = 'switch_port_protocol'
LLDP_PORT_PROT_VLAN_ENABLED_NM = 'switch_port_protocol_vlan_enabled'
LLDP_PORT_PROT_VLAN_SUPPORT_NM = 'switch_port_protocol_vlan_support'
LLDP_PORT_PROT_VLANIDS_NM = 'switch_port_protocol_vlan_ids'
LLDP_PORT_VLANS_NM = 'switch_port_vlans'
LLDP_PROTOCOL_IDENTITIES_NM = 'switch_protocol_identities'
LLDP_PORT_MGMT_VLANID_NM = 'switch_port_management_vlan_id'
LLDP_PORT_LINK_AGG_NM = 'switch_port_link_aggregation'
LLDP_PORT_LINK_AGG_ENABLED_NM = 'switch_port_link_aggregation_enabled'
LLDP_PORT_LINK_AGG_SUPPORT_NM = 'switch_port_link_aggregation_support'
LLDP_PORT_LINK_AGG_ID_NM = 'switch_port_link_aggregation_id'
LLDP_PORT_MAC_PHY_NM = 'switch_port_mac_phy_config'
LLDP_PORT_LINK_AUTONEG_ENABLED_NM = 'switch_port_autonegotiation_enabled'
LLDP_PORT_LINK_AUTONEG_SUPPORT_NM = 'switch_port_autonegotiation_support'
LLDP_PORT_CAPABILITIES_NM = 'switch_port_physical_capabilities'
LLDP_PORT_MAU_TYPE_NM = 'switch_port_mau_type'
LLDP_MTU_NM = 'switch_port_mtu'


class LLDPParser(object):
    """Base class to handle parsing of LLDP TLVs

    Each class that inherits from this base class must provide a parser map.
    Parser maps are used to associate a LLDP TLV with a function handler and
    arguments necessary to parse the TLV and generate one or more name/value
    pairs. Each LLDP TLV maps to a tuple with the following fields:

    function - Handler function to generate name/value pairs

    construct - Name of construct definition for TLV

    name - User-friendly name of TLV. For TLVs that generate only one
    name/value pair, this is the name used

    len_check - Boolean indicating if length check should be done on construct

    It is valid to have a function handler of None, this is for TLVs that
    are not mapped to a name/value pair (e.g.LLDP_TLV_TTL).
    """

    def __init__(self, node_uuid, nv=None):
        """Create LLDPParser

        :param node_uuid - UUID of node being inspected
        :param nv - dictionary of name/value pairs to use
        """
        self.nv_dict = nv or {}
        self.node_uuid = node_uuid
        self.parser_map = {}

    def set_value(self, name, value):
        """Set name value pair in dictionary

        The value for a name should not be changed if it exists.
        """
        self.nv_dict.setdefault(name, value)

    def append_value(self, name, value):
        """Add value to a list mapped to name"""
        self.nv_dict.setdefault(name, []).append(value)

    def add_single_value(self, struct, name, data):
        """Add a single name/value pair to the nv dictionary"""
        self.set_value(name, struct.value)

    def add_nested_value(self, struct, name, data):
        """Add a single nested name/value pair to the dictionary"""
        self.set_value(name, struct.value.value)

    def parse_tlv(self, tlv_type, data):
        """Parse TLVs from mapping table

        This functions takes the TLV type and the raw data for this TLV and
        gets a tuple from the parser_map. The construct field in the tuple
        contains the construct lib definition of the TLV which can be parsed
        to access individual fields. Once the TLV is parsed, the handler
        function for each TLV will store the individual fields as name/value
        pairs in nv_dict.

        If the handler function does not exist, then no name/value pairs will
        be added to nv_dict, but since the TLV was handled, True will be
        returned.

        :param: tlv_type - type identifier for TLV
        :param: data - raw TLV value
        :returns: True if TLV in parser_map and data is valid, otherwise False.
        """

        s = self.parser_map.get(tlv_type)
        if not s:
            return False

        func = s[0]  # handler

        if not func:
            return True  # TLV is handled

        try:
            tlv_parser = s[1]
            name = s[2]
            check_len = s[3]
        except KeyError as e:
            LOG.warning("Key error in TLV table: %s. Node: %s", e,
                        self.node_uuid)
            return False

        # Some constructs require a length validation to ensure that the
        # proper number of bytes have been provided, for example when a
        # BitStruct is used.
        if check_len and (tlv_parser.sizeof() != len(data)):
            LOG.warning("Invalid data for %(name)s expected len %(expect)d, "
                        "got %(actual)d. Node: %(node)s",
                        {'name': name, 'expect': tlv_parser.sizeof(),
                         'actual': len(data), 'node': self.node_uuid})
            return False

        # Use the construct parser to parse the TLV so that its individual
        # fields can be accessed
        try:
            struct = tlv_parser.parse(data)
        except (core.ConstructError, netaddr.AddrFormatError) as e:
            LOG.warning("TLV parse error: %s. Node: %s", e, self.node_uuid)
            return False

        # Call functions with parsed structure
        try:
            func(struct, name, data)
        except ValueError as e:
            LOG.warning("TLV value error: %s. Node: %s", e, self.node_uuid)
            return False

        return True

    def add_dot1_link_aggregation(self, struct, name, data):
        """Add name/value pairs for TLV Dot1_LinkAggregationId

        This is in the base class since it can be used by both dot1 and dot3.
        """

        self.set_value(LLDP_PORT_LINK_AGG_ENABLED_NM,
                       struct.status.enabled)
        self.set_value(LLDP_PORT_LINK_AGG_SUPPORT_NM,
                       struct.status.supported)
        self.set_value(LLDP_PORT_LINK_AGG_ID_NM, struct.portid)


class LLDPBasicMgmtParser(LLDPParser):
    """Class to handle parsing of 802.1AB Basic Management set

    This class will also handle 802.1Q and 802.3 OUI TLVs.
    """
    def __init__(self, nv=None):
        super(LLDPBasicMgmtParser, self).__init__(nv)

        self.parser_map = {
            tlv.LLDP_TLV_CHASSIS_ID:
                (self.add_nested_value, tlv.ChassisId, LLDP_CHASSIS_ID_NM,
                 False),
            tlv.LLDP_TLV_PORT_ID:
                (self.add_nested_value, tlv.PortId, LLDP_PORT_ID_NM, False),
            tlv.LLDP_TLV_TTL: (None, None, None, False),
            tlv.LLDP_TLV_PORT_DESCRIPTION:
                (self.add_single_value, tlv.PortDesc, LLDP_PORT_DESC_NM,
                 False),
            tlv.LLDP_TLV_SYS_NAME:
                (self.add_single_value, tlv.SysName, LLDP_SYS_NAME_NM, False),
            tlv.LLDP_TLV_SYS_DESCRIPTION:
                (self.add_single_value, tlv.SysDesc, LLDP_SYS_DESC_NM, False),
            tlv.LLDP_TLV_SYS_CAPABILITIES:
                (self.add_capabilities, tlv.SysCapabilities,
                 LLDP_SWITCH_CAP_NM, True),
            tlv.LLDP_TLV_MGMT_ADDRESS:
                (self.add_mgmt_address, tlv.MgmtAddress,
                 LLDP_MGMT_ADDRESSES_NM, False),
            tlv.LLDP_TLV_ORG_SPECIFIC:
                (self.handle_org_specific_tlv, tlv.OrgSpecific, None, False),
            tlv.LLDP_TLV_END_LLDPPDU: (None, None, None, False)
        }

    def add_mgmt_address(self, struct, name, data):
        """Handle LLDP_TLV_MGMT_ADDRESS

        There can be multiple Mgmt Address TLVs, store in list.
        """
        if struct.address:
            self.append_value(name, struct.address)

    def _get_capabilities_list(self, caps):
        """Get capabilities from bit map"""
        cap_map = [
            (caps.repeater, 'Repeater'),
            (caps.bridge, 'Bridge'),
            (caps.wlan, 'WLAN'),
            (caps.router, 'Router'),
            (caps.telephone, 'Telephone'),
            (caps.docsis, 'DOCSIS cable device'),
            (caps.station, 'Station only'),
            (caps.cvlan, 'C-Vlan'),
            (caps.svlan, 'S-Vlan'),
            (caps.tpmr, 'TPMR')]

        return [cap for (bit, cap) in cap_map if bit]

    def add_capabilities(self, struct, name, data):
        """Handle LLDP_TLV_SYS_CAPABILITIES"""
        self.set_value(LLDP_CAP_SUPPORT_NM,
                       self._get_capabilities_list(struct.system))
        self.set_value(LLDP_CAP_ENABLED_NM,
                       self._get_capabilities_list(struct.enabled))

    def handle_org_specific_tlv(self, struct, name, data):
        """Handle Organizationally Unique ID TLVs

        This class supports 802.1Q and 802.3 OUI TLVs.

        See http://www.ieee802.org/1/pages/802.1Q-2014.html, Annex D
        and http://standards.ieee.org/about/get/802/802.3.html
        """
        oui = binascii.hexlify(struct.oui).decode()
        subtype = struct.subtype
        oui_data = data[4:]

        if oui == tlv.LLDP_802dot1_OUI:
            parser = LLDPdot1Parser(self.node_uuid, self.nv_dict)
            if parser.parse_tlv(subtype, oui_data):
                LOG.debug("Handled 802.1 subtype %d", subtype)
            else:
                LOG.debug("Subtype %d not found for 802.1", subtype)
        elif oui == tlv.LLDP_802dot3_OUI:
            parser = LLDPdot3Parser(self.node_uuid, self.nv_dict)
            if parser.parse_tlv(subtype, oui_data):
                LOG.debug("Handled 802.3 subtype %d", subtype)
            else:
                LOG.debug("Subtype %d not found for 802.3", subtype)
        else:
            LOG.warning("Organizationally Unique ID %s not recognized for "
                        "node %s", oui, self.node_uuid)


class LLDPdot1Parser(LLDPParser):
    """Class to handle parsing of 802.1Q TLVs"""
    def __init__(self, node_uuid, nv=None):
        super(LLDPdot1Parser, self).__init__(node_uuid, nv)

        self.parser_map = {
            tlv.dot1_PORT_VLANID:
                (self.add_single_value, tlv.Dot1_UntaggedVlanId,
                 LLDP_PORT_VLANID_NM, False),
            tlv.dot1_PORT_PROTOCOL_VLANID:
                (self.add_dot1_port_protocol_vlan, tlv.Dot1_PortProtocolVlan,
                 LLDP_PORT_PROT_NM, True),
            tlv.dot1_VLAN_NAME:
                (self.add_dot1_vlans, tlv.Dot1_VlanName, None, False),
            tlv.dot1_PROTOCOL_IDENTITY:
                (self.add_dot1_protocol_identities, tlv.Dot1_ProtocolIdentity,
                 LLDP_PROTOCOL_IDENTITIES_NM, False),
            tlv.dot1_MANAGEMENT_VID:
                (self.add_single_value, tlv.Dot1_MgmtVlanId,
                 LLDP_PORT_MGMT_VLANID_NM, False),
            tlv.dot1_LINK_AGGREGATION:
                (self.add_dot1_link_aggregation, tlv.Dot1_LinkAggregationId,
                 LLDP_PORT_LINK_AGG_NM, True)
        }

    def add_dot1_port_protocol_vlan(self, struct, name, data):
        """Handle dot1_PORT_PROTOCOL_VLANID"""
        self.set_value(LLDP_PORT_PROT_VLAN_ENABLED_NM, struct.flags.enabled)
        self.set_value(LLDP_PORT_PROT_VLAN_SUPPORT_NM, struct.flags.supported)

        # There can be multiple port/protocol vlans TLVs, store in list
        self.append_value(LLDP_PORT_PROT_VLANIDS_NM, struct.vlanid)

    def add_dot1_vlans(self, struct, name, data):
        """Handle dot1_VLAN_NAME

        There can be multiple VLAN TLVs, add dictionary entry with id/vlan
        to list.
        """
        vlan_dict = {}
        vlan_dict['name'] = struct.vlan_name
        vlan_dict['id'] = struct.vlanid
        self.append_value(LLDP_PORT_VLANS_NM, vlan_dict)

    def add_dot1_protocol_identities(self, struct, name, data):
        """Handle dot1_PROTOCOL_IDENTITY

        There can be multiple protocol ids TLVs, store in list
        """
        self.append_value(LLDP_PROTOCOL_IDENTITIES_NM,
                          binascii.b2a_hex(struct.protocol).decode())


class LLDPdot3Parser(LLDPParser):
    """Class to handle parsing of 802.3 TLVs"""
    def __init__(self, node_uuid, nv=None):
        super(LLDPdot3Parser, self).__init__(node_uuid, nv)

        # Note that 802.3 link Aggregation has been deprecated and moved to
        # 802.1 spec, but it is in the same format. Use the same function as
        # dot1 handler.
        self.parser_map = {
            tlv.dot3_MACPHY_CONFIG_STATUS:
                (self.add_dot3_macphy_config, tlv.Dot3_MACPhy_Config_Status,
                 LLDP_PORT_MAC_PHY_NM, True),
            tlv.dot3_LINK_AGGREGATION:
                (self.add_dot1_link_aggregation, tlv.Dot1_LinkAggregationId,
                 LLDP_PORT_LINK_AGG_NM, True),
            tlv.dot3_MTU:
                (self.add_single_value, tlv.Dot3_MTU, LLDP_MTU_NM, False)
        }

    def add_dot3_macphy_config(self, struct, name, data):
        """Handle dot3_MACPHY_CONFIG_STATUS"""

        try:
            mau_type = tlv.OPER_MAU_TYPES[struct.mau_type]
        except KeyError:
            raise ValueError(_('Invalid index for mau type'))

        self.set_value(LLDP_PORT_LINK_AUTONEG_ENABLED_NM,
                       struct.autoneg.enabled)
        self.set_value(LLDP_PORT_LINK_AUTONEG_SUPPORT_NM,
                       struct.autoneg.supported)
        self.set_value(LLDP_PORT_CAPABILITIES_NM,
                       tlv.get_autoneg_cap(struct.pmd_autoneg))
        self.set_value(LLDP_PORT_MAU_TYPE_NM, mau_type)
