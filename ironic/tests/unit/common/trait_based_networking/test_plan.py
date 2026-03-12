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
import ironic.common.trait_based_networking.plan as tbn_plan

from ironic.tests import base
import ironic.tests.unit.common.trait_based_networking.utils as utils

from ddt import data
from ddt import ddt
from ddt import unpack


def annotate(name, *args):
    class AnnotatedList(list):
        pass

    al = AnnotatedList([*args])
    al.__name__ = name
    return al


@ddt
class TraitBasedNetworkingPlanningTestCase(base.TestCase):
    @data(
        annotate(
            "Match a port",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORT,
                tbn_base.FilterExpression.parse("port.vendor == 'clover'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid",
                    vendor="clover",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.AttachPort(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'clover'")
                    ),
                    "fake_node_uuid",
                    "fake_port_uuid",
                    "fake_net_id")
            ],
            'port'
        ),
        annotate(
            "Match no ports",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORT,
                tbn_base.FilterExpression.parse(
                    "port.vendor == 'cogwork'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid",
                    vendor="clover",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid2",
                    vendor="clover",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.NoMatch(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'cogwork'")
                    ),
                    "fake_node_uuid",
                    "No (port, network) pairs matched rule."
                )
            ],
            'port'
        ),
        annotate(
            "Match a specific port based on order",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORT,
                tbn_base.FilterExpression.parse(
                    "port.vendor == 'cogwork'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid",
                    vendor="clover",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid3",
                    vendor="cogwork",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid2",
                    vendor="cogwork",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.AttachPort(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'cogwork'")
                    ),
                    "fake_node_uuid",
                    "fake_port_uuid3",
                    "fake_net_id"
                )
            ],
            'port'
        ),
        annotate(
            "Match one portgroup",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORTGROUP,
                tbn_base.FilterExpression.parse(
                    "port.physical_network == 'hypernet'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid",
                    vendor="clover",
                    physical_network="hypernet",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.AttachPortgroup(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORTGROUP,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'hypernet'"),
                    ),
                    "fake_node_uuid",
                    "fake_portgroup_uuid",
                    "fake_net_id")
            ],
            'portgroup'
        ),
        annotate(
            "Match no portgroups",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORTGROUP,
                tbn_base.FilterExpression.parse(
                    "port.category == 'blue'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid",
                    category="green",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid2",
                    category="red",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.NoMatch(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORTGROUP,
                        tbn_base.FilterExpression.parse(
                            "port.category == 'blue'")
                    ),
                    "fake_node_uuid",
                    "No (portgroup, network) pairs matched rule."
                )
            ],
            'portgroup'
        ),
        annotate(
            "Match a specific portgroup based on order",
            tbn_base.TraitAction(
                "CUSTOM_TRAIT",
                tbn_base.Actions.ATTACH_PORTGROUP,
                tbn_base.FilterExpression.parse(
                    "port.category == 'red'"),
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid",
                    vendor="clover",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid3",
                    category="red",
                ),
                utils.FauxPortLikeObject(
                    uuid="fake_portgroup_uuid2",
                    category="red",
                )
            ],
            [tbn_base.Network("fake_net_id", "network_name", frozenset())],
            [
                tbn_base.AttachPortgroup(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORTGROUP,
                        tbn_base.FilterExpression.parse(
                            "port.category == 'red'"),
                    ),
                    "fake_node_uuid",
                    "fake_portgroup_uuid3",
                    "fake_net_id")
            ],
            'portgroup'
        ),
        # TODO(clif): Test min_count and max_count
    )
    @unpack
    def test_plan_attach_portlike(
        self,
        trait_action: tbn_base.TraitAction,
        node_uuid: str,
        node_portlikes: list[utils.FauxPortLikeObject],
        node_networks: list[tbn_base.Network],
        expected_actions: list[tbn_base.RenderedAction],
            type_name: str):
        action_funcs = {
            'port': lambda args: tbn_base.AttachPort(*args),
            'portgroup': lambda args: tbn_base.AttachPortgroup(*args)
        }

        result_actions = tbn_plan._plan_attach_portlike(
            trait_action,
            node_uuid,
            node_portlikes,
            node_networks,
            type_name,
            action_funcs[type_name])
        self.assertEqual(expected_actions, result_actions)

    @data(
        annotate(
            "Attach one port",
            tbn_base.NetworkTrait(
                "CUSTOM_TRAIT",
                [
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'hypernet'"),
                    )
                ]
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid",
                    vendor="clover",
                    physical_network="hypernet",
                )
            ],
            [],
            [tbn_base.Network("fake_net_id", "fake_net_name", frozenset())],
            [
                tbn_base.AttachPort(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'hypernet'"),
                    ),
                    "fake_node_uuid",
                    "fake_port_uuid",
                    "fake_net_id")
            ],
        ),
        annotate(("Only one port attach generated for two actions matching"
                  "the same port"),
                 tbn_base.NetworkTrait(
                "CUSTOM_TRAIT",
                [
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'hypernet'"),
                    ),
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'clover'"),
                    )
                ]
            ),
            "fake_node_uuid",
            [
                utils.FauxPortLikeObject(
                    uuid="fake_port_uuid",
                    vendor="clover",
                    physical_network="hypernet",
                )
            ],
            [],
            [tbn_base.Network("fake_net_id", "fake_net_name", [])],
            [
                tbn_base.AttachPort(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'hypernet'"),
                    ),
                    "fake_node_uuid",
                    "fake_port_uuid",
                    "fake_net_id"),
                tbn_base.NoMatch(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.ATTACH_PORT,
                        tbn_base.FilterExpression.parse(
                            "port.vendor == 'clover'"),
                    ),
                    "fake_node_uuid",
                    "No (port, network) pairs matched rule.")
            ],
        ),
    )
    @unpack
    def test_plan_network(self,
                          network_trait: tbn_base.NetworkTrait,
                          node_uuid: str,
                          node_ports: list[tbn_base.Port],
                          node_portgroups: list[tbn_base.Portgroup],
                          node_networks: list,
                          expected_actions: list[tbn_base.RenderedAction]):
        result_actions = tbn_plan.plan_network(
            network_trait,
            node_uuid,
            node_ports,
            node_portgroups,
            node_networks)
        self.assertEqual(expected_actions, result_actions)

    @data(
        annotate("match a port",
                 [tbn_base.NetworkTrait(
                     "CUSTOM_TRAIT",
                     [
                         tbn_base.TraitAction(
                             "CUSTOM_TRAIT",
                             tbn_base.Actions.ATTACH_PORT,
                             tbn_base.FilterExpression.parse(
                                 "port.physical_network == 'hypernet'"),
                         )
                     ]
                 )],
                 utils.FauxTask(
                     utils.FauxNode(instance_info={
                        'traits': ['CUSTOM_TRAIT']
                     }),
                     [utils.FauxPortLikeObject(uuid="fake_port_uuid",
                                               physical_network="hypernet")],
                     []
                 ),
                 {
                     'id': 'fake_net_id',
                 },
                 [tbn_base.AttachPort(
                     tbn_base.TraitAction(
                         "CUSTOM_TRAIT",
                         tbn_base.Actions.ATTACH_PORT,
                         tbn_base.FilterExpression.parse(
                             "port.physical_network == 'hypernet'"),
                     ),
                     "fake_node_uuid",
                     "fake_port_uuid",
                     "fake_net_id"
                 )],
                 ),
        annotate("trait order matters",
                 [
                     tbn_base.NetworkTrait(
                         "CUSTOM_TRAIT_ORDER_SECOND",
                         [
                             tbn_base.TraitAction(
                                 "CUSTOM_TRAIT_ORDER_SECOND",
                                 tbn_base.Actions.ATTACH_PORT,
                                 tbn_base.FilterExpression.parse(
                                     "port.physical_network == 'hypernet'"),
                             )
                         ],
                         order=2,
                     ),
                     tbn_base.NetworkTrait(
                         "CUSTOM_TRAIT_ORDER_FIRST",
                         [
                             tbn_base.TraitAction(
                                 "CUSTOM_TRAIT_ORDER_FIRST",
                                 tbn_base.Actions.ATTACH_PORT,
                                 tbn_base.FilterExpression.parse(
                                     "port.physical_network == 'hypernet'"),
                             )
                         ],
                         order=1,
                     ),
                 ],
                 utils.FauxTask(
                     utils.FauxNode(
                         instance_info={
                             'traits': ['CUSTOM_TRAIT_ORDER_SECOND',
                                        'CUSTOM_TRAIT_ORDER_FIRST']}),
                     [utils.FauxPortLikeObject(
                         uuid="fake_port_uuid",
                         physical_network="hypernet")],
                     []
                 ),
                 {
                     'id': 'fake_net_id',
                 },
                 [
                     tbn_base.AttachPort(tbn_base.TraitAction(
                         "CUSTOM_TRAIT_ORDER_FIRST",
                         tbn_base.Actions.ATTACH_PORT,
                         tbn_base.FilterExpression.parse(
                             "port.physical_network == 'hypernet'"),
                     ),
                         "fake_node_uuid",
                         "fake_port_uuid",
                         "fake_net_id"
                     )
                 ],
                 ),
        annotate("already attached port not considered",
                 [
                     tbn_base.NetworkTrait(
                         "CUSTOM_TRAIT",
                         [
                             tbn_base.TraitAction(
                                 "CUSTOM_TRAIT",
                                 tbn_base.Actions.ATTACH_PORT,
                                 tbn_base.FilterExpression.parse(
                                     "port.physical_network == 'hypernet'"),
                             )
                         ]
                     ),
                 ],
                 utils.FauxTask(
                     utils.FauxNode(
                         instance_info={'traits': ['CUSTOM_TRAIT']}),
                     [utils.FauxPortLikeObject(
                         uuid="fake_port_uuid",
                         physical_network="hypernet",
                         internal_info={utils.TENANT_VIF_KEY: 'some_vif_id'})],
                     []
                 ),
                 {
                     'id': 'fake_net_id',
                 },
                 [
                     tbn_base.NoMatch(tbn_base.TraitAction(
                         'plan_vif_attach',
                         tbn_base.Actions.ATTACH_PORT,
                         tbn_base.FilterExpression.parse(
                             "port.category == 'plan_vif_attach'")),
                         'fake_node_uuid',
                         ("Could not find an applicable port or portgroup to "
                          "attach to network 'fake_net_id' in any applicable "
                          "trait."))
                 ],
                 ),
    )
    @unpack
    def test_plan_vif_attach(self,
                             traits: list[tbn_base.NetworkTrait],
                             task: utils.FauxTask,
                             vif_info: dict,
                             expected_actions: list[tbn_base.RenderedAction]):
        result_actions = tbn_plan.plan_vif_attach(traits, task, vif_info)
        self.assertEqual(expected_actions, result_actions)

    @data(
        annotate("port is attached",
                 utils.FauxPortLikeObject(
                     internal_info={tbn_plan.TENANT_VIF_KEY: 'vif_id'}),
                 True),
        annotate("port is not attached",
                 utils.FauxPortLikeObject(
                     internal_info={tbn_plan.TENANT_VIF_KEY: None}),
                 False),
        annotate("port is not attached, internal_info is None",
                 utils.FauxPortLikeObject(internal_info=None),
                 False),
    )
    @unpack
    def test_is_portlike_attached(
            self,
            portlike: utils.FauxPortLikeObject,
            expected_result: bool):
        self.assertEqual(expected_result,
                         tbn_plan.is_portlike_attached(portlike))

    @data(
        annotate("a dynamic portgroup is created and attached",
                 tbn_base.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                    tbn_base.FilterExpression.parse(
                        "port.physical_network == 'test_physnet' "
                        "&& network.name == 'test'"),
                    2,
                    2
                 ),
                 "fake_node_uuid",
                 [
                     utils.FauxPortLikeObject(),
                     utils.FauxPortLikeObject(uuid="fake_uuid2"),
                 ],
                 [utils.FauxNetwork(name="test")],
                 [tbn_base.GroupAndAttachPorts(
                     tbn_base.TraitAction(
                         "CUSTOM_TRAIT",
                         tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                         tbn_base.FilterExpression.parse(
                            "port.physical_network == 'test_physnet' "
                            "&& network.name == 'test'"),
                         2,
                         2
                     ),
                     "fake_node_uuid",
                     ["fake_uuid", "fake_uuid2"],
                     "fake_net_id")]),
        annotate("cannot create dynamic portgroup, too few ports matched",
                 tbn_base.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                    tbn_base.FilterExpression.parse(
                        "port.physical_network == 'test_physnet' "
                        "&& network.name == 'test'"),
                    2,
                    2,
                 ),
                 "fake_node_uuid",
                 [
                     utils.FauxPortLikeObject(physical_network='wrong'),
                     utils.FauxPortLikeObject(uuid="fake_uuid2"),
                 ],
                 [utils.FauxNetwork(name="test")],
                 [tbn_base.NoMatch(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'test_physnet' "
                            "&& network.name == 'test'"),
                        2,
                        2
                    ),
                    "fake_node_uuid",
                    ("Couldn't match enough ports to form a "
                     "dynamic portgroup for node 'fake_node_uuid'."
                     "Minimum ports needed is 2, and 1 ports matched.")
                 )]),
        annotate("a suitable network couldn't be found",
                 tbn_base.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                    tbn_base.FilterExpression.parse(
                        "port.physical_network == 'test_physnet' "
                        "&& network.name == 'test'"),
                    2,
                    2
                 ),
                 "fake_node_uuid",
                 [
                     utils.FauxPortLikeObject(),
                     utils.FauxPortLikeObject(uuid="fake_uuid2"),
                 ],
                 [utils.FauxNetwork(name="bad_name")],
                 [tbn_base.NoMatch(
                    tbn_base.TraitAction(
                        "CUSTOM_TRAIT",
                        tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                        tbn_base.FilterExpression.parse(
                            "port.physical_network == 'test_physnet' "
                            "&& network.name == 'test'"),
                        2,
                        2
                    ),
                    "fake_node_uuid",
                    ("Enough ports matched to form a dynamic "
                     "portgroup for node 'fake_node_uuid'. Unfortunately "
                     "no suitable networks were found to attach.")
                 )]),
        annotate("only allow available_for_dynamic_portgroup",
                 tbn_base.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                    tbn_base.FilterExpression.parse(
                        "network.name == 'test'"),
                    2,
                    2
                 ),
                 "fake_node_uuid",
                 [
                     utils.FauxPortLikeObject(
                         available_for_dynamic_portgroup=False),
                     utils.FauxPortLikeObject(uuid="fake_uuid2"),
                     utils.FauxPortLikeObject(uuid="fake_uuid3"),
                 ],
                 [utils.FauxNetwork(name="test")],
                 [tbn_base.GroupAndAttachPorts(
                     tbn_base.TraitAction(
                         "CUSTOM_TRAIT",
                         tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                         tbn_base.FilterExpression.parse(
                            "network.name == 'test'"),
                         2,
                         2
                     ),
                     "fake_node_uuid",
                     ["fake_uuid2", "fake_uuid3"],
                     "fake_net_id")]),

        annotate("all ports have the same physical_network",
                 tbn_base.TraitAction(
                    "CUSTOM_TRAIT",
                    tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                    tbn_base.FilterExpression.parse("network.name == 'test'"),
                    2,
                    2
                 ),
                 "fake_node_uuid",
                 [
                     utils.FauxPortLikeObject(physical_network='alpha'),
                     utils.FauxPortLikeObject(uuid="fake_uuid2",
                                              physical_network='beta'),
                     utils.FauxPortLikeObject(uuid="fake_uuid3",
                                              physical_network='alpha'),
                 ],
                 [utils.FauxNetwork(name="test")],
                 [tbn_base.GroupAndAttachPorts(
                     tbn_base.TraitAction(
                         "CUSTOM_TRAIT",
                         tbn_base.Actions.GROUP_AND_ATTACH_PORTS,
                         tbn_base.FilterExpression.parse(
                            "network.name == 'test'"),
                         2,
                         2
                     ),
                     "fake_node_uuid",
                     # Only 'alpha' physical_network ports are picked
                     ["fake_uuid", "fake_uuid3"],
                     "fake_net_id")]),
    )
    @unpack
    def test__plan_group_and_attach_ports(
            self,
            trait: tbn_base.NetworkTrait,
            node_uuid: str,
            node_portlikes: list[utils.FauxPortLikeObject],
            node_networks: list[tbn_base.Network],
            expected_actions: list[tbn_base.RenderedAction]):
        self.assertEqual(expected_actions,
                         tbn_plan._plan_group_and_attach_ports(
                             trait, node_uuid, node_portlikes,
                             node_networks))
