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

from ironic.common import config
from ironic.common import exception
from ironic.conf import CONF
from ironic.tests.base import TestCase


class CommonConfigTestCase(TestCase):
    def test_validate_opts_using_custom_ironic_config_types(self):
        # Should run without throwing an exception, since defaults for these
        # options should validate.
        self.assertFalse(CONF.conductor.disable_kernel_parameter_parsing)
        self.assertIsNone(
            config.validate_opts_using_custom_ironic_config_types())

    def test_validate_image_server_auth_opts_noauth(self):
        # Default strategy is noauth; credentials are ignored.
        self.config(image_server_auth_strategy='noauth', group='deploy')
        self.config(image_server_password='password', group='deploy')
        self.assertIsNone(config.validate_image_server_auth_opts())

    def test_validate_image_server_auth_opts_no_password(self):
        self.config(image_server_auth_strategy='http_basic', group='deploy')
        self.assertIsNone(config.validate_image_server_auth_opts())

    def test_validate_image_server_auth_opts_with_hosts(self):
        self.config(image_server_auth_strategy='http_basic', group='deploy')
        self.config(image_server_password='password', group='deploy')
        self.config(image_server_auth_hosts=['images.example.com'],
                    group='deploy')
        self.assertIsNone(config.validate_image_server_auth_opts())

    def test_validate_image_server_auth_opts_permit_unknown(self):
        self.config(image_server_auth_strategy='http_basic', group='deploy')
        self.config(image_server_password='password', group='deploy')
        self.config(image_server_auth_permit_unknown_hosts=True,
                    group='deploy')
        self.assertIsNone(config.validate_image_server_auth_opts())

    def test_validate_image_server_auth_opts_missing_host_policy(self):
        self.config(image_server_auth_strategy='http_basic', group='deploy')
        self.config(image_server_password='password', group='deploy')
        self.assertRaises(exception.ConfigInvalid,
                          config.validate_image_server_auth_opts)
