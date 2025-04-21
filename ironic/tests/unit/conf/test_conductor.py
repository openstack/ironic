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


class ValidateConductorAllowedPaths(TestCase):
    def test_abspath_validation_bad_path_raises(self):
        """Verifies setting a relative path raises an error via oslo.config."""
        self.assertRaises(
            ValueError,
            CONF.set_override,
            'file_url_allowed_paths',
            ['bad/path'],
            'conductor'
        )

    def test_abspath_validation_good_paths(self):
        """Verifies setting an absolute path works via oslo.config."""
        CONF.set_override('file_url_allowed_paths', ['/var'], 'conductor')

    def test_abspath_validation_good_paths_trailing_slash(self):
        """Verifies setting an absolute path works via oslo.config."""
        CONF.set_override('file_url_allowed_paths', ['/var/'], 'conductor')
