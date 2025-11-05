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

    def test_parse_vlan_ranges_string_single_vlan(self):
        """Test parsing a string with single VLAN ID."""
        result = utils.parse_vlan_ranges('100')
        self.assertEqual({100}, result)

    def test_parse_vlan_ranges_string_multiple_vlans(self):
        """Test parsing a string with multiple VLAN IDs."""
        result = utils.parse_vlan_ranges('100,200,300')
        self.assertEqual({100, 200, 300}, result)

    def test_parse_vlan_ranges_string_simple_range(self):
        """Test parsing a string with a simple VLAN range."""
        result = utils.parse_vlan_ranges('100-103')
        self.assertEqual({100, 101, 102, 103}, result)

    def test_parse_vlan_ranges_string_complex_spec(self):
        """Test parsing a string with ranges and singles."""
        result = utils.parse_vlan_ranges('100,101,102-104,106')
        self.assertEqual({100, 101, 102, 103, 104, 106}, result)

    def test_parse_vlan_ranges_string_with_spaces(self):
        """Test parsing a string with spaces."""
        result = utils.parse_vlan_ranges(' 100 , 102 - 104 , 106 ')
        self.assertEqual({100, 102, 103, 104, 106}, result)

    def test_parse_vlan_ranges_string_with_trailing_comma(self):
        """Test parsing a string with trailing comma."""
        result = utils.parse_vlan_ranges('100,200,')
        self.assertEqual({100, 200}, result)

    def test_parse_vlan_ranges_string_with_leading_comma(self):
        """Test parsing a string with leading comma."""
        result = utils.parse_vlan_ranges(',100,200')
        self.assertEqual({100, 200}, result)

    def test_parse_vlan_ranges_string_with_double_comma(self):
        """Test parsing a string with double commas (empty elements)."""
        result = utils.parse_vlan_ranges('100,,200')
        self.assertEqual({100, 200}, result)

    def test_parse_vlan_ranges_string_empty(self):
        """Test parsing an empty string returns empty set."""
        result = utils.parse_vlan_ranges('')
        self.assertEqual(set(), result)

    def test_parse_vlan_ranges_string_whitespace_only(self):
        """Test parsing a whitespace-only string returns empty set."""
        result = utils.parse_vlan_ranges('   ')
        self.assertEqual(set(), result)

    def test_parse_vlan_ranges_string_invalid_vlan_too_low(self):
        """Test that string with VLAN ID 0 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            '0'
        )

    def test_parse_vlan_ranges_string_invalid_vlan_too_high(self):
        """Test that string with VLAN ID 4095 raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            '4095'
        )

    def test_parse_vlan_ranges_string_invalid_format_not_a_number(self):
        """Test that string with non-numeric VLAN raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            'abc'
        )

    def test_parse_vlan_ranges_string_invalid_format_bad_range(self):
        """Test that string with malformed range raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            '100-200-300'
        )

    def test_parse_vlan_ranges_string_mixed_valid_invalid(self):
        """Test that string with mixed valid and invalid raises an error."""
        self.assertRaises(
            exception.InvalidParameterValue,
            utils.parse_vlan_ranges,
            '100,abc,200'
        )


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
