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

import dataclasses

from ironic.common import exception
from ironic.drivers.modules.network.switchport_config import SwitchPortConfig
from ironic.tests import base as test_base


class TestSwitchPortConfigFromString(test_base.TestCase):

    def test_access_with_native_vlan(self):
        config = SwitchPortConfig.from_string('access/native_vlan=100')
        self.assertEqual('access', config.mode)
        self.assertEqual(100, config.native_vlan)
        self.assertIsNone(config.allowed_vlans)

    def test_trunk_with_native_vlan(self):
        config = SwitchPortConfig.from_string('trunk/native_vlan=200')
        self.assertEqual('trunk', config.mode)
        self.assertEqual(200, config.native_vlan)
        self.assertIsNone(config.allowed_vlans)

    def test_hybrid_with_native_vlan(self):
        config = SwitchPortConfig.from_string('hybrid/native_vlan=300')
        self.assertEqual('hybrid', config.mode)
        self.assertEqual(300, config.native_vlan)

    def test_with_allowed_vlans(self):
        config = SwitchPortConfig.from_string(
            'trunk/native_vlan=100/allowed_vlans=100,200,300')
        self.assertEqual('trunk', config.mode)
        self.assertEqual(100, config.native_vlan)
        self.assertEqual([100, 200, 300], config.allowed_vlans)

    def test_with_allowed_vlans_single(self):
        config = SwitchPortConfig.from_string(
            'access/native_vlan=50/allowed_vlans=50')
        self.assertEqual('access', config.mode)
        self.assertEqual(50, config.native_vlan)
        self.assertEqual([50], config.allowed_vlans)

    def test_with_allowed_vlans_ranges(self):
        config = SwitchPortConfig.from_string(
            'trunk/native_vlan=100/allowed_vlans=1,2,4-7,9')
        self.assertEqual('trunk', config.mode)
        self.assertEqual(100, config.native_vlan)
        self.assertEqual([1, 2, 4, 5, 6, 7, 9],
                         config.allowed_vlans)

    def test_with_allowed_vlans_range_only(self):
        config = SwitchPortConfig.from_string(
            'trunk/native_vlan=10/allowed_vlans=100-103')
        self.assertEqual([100, 101, 102, 103],
                         config.allowed_vlans)

    def test_mode_only_raises(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string, 'access')

    def test_whitespace_stripped(self):
        config = SwitchPortConfig.from_string(
            ' trunk / native_vlan = 100 ')
        self.assertEqual('trunk', config.mode)
        self.assertEqual(100, config.native_vlan)

    def test_empty_string_raises(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string, '')

    def test_invalid_vlan_not_integer(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string, 'access/native_vlan=abc')

    def test_invalid_allowed_vlans_element(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string,
            'trunk/native_vlan=10/allowed_vlans=a,b')

    def test_invalid_allowed_vlans_bad_range(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string,
            'trunk/native_vlan=10/allowed_vlans=1-2-3')

    def test_invalid_mode(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string,
            'bogus/native_vlan=10')

    def test_unknown_key_ignored(self):
        config = SwitchPortConfig.from_string(
            'trunk/native_vlan=10/unknown=42/allowed_vlans=10,20')
        self.assertEqual('trunk', config.mode)
        self.assertEqual(10, config.native_vlan)
        self.assertEqual([10, 20], config.allowed_vlans)

    def test_invalid_missing_equals(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_string,
            'trunk/no_equals')

    def test_network_type_in_error_message(self):
        self.assertRaisesRegex(
            exception.InvalidParameterValue, 'cleaning',
            SwitchPortConfig.from_string,
            'trunk/native_vlan=abc', network_type='cleaning')

    def test_frozen(self):
        config = SwitchPortConfig.from_string(
            'access/native_vlan=10')
        self.assertRaises(
            dataclasses.FrozenInstanceError,
            setattr, config, 'mode', 'trunk')


class TestSwitchPortConfigFromSwitchport(test_base.TestCase):

    def test_full_switchport_dict(self):
        switchport = {
            'mode': 'trunk',
            'native_vlan': 100,
            'allowed_vlans': [100, 200],
        }
        config = SwitchPortConfig.from_switchport(switchport)
        self.assertEqual('trunk', config.mode)
        self.assertEqual(100, config.native_vlan)
        self.assertEqual([100, 200], config.allowed_vlans)

    def test_mode_and_native_vlan_only(self):
        switchport = {'mode': 'access', 'native_vlan': 50}
        config = SwitchPortConfig.from_switchport(switchport)
        self.assertEqual('access', config.mode)
        self.assertEqual(50, config.native_vlan)
        self.assertIsNone(config.allowed_vlans)

    def test_mode_only(self):
        switchport = {'mode': 'access'}
        config = SwitchPortConfig.from_switchport(switchport)
        self.assertEqual('access', config.mode)
        self.assertIsNone(config.native_vlan)
        self.assertFalse(config.is_valid)

    def test_no_mode_returns_none(self):
        switchport = {'native_vlan': 100}
        config = SwitchPortConfig.from_switchport(switchport)
        self.assertIsNone(config)

    def test_empty_dict_returns_none(self):
        config = SwitchPortConfig.from_switchport({})
        self.assertIsNone(config)

    def test_empty_mode_returns_none(self):
        config = SwitchPortConfig.from_switchport({'mode': ''})
        self.assertIsNone(config)

    def test_invalid_mode_raises(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_switchport,
            {'mode': 'bogus', 'native_vlan': 10})

    def test_native_vlan_not_integer_raises(self):
        self.assertRaises(
            exception.InvalidParameterValue,
            SwitchPortConfig.from_switchport,
            {'mode': 'access', 'native_vlan': 'abc'})


class TestSwitchPortConfigIsValid(test_base.TestCase):

    def test_access_with_native_vlan(self):
        config = SwitchPortConfig(mode='access', native_vlan=10)
        self.assertTrue(config.is_valid)

    def test_access_native_vlan_zero(self):
        config = SwitchPortConfig(mode='access', native_vlan=0)
        self.assertTrue(config.is_valid)

    def test_access_missing_native_vlan(self):
        config = SwitchPortConfig(mode='access')
        self.assertFalse(config.is_valid)

    def test_access_with_only_allowed_vlans(self):
        config = SwitchPortConfig(
            mode='access', allowed_vlans=[10])
        self.assertFalse(config.is_valid)

    def test_trunk_with_allowed_vlans(self):
        config = SwitchPortConfig(
            mode='trunk', allowed_vlans=[10, 20])
        self.assertTrue(config.is_valid)

    def test_trunk_missing_allowed_vlans(self):
        config = SwitchPortConfig(mode='trunk', native_vlan=10)
        self.assertFalse(config.is_valid)

    def test_hybrid_with_allowed_vlans(self):
        config = SwitchPortConfig(
            mode='hybrid', allowed_vlans=[10, 20])
        self.assertTrue(config.is_valid)

    def test_hybrid_missing_allowed_vlans(self):
        config = SwitchPortConfig(mode='hybrid', native_vlan=10)
        self.assertFalse(config.is_valid)

    def test_empty_mode(self):
        config = SwitchPortConfig(mode='', native_vlan=10)
        self.assertFalse(config.is_valid)


class TestSwitchPortConfigEquality(test_base.TestCase):

    def test_equal_instances(self):
        a = SwitchPortConfig(mode='access', native_vlan=10)
        b = SwitchPortConfig(mode='access', native_vlan=10)
        self.assertEqual(a, b)

    def test_different_mode(self):
        a = SwitchPortConfig(mode='access', native_vlan=10)
        b = SwitchPortConfig(mode='trunk', native_vlan=10)
        self.assertNotEqual(a, b)

    def test_different_vlan(self):
        a = SwitchPortConfig(mode='access', native_vlan=10)
        b = SwitchPortConfig(mode='access', native_vlan=20)
        self.assertNotEqual(a, b)

    def test_from_string_equals_constructor(self):
        a = SwitchPortConfig.from_string('access/native_vlan=10')
        b = SwitchPortConfig(mode='access', native_vlan=10)
        self.assertEqual(a, b)

    def test_from_switchport_equals_constructor(self):
        a = SwitchPortConfig.from_switchport(
            {'mode': 'trunk', 'native_vlan': 100,
             'allowed_vlans': [100, 200]})
        b = SwitchPortConfig(
            mode='trunk', native_vlan=100, allowed_vlans=[100, 200])
        self.assertEqual(a, b)
