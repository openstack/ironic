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

import ironic.common.trait_based_networking.base as tbn
import ironic.common.trait_based_networking.grammar.parser as tbn_parser

from ironic.tests import base
import ironic.tests.unit.common.trait_based_networking.utils as tbn_test_utils

import lark

from dataclasses import dataclass


class TraitBasedNetworkingFilterParserTestCase(base.TestCase):
    def test_grammar_acceptable_to_lark(self):
        parser = lark.Lark(
            tbn_parser.FILTER_EXPRESSION_GRAMMAR,
            start=tbn_parser.FILTER_EXPRESSION_GRAMMAR_START_RULE)
        self.assertIsNotNone(parser)

    def test_filter_expression_parser(self):
        @dataclass
        class SubTestCase(object):
            description: str
            expression: str
            port_args: list[dict]
            # TODO(clif): Also test networks here
            expected_eval_result: list[bool]

        subtests = [
            SubTestCase(
                "Basic single expression",
                "port.vendor == 'vendor_string'",
                [{"vendor": "vendor_string"}],
                [True],
            ),
            SubTestCase(
                "Compound expressions with parenthesis",
                (
                    "port.vendor == 'green' "
                    "&& port.category == 'storage' "
                    "&& (port.physical_network =~ 'storage' "
                    "|| port.address == '192.168.1.1')"
                ),
                [
                    {
                        "vendor": "green",
                        "address": "192.168.1.1",
                        "physical_network": "storagenet",
                        "category": "storage",
                    },
                    {
                        "vendor": "green",
                        "address": "192.168.1.1",
                        "physical_network": "othernet",
                        "category": "storage",
                    },
                    {
                        "vendor": "brown",
                        "address": "192.168.1.1",
                        "physical_network": "storagenet",
                        "category": "storage_alpha",
                    },
                ],
                [True, True, False],
            ),
            SubTestCase(
                "Part 1 ensuring parens are respected",
                (
                    "(port.vendor == 'green' "
                    "&& port.category == 'test') "
                    "|| port.address == '192.168.1.1'"
                ),
                [
                    {
                        "vendor": "brown",
                        "address": "192.168.1.1",
                        "category": "prod",
                    },
                    {
                        "vendor": "brown",
                        "address": "192.168.1.1",
                        "category": "prod",
                    },
                ],
                [True, True],
            ),
            SubTestCase(
                "Part 2 ensuring parens are respected",
                (
                    "port.vendor == 'green' "
                    "&& (port.category == 'test' "
                    "|| port.address == '192.168.1.1')"
                ),
                [
                    {
                        "vendor": "brown",
                        "address": "192.168.1.1",
                        "category": "prod",
                    },
                    {
                        "vendor": "brown",
                        "address": "192.168.1.1",
                        "category": "prod",
                    },
                ],
                [False, False],
            ),
            # TODO(clif): Test case about network variables
        ]

        for subtest in subtests:
            with self.subTest(subtest=subtest):
                # Assert expression parses correctly.
                result = tbn.FilterExpression.parse(subtest.expression)
                self.assertIsNotNone(result)

                # Assert the transformation of the parse tree to
                # trait based networking objects renders back to the original
                # expression exactly.
                self.assertEqual(str(result), subtest.expression)

                self.assertEqual(
                    len(subtest.port_args), len(subtest.expected_eval_result)
                )

                # Assert the evaluation of the expression returns the correct
                # result.
                for i in range(0, len(subtest.port_args)):
                    self.assertEqual(
                        result.eval(
                            tbn.Port.from_ironic_port(
                                tbn_test_utils.FauxPortLikeObject(
                                    **subtest.port_args[i]
                                )
                            ),
                            tbn.Network("test_net_id", "test_network", []),
                        ),
                        subtest.expected_eval_result[i],
                    )
