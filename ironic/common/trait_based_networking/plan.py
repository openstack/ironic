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


from ironic.common.i18n import _
from ironic.common.trait_based_networking import base

from collections.abc import Callable
import itertools


def plan_network(
        network_trait: base.NetworkTrait,
        node_uuid: str,
        node_ports: list[base.Port],
        node_portgroups: list[base.Portgroup],
        node_networks: list[base.Network]) -> list[base.RenderedAction]:
    rendered_actions = []

    # Order ports and portgroups by ID, newest first.
    node_ports.sort(key=lambda port: port.id, reverse=True)
    node_portgroups.sort(key=lambda portgroup: portgroup.id, reverse=True)

    portlikes = [base.Port.from_ironic_port(port) for port in node_ports]
    portgrouplikes = [base.Portgroup.from_ironic_portgroup(portgroup)
                      for portgroup in node_portgroups]

    for trait_action in network_trait.actions:
        match trait_action.action:
            case base.Actions.ATTACH_PORT:
                rendered_actions.extend(
                    plan_attach_portlike(
                        trait_action, node_uuid, portlikes,
                        node_networks, 'port',
                        lambda action_args:
                            base.AttachPort(*action_args)))
            case base.Actions.ATTACH_PORTGROUP:
                rendered_actions.extend(
                    plan_attach_portlike(
                        trait_action, node_uuid, portgrouplikes,
                        node_networks, 'portgroup',
                        lambda action_args:
                            base.AttachPortgroup(*action_args)))
            # TODO(clif): Support bond_ports and group_and_attach_ports
            case _:
                rendered_actions.append(
                    base.NotImplementedAction(trait_action.action))

    return rendered_actions


def plan_attach_portlike(
        trait_action: base.NetworkTrait,
        node_uuid: str,
        node_portlikes: list[base.PrimordialPort],
        node_networks: list[base.Network],
        type_name: str,
        action_func: Callable[[base.NetworkTrait, str, str, str],
                              base.RenderedAction]
        ) -> list[base.RenderedAction]:
    actions = []
    for (portlike, network) in itertools.product(node_portlikes,
                                                 node_networks):
        if trait_action.matches(portlike, network):
            actions.append(action_func((trait_action,
                                       node_uuid,
                                       portlike.uuid,
                                       network.id)))
            # No minimum count means match the first one.
            if trait_action.min_count is None:
                break
            if trait_action.max_count == len(actions):
                break

    if len(actions) == 0:
        return [base.NoMatch(trait_action,
                             node_uuid,
                             _(f"No ({type_name}, network) pairs matched "
                               "rule."))]

    if (trait_action.min_count is not None
        and len(actions) < trait_action.min_count):
        return [base.NoMatch(trait_action,
                             node_uuid,
                             _(f"Not enough ({type_name}, network) pairs "
                               "matched to meet minimum count threshold. "
                               f"Matched {len(actions)} but min_count is "
                               f"{trait_action.min_count}."))]

    return actions
