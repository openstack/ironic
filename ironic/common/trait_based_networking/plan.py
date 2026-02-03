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
from ironic.conductor.task_manager import TaskManager
from ironic.objects.node import Node
from ironic.objects.port import Port
from ironic.objects.portgroup import Portgroup

from collections.abc import Callable
import itertools


def filter_out_attached_portlikes(
        portlikes: list[base.PrimordialPort],
        actions: list[base.AttachAction]) -> list[base.PrimordialPort]:
    """Filters out attached portlikes based on generated attach actions"""
    matched_uuids = set([action.portlike_uuid() for action in actions])
    return [portlike for portlike in portlikes
            if portlike.uuid not in matched_uuids]


def is_no_match_list(actions: list[base.RenderedAction]) -> bool:
    """Check if a list contains only a NoMatch action"""
    return len(actions) == 1 and isinstance(actions[0], base.NoMatch)


def plan_network(
        network_trait: base.NetworkTrait,
        node_uuid: str,
        node_ports: list[base.Port],
        node_portgroups: list[base.Portgroup],
        node_networks: list[base.Network]) -> list[base.RenderedAction]:
    """Plan the network of a node based on TBN traits

    :param network_trait: A single NetworkTrait to consider for planning.
    :param node_uuid: The UUID of the node to which this plan applies.
    :param ports: A list of Ports available to this node.
    :param portgroups: A list of Portgroups available to this node.
    :param node_networks: A list of networks available to this node.

    :returns: A list of RenderedActions which should be executed by the
    appropriate network driver.
    """
    rendered_actions = []

    # Order ports and portgroups by ID, newest first.
    node_ports.sort(key=lambda port: port.id, reverse=True)
    node_portgroups.sort(key=lambda portgroup: portgroup.id, reverse=True)

    portlikes = [base.Port.from_ironic_port(port) for port in node_ports]
    portgrouplikes = [base.Portgroup.from_ironic_portgroup(portgroup)
                      for portgroup in node_portgroups]

    for trait_action in network_trait.actions:
        new_actions = []
        match trait_action.action:
            case base.Actions.ATTACH_PORT:
                new_actions = _plan_attach_portlike(
                    trait_action, node_uuid, portlikes,
                    node_networks, 'port',
                    lambda action_args:
                        base.AttachPort(*action_args))

                if not is_no_match_list(new_actions):
                    portlikes = filter_out_attached_portlikes(portlikes,
                                                              new_actions)
            case base.Actions.ATTACH_PORTGROUP:
                new_actions = _plan_attach_portlike(
                    trait_action, node_uuid, portgrouplikes,
                    node_networks, 'portgroup',
                    lambda action_args:
                        base.AttachPortgroup(*action_args))

                if not is_no_match_list(new_actions):
                    portgrouplikes = filter_out_attached_portlikes(
                            portgrouplikes,
                            new_actions)

            # TODO(clif): Support bond_ports and group_and_attach_ports
            case _:
                new_actions = [base.NotImplementedAction(trait_action.action)]

        rendered_actions.extend(new_actions)

    return rendered_actions


def _plan_attach_portlike(
        trait_action: base.NetworkTrait,
        node_uuid: str,
        node_portlikes: list[base.PrimordialPort],
        node_networks: list[base.Network],
        type_name: str,
        action_func: Callable[[base.NetworkTrait, str, str, str],
                              base.RenderedAction]
        ) -> list[base.RenderedAction]:
    """Mainly called by plan_netwrok to determine which portlikes to attach"""
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


def all_no_match(actions: list[base.RenderedAction]) -> bool:
    """Check if a list of actions contains only NoMatch actions"""
    return all(isinstance(action, base.NoMatch) for action in actions)


def order_traits(traits: list[base.NetworkTrait]) -> list[base.NetworkTrait]:
    """Sort a list of traits in ascending trait.order"""
    return sorted(traits, key=lambda t: t.order)

# TODO(clif): Lifted from ironic.drivers.network.common to break a circular
# dependency. Maybe there's a common spot to lift this out to?
TENANT_VIF_KEY = 'tenant_vif_port_id'

def is_portlike_attached(portlike: Port | Portgroup) -> bool:
    """Check if a portlike is attached or not"""
    return (portlike.internal_info is not None
            and portlike.internal_info.get(TENANT_VIF_KEY) is not None)


def plan_vif_attach(traits: list[base.NetworkTrait],
                    task: TaskManager,
                    vif_info: dict) -> list[base.RenderedAction]:
    """Main entry point of TBN from _vif_attach_tbn in NeutronVIFPortIDMixIn

    :param traits: A list of NetworkTraits that apply to the node being
        considered.
    :param task: A TaskManager which contains important information about the
        node and network objects available.
    :param vif_info: Information about the network (aka vif) which TBN will
        use to plan actions.

    :returns: A list of RenderedActions which should be executed by the
    appropriate network driver.
    """
    # TODO(clif): Take cues from get_free_port_like_object where appropriate.
    net = base.Network.from_vif_info(vif_info)

    # Filter out already attached ports and portgroups.
    free_ports = [port for port in task.ports
                  if not is_portlike_attached(port)]

    free_portgroups = [pg for pg in task.portgroups
                       if not is_portlike_attached(pg)]

    for trait in order_traits(traits):
        actions = plan_network(
            trait,
            task.node.uuid,
            free_ports,
            free_portgroups,
            [net])
        # If no actions matched, try the next trait.
        if all_no_match(actions):
            continue
        else:
            return actions

    # TODO(clif): Maybe this should raise, because vif_attach raises when
    # it can't find a free port or portgroup to attach.
    return [base.NoMatch(base.TraitAction(
                            'plan_vif_attach',
                            base.Actions.ATTACH_PORT,
                            base.FilterExpression.parse(
                                "port.category == 'plan_vif_attach'")),
                        task.node.uuid,
                        _("Could not find an applicable port or portgroup to "
                          f"attach to network '{net.id}' in any applicable "
                          "trait."))]


def filter_traits_for_node(node: Node,
                           traits: list[base.NetworkTrait]
                           ) -> list[base.NetworkTrait]:
    """Return a list of NetworkTraits that apply to a node"""
    instance_traits = node.instance_info.get('traits') or []
    return [trait for trait in traits if trait.name in set(instance_traits)]
