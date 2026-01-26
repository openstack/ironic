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

import ironic.common.trait_based_networking.base as tbn_base
import ironic.common.trait_based_networking.config_file as cf

from ironic.tests import base

from dataclasses import dataclass
import tempfile


EXAMPLE_CONFIG_FILE_LOCATION = "etc/ironic/trait_based_networks.yaml.sample"


class TraitBasedNetworkingConfigFileTestCase(base.TestCase):
    def setUp(self):
        super(TraitBasedNetworkingConfigFileTestCase, self).setUp()
        self.tmpdir = tempfile.TemporaryDirectory()

        self.addTypeEqualityFunc(
            tbn_base.NetworkTrait,
            lambda first, second, msg=None: first == second
        )

    def test_load_example_config_file(self):
        config_file = cf.ConfigFile(EXAMPLE_CONFIG_FILE_LOCATION)
        self.assertIsNotNone(config_file)
        self.assertTrue(config_file.validate()[0])
        config_file.parse()

    def test_validate(self):
        @dataclass
        class SubTestCase(object):
            description: str
            contents: str
            expected_valid: bool
            expected_reasons: list[str]

        subtests = [
            SubTestCase(
                "Valid - single trait",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  order: 1\n"
                 "  actions:\n"
                 "    - action: bond_ports\n"
                 "      filter: port.vendor == 'vendor_string'\n"
                 "      min_count: 2\n"),
                True,
                [],
            ),
            SubTestCase(
                "Valid - Several traits",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    - action: bond_ports\n"
                 "      filter: port.vendor == 'vendor_string'\n"
                 "      min_count: 2\n"
                 "CUSTOM_TRAIT_2:\n"
                 "  actions:\n"
                 "    - action: attach_port\n"
                 "      filter: port.vendor != 'vendor_string'\n"
                 "      max_count: 2\n"
                 "CUSTOM_TRAIT_3:\n"
                 "  actions:\n"
                 "    - action: attach_port\n"
                 "      filter: port.vendor != 'vendor_string'\n"
                 "      max_count: 2\n"),
                True,
                [],
            ),
            SubTestCase(
                "Invalid - Missing trait has required entry missing",
                ("trait_name:\n"
                 "  actions:\n"
                 "  - action: bond_ports\n"),
                False,
                ["'trait_name' trait is missing 'filter' key"],
            ),
            SubTestCase(
                "Invalid - Unrecognized trait entry",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    - action: bond_ports\n"
                 "      filter: port.vendor == 'vendor_string'\n"
                 "      min_count: 2\n"
                 "      wrong: hi\n"),
                False,
                [("'CUSTOM_TRAIT_NAME' trait action has unrecognized key "
                 "'wrong'")],
            ),
            SubTestCase(
                "Invalid - Unrecognized action",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    - action: invalid\n"
                 "      filter: port.vendor == 'vendor_string'\n"
                 "      min_count: 2\n"),
                False,
                ["'CUSTOM_TRAIT_NAME' trait action has unrecognized action "
                 "'invalid'"],
            ),
            SubTestCase(
                ("Invalid - trait actions does not consist of a list of "
                 "actions"),
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    action: bond_ports\n"
                 "    filter: port.vendor == 'vendor_string'\n"
                 "    min_count: 2\n"),
                False,
                [("'CUSTOM_TRAIT_NAME.actions' does not consist of a list "
                  "of actions")],
            ),
            SubTestCase(
                "Invalid - trait action has malformed filter expression",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    - action: bond_ports\n"
                 "      filter: port.vendor &= 'vendor_string'\n"
                 "      min_count: 2\n"),
                False,
                [("'CUSTOM_TRAIT_NAME' trait action has malformed filter "
                  "expression: 'port.vendor &= 'vendor_string''")],
            ),
            SubTestCase(
                "Invalid - several things wrong",
                ("CUSTOM_TRAIT_NAME:\n"
                 "  actions:\n"
                 "    - filter: port.vendor &= 'vendor_string'\n"
                 "      min_count: 2\n"
                 "      wrong: oops\n"),
                False,
                [("'CUSTOM_TRAIT_NAME' trait action has malformed filter "
                  "expression: 'port.vendor &= 'vendor_string''"),
                 "'CUSTOM_TRAIT_NAME' trait is missing 'action' key",
                 ("'CUSTOM_TRAIT_NAME' trait action has unrecognized key "
                  "'wrong'")],
            ),
        ]

        for subtest in subtests:
            with self.subTest(subtest=subtest):
                with tempfile.NamedTemporaryFile(
                        mode='w',
                        dir=self.tmpdir.name,
                        delete=False) as tmpfile:
                    tmpfile.write(subtest.contents)
                    tmpfile.close()
                    config_file = cf.ConfigFile(tmpfile.name)
                    valid, reasons = config_file.validate()
                    self.assertEqual(subtest.expected_valid, valid)
                    self.assertCountEqual(subtest.expected_reasons, reasons)

    def test_parse(self):
        contents = (
            "CUSTOM_TRAIT_NAME:\n"
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
            config_file = cf.ConfigFile(tmpfile.name)
            valid, reasons = config_file.validate()
            self.assertTrue(valid)
            self.assertCountEqual(reasons, [])

            config_file.parse()
            result = config_file.traits()

            self.assertCountEqual(result, [
                tbn_base.NetworkTrait(
                    "CUSTOM_TRAIT_NAME",
                    [tbn_base.TraitAction(
                        "CUSTOM_TRAIT_NAME",
                        tbn_base.Actions("bond_ports"),
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'vendor_string'"),
                        min_count=2)]
                )
            ])
