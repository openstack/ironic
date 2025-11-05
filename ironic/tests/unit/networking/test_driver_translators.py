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

"""Unit tests for ironic.networking.driver_translators"""

import unittest
from unittest import mock

from ironic.networking.switch_drivers import driver_translators


class ConcreteTranslatorForTesting(driver_translators.BaseTranslator):
    """Concrete implementation of BaseTranslator for testing purposes."""

    def _get_section_name(self, switch_name):
        """Return a test section name."""
        return f"section_{switch_name}"

    def _translate_switch_config(self, config):
        """Return a test translated config."""
        return {'translated': True, **config}


class BaseTranslatorTestCase(unittest.TestCase):
    """Test cases for BaseTranslator class."""

    def setUp(self):
        super(BaseTranslatorTestCase, self).setUp()
        self.translator = ConcreteTranslatorForTesting()

    def test_translate_configs(self):
        """Test translate_configs method."""
        switch_configs = {
            'switch1': {'address': '192.168.1.1', 'username': 'admin'},
            'switch2': {'address': '192.168.1.2', 'device_type': 'cisco_ios'}
        }

        with mock.patch.object(self.translator,
                               'translate_config',
                               autospec=True) as mock_translate:
            mock_translate.side_effect = [
                {'section1': {'config1': 'value1'}},
                {'section2': {'config2': 'value2'}},
            ]

            result = self.translator.translate_configs(switch_configs)

            expected = {
                'section1': {'config1': 'value1'},
                'section2': {'config2': 'value2'}
            }
            self.assertEqual(expected, result)

            mock_translate.assert_has_calls([
                mock.call('switch1',
                          {'address': '192.168.1.1',
                           'username': 'admin'}),
                mock.call('switch2',
                          {'address': '192.168.1.2',
                           'device_type': 'cisco_ios'})
            ])

    def test_translate_config_success(self):
        """Test translate_config method with successful translation."""
        config = {'address': '192.168.1.1', 'username': 'admin'}

        with mock.patch.object(self.translator,
                               '_get_section_name',
                               autospec=True) as mock_section:
            with mock.patch.object(
                self.translator,
                '_translate_switch_config',
                autospec=True) as mock_translate:
                mock_section.return_value = 'test_section'
                mock_translate.return_value = {'translated': 'config'}

                result = self.translator.translate_config(
                    'test_switch', config)

                expected = {'test_section': {'translated': 'config'}}
                self.assertEqual(expected, result)

                mock_section.assert_called_once_with('test_switch')
                mock_translate.assert_called_once_with(config)

    def test_translate_config_empty_translation(self):
        """Test translate_config method with empty translation."""
        config = {'address': '192.168.1.1'}

        with mock.patch.object(self.translator,
                               '_get_section_name',
                               autospec=True) as mock_section:
            with mock.patch.object(
                self.translator,
                '_translate_switch_config',
                autospec=True) as mock_translate:
                mock_section.return_value = 'test_section'
                mock_translate.return_value = {}

                result = self.translator.translate_config(
                    'test_switch', config)

                self.assertEqual({}, result)

    def test_translate_config_none_translation(self):
        """Test translate_config method with None translation."""
        config = {'address': '192.168.1.1'}

        with mock.patch.object(self.translator,
                               '_get_section_name',
                               autospec=True) as mock_section:
            with mock.patch.object(
                self.translator,
                '_translate_switch_config',
                autospec=True) as mock_translate:
                mock_section.return_value = 'test_section'
                mock_translate.return_value = None

                result = self.translator.translate_config(
                    'test_switch', config)

                self.assertEqual({}, result)
