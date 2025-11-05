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
"""Unit tests for ``ironic.networking.utils``."""

import unittest
from unittest import mock

from ironic.common import exception
from ironic.networking import utils
from ironic.tests import base


class ParseVlanRangesTestCase(base.TestCase):
    """Test cases for parse_vlan_ranges function."""

    def test_parse_vlan_ranges_none(self):
        """Test that None returns None."""
        result = utils.parse_vlan_ranges(None)
        self.assertIsNone(result)

    def test_parse_vlan_ranges_empty_list(self):
        """Test that empty list returns empty set."""
        result = utils.parse_vlan_ranges([])
        self.assertEqual(set(), result)

    def test_parse_vlan_ranges_single_vlan(self):
        """Test parsing a single VLAN ID."""
        result = utils.parse_vlan_ranges(['100'])
        self.assertEqual({100}, result)

    def test_parse_vlan_ranges_multiple_vlans(self):
        """Test parsing multiple VLAN IDs."""
        result = utils.parse_vlan_ranges(['100', '200', '300'])
        self.assertEqual({100, 200, 300}, result)

    def test_parse_vlan_ranges_simple_range(self):
        """Test parsing a simple VLAN range."""
        result = utils.parse_vlan_ranges(['100-103'])
        self.assertEqual({100, 101, 102, 103}, result)

    def test_parse_vlan_ranges_complex_spec(self):
        """Test parsing complex specification with ranges and singles."""
        result = utils.parse_vlan_ranges(
            ['100', '101', '102-104', '106']
        )
        self.assertEqual({100, 101, 102, 103, 104, 106}, result)

    def test_parse_vlan_ranges_with_spaces(self):
        """Test parsing with spaces in the specification."""
        result = utils.parse_vlan_ranges(
            [' 100 ', ' 102 - 104 ', ' 106']
        )
        self.assertEqual({100, 102, 103, 104, 106}, result)

    def test_parse_vlan_ranges_invalid_vlan_too_low(self):
        """Test that VLAN ID 0 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['0']
        )

    def test_parse_vlan_ranges_invalid_vlan_too_high(self):
        """Test that VLAN ID 4095 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['4095']
        )

    def test_parse_vlan_ranges_invalid_range_start_too_low(self):
        """Test that range starting at 0 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['0-10']
        )

    def test_parse_vlan_ranges_invalid_range_end_too_high(self):
        """Test that range ending at 4095 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['4090-4095']
        )

    def test_parse_vlan_ranges_invalid_range_start_greater_than_end(self):
        """Test that reversed range raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['104-100']
        )

    def test_parse_vlan_ranges_invalid_format_not_a_number(self):
        """Test that non-numeric VLAN raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['abc']
        )

    def test_parse_vlan_ranges_invalid_format_bad_range(self):
        """Test that malformed range raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            ['100-200-300']
        )

    def test_parse_vlan_ranges_boundary_values(self):
        """Test parsing with boundary VLAN values (1 and 4094)."""
        result = utils.parse_vlan_ranges(['1', '4094'])
        self.assertEqual({1, 4094}, result)


class ValidateVlanAllowedTestCase(base.TestCase):
    """Test cases for validate_vlan_allowed function."""

    def test_validate_vlan_allowed_none_config(self):
        """Test that None config allows all VLANs."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = None
            result = utils.validate_vlan_allowed(100)
            self.assertTrue(result)

    def test_validate_vlan_allowed_empty_list_config(self):
        """Test that empty list config denies all VLANs."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = []
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                100
            )

    def test_validate_vlan_allowed_vlan_in_list(self):
        """Test that VLAN in allowed list is accepted."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100', '200', '300']
            result = utils.validate_vlan_allowed(100)
            self.assertTrue(result)

    def test_validate_vlan_allowed_vlan_not_in_list(self):
        """Test that VLAN not in allowed list is rejected."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100', '200', '300']
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                150
            )

    def test_validate_vlan_allowed_vlan_in_range(self):
        """Test that VLAN in allowed range is accepted."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-200']
            result = utils.validate_vlan_allowed(150)
            self.assertTrue(result)

    def test_validate_vlan_allowed_vlan_not_in_range(self):
        """Test that VLAN not in allowed range is rejected."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100-200']
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                250
            )

    def test_validate_vlan_allowed_complex_spec(self):
        """Test validation with complex allowed VLAN specification."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = [
                '100', '101', '102-104', '106'
            ]
            # Test allowed VLANs
            self.assertTrue(utils.validate_vlan_allowed(100))
            self.assertTrue(utils.validate_vlan_allowed(101))
            self.assertTrue(utils.validate_vlan_allowed(102))
            self.assertTrue(utils.validate_vlan_allowed(103))
            self.assertTrue(utils.validate_vlan_allowed(104))
            self.assertTrue(utils.validate_vlan_allowed(106))
            # Test disallowed VLAN
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                105
            )

    def test_validate_vlan_allowed_override_config(self):
        """Test that allowed_vlans_config parameter overrides CONF."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            # Override should allow 200, not 100
            result = utils.validate_vlan_allowed(
                200,
                allowed_vlans_config=['200']
            )
            self.assertTrue(result)
            # Should reject 100 when using override
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                100,
                allowed_vlans_config=['200']
            )

    def test_validate_vlan_allowed_switch_config_override(self):
        """Test that switch config overrides global config."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_config = {'allowed_vlans': ['200']}
            # Switch config should allow 200, not 100
            result = utils.validate_vlan_allowed(
                200,
                switch_config=switch_config
            )
            self.assertTrue(result)
            # Should reject 100 when using switch config
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                100,
                switch_config=switch_config
            )

    def test_validate_vlan_allowed_switch_config_no_allowed_vlans(self):
        """Test that switch config without allowed_vlans uses global."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_config = {'some_other_key': 'value'}
            # Should fall back to global config
            result = utils.validate_vlan_allowed(
                100,
                switch_config=switch_config
            )
            self.assertTrue(result)

    def test_validate_vlan_allowed_switch_config_empty_list(self):
        """Test that switch config with empty list denies all VLANs."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_config = {'allowed_vlans': []}
            # Switch config empty list should deny even though global allows
            self.assertRaises(
                exception.InvalidParameterValue,
                utils.validate_vlan_allowed,
                100,
                switch_config=switch_config
            )

    def test_validate_vlan_allowed_switch_config_none(self):
        """Test that switch config with None allows all VLANs."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking']) as mock_conf:
            mock_conf.ironic_networking.allowed_vlans = ['100']
            switch_config = {'allowed_vlans': None}
            # Switch config None should allow all, even though global restricts
            result = utils.validate_vlan_allowed(
                200,
                switch_config=switch_config
            )
            self.assertTrue(result)


class RpcTransportTestCase(unittest.TestCase):
    """Test cases for rpc_transport function."""

    def test_rpc_transport_uses_networking_when_set(self):
        """Test that networking.rpc_transport is used when set."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking', 'rpc_transport']
                        ) as mock_conf:
            mock_conf.ironic_networking.rpc_transport = 'json-rpc'
            mock_conf.rpc_transport = 'oslo_messaging'
            result = utils.rpc_transport()
            self.assertEqual('json-rpc', result)

    def test_rpc_transport_falls_back_to_global(self):
        """Test that global rpc_transport is used when networking is None."""
        with mock.patch('ironic.networking.utils.CONF',
                        spec_set=['ironic_networking', 'rpc_transport']
                        ) as mock_conf:
            mock_conf.ironic_networking.rpc_transport = None
            mock_conf.rpc_transport = 'oslo_messaging'
            result = utils.rpc_transport()
            self.assertEqual('oslo_messaging', result)
