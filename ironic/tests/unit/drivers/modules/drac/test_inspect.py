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
Test class for DRAC inspection interface
"""

from unittest import mock

from oslo_utils import units
import sushy

from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import inspect as drac_inspect
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import inspect as redfish_inspect
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


class DracRedfishInspectionTestCase(test_utils.BaseDracTest):
    def setUp(self):
        super(DracRedfishInspectionTestCase, self).setUp()
        self.config(enabled_hardware_types=['idrac'],
                    enabled_power_interfaces=['idrac-redfish'],
                    enabled_management_interfaces=['idrac-redfish'],
                    enabled_inspect_interfaces=['idrac-redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='idrac',
            driver_info=INFO_DICT)

    def init_system_mock(self, system_mock, **properties):
        system_mock.reset()
        system_mock.boot.mode = 'uefi'
        system_mock.bios.attributes = {
            'PxeDev1EnDis': 'Enabled', 'PxeDev2EnDis': 'Disabled',
            'PxeDev3EnDis': 'Disabled', 'PxeDev4EnDis': 'Disabled',
            'PxeDev1Interface': 'NIC.Integrated.1-1-1',
            'PxeDev2Interface': None, 'PxeDev3Interface': None,
            'PxeDev4Interface': None}

        system_mock.memory_summary.size_gib = 2

        system_mock.processors.summary = '8', 'MIPS'

        system_mock.simple_storage.disks_sizes_bytes = (
            1 * units.Gi, units.Gi * 3, units.Gi * 5)
        system_mock.storage.volumes_sizes_bytes = (
            2 * units.Gi, units.Gi * 4, units.Gi * 6)

        system_mock.ethernet_interfaces.summary = {
            '00:11:22:33:44:55': sushy.STATE_ENABLED,
            '24:6E:96:70:49:00': sushy.STATE_DISABLED}
        member_data = [{
            'description': 'Integrated NIC 1 Port 1 Partition 1',
            'name': 'System Ethernet Interface',
            'full_duplex': False,
            'identity': 'NIC.Integrated.1-1-1',
            'mac_address': '24:6E:96:70:49:00',
            'mtu_size': None,
            'speed_mbps': 0,
            'vlan': None}]
        system_mock.ethernet_interfaces.get_members.return_value = [
            test_utils.dict_to_namedtuple(values=interface)
            for interface in member_data
        ]
        return system_mock

    def _setup_lldp_system_mock(self, mock_get_system):
        """System mock for LLDP tests."""
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.identity = 'System.Embedded.1'
        return system_mock

    def _setup_dell_connection_mock(self, system_mock, url='https://bmc.example.com/redfish/v1'):
        """Helper to setup Dell connection mock for LLDP tests."""
        mock_conn = mock.MagicMock()
        mock_conn._url = url
        system_mock._conn = mock_conn
        return mock_conn

    def _create_switch_connections_response(self, members):
        """Create a Mock response for Dell switch connections."""
        mock_response = mock.MagicMock()
        mock_response.json.return_value = {'Members': members}
        return mock_response

    def test_get_properties(self):
        expected = redfish_utils.COMMON_PROPERTIES
        driver = drac_inspect.DracRedfishInspect()
        self.assertEqual(expected, driver.get_properties())

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__get_pxe_port_macs_with_UEFI_boot_mode(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.boot.mode = 'uefi'
        expected_pxe_mac = ['24:6E:96:70:49:00']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_port_macs = task.driver.inspect._get_pxe_port_macs(task)
            self.assertEqual(expected_pxe_mac, pxe_port_macs)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__get_pxe_port_macs_with_BIOS_boot_mode(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.boot.mode = 'bios'
        mock_manager = mock.MagicMock()
        system_mock.managers = [mock_manager]
        mock_manager_oem = mock_manager.get_oem_extension.return_value
        mock_manager_oem.get_pxe_port_macs_bios.return_value = \
            ['24:6E:96:70:49:00']
        expected_pxe_mac = ['24:6E:96:70:49:00']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_port_macs = task.driver.inspect._get_pxe_port_macs(task)
            self.assertEqual(expected_pxe_mac, pxe_port_macs)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__get_pxe_port_macs_without_boot_mode(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.boot.mode = None
        expected_pxe_mac = []
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            pxe_port_macs = task.driver.inspect._get_pxe_port_macs(task)
            self.assertEqual(expected_pxe_mac, pxe_port_macs)

    @mock.patch.object(redfish_inspect.RedfishInspect, 'inspect_hardware',
                       autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_hardware_with_ethernet_interfaces_mac(
            self, mock_create_ports_if_not_exist, mock_inspect_hardware):
        ethernet_interfaces_mac = {'NIC.Integrated.1-1-1':
                                   '24:6E:96:70:49:00'}
        mock_inspect_hardware.return_value = states.MANAGEABLE
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_mac_address = mock.Mock()
            task.driver.inspect._get_mac_address.return_value = \
                ethernet_interfaces_mac
            return_value = task.driver.inspect.inspect_hardware(task)
            self.assertEqual(states.MANAGEABLE, return_value)
            mock_create_ports_if_not_exist.assert_called_once_with(
                task, ['24:6E:96:70:49:00'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__get_mac_address_with_ethernet_interfaces(self, mock_get_system):
        self.init_system_mock(mock_get_system.return_value)
        expected_value = {'NIC.Integrated.1-1-1': '24:6E:96:70:49:00'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            return_value = task.driver.inspect._get_mac_address(task)
            self.assertEqual(expected_value, return_value)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__get_mac_address_without_ethernet_interfaces(self,
                                                          mock_get_system):
        mock_system = self.init_system_mock(mock_get_system.return_value)
        mock_system.ethernet_interfaces.summary = None
        expected_value = {}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            return_value = task.driver.inspect._get_mac_address(task)
            self.assertEqual(expected_value, return_value)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_successful_dell_oem(self, mock_get_system):
        """Test successful LLDP data collection from Dell OEM endpoints."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)
        mock_conn = self._setup_dell_connection_mock(system_mock)

        # Mock the HTTP response with switch connections
        members = [
            {
                'FQDD': 'NIC.Integrated.1-1-1',
                'SwitchConnectionID': 'aa:bb:cc:dd:ee:ff',
                'SwitchPortConnectionID': 'Ethernet1/0/1'
            },
            {
                'FQDD': 'NIC.Integrated.1-1-2',
                'SwitchConnectionID': 'aa:bb:cc:dd:ee:gg',
                'SwitchPortConnectionID': 'Ethernet1/8'
            }
        ]
        mock_response = self._create_switch_connections_response(members)
        mock_conn.get.return_value = mock_response

        expected_lldp = {
            'NIC.Integrated.1-1-1': {
                'switch_chassis_id': 'aa:bb:cc:dd:ee:ff',
                'switch_port_id': 'Ethernet1/0/1'
            },
            'NIC.Integrated.1-1-2': {
                'switch_chassis_id': 'aa:bb:cc:dd:ee:gg',
                'switch_port_id': 'Ethernet1/8'
            }
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._collect_lldp_data(task, system_mock)
            self.assertEqual(expected_lldp, result)

    @mock.patch.object(redfish_inspect.RedfishInspect, '_collect_lldp_data',
                       autospec=True)
    @mock.patch.object(drac_inspect.DracRedfishInspect,
                       '_get_dell_switch_connections', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_fallback_to_standard(self, mock_get_system,
                                                   mock_get_connections,
                                                   mock_super_collect):
        """Test fallback to standard Redfish LLDP when Dell OEM fails."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)

        # Mock _get_dell_switch_connections to raise an exception
        mock_get_connections.side_effect = Exception("Dell OEM failed")

        # Mock fallback response
        mock_super_collect.return_value = {
            'NIC.Integrated.1-1-1': {
                'switch_chassis_id': 'fallback_chassis',
                'switch_port_id': 'fallback_port'
            }
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._collect_lldp_data(task, system_mock)
            # Should return the fallback data
            mock_super_collect.assert_called_once_with(
                task.driver.inspect, task, system_mock)
            self.assertEqual(mock_super_collect.return_value, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_filters_no_link(self, mock_get_system):
        """Test that 'No Link' connections are filtered out."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)
        mock_conn = self._setup_dell_connection_mock(system_mock)

        # Mock the HTTP response with mixed valid/invalid connections
        members = [
            {
                'FQDD': 'NIC.Integrated.1-1-1',
                'SwitchConnectionID': 'aa:bb:cc:dd:ee:ff',
                'SwitchPortConnectionID': 'Ethernet1/8'
            },
            {
                'FQDD': 'NIC.Integrated.1-1-2',
                'SwitchConnectionID': 'No Link',
                'SwitchPortConnectionID': 'No Link'
            },
            {
                'FQDD': None,
                'SwitchConnectionID': 'aa:bb:cc:dd:ee:gg',
                'SwitchPortConnectionID': 'Ethernet1/8'
            }
        ]
        mock_response = self._create_switch_connections_response(members)
        mock_conn.get.return_value = mock_response

        expected_lldp = {
            'NIC.Integrated.1-1-1': {
                'switch_chassis_id': 'aa:bb:cc:dd:ee:ff',
                'switch_port_id': 'Ethernet1/8'
            }
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._collect_lldp_data(task, system_mock)
            self.assertEqual(expected_lldp, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_dell_switch_connections_success(self, mock_get_system):
        """Test successful retrieval of Dell switch connections."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)
        mock_conn = self._setup_dell_connection_mock(system_mock)

        expected_members = [
            {'FQDD': 'NIC.Integrated.1-1-1',
             'SwitchConnectionID': 'aa:bb:cc:dd:ee:ff'},
            {'FQDD': 'NIC.Integrated.1-1-2',
             'SwitchConnectionID': 'aa:bb:cc:dd:ee:gg'}
        ]
        mock_response = self._create_switch_connections_response(
            expected_members)
        mock_conn.get.return_value = mock_response

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._get_dell_switch_connections(task)
            self.assertEqual(expected_members, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_dell_switch_connections_attr_error(self, mock_get_system):
        """Test AttributeError when accessing private attributes."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)

        # Mock missing _conn attribute
        delattr(system_mock, '_conn')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._get_dell_switch_connections(task)
            self.assertEqual([], result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_dell_switch_connections_conn_error(self, mock_get_system):
        """Test handling of connection errors during HTTP request."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)
        mock_conn = self._setup_dell_connection_mock(system_mock)

        # Mock connection failure
        mock_conn.get.side_effect = Exception("HTTP connection failed")

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._get_dell_switch_connections(task)
            self.assertEqual([], result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_get_dell_switch_connections_empty_response(self, mock_get_system):
        """Test handling of empty response from Dell OEM endpoint."""
        system_mock = self._setup_lldp_system_mock(mock_get_system)
        mock_conn = self._setup_dell_connection_mock(system_mock)

        # Mock empty response
        mock_response = self._create_switch_connections_response([])
        mock_conn.get.return_value = mock_response

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            result = task.driver.inspect._get_dell_switch_connections(task)
            self.assertEqual([], result)
