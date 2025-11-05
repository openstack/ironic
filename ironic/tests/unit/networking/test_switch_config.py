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
"""Unit tests for ``ironic.networking.switch_config``."""

from unittest import mock

from ironic.common import exception
from ironic.networking import switch_config
from ironic.tests import base


class ValidateVlanAllowedTestCase(base.TestCase):
    """Test cases for validate_vlan_allowed function."""

    def test_validate_vlan_allowed_none_config(self):
        """Test that None config allows all VLANs."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = None
            result = switch_config.validate_vlan_allowed(100)
            self.assertTrue(result)

    def test_validate_vlan_allowed_empty_list_config(self):
        """Test that empty list config denies all VLANs."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = []
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                100
            )

    def test_validate_vlan_allowed_vlan_in_list(self):
        """Test that VLAN in allowed list is accepted."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100', '200', '300']
            result = switch_config.validate_vlan_allowed(100)
            self.assertTrue(result)

    def test_validate_vlan_allowed_vlan_not_in_list(self):
        """Test that VLAN not in allowed list is rejected."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100', '200', '300']
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                150
            )

    def test_validate_vlan_allowed_vlan_in_range(self):
        """Test that VLAN in allowed range is accepted."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-200']
            result = switch_config.validate_vlan_allowed(150)
            self.assertTrue(result)

    def test_validate_vlan_allowed_vlan_not_in_range(self):
        """Test that VLAN not in allowed range is rejected."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-200']
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                250
            )

    def test_validate_vlan_allowed_complex_spec(self):
        """Test validation with complex allowed VLAN specification."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = [
                '100', '101', '102-104', '106'
            ]
            # Test allowed VLANs
            self.assertTrue(switch_config.validate_vlan_allowed(100))
            self.assertTrue(switch_config.validate_vlan_allowed(101))
            self.assertTrue(switch_config.validate_vlan_allowed(102))
            self.assertTrue(switch_config.validate_vlan_allowed(103))
            self.assertTrue(switch_config.validate_vlan_allowed(104))
            self.assertTrue(switch_config.validate_vlan_allowed(106))
            # Test disallowed VLAN
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                105
            )

    def test_validate_vlan_allowed_override_config(self):
        """Test that allowed_vlans_config parameter overrides CONF."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            # Override should allow 200, not 100
            result = switch_config.validate_vlan_allowed(
                200,
                allowed_vlans_config=['200']
            )
            self.assertTrue(result)
            # Should reject 100 when using override
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                100,
                allowed_vlans_config=['200']
            )

    def test_validate_vlan_allowed_switch_config_override(self):
        """Test that switch config overrides global config."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_cfg = {'allowed_vlans': ['200']}
            # Switch config should allow 200, not 100
            result = switch_config.validate_vlan_allowed(
                200,
                switch_config=switch_cfg
            )
            self.assertTrue(result)
            # Should reject 100 when using switch config
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                100,
                switch_config=switch_cfg
            )

    def test_validate_vlan_allowed_switch_config_no_allowed_vlans(self):
        """Test that switch config without allowed_vlans uses global."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_cfg = {'some_other_key': 'value'}
            # Should fall back to global config
            result = switch_config.validate_vlan_allowed(
                100,
                switch_config=switch_cfg
            )
            self.assertTrue(result)

    def test_validate_vlan_allowed_switch_config_empty_list(self):
        """Test that switch config with empty list denies all VLANs."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_cfg = {'allowed_vlans': []}
            # Switch config empty list should deny even though global allows
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_allowed,
                100,
                switch_config=switch_cfg
            )

    def test_validate_vlan_allowed_switch_config_none(self):
        """Test that switch config with None allows all VLANs."""
        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_cfg = {'allowed_vlans': None}
            # Switch config None should allow all, even though global restricts
            result = switch_config.validate_vlan_allowed(
                200,
                switch_config=switch_cfg
            )
            self.assertTrue(result)


class GetSwitchVlanConfigTestCase(base.TestCase):
    """Test cases for get_switch_vlan_config function."""

    def test_get_switch_vlan_config_with_switch_allowed_vlans(self):
        """Test getting config when switch has allowed_vlans."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100', '200-300']
        }

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['400']

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Should use switch-specific config, not global
            self.assertEqual({100, 200, 201, 202, 203, 204, 205, 206, 207,
                            208, 209, 210, 211, 212, 213, 214, 215, 216,
                            217, 218, 219, 220, 221, 222, 223, 224, 225,
                            226, 227, 228, 229, 230, 231, 232, 233, 234,
                            235, 236, 237, 238, 239, 240, 241, 242, 243,
                            244, 245, 246, 247, 248, 249, 250, 251, 252,
                            253, 254, 255, 256, 257, 258, 259, 260, 261,
                            262, 263, 264, 265, 266, 267, 268, 269, 270,
                            271, 272, 273, 274, 275, 276, 277, 278, 279,
                            280, 281, 282, 283, 284, 285, 286, 287, 288,
                            289, 290, 291, 292, 293, 294, 295, 296, 297,
                            298, 299, 300},
                            result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_get_switch_vlan_config_fallback_to_global(self):
        """Test fallback to global config when switch has no allowed_vlans."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {}

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100', '200-202']

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Should use global config
            self.assertEqual({100, 200, 201, 202}, result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_get_switch_vlan_config_switch_info_none(self):
        """Test when get_switch_info returns None."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = None

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['500']

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Should use global config
            self.assertEqual({500}, result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_get_switch_vlan_config_empty_switch_allowed_vlans(self):
        """Test when switch has empty allowed_vlans."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': []
        }

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Empty switch config should fallback to global
            self.assertEqual({100}, result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_get_switch_vlan_config_no_global_config(self):
        """Test when there's no global config."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {}

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = None

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Should return empty set
            self.assertEqual(set(), result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_get_switch_vlan_config_switch_specific_priority(self):
        """Test that switch-specific config takes priority over global."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['300-302']
        }

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-200']

            result = switch_config.get_switch_vlan_config(
                mock_driver, 'switch1'
            )

            # Should use switch-specific, not global
            self.assertEqual({300, 301, 302}, result['allowed_vlans'])
            mock_driver.get_switch_info.assert_called_once_with('switch1')


class ValidateVlanConfigurationTestCase(base.TestCase):
    """Test cases for validate_vlan_configuration function."""

    def test_validate_vlan_configuration_empty_vlans(self):
        """Test that empty VLAN list returns without validation."""
        mock_driver = mock.Mock()

        # Should not call get_switch_info if vlans_to_check is empty
        switch_config.validate_vlan_configuration(
            [], mock_driver, 'switch1'
        )
        mock_driver.get_switch_info.assert_not_called()

    def test_validate_vlan_configuration_none_vlans(self):
        """Test that None VLAN list returns without validation."""
        mock_driver = mock.Mock()

        # Should not call get_switch_info if vlans_to_check is None
        switch_config.validate_vlan_configuration(
            None, mock_driver, 'switch1'
        )
        mock_driver.get_switch_info.assert_not_called()

    def test_validate_vlan_configuration_all_allowed(self):
        """Test when all VLANs are allowed."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100-200']
        }

        # Should not raise exception
        switch_config.validate_vlan_configuration(
            [100, 150, 200], mock_driver, 'switch1'
        )
        mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_validate_vlan_configuration_some_disallowed(self):
        """Test when some VLANs are not allowed."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100-200']
        }

        # Should raise exception for VLANs outside allowed range
        exc = self.assertRaises(
            exception.InvalidParameterValue,
            switch_config.validate_vlan_configuration,
            [100, 250, 300],
            mock_driver,
            'switch1',
            'port configuration'
        )

        # Check exception message contains expected info
        self.assertIn('250', str(exc))
        self.assertIn('300', str(exc))
        self.assertIn('switch1', str(exc))
        self.assertIn('port configuration', str(exc))
        mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_validate_vlan_configuration_no_allowed_vlans_set(self):
        """Test when no allowed VLANs are configured (all allowed)."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {}

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = None

            # Should not raise exception when no restrictions
            switch_config.validate_vlan_configuration(
                [100, 200, 300], mock_driver, 'switch1'
            )
            mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_validate_vlan_configuration_single_vlan_allowed(self):
        """Test validation with a single VLAN."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100']
        }

        # Should not raise exception for allowed VLAN
        switch_config.validate_vlan_configuration(
            [100], mock_driver, 'switch1'
        )
        mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_validate_vlan_configuration_single_vlan_disallowed(self):
        """Test validation with a single disallowed VLAN."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100']
        }

        # Should raise exception for disallowed VLAN
        exc = self.assertRaises(
            exception.InvalidParameterValue,
            switch_config.validate_vlan_configuration,
            [200],
            mock_driver,
            'switch1',
            'VLAN assignment'
        )

        self.assertIn('200', str(exc))
        self.assertIn('switch1', str(exc))
        self.assertIn('VLAN assignment', str(exc))
        mock_driver.get_switch_info.assert_called_once_with('switch1')

    def test_validate_vlan_configuration_complex_ranges(self):
        """Test validation with complex VLAN ranges."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100', '200-202', '300-310']
        }

        # Should not raise for VLANs in allowed list/ranges
        switch_config.validate_vlan_configuration(
            [100, 200, 201, 202, 305],
            mock_driver,
            'switch1'
        )

        # Should raise for VLANs outside allowed list/ranges
        self.assertRaises(
            exception.InvalidParameterValue,
            switch_config.validate_vlan_configuration,
            [100, 150, 200],  # 150 is not in allowed list
            mock_driver,
            'switch1'
        )

    def test_validate_vlan_configuration_custom_operation_description(self):
        """Test that custom operation description appears in error."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {
            'allowed_vlans': ['100']
        }

        exc = self.assertRaises(
            exception.InvalidParameterValue,
            switch_config.validate_vlan_configuration,
            [200],
            mock_driver,
            'switch-xyz',
            'trunk port configuration'
        )

        # Verify custom operation description is in error message
        self.assertIn('trunk port configuration', str(exc))
        self.assertIn('switch-xyz', str(exc))

    def test_validate_vlan_configuration_fallback_to_global(self):
        """Test validation falls back to global config."""
        mock_driver = mock.Mock()
        mock_driver.get_switch_info.return_value = {}

        with mock.patch('ironic.networking.switch_config.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-105']

            # Should use global config and allow VLANs in range
            switch_config.validate_vlan_configuration(
                [100, 105], mock_driver, 'switch1'
            )

            # Should raise for VLANs outside global range
            self.assertRaises(
                exception.InvalidParameterValue,
                switch_config.validate_vlan_configuration,
                [200],
                mock_driver,
                'switch1'
            )
