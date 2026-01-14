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

import ironic.common.exception as exc
import ironic.common.trait_based_networking.base as tbn

from ironic.tests import base
import ironic.tests.unit.common.trait_based_networking.utils as tbn_test_utils

import itertools


class TraitBasedNetworkingBaseTestCase(base.TestCase):
    def test_filter_expression_str_representation(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_ADDRESS, tbn.Comparator.EQUALITY, "test"
        )
        self.assertEqual("port.address == 'test'", str(exp))

    def test_filter_object_missing_attribute_raises(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_ADDRESS, tbn.Comparator.EQUALITY, "test"
        )

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(address=None))
        net = tbn_test_utils.FauxNetwork()
        self.assertRaises(exc.TraitBasedNetworkingException, exp.eval,
                          obj, net)

    def test_filter_comparator_eval_equality(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_ADDRESS, tbn.Comparator.EQUALITY, "test"
        )

        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        net = tbn_test_utils.FauxNetwork()
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(address="bad")
        )
        self.assertFalse(exp.eval(obj, net))

    def test_filter_comparator_eval_inequality(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_ADDRESS, tbn.Comparator.INEQUALITY, "test"
        )

        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        net = tbn_test_utils.FauxNetwork()
        self.assertFalse(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(address="bad")
        )
        self.assertTrue(exp.eval(obj, net))

    def test_filter_comparator_eval_greater_than_or_equal(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_CATEGORY, tbn.Comparator.GT_OR_EQ, "test"
        )

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="test2")
        )
        net = tbn_test_utils.FauxNetwork()
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="test")
        )
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="abcd")
        )
        self.assertFalse(exp.eval(obj, net))

    def test_filter_comparator_eval_greater_than(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_CATEGORY, tbn.Comparator.GT, "test"
        )

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="test2")
        )
        net = tbn_test_utils.FauxNetwork()
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="test")
        )
        self.assertFalse(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(category="abcd")
        )
        self.assertFalse(exp.eval(obj, net))

    def test_filter_comparator_eval_less_than_or_equal(self):
        exp = tbn.SingleExpression(
            tbn.Variables.NETWORK_NAME, tbn.Comparator.LT_OR_EQ, "test"
        )
        port = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject()
        )

        net = tbn.Network("fake_id", "test2", [])
        self.assertFalse(exp.eval(port, net))

        net = tbn.Network("fake_id", "test", [])
        self.assertTrue(exp.eval(port, net))

        net = tbn.Network("fake_id", "abcd", [])
        self.assertTrue(exp.eval(port, net))

    def test_filter_comparator_eval_less_than(self):
        exp = tbn.SingleExpression(
            tbn.Variables.NETWORK_NAME, tbn.Comparator.LT, "test"
        )
        port = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject()
        )

        net = tbn.Network("fake_id", "test2", [])
        self.assertFalse(exp.eval(port, net))

        net = tbn.Network("fake_id", "test", [])
        self.assertFalse(exp.eval(port, net))

        net = tbn.Network("fake_id", "abcd", [])
        self.assertTrue(exp.eval(port, net))

    def test_filter_comparator_eval_prefix_match(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_VENDOR, tbn.Comparator.PREFIX_MATCH, "some"
        )
        net = tbn_test_utils.FauxNetwork()

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(vendor="some_vendor")
        )
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Port.from_ironic_port(
            tbn_test_utils.FauxPortLikeObject(vendor="another_vendor")
        )
        self.assertFalse(exp.eval(obj, net))

    def test_filter_comparator_eval_prefix_match_bad_variable_type(self):
        exp = tbn.SingleExpression(
            tbn.Variables.PORT_IS_PORT, tbn.Comparator.PREFIX_MATCH, "some"
        )
        net = tbn_test_utils.FauxNetwork()

        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        self.assertTrue(obj.is_port())
        self.assertRaises(exc.TraitBasedNetworkingException,
                          exp.eval, obj, net)

    def test_filter_operator_eval_and(self):
        exp = tbn.CompoundExpression(
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORT),
            tbn.Operator.AND,
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORT),
        )
        net = tbn_test_utils.FauxNetwork()

        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Portgroup.from_ironic_portgroup(
            tbn_test_utils.FauxPortLikeObject())
        self.assertFalse(exp.eval(obj, net))

    def test_filter_operator_eval_or(self):
        exp = tbn.CompoundExpression(
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORT),
            tbn.Operator.OR,
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORT),
        )
        net = tbn_test_utils.FauxNetwork()
        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        self.assertTrue(exp.eval(obj, net))

        obj = tbn.Portgroup.from_ironic_portgroup(
            tbn_test_utils.FauxPortLikeObject())
        self.assertFalse(exp.eval(obj, net))

        exp = tbn.CompoundExpression(
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORT),
            tbn.Operator.OR,
            tbn.FunctionExpression(tbn.Variables.PORT_IS_PORTGROUP),
        )
        obj = tbn.Port.from_ironic_port(tbn_test_utils.FauxPortLikeObject())
        self.assertTrue(exp.eval(obj, net))

    def test_attach_port_equality(self):
        self.assertEqual(
            tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_port_uuid",
                "fake_network_id"),
            tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_port_uuid",
                "fake_network_id")
        )
        self.assertNotEqual(
            tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_port_uuid",
                "fake_network_id"),
            tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "real_node_uuid",
                "fake_port_uuid",
                "fake_network_id")
        )

    def test_attach_portgroup_equality(self):
        self.assertEqual(
            tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_portgroup_uuid",
                "fake_network_id"),

            tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_portgroup_uuid",
                "fake_network_id")
        )

        self.assertNotEqual(
            tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "fake_portgroup_uuid",
                "fake_network_id"),
            tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse(
                        "port.vendor == 'clover'")
                ),
                "fake_node_uuid",
                "real_portgroup_uuid",
                "fake_network_id"),
        )

    def test_rendered_actions_type_mismatch_equality(self):
        types = [
            tbn.RenderedAction(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_node_uuid"
            ),
            tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_network_id",
                "fake_port_uuid",
                "fake_network_id"
            ),
            tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_node_uuid",
                "fake_portgroup_uuid",
                "fake_network_id"
            ),
            tbn.NoMatch(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_node_uuid",
                "didn't match"
            )
        ]

        # Make sure we can compare differing types of RenderedActions and not
        # blow up. Inequal types of RenderedActions must not evaluate as equal
        # with __eq__/==.
        for prod in itertools.product(types, repeat=2):
            if type(prod[0]) is type(prod[1]):
                self.assertEqual(prod[0], prod[1])
            else:
                self.assertNotEqual(prod[0], prod[1])

    def test_attach_class_hierarchy(self):
        attach_port = tbn.AttachPort(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORT,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_node_uuid",
                "fake_port_uuid",
                "fake_network_id")
        self.assertEqual("fake_port_uuid", attach_port.portlike_uuid())

        attach_portgroup = tbn.AttachPortgroup(
                tbn.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn.Actions.ATTACH_PORTGROUP,
                    tbn.FilterExpression.parse("port.vendor == 'cogwork'")),
                "fake_node_uuid",
                "fake_portgroup_uuid",
                "fake_network_id")

        self.assertEqual("fake_portgroup_uuid",
                         attach_portgroup.portlike_uuid())
