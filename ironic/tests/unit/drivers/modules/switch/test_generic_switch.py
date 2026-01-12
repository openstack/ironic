#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Test class for GenericSwitch module."""
from unittest import mock

from ironic.drivers.modules.switch.base import SwitchDriverException
from ironic.drivers.modules.switch.base import SwitchNotFound
from ironic.drivers.modules.switch import generic_switch as gs
from ironic.drivers.modules.switch.generic_switch import GenericSwitchDriver
from ironic.tests import base


class GenericSwitchDriverTestCase(base.TestCase):
    """Test cases for GenericSwitchDriver."""

    def setUp(self):
        super(GenericSwitchDriverTestCase, self).setUp()

        # Dictionary to hold configured switches
        self.mock_devices = {}

        # Patch devices.get_devices to return our mock devices
        self.mock_get_devices = mock.patch.object(  # noqa: H210
            gs.devices, 'get_devices',
            return_value=self.mock_devices).start()

        # Patch device_utils.get_switch_device to look up switches
        self.mock_get_switch_device = mock.patch.object(  # noqa: H210
            gs.device_utils, 'get_switch_device',
            side_effect=lambda devices, switch_info=None, **kwargs:
                devices.get(switch_info)).start()

        self.addCleanup(mock.patch.stopall)

    def _create_switch_mock(self, device_name='test_switch',
                           device_type='cisco_ios',
                           ip='192.168.1.1',
                           support_trunk=True,
                           allowed_vlans=None):
        """Create a mock switch device with standard attributes."""
        switch = mock.Mock()
        switch.device_name = device_name
        switch.config = {
            'device_type': device_type,
            'ip': ip
        }
        switch.ngs_config = {
            'ngs_allowed_vlans': allowed_vlans
        }
        switch.support_trunk_on_ports = support_trunk
        return switch

    def test_initialize_with_devices(self):
        """Test driver initialization with configured switches."""
        self.mock_devices['test_switch'] = self._create_switch_mock()

        driver = gs.GenericSwitchDriver()

        self.assertEqual(1, len(driver._devices))
        self.assertIn('test_switch', driver._devices)

    def test_initialize_no_devices(self):
        """Test driver initialization with no configured switches."""
        driver = gs.GenericSwitchDriver()

        self.assertEqual(0, len(driver._devices))

    def test_initialize_multiple_switches(self):
        """Test driver initialization with multiple switches."""
        self.mock_devices['switch1'] = self._create_switch_mock(
            device_name='switch1', device_type='cisco')
        self.mock_devices['switch2'] = self._create_switch_mock(
            device_name='switch2', device_type='arista')

        driver = gs.GenericSwitchDriver()

        self.assertEqual(2, len(driver._devices))
        self.assertIn('switch1', driver._devices)
        self.assertIn('switch2', driver._devices)

    def test_update_port_access_mode(self):
        """Test updating port in access mode."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=None, default_vlan=None)

    def test_update_port_trunk_mode(self):
        """Test updating port in trunk mode."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Trunk Port',
            mode='trunk',
            native_vlan=1,
            allowed_vlans=[100, 200, 300]
        )

        expected_trunk_details = {
            'sub_ports': [
                {'segmentation_id': 100},
                {'segmentation_id': 200},
                {'segmentation_id': 300}
            ]
        }
        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 1, trunk_details=expected_trunk_details,
            default_vlan=None)

    def test_update_port_trunk_mode_excludes_native_vlan(self):
        """Test trunk mode excludes native VLAN from sub_ports."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Trunk Port',
            mode='trunk',
            native_vlan=100,
            allowed_vlans=[100, 200, 300]
        )

        # Native VLAN (100) should be excluded from sub_ports
        expected_trunk_details = {
            'sub_ports': [
                {'segmentation_id': 200},
                {'segmentation_id': 300}
            ]
        }
        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=expected_trunk_details,
            default_vlan=None)

    def test_update_port_hybrid_mode(self):
        """Test updating port in hybrid mode."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Hybrid Port',
            mode='hybrid',
            native_vlan=100,
            allowed_vlans=[200, 300]
        )

        expected_trunk_details = {
            'sub_ports': [
                {'segmentation_id': 200},
                {'segmentation_id': 300}
            ]
        }
        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=expected_trunk_details,
            default_vlan=None)

    def test_update_port_trunk_mode_only_native_vlan(self):
        """Trunk mode with only native VLAN results in no trunk_details."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Trunk Port',
            mode='trunk',
            native_vlan=100,
            allowed_vlans=[100]
        )

        # Should call with trunk_details=None when no sub_ports
        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=None, default_vlan=None)

    def test_update_port_with_default_vlan(self):
        """Test that default_vlan parameter is passed through."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.update_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100,
            default_vlan=1
        )

        switch.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=None, default_vlan=1)

    def test_update_port_invalid_mode(self):
        """Test that invalid mode raises ValueError."""
        self.mock_devices['switch01'] = self._create_switch_mock()
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            ValueError,
            "Invalid mode 'invalid'",
            driver.update_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='invalid',
            native_vlan=100
        )

    def test_update_port_trunk_mode_missing_allowed_vlans(self):
        """Test trunk mode without allowed_vlans raises ValueError."""
        self.mock_devices['switch01'] = self._create_switch_mock()
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            ValueError,
            "allowed_vlans parameter cannot be empty or missing when "
            "mode is 'trunk'",
            driver.update_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Trunk Port',
            mode='trunk',
            native_vlan=1
        )

    def test_update_port_hybrid_mode_empty_allowed_vlans(self):
        """Test hybrid mode with empty allowed_vlans raises ValueError."""
        self.mock_devices['switch01'] = self._create_switch_mock()
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            ValueError,
            "allowed_vlans parameter cannot be empty or missing when "
            "mode is 'hybrid'",
            driver.update_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Hybrid Port',
            mode='hybrid',
            native_vlan=1,
            allowed_vlans=[]
        )

    def test_update_port_trunk_mode_no_trunk_support(self):
        """Test trunk mode on switch without trunk support raises exception."""
        switch = self._create_switch_mock(support_trunk=False)
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        self.assertRaises(
            SwitchDriverException,
            driver.update_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Trunk Port',
            mode='trunk',
            native_vlan=1,
            allowed_vlans=[100, 200]
        )

    def test_update_port_switch_not_found(self):
        """Test updating port on non-existent switch raises SwitchNotFound."""
        driver = gs.GenericSwitchDriver()

        self.assertRaises(
            SwitchNotFound,
            driver.update_port,
            switch_id='nonexistent',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

    def test_update_port_switch_failure(self):
        """Test that switch errors are wrapped in SwitchDriverException."""
        switch = self._create_switch_mock()
        switch.plug_port_to_network.side_effect = ValueError('boom')
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            SwitchDriverException,
            'boom',
            driver.update_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

    def test_update_port_invalid_switch_id(self):
        """Test invalid switch_id parameters raise ValueError."""
        driver = gs.GenericSwitchDriver()

        # Test None switch_id
        self.assertRaisesRegex(
            ValueError,
            "switch_id must be a non-empty string",
            driver.update_port,
            switch_id=None,
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

        # Test empty switch_id
        self.assertRaisesRegex(
            ValueError,
            "switch_id must be a non-empty string",
            driver.update_port,
            switch_id='',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

        # Test whitespace-only switch_id
        self.assertRaisesRegex(
            ValueError,
            "switch_id cannot be only whitespace",
            driver.update_port,
            switch_id='   ',
            port_name='Ethernet1/1',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

    def test_update_port_invalid_port_name(self):
        """Test invalid port_name parameters raise ValueError."""
        driver = gs.GenericSwitchDriver()

        # Test None port_name
        self.assertRaisesRegex(
            ValueError,
            "port_name must be a non-empty string",
            driver.update_port,
            switch_id='switch01',
            port_name=None,
            description='Test Port',
            mode='access',
            native_vlan=100
        )

        # Test empty port_name
        self.assertRaisesRegex(
            ValueError,
            "port_name must be a non-empty string",
            driver.update_port,
            switch_id='switch01',
            port_name='',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

        # Test whitespace-only port_name
        self.assertRaisesRegex(
            ValueError,
            "port_name cannot be only whitespace",
            driver.update_port,
            switch_id='switch01',
            port_name='   ',
            description='Test Port',
            mode='access',
            native_vlan=100
        )

    def test_reset_port(self):
        """Test resetting a port configuration."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.reset_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            native_vlan=1
        )

        switch.delete_port.assert_called_once_with(
            'Ethernet1/1', 1, trunk_details=None, default_vlan=None)

    def test_reset_port_with_allowed_vlans(self):
        """Test reset_port properly formats trunk_details."""
        switch = self._create_switch_mock()
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        driver.reset_port(
            switch_id='switch01',
            port_name='Ethernet1/1',
            native_vlan=100,
            allowed_vlans=[200, 300]
        )

        expected_trunk_details = {
            'sub_ports': [
                {'segmentation_id': 200},
                {'segmentation_id': 300}
            ]
        }
        switch.delete_port.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=expected_trunk_details,
            default_vlan=None)

    def test_reset_port_switch_not_found(self):
        """Test reset_port on non-existent switch raises SwitchNotFound."""
        driver = gs.GenericSwitchDriver()

        self.assertRaises(
            SwitchNotFound,
            driver.reset_port,
            switch_id='nonexistent',
            port_name='Ethernet1/1',
            native_vlan=1
        )

    def test_reset_port_switch_failure(self):
        """Test reset_port wraps switch errors in SwitchDriverException."""
        switch = self._create_switch_mock()
        switch.delete_port.side_effect = ValueError('boom')
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            SwitchDriverException,
            'boom',
            driver.reset_port,
            switch_id='switch01',
            port_name='Ethernet1/1',
            native_vlan=1
        )

    def test_get_switch_info(self):
        """Test retrieving switch information."""
        switch = self._create_switch_mock(
            device_name='test_switch',
            device_type='cisco_ios',
            ip='192.168.1.10',
            allowed_vlans='1,2,3'
        )
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        info = driver.get_switch_info('switch01')

        expected_info = {
            'switch_id': 'switch01',
            'device_name': 'test_switch',
            'device_type': 'cisco_ios',
            'allowed_vlans': '1,2,3'
        }
        self.assertEqual(expected_info, info)

    def test_get_switch_info_switch_not_found(self):
        """Test get_switch_info on non-existent switch."""
        driver = gs.GenericSwitchDriver()

        self.assertRaises(
            SwitchNotFound,
            driver.get_switch_info,
            'nonexistent'
        )

    def test_get_switch_info_missing_attributes(self):
        """Test get_switch_info with missing attributes uses defaults."""
        switch = mock.Mock()
        switch.config = {}
        switch.ngs_config = {}
        del switch.device_name  # Remove device_name attribute

        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        info = driver.get_switch_info('switch01')

        expected_info = {
            'switch_id': 'switch01',
            'device_name': 'switch01',  # Falls back to switch_id
            'device_type': 'unknown',
            'allowed_vlans': None
        }
        self.assertEqual(expected_info, info)

    def test_is_switch_configured_valid(self):
        """Test is_switch_configured with properly configured switch."""
        switch = self._create_switch_mock(
            device_type='cisco_ios',
            ip='192.168.1.10')
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        result = driver.is_switch_configured('switch01')

        self.assertTrue(result)

    def test_is_switch_configured_missing_device_type(self):
        """Test is_switch_configured returns False without device_type."""
        switch = mock.Mock()
        switch.config = {'ip': '192.168.1.10'}
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        result = driver.is_switch_configured('switch01')

        self.assertFalse(result)

    def test_is_switch_configured_missing_connection_info(self):
        """Test is_switch_configured returns False without connection info."""
        switch = mock.Mock()
        switch.config = {'device_type': 'cisco_ios'}
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        result = driver.is_switch_configured('switch01')

        self.assertFalse(result)

    def test_is_switch_configured_with_host_instead_of_ip(self):
        """Test is_switch_configured accepts 'host' instead of 'ip'."""
        switch = mock.Mock()
        switch.config = {
            'device_type': 'cisco_ios',
            'host': 'switch.example.com'
        }
        self.mock_devices['switch01'] = switch
        driver = gs.GenericSwitchDriver()

        result = driver.is_switch_configured('switch01')

        self.assertTrue(result)

    def test_update_lag_not_supported(self):
        """Test that LAG update operation raises exception."""
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            SwitchDriverException,
            "LAG operations not supported",
            driver.update_lag,
            switch_ids=['switch01', 'switch02'],
            lag_name='Po1',
            description='Test Port',
            mode='access',
            native_vlan=100,
            aggregation_mode='static'
        )

    def test_delete_lag_not_supported(self):
        """Test that LAG delete operation raises exception."""
        driver = gs.GenericSwitchDriver()

        self.assertRaisesRegex(
            SwitchDriverException,
            "LAG operations not supported",
            driver.delete_lag,
            switch_ids=['switch01', 'switch02'],
            lag_name='Po1'
        )

    def test_get_switch_ids(self):
        """Test retrieving list of configured switch IDs."""
        self.mock_devices['switch1'] = self._create_switch_mock('switch1')
        self.mock_devices['switch2'] = self._create_switch_mock('switch2')
        driver = gs.GenericSwitchDriver()

        switch_ids = driver.get_switch_ids()

        self.assertEqual(2, len(switch_ids))
        self.assertIn('switch1', switch_ids)
        self.assertIn('switch2', switch_ids)

    def test_update_port_on_different_switches(self):
        """Test updating ports on different switches independently."""
        switch1 = self._create_switch_mock('switch1')
        switch2 = self._create_switch_mock('switch2')
        self.mock_devices['switch1'] = switch1
        self.mock_devices['switch2'] = switch2
        driver = gs.GenericSwitchDriver()

        # Update port on switch1
        driver.update_port(
            switch_id='switch1',
            port_name='Ethernet1/1',
            description='Port on switch1',
            mode='access',
            native_vlan=100
        )

        # Update port on switch2
        driver.update_port(
            switch_id='switch2',
            port_name='Ethernet1/1',
            description='Port on switch2',
            mode='access',
            native_vlan=200
        )

        # Verify each switch received its own call
        switch1.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 100, trunk_details=None, default_vlan=None)
        switch2.plug_port_to_network.assert_called_once_with(
            'Ethernet1/1', 200, trunk_details=None, default_vlan=None)

    def test_reset_port_on_different_switches(self):
        """Test resetting ports on different switches independently."""
        switch1 = self._create_switch_mock('switch1')
        switch2 = self._create_switch_mock('switch2')
        self.mock_devices['switch1'] = switch1
        self.mock_devices['switch2'] = switch2
        driver = gs.GenericSwitchDriver()

        # Reset port on switch1
        driver.reset_port(
            switch_id='switch1',
            port_name='Ethernet1/1',
            native_vlan=1
        )

        # Reset port on switch2
        driver.reset_port(
            switch_id='switch2',
            port_name='Ethernet1/2',
            native_vlan=1
        )

        # Verify each switch received its own call
        switch1.delete_port.assert_called_once_with(
            'Ethernet1/1', 1, trunk_details=None, default_vlan=None)
        switch2.delete_port.assert_called_once_with(
            'Ethernet1/2', 1, trunk_details=None, default_vlan=None)


class GenericSwitchTranslatorTestCase(base.TestCase):
    """Test cases for GenericSwitchTranslator class."""

    def setUp(self):
        super(GenericSwitchTranslatorTestCase, self).setUp()
        self.translator = GenericSwitchDriver.get_translator()

    def test__get_section_name(self):
        """Test _get_section_name method."""
        result = self.translator._get_section_name('my_switch')
        self.assertEqual('genericswitch:my_switch', result)

    def test__translate_switch_config_full_config(self):
        """Test _translate_switch_config with all supported fields."""
        config = {
            'driver_type': 'generic-switch',
            'address': '192.168.1.1',
            'device_type': 'netmiko_cisco_ios',
            'username': 'admin',
            'password': 'secret',
            'key_file': '/path/to/key',
            'enable_secret': 'enable_pass',
            'port': '22',
            'mac_address': '00:11:22:33:44:55',
            'default_vlan': '100',
            'extra_field': 'ignored'
        }

        result = self.translator._translate_switch_config(config)

        expected = {
            'device_type': 'netmiko_cisco_ios',
            'ip': '192.168.1.1',
            'username': 'admin',
            'password': 'secret',
            'key_file': '/path/to/key',
            'secret': 'enable_pass',
            'port': '22',
            'ngs_mac_address': '00:11:22:33:44:55',
            'ngs_save_configuration': False
        }
        self.assertEqual(expected, result)

    def test__translate_switch_config_minimal_config(self):
        """Test _translate_switch_config with minimal config."""
        config = {
            'device_type': 'netmiko_ovs_linux',
            'address': '192.168.1.1'
        }

        result = self.translator._translate_switch_config(config)

        expected = {
            'device_type': 'netmiko_ovs_linux',
            'ip': '192.168.1.1',
            'ngs_save_configuration': False
        }
        self.assertEqual(expected, result)

    def test__translate_switch_config_with_device_type(self):
        """Test _translate_switch_config with specific device type."""
        config = {
            'address': '192.168.1.1',
            'device_type': 'netmiko_cisco_nxos',
            'username': 'admin'
        }

        result = self.translator._translate_switch_config(config)

        expected = {
            'device_type': 'netmiko_cisco_nxos',
            'ip': '192.168.1.1',
            'username': 'admin',
            'ngs_save_configuration': False
        }
        self.assertEqual(expected, result)

    def test__translate_switch_config_ignores_driver_type(self):
        """Test _translate_switch_config ignores driver_type field."""
        config = {
            'driver_type': 'some_other_driver',
            'address': '192.168.1.1',
            'device_type': 'netmiko_arista_eos'
        }

        result = self.translator._translate_switch_config(config)

        # Should not include driver_type in output
        self.assertNotIn('driver_type', result)
        # Should include device_type translation
        self.assertEqual('netmiko_arista_eos', result['device_type'])

    def test_translate_config_integration(self):
        """Test full translate_config integration."""
        config = {
            'address': '192.168.1.100',
            'device_type': 'netmiko_cisco_ios',
            'username': 'test_user',
            'password': 'test_pass'
        }

        result = self.translator.translate_config('production_switch', config)

        expected = {
            'genericswitch:production_switch': {
                'device_type': 'netmiko_cisco_ios',
                'ip': '192.168.1.100',
                'username': 'test_user',
                'password': 'test_pass',
                'ngs_save_configuration': False,
            }
        }
        self.assertEqual(expected, result)

    def test_translate_configs_integration(self):
        """Test full translate_configs integration."""
        switch_configs = {
            'switch1': {
                'address': '192.168.1.1',
                'device_type': 'netmiko_cisco_ios',
                'username': 'admin'
            },
            'switch2': {
                'address': '192.168.1.2',
                'device_type': 'netmiko_ovs_linux'
            }
        }

        result = self.translator.translate_configs(switch_configs)

        expected = {
            'genericswitch:switch1': {
                'device_type': 'netmiko_cisco_ios',
                'ip': '192.168.1.1',
                'username': 'admin',
                'ngs_save_configuration': False,
            },
            'genericswitch:switch2': {
                'device_type': 'netmiko_ovs_linux',
                'ip': '192.168.1.2',
                'ngs_save_configuration': False,
            }
        }
        self.assertEqual(expected, result)

    def test__translate_allowed_vlans_string_single(self):
        """Test _translate_allowed_vlans with single VLAN string."""
        result = self.translator._translate_allowed_vlans('100')
        self.assertEqual('100', result)

    def test__translate_allowed_vlans_string_multiple(self):
        """Test _translate_allowed_vlans with multiple VLANs string."""
        result = self.translator._translate_allowed_vlans('100,200,300')
        self.assertEqual('100,200,300', result)

    def test__translate_allowed_vlans_string_range(self):
        """Test _translate_allowed_vlans with VLAN range string."""
        result = self.translator._translate_allowed_vlans('100-103')
        self.assertEqual('100,101,102,103', result)

    def test__translate_allowed_vlans_string_complex(self):
        """Test _translate_allowed_vlans with complex string spec."""
        result = self.translator._translate_allowed_vlans('100,102-104,106')
        self.assertEqual('100,102,103,104,106', result)

    def test__translate_allowed_vlans_string_with_spaces(self):
        """Test _translate_allowed_vlans with spaces in string."""
        result = self.translator._translate_allowed_vlans(
            ' 100 , 102-104 , 106 ')
        self.assertEqual('100,102,103,104,106', result)

    def test__translate_allowed_vlans_list_single(self):
        """Test _translate_allowed_vlans with single VLAN list."""
        result = self.translator._translate_allowed_vlans(['100'])
        self.assertEqual('100', result)

    def test__translate_allowed_vlans_list_multiple(self):
        """Test _translate_allowed_vlans with multiple VLANs list."""
        result = self.translator._translate_allowed_vlans(
            ['100', '200', '300'])
        self.assertEqual('100,200,300', result)

    def test__translate_allowed_vlans_list_range(self):
        """Test _translate_allowed_vlans with VLAN range in list."""
        result = self.translator._translate_allowed_vlans(['100-103'])
        self.assertEqual('100,101,102,103', result)

    def test__translate_allowed_vlans_list_complex(self):
        """Test _translate_allowed_vlans with complex list spec."""
        result = self.translator._translate_allowed_vlans(
            ['100', '102-104', '106'])
        self.assertEqual('100,102,103,104,106', result)

    def test__translate_allowed_vlans_none(self):
        """Test _translate_allowed_vlans with None (all VLANs allowed)."""
        result = self.translator._translate_allowed_vlans(None)
        self.assertIsNone(result)

    def test__translate_allowed_vlans_empty_string(self):
        """Test _translate_allowed_vlans with empty string."""
        result = self.translator._translate_allowed_vlans('')
        self.assertEqual('', result)

    def test__translate_allowed_vlans_empty_list(self):
        """Test _translate_allowed_vlans with empty list."""
        result = self.translator._translate_allowed_vlans([])
        self.assertEqual('', result)

    def test__translate_allowed_vlans_preserves_order(self):
        """Test _translate_allowed_vlans returns sorted VLANs."""
        # Input is out of order
        result = self.translator._translate_allowed_vlans('300,100,200')
        # Output should be sorted
        self.assertEqual('100,200,300', result)

    def test__translate_allowed_vlans_deduplicates(self):
        """Test _translate_allowed_vlans removes duplicates."""
        # Overlapping ranges
        result = self.translator._translate_allowed_vlans('100-102,101-103')
        # Should deduplicate
        self.assertEqual('100,101,102,103', result)

    def test__translate_switch_config_with_allowed_vlans_string(self):
        """Test _translate_switch_config with allowed_vlans string."""
        config = {
            'device_type': 'netmiko_ovs_linux',
            'address': '192.168.1.1',
            'allowed_vlans': '100,102-104,106'
        }

        result = self.translator._translate_switch_config(config)

        expected = {
            'device_type': 'netmiko_ovs_linux',
            'ip': '192.168.1.1',
            'ngs_allowed_vlans': '100,102,103,104,106',
            'ngs_save_configuration': False
        }
        self.assertEqual(expected, result)

    def test__translate_switch_config_with_allowed_vlans_list(self):
        """Test _translate_switch_config with allowed_vlans list."""
        config = {
            'device_type': 'netmiko_ovs_linux',
            'address': '192.168.1.1',
            'allowed_vlans': ['100', '102-104', '106']
        }

        result = self.translator._translate_switch_config(config)

        expected = {
            'device_type': 'netmiko_ovs_linux',
            'ip': '192.168.1.1',
            'ngs_allowed_vlans': '100,102,103,104,106',
            'ngs_save_configuration': False
        }
        self.assertEqual(expected, result)
