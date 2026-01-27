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

from ironic.common.trait_based_networking import defaults
from ironic.common.trait_based_networking import loader

from ironic.tests import base

import tempfile


class TraitBasedNetworkingDefaultsTestCase(base.TestCase):
    def test_default_network_trait_draws_from_config_file(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        contents = ("CUSTOM_DEFAULT_TBN_TRAIT:\n"
                    "  actions:\n"
                    "    - action: attach_port\n"
                    "      filter: port.vendor == 'vendor_string'\n")
        with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.tmpdir.name,
                delete=False) as tmpfile:
            tmpfile.write(contents)
            tmpfile.close()

        self.config(trait_based_networking_config_file=tmpfile.name,
                    group='conductor')
        self.config(enable_trait_based_networking=True, group='conductor')

        result = defaults.default_network_trait()
        self.assertEqual(result.name, defaults.DEFAULT_TRAIT_NAME)
        self.assertEqual(loader.tbn_config_file_traits()[0], result)

    def test_default_network_trait_draws_from_defaults(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        contents = ("CUSTOM_TRAIT:\n"
                    "  actions:\n"
                    "    - action: attach_port\n"
                    "      filter: port.vendor == 'vendor_string'\n")
        with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.tmpdir.name,
                delete=False) as tmpfile:
            tmpfile.write(contents)
            tmpfile.close()

        self.config(trait_based_networking_config_file=tmpfile.name,
                    group='conductor')
        self.config(enable_trait_based_networking=True, group='conductor')

        result = defaults.default_network_trait()
        self.assertEqual(result.name, defaults.DEFAULT_TRAIT_NAME)
        self.assertEqual(result, defaults.DEFAULT_TRAIT)
