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

from ironic.conf import CONF
from ironic.tests.base import TestCase


class ValidateConsoleAllowedPortRanges(TestCase):
    def test_success(self):
        CONF.set_override('port_range', '', 'console')
        self.assertEqual([], CONF.console.port_range)
        CONF.set_override('port_range', '1:10', 'console')
        self.assertEqual([range(1, 10)], CONF.console.port_range)
        CONF.set_override('port_range', '1:10,11:12,13:13', 'console')
        self.assertEqual([range(1, 10), range(11, 12), range(13, 13)],
                         CONF.console.port_range)
        CONF.set_override('port_range', '0:65535', 'console')
        self.assertEqual([range(0, 65535)], CONF.console.port_range)

    def test_invalid_elements(self):
        self.assertRaisesRegex(
            ValueError, r'Value should be in <start>:<end> format',
            CONF.set_override, 'port_range', '10', 'console')
        self.assertRaisesRegex(
            ValueError, r'Value should be in <start>:<end> format',
            CONF.set_override, 'port_range', '10:20:30', 'console')

    def test_non_integer(self):
        self.assertRaisesRegex(
            ValueError, r'Port numbers should be integers',
            CONF.set_override, 'port_range', '10:a', 'console')
        self.assertRaisesRegex(
            ValueError, r'Port numbers should be integers',
            CONF.set_override, 'port_range', 'a:10', 'console')
        self.assertRaisesRegex(
            ValueError, r'Port numbers should be integers',
            CONF.set_override, 'port_range', '10:', 'console')
        self.assertRaisesRegex(
            ValueError, r'Port numbers should be integers',
            CONF.set_override, 'port_range', ':10', 'console')

    def test_bad_order(self):
        self.assertRaisesRegex(
            ValueError, r'Start should not be greater than end.',
            CONF.set_override, 'port_range', '11:10', 'console')
        self.assertRaisesRegex(
            ValueError, r'Start should not be greater than end.',
            CONF.set_override, 'port_range', '10:11,21:20', 'console')

    def test_out_of_range(self):
        self.assertRaisesRegex(
            ValueError, r'Port range should be in \[0, 65535\]',
            CONF.set_override, 'port_range', '-1:10', 'console')
        self.assertRaisesRegex(
            ValueError, r'Port range should be in \[0, 65535\]',
            CONF.set_override, 'port_range', '65530:65536', 'console')
