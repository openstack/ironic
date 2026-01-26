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

from ironic.common.trait_based_networking.loader import ConfigLoader

from ironic.tests import base

import tempfile
import time


class TraitBasedNetworkingConfigLoaderTestCase(base.TestCase):
    def test_config_loader(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        contents = ("CUSTOM_TRAIT_NAME:\n"
                    "  actions:\n"
                    "    - action: bond_ports\n"
                    "      filter: port.vendor == 'vendor_string'\n"
                    "      min_count: 2\n")
        with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.tmpdir.name,
                delete=False) as tmpfile:
            tmpfile.write(contents)
            tmpfile.close()

            self.config(trait_based_networking_config_file=tmpfile.name,
                        group='conductor')
            self.config(enable_trait_based_networking=True, group='conductor')

            cl = ConfigLoader()
            self.assertEqual(len(cl.traits), 1)

    def test_config_loader_refresh(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        contents = ("CUSTOM_TRAIT_NAME:\n"
                    "  actions:\n"
                    "    - action: bond_ports\n"
                    "      filter: port.vendor == 'vendor_string'\n"
                    "      min_count: 2\n")
        with tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.tmpdir.name,
                delete=False) as tmpfile:
            tmpfile.write(contents)
            tmpfile.close()

            self.config(trait_based_networking_config_file=tmpfile.name,
                        group='conductor')
            self.config(enable_trait_based_networking=True, group='conductor')

            cl = ConfigLoader()
            self.assertEqual(len(cl.traits), 1)
            self.assertEqual(cl.traits[0].name, "CUSTOM_TRAIT_NAME")

            # Refresh, nothing should change.
            old_mtime = cl._last_mtime
            cl.refresh()
            self.assertEqual(old_mtime, cl._last_mtime)
            self.assertEqual(len(cl.traits), 1)
            self.assertEqual(cl.traits[0].name, "CUSTOM_TRAIT_NAME")

            # Try to guarantee the mtime will change.
            time.sleep(1)

            with open(tmpfile.name, mode='w') as newfile:
                contents = ("CUSTOM_TRAIT_NAME_CHANGED:\n"
                    "  actions:\n"
                    "    - action: bond_ports\n"
                    "      filter: port.vendor == 'vendor_string'\n"
                    "      min_count: 2\n")
                newfile.write(contents)
                newfile.close()

                cl.refresh()
                self.assertNotEqual(old_mtime, cl._last_mtime)
                self.assertEqual(len(cl.traits), 1)
                self.assertEqual(cl.traits[0].name,
                                 "CUSTOM_TRAIT_NAME_CHANGED")
