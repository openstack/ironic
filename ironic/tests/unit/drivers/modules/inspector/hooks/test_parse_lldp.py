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

from unittest import mock

from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules.inspector.hooks import parse_lldp as hook
from ironic.drivers.modules.inspector import lldp_parsers as nv
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class ParseLLDPTestCase(db_base.DbTestCase):
    def setUp(self):
        super().setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['agent', 'no-inspect'])
        self.node = obj_utils.create_test_node(self.context,
                                               inspect_interface='agent')
        self.inventory = {
            'interfaces': [{
                'name': 'em1',
            }],
            'cpu': 1,
            'disks': 1,
            'memory': 1
        }
        self.ip = '1.2.1.2'
        self.mac = '11:22:33:44:55:66'
        self.plugin_data = {'all_interfaces':
                            {'em1': {'mac': self.mac,
                                     'ip': self.ip}}}
        self.expected = {'em1': {'ip': self.ip, 'mac': self.mac}}

    def test_all_valid_data(self):
        self.plugin_data['lldp_raw'] = {
            'em1': [
                [1, "04112233aabbcc"],  # ChassisId
                [2, "07373334"],        # PortId
                [3, "003c"],            # TTL
                [4, "686f737430322e6c61622e656e6720706f7274203320"
                 "28426f6e6429"],  # PortDesc
                [5, "737730312d646973742d31622d623132"],  # SysName
                [6, "4e6574776f726b732c20496e632e20353530302c2076657273696f"
                 "6e203132204275696c6420646174653a20323031342d30332d31332030"
                 "383a33383a33302055544320"],  # SysDesc
                [7, "00140014"],  # SysCapabilities
                [8, "0501c000020f020000000000"],  # MgmtAddress
                [8, "110220010db885a3000000008a2e03707334020000000000"],
                [8, "0706aa11bb22cc3302000003e900"],  # MgmtAddress
                [127, "00120f01036c110010"],  # dot3 MacPhyConfigStatus
                [127, "00120f030300000002"],  # dot3 LinkAggregation
                [127, "00120f0405ea"],  # dot3 MTU
                [127, "0080c2010066"],  # dot1 PortVlan
                [127, "0080c20206000a"],  # dot1 PortProtocolVlanId
                [127, "0080c202060014"],  # dot1 PortProtocolVlanId
                [127, "0080c204080026424203000000"],   # dot1 ProtocolIdentity
                [127, "0080c203006507766c616e313031"],  # dot1 VlanName
                [127, "0080c203006607766c616e313032"],  # dot1 VlanName
                [127, "0080c203006807766c616e313034"],  # dot1 VlanName
                [127, "0080c2060058"],  # dot1 MgmtVID
                [0, ""],
            ]
        }
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [[0, ""]]
        }]

        expected = {
            nv.LLDP_CAP_ENABLED_NM: ['Bridge', 'Router'],
            nv.LLDP_CAP_SUPPORT_NM: ['Bridge', 'Router'],
            nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:cc",
            nv.LLDP_MGMT_ADDRESSES_NM: ['192.0.2.15',
                                        '2001:db8:85a3::8a2e:370:7334',
                                        'aa:11:bb:22:cc:33'],
            nv.LLDP_PORT_LINK_AUTONEG_ENABLED_NM: True,
            nv.LLDP_PORT_DESC_NM: 'host02.lab.eng port 3 (Bond)',
            nv.LLDP_PORT_ID_NM: '734',
            nv.LLDP_PORT_LINK_AGG_ENABLED_NM: True,
            nv.LLDP_PORT_LINK_AGG_ID_NM: 2,
            nv.LLDP_PORT_LINK_AGG_SUPPORT_NM: True,
            nv.LLDP_PORT_MGMT_VLANID_NM: 88,
            nv.LLDP_PORT_MAU_TYPE_NM: '100BASE-TX full duplex',
            nv.LLDP_MTU_NM: 1514,
            nv.LLDP_PORT_CAPABILITIES_NM: ['1000BASE-T fdx',
                                           '100BASE-TX fdx',
                                           '100BASE-TX hdx',
                                           '10BASE-T fdx',
                                           '10BASE-T hdx',
                                           'Asym and Sym PAUSE fdx'],
            nv.LLDP_PORT_PROT_VLAN_ENABLED_NM: True,
            nv.LLDP_PORT_PROT_VLANIDS_NM: [10, 20],
            nv.LLDP_PORT_PROT_VLAN_SUPPORT_NM: True,
            nv.LLDP_PORT_VLANID_NM: 102,
            nv.LLDP_PORT_VLANS_NM: [{'id': 101, 'name': 'vlan101'},
                                    {'id': 102, 'name': 'vlan102'},
                                    {'id': 104, "name": 'vlan104'}],
            nv.LLDP_PROTOCOL_IDENTITIES_NM: ['0026424203000000'],
            nv.LLDP_SYS_DESC_NM: 'Networks, Inc. 5500, version 12'
            ' Build date: 2014-03-13 08:38:30 UTC ',
            nv.LLDP_SYS_NAME_NM: 'sw01-dist-1b-b12'
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            actual = self.plugin_data.get('parsed_lldp').get('em1')

            for name, value in expected.items():
                if name is nv.LLDP_PORT_VLANS_NM:
                    for d1, d2 in zip(expected[name], actual[name]):
                        for key, value in d1.items():
                            self.assertEqual(d2[key], value)
                else:
                    self.assertEqual(actual[name], expected[name])

    def test_old_format(self):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [1, "04112233aabbcc"],  # ChassisId
                [2, "07373334"],        # PortId
                [3, "003c"],            # TTL
                [4, "686f737430322e6c61622e656e6720706f7274203320"
                 "28426f6e6429"],  # PortDesc
                [5, "737730312d646973742d31622d623132"],  # SysName
                [6, "4e6574776f726b732c20496e632e20353530302c2076657273696f"
                 "6e203132204275696c6420646174653a20323031342d30332d31332030"
                 "383a33383a33302055544320"],  # SysDesc
                [7, "00140014"],  # SysCapabilities
                [8, "0501c000020f020000000000"],  # MgmtAddress
                [8, "110220010db885a3000000008a2e03707334020000000000"],
                [8, "0706aa11bb22cc3302000003e900"],  # MgmtAddress
                [127, "00120f01036c110010"],  # dot3 MacPhyConfigStatus
                [127, "00120f030300000002"],  # dot3 LinkAggregation
                [127, "00120f0405ea"],  # dot3 MTU
                [127, "0080c2010066"],  # dot1 PortVlan
                [127, "0080c20206000a"],  # dot1 PortProtocolVlanId
                [127, "0080c202060014"],  # dot1 PortProtocolVlanId
                [127, "0080c204080026424203000000"],   # dot1 ProtocolIdentity
                [127, "0080c203006507766c616e313031"],  # dot1 VlanName
                [127, "0080c203006607766c616e313032"],  # dot1 VlanName
                [127, "0080c203006807766c616e313034"],  # dot1 VlanName
                [127, "0080c2060058"],  # dot1 MgmtVID
                [0, ""]]
        }]

        expected = {
            nv.LLDP_CAP_ENABLED_NM: ['Bridge', 'Router'],
            nv.LLDP_CAP_SUPPORT_NM: ['Bridge', 'Router'],
            nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:cc",
            nv.LLDP_MGMT_ADDRESSES_NM: ['192.0.2.15',
                                        '2001:db8:85a3::8a2e:370:7334',
                                        'aa:11:bb:22:cc:33'],
            nv.LLDP_PORT_LINK_AUTONEG_ENABLED_NM: True,
            nv.LLDP_PORT_DESC_NM: 'host02.lab.eng port 3 (Bond)',
            nv.LLDP_PORT_ID_NM: '734',
            nv.LLDP_PORT_LINK_AGG_ENABLED_NM: True,
            nv.LLDP_PORT_LINK_AGG_ID_NM: 2,
            nv.LLDP_PORT_LINK_AGG_SUPPORT_NM: True,
            nv.LLDP_PORT_MGMT_VLANID_NM: 88,
            nv.LLDP_PORT_MAU_TYPE_NM: '100BASE-TX full duplex',
            nv.LLDP_MTU_NM: 1514,
            nv.LLDP_PORT_CAPABILITIES_NM: ['1000BASE-T fdx',
                                           '100BASE-TX fdx',
                                           '100BASE-TX hdx',
                                           '10BASE-T fdx',
                                           '10BASE-T hdx',
                                           'Asym and Sym PAUSE fdx'],
            nv.LLDP_PORT_PROT_VLAN_ENABLED_NM: True,
            nv.LLDP_PORT_PROT_VLANIDS_NM: [10, 20],
            nv.LLDP_PORT_PROT_VLAN_SUPPORT_NM: True,
            nv.LLDP_PORT_VLANID_NM: 102,
            nv.LLDP_PORT_VLANS_NM: [{'id': 101, 'name': 'vlan101'},
                                    {'id': 102, 'name': 'vlan102'},
                                    {'id': 104, "name": 'vlan104'}],
            nv.LLDP_PROTOCOL_IDENTITIES_NM: ['0026424203000000'],
            nv.LLDP_SYS_DESC_NM: 'Networks, Inc. 5500, version 12 '
            'Build date: 2014-03-13 08:38:30 UTC ',
            nv.LLDP_SYS_NAME_NM: 'sw01-dist-1b-b12'
        }

        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            actual = self.plugin_data['parsed_lldp']['em1']
            for name, value in expected.items():
                if name is nv.LLDP_PORT_VLANS_NM:
                    for d1, d2 in zip(expected[name], actual[name]):
                        for key, value in d1.items():
                            self.assertEqual(d2[key], value)
                else:
                    self.assertEqual(actual[name], expected[name])

    def test_multiple_interfaces(self):
        self.inventory = {
            # An artificial mix of old and new LLDP fields.
            'interfaces': [
                {
                    'name': 'em1'
                },
                {
                    'name': 'em2',
                    'lldp': [
                        [1, "04112233aabbdd"],
                        [2, "07373838"],
                        [3, "003c"]
                    ]
                },
                {
                    'name': 'em3',
                    'lldp': [[3, "003c"]]
                }
            ],
            'cpu': 1,
            'disks': 1,
            'memory': 1
        }
        self.plugin_data = {
            'all_interfaces': {
                'em1': {'mac': self.mac, 'ip': self.ip},
                'em2': {'mac': self.mac, 'ip': self.ip},
                'em3': {'mac': self.mac, 'ip': self.ip}
            },
            'lldp_raw': {
                'em1': [
                    [1, "04112233aabbcc"],
                    [2, "07373334"],
                    [3, "003c"]
                ],
                'em3': [
                    [1, "04112233aabbee"],
                    [2, "07373939"],
                    [3, "003c"]
                ],
            }
        }
        expected = {"em1": {nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:cc",
                            nv.LLDP_PORT_ID_NM: "734"},
                    "em2": {nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:dd",
                            nv.LLDP_PORT_ID_NM: "788"},
                    "em3": {nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:ee",
                            nv.LLDP_PORT_ID_NM: "799"}}
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertEqual(expected, self.plugin_data['parsed_lldp'])

    def test_chassis_ids(self):
        # Test IPv4 address
        self.inventory['interfaces'] = [
            {
                'name': 'em1',
                'lldp': [[1, '0501c000020f']]
            },
            {
                'name': 'em2',
                'lldp': [[1, '0773773031']]
            }
        ]
        self.expected = {
            'em1': {nv.LLDP_CHASSIS_ID_NM: '192.0.2.15'},
            'em2': {nv.LLDP_CHASSIS_ID_NM: "sw01"}
        }
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertEqual(self.expected, self.plugin_data['parsed_lldp'])

    def test_duplicate_tlvs(self):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [1, "04112233aabbcc"],  # ChassisId
                [1, "04332211ddeeff"],  # ChassisId
                [1, "04556677aabbcc"],  # ChassisId
                [2, "07373334"],  # PortId
                [2, "07373435"],  # PortId
                [2, "07373536"]   # PortId
            ]}]
        # Only the first unique TLV is processed
        self.expected = {'em1': {
            nv.LLDP_CHASSIS_ID_NM: "11:22:33:aa:bb:cc",
            nv.LLDP_PORT_ID_NM: "734"
        }}
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertEqual(self.expected, self.plugin_data['parsed_lldp'])

    def test_unhandled_tlvs(self):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [10, "04112233aabbcc"],
                [12, "07373334"],
                [128, "00120f080300010000"]]}]
        # Nothing should be written to lldp_processed
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)

    def test_unhandled_oui(self):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [127, "00906901425030323134323530393236"],
                [127, "23ac0074657374"],
                [127, "00120e010300010000"]]}]
        # Nothing should be written to lldp_processed
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_null_strings(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [1, "04"],
                [4, ""],  # PortDesc
                [5, ""],  # SysName
                [6, ""],  # SysDesc
                [127, "0080c203006507"]  # dot1 VlanName
            ]}]
        self.expected = {'em1': {
            nv.LLDP_PORT_DESC_NM: '',
            nv.LLDP_SYS_DESC_NM: '',
            nv.LLDP_SYS_NAME_NM: ''
        }}
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertEqual(self.expected, self.plugin_data['parsed_lldp'])
            self.assertEqual(2, mock_log.call_count)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_truncated_int(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [127, "00120f04"],  # dot3 MTU
                [127, "0080c201"],  # dot1 PortVlan
                [127, "0080c206"],  # dot1 MgmtVID
            ]
        }]
        # Nothing should be written to lldp_processed
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)
            self.assertEqual(3, mock_log.call_count)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_invalid_ip(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [8, "0501"],  # truncated
                [8, "0507c000020f020000000000"]
            ]  # invalid id
        }]
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)
            self.assertEqual(1, mock_log.call_count)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_truncated_mac(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [[8, "0506"]]
        }]
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)
            self.assertEqual(1, mock_log.call_count)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_bad_value_macphy(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [127, "00120f01036c11FFFF"],  # invalid mau type
                [127, "00120f01036c11"],      # truncated
                [127, "00120f01036c"]         # truncated
            ]
        }]
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)
            self.assertEqual(3, mock_log.call_count)

    @mock.patch.object(nv.LOG, 'warning', autospec=True)
    def test_bad_value_linkagg(self, mock_log):
        self.inventory['interfaces'] = [{
            'name': 'em1',
            'lldp': [
                [127, "00120f0303"],  # dot3 LinkAggregation
                [127, "00120f03"]     # truncated
            ]
        }]
        with task_manager.acquire(self.context, self.node.id) as task:
            hook.ParseLLDPHook().__call__(task, self.inventory,
                                          self.plugin_data)
            self.assertNotIn('parsed_lldp', self.plugin_data)
            self.assertEqual(2, mock_log.call_count)
