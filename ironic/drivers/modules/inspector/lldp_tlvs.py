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

""" Link Layer Discovery Protocol TLVs """

# See http://construct.readthedocs.io/en/latest/index.html

import functools

import construct
from construct import core
import netaddr
from oslo_log import log as logging

LOG = logging.getLogger(__name__)

# Constants defined according to 802.1AB-2016 LLDP spec
# https://standards.ieee.org/findstds/standard/802.1AB-2016.html

# TLV types
LLDP_TLV_END_LLDPPDU = 0
LLDP_TLV_CHASSIS_ID = 1
LLDP_TLV_PORT_ID = 2
LLDP_TLV_TTL = 3
LLDP_TLV_PORT_DESCRIPTION = 4
LLDP_TLV_SYS_NAME = 5
LLDP_TLV_SYS_DESCRIPTION = 6
LLDP_TLV_SYS_CAPABILITIES = 7
LLDP_TLV_MGMT_ADDRESS = 8
LLDP_TLV_ORG_SPECIFIC = 127

# 802.1Q defines from http://www.ieee802.org/1/pages/802.1Q-2014.html, Annex D
LLDP_802dot1_OUI = "0080c2"
# subtypes
dot1_PORT_VLANID = 1
dot1_PORT_PROTOCOL_VLANID = 2
dot1_VLAN_NAME = 3
dot1_PROTOCOL_IDENTITY = 4
dot1_MANAGEMENT_VID = 6
dot1_LINK_AGGREGATION = 7

# 802.3 defines from http://standards.ieee.org/about/get/802/802.3.html,
# section 79
LLDP_802dot3_OUI = "00120f"
# Subtypes
dot3_MACPHY_CONFIG_STATUS = 1
dot3_LINK_AGGREGATION = 3  # Deprecated, but still in use
dot3_MTU = 4


def bytes_to_int(obj):
    """Convert bytes to an integer

    :param: obj - array of bytes
    """
    return functools.reduce(lambda x, y: x << 8 | y, obj)


def mapping_for_enum(mapping):
    """Return tuple used for keys as a dict

    :param: mapping - dict with tuple as keys
    """
    return dict(mapping.keys())


def mapping_for_switch(mapping):
    """Return dict from values

     :param: mapping - dict with tuple as keys
     """
    return {key[0]: value for key, value in mapping.items()}


IPv4Address = core.ExprAdapter(
    core.Byte[4],
    encoder=lambda obj, ctx: netaddr.IPAddress(obj).words,
    decoder=lambda obj, ctx: str(netaddr.IPAddress(bytes_to_int(obj)))
)

IPv6Address = core.ExprAdapter(
    core.Byte[16],
    encoder=lambda obj, ctx: netaddr.IPAddress(obj).words,
    decoder=lambda obj, ctx: str(netaddr.IPAddress(bytes_to_int(obj)))
)

MACAddress = core.ExprAdapter(
    core.Byte[6],
    encoder=lambda obj, ctx: netaddr.EUI(obj).words,
    decoder=lambda obj, ctx: str(netaddr.EUI(bytes_to_int(obj),
                                 dialect=netaddr.mac_unix_expanded))
)

IANA_ADDRESS_FAMILY_ID_MAPPING = {
    ('ipv4', 1): IPv4Address,
    ('ipv6', 2): IPv6Address,
    ('mac', 6): MACAddress,
}

IANAAddress = core.Struct(
    'family' / core.Enum(core.Int8ub, **mapping_for_enum(
        IANA_ADDRESS_FAMILY_ID_MAPPING)),
    'value' / core.Switch(construct.this.family, mapping_for_switch(
        IANA_ADDRESS_FAMILY_ID_MAPPING)))

# Note that 'GreedyString()' is used in cases where string len is not defined
CHASSIS_ID_MAPPING = {
    ('entPhysAlias_c', 1): core.Struct('value' / core.GreedyString("utf8")),
    ('ifAlias', 2): core.Struct('value' / core.GreedyString("utf8")),
    ('entPhysAlias_p', 3): core.Struct('value' / core.GreedyString("utf8")),
    ('mac_address', 4): core.Struct('value' / MACAddress),
    ('IANA_address', 5): IANAAddress,
    ('ifName', 6): core.Struct('value' / core.GreedyString("utf8")),
    ('local', 7): core.Struct('value' / core.GreedyString("utf8"))
}

#
# Basic Management Set TLV field definitions
#

# Chassis ID value is based on the subtype
ChassisId = core.Struct(
    'subtype' / core.Enum(core.Byte, **mapping_for_enum(
        CHASSIS_ID_MAPPING)),
    'value' / core.Switch(construct.this.subtype,
                          mapping_for_switch(CHASSIS_ID_MAPPING))
)

PORT_ID_MAPPING = {
    ('ifAlias', 1): core.Struct('value' / core.GreedyString("utf8")),
    ('entPhysicalAlias', 2): core.Struct('value' / core.GreedyString("utf8")),
    ('mac_address', 3): core.Struct('value' / MACAddress),
    ('IANA_address', 4): IANAAddress,
    ('ifName', 5): core.Struct('value' / core.GreedyString("utf8")),
    ('local', 7): core.Struct('value' / core.GreedyString("utf8"))
}

# Port ID value is based on the subtype
PortId = core.Struct(
    'subtype' / core.Enum(core.Byte, **mapping_for_enum(
        PORT_ID_MAPPING)),
    'value' / core.Switch(construct.this.subtype,
                          mapping_for_switch(PORT_ID_MAPPING))
)

PortDesc = core.Struct('value' / core.GreedyString("utf8"))

SysName = core.Struct('value' / core.GreedyString("utf8"))

SysDesc = core.Struct('value' / core.GreedyString("utf8"))

MgmtAddress = core.Struct(
    'len' / core.Int8ub,
    'family' / core.Enum(core.Int8ub, **mapping_for_enum(
        IANA_ADDRESS_FAMILY_ID_MAPPING)),
    'address' / core.Switch(construct.this.family, mapping_for_switch(
        IANA_ADDRESS_FAMILY_ID_MAPPING))
)

Capabilities = core.BitStruct(
    core.Padding(5),
    'tpmr' / core.Bit,
    'svlan' / core.Bit,
    'cvlan' / core.Bit,
    'station' / core.Bit,
    'docsis' / core.Bit,
    'telephone' / core.Bit,
    'router' / core.Bit,
    'wlan' / core.Bit,
    'bridge' / core.Bit,
    'repeater' / core.Bit,
    core.Padding(1)
)

SysCapabilities = core.Struct(
    'system' / Capabilities,
    'enabled' / Capabilities
)

OrgSpecific = core.Struct(
    'oui' / core.Bytes(3),
    'subtype' / core.Int8ub
)

#
# 802.1Q TLV field definitions
# See http://www.ieee802.org/1/pages/802.1Q-2014.html, Annex D
#

Dot1_UntaggedVlanId = core.Struct('value' / core.Int16ub)

Dot1_PortProtocolVlan = core.Struct(
    'flags' / core.BitStruct(
        core.Padding(5),
        'enabled' / core.Flag,
        'supported' / core.Flag,
        core.Padding(1),
    ),
    'vlanid' / core.Int16ub
)

Dot1_VlanName = core.Struct(
    'vlanid' / core.Int16ub,
    'name_len' / core.Rebuild(core.Int8ub,
                              construct.len_(construct.this.value)),
    'vlan_name' / core.PaddedString(construct.this.name_len, "utf8")
)

Dot1_ProtocolIdentity = core.Struct(
    'len' / core.Rebuild(core.Int8ub, construct.len_(construct.this.value)),
    'protocol' / core.Bytes(construct.this.len)
)

Dot1_MgmtVlanId = core.Struct('value' / core.Int16ub)

Dot1_LinkAggregationId = core.Struct(
    'status' / core.BitStruct(
        core.Padding(6),
        'enabled' / core.Flag,
        'supported' / core.Flag
    ),
    'portid' / core.Int32ub
)

#
# 802.3 TLV field definitions
# See http://standards.ieee.org/about/get/802/802.3.html,
# section 79
#


def get_autoneg_cap(pmd):
    """Get autonegotiated capability strings

    This returns a list of capability strings from the Physical Media
    Dependent (PMD) capability bits.

    :param  pmd: PMD bits
    :return: Sorted list containing capability strings
    """
    caps_set = set()

    pmd_map = [
        (pmd._10base_t_hdx, '10BASE-T hdx'),
        (pmd._10base_t_hdx, '10BASE-T fdx'),
        (pmd._10base_t4, '10BASE-T4'),
        (pmd._100base_tx_hdx, '100BASE-TX hdx'),
        (pmd._100base_tx_fdx, '100BASE-TX fdx'),
        (pmd._100base_t2_hdx, '100BASE-T2 hdx'),
        (pmd._100base_t2_fdx, '100BASE-T2 fdx'),
        (pmd.pause_fdx, 'PAUSE fdx'),
        (pmd.asym_pause, 'Asym PAUSE fdx'),
        (pmd.sym_pause, 'Sym PAUSE fdx'),
        (pmd.asym_sym_pause, 'Asym and Sym PAUSE fdx'),
        (pmd._1000base_x_hdx, '1000BASE-X hdx'),
        (pmd._1000base_x_fdx, '1000BASE-X fdx'),
        (pmd._1000base_t_hdx, '1000BASE-T hdx'),
        (pmd._1000base_t_fdx, '1000BASE-T fdx')]

    for bit, cap in pmd_map:
        if bit:
            caps_set.add(cap)

    return sorted(caps_set)


Dot3_MACPhy_Config_Status = core.Struct(
    'autoneg' / core.BitStruct(
        core.Padding(6),
        'enabled' / core.Flag,
        'supported' / core.Flag,
    ),
    # See IANAifMauAutoNegCapBits
    # RFC 4836, Definitions of Managed Objects for IEEE 802.3
    'pmd_autoneg' / core.BitStruct(
        core.Padding(1),
        '_10base_t_hdx' / core.Bit,
        '_10base_t_fdx' / core.Bit,
        '_10base_t4' / core.Bit,
        '_100base_tx_hdx' / core.Bit,
        '_100base_tx_fdx' / core.Bit,
        '_100base_t2_hdx' / core.Bit,
        '_100base_t2_fdx' / core.Bit,
        'pause_fdx' / core.Bit,
        'asym_pause' / core.Bit,
        'sym_pause' / core.Bit,
        'asym_sym_pause' / core.Bit,
        '_1000base_x_hdx' / core.Bit,
        '_1000base_x_fdx' / core.Bit,
        '_1000base_t_hdx' / core.Bit,
        '_1000base_t_fdx' / core.Bit
    ),
    'mau_type' / core.Int16ub
)

# See ifMauTypeList in
# RFC 4836, Definitions of Managed Objects for IEEE 802.3
OPER_MAU_TYPES = {
    0: "Unknown",
    1: "AUI",
    2: "10BASE-5",
    3: "FOIRL",
    4: "10BASE-2",
    5: "10BASE-T duplex mode unknown",
    6: "10BASE-FP",
    7: "10BASE-FB",
    8: "10BASE-FL duplex mode unknown",
    9: "10BROAD36",
    10: "10BASE-T half duplex",
    11: "10BASE-T full duplex",
    12: "10BASE-FL half duplex",
    13: "10BASE-FL full duplex",
    14: "100 BASE-T4",
    15: "100BASE-TX half duplex",
    16: "100BASE-TX full duplex",
    17: "100BASE-FX half duplex",
    18: "100BASE-FX full duplex",
    19: "100BASE-T2 half duplex",
    20: "100BASE-T2 full duplex",
    21: "1000BASE-X half duplex",
    22: "1000BASE-X full duplex",
    23: "1000BASE-LX half duplex",
    24: "1000BASE-LX full duplex",
    25: "1000BASE-SX half duplex",
    26: "1000BASE-SX full duplex",
    27: "1000BASE-CX half duplex",
    28: "1000BASE-CX full duplex",
    29: "1000BASE-T half duplex",
    30: "1000BASE-T full duplex",
    31: "10GBASE-X",
    32: "10GBASE-LX4",
    33: "10GBASE-R",
    34: "10GBASE-ER",
    35: "10GBASE-LR",
    36: "10GBASE-SR",
    37: "10GBASE-W",
    38: "10GBASE-EW",
    39: "10GBASE-LW",
    40: "10GBASE-SW",
    41: "10GBASE-CX4",
    42: "2BASE-TL",
    43: "10PASS-TS",
    44: "100BASE-BX10D",
    45: "100BASE-BX10U",
    46: "100BASE-LX10",
    47: "1000BASE-BX10D",
    48: "1000BASE-BX10U",
    49: "1000BASE-LX10",
    50: "1000BASE-PX10D",
    51: "1000BASE-PX10U",
    52: "1000BASE-PX20D",
    53: "1000BASE-PX20U",
}

Dot3_MTU = core.Struct('value' / core.Int16ub)
