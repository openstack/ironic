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

import enum

import ironic.common.exception as exc
from ironic.common.i18n import _
import ironic.common.trait_based_networking.grammar.parser as tbn_parser


class Operator(enum.Enum):
    """A FilterExpression Operator

    Represents a boolean operator (AND, OR) between two expressions in a
    filter expression.
    """
    AND = "&&"
    OR = "||"

    def eval(self, variable, value):
        # NOTE(clif): These can operate on string values, and return the values
        # themselves instead of a boolean!
        match self.name:
            case self.AND.name:
                return variable and value
            case self.OR.name:
                return variable or value

    def __str__(self):
        return self.value


class Comparator(enum.Enum):
    """A FilterExpression Comparator

    Comparators test mathematical-esque relations between a variable and a
    string.
    """
    EQUALITY = "=="
    INEQUALITY = "!="
    GT_OR_EQ = ">="
    GT = ">"
    LT_OR_EQ = "<="
    LT = "<"
    PREFIX_MATCH = "=~"

    def eval(self, variable, value):
        # TODO(clif): Should we some sort of checking of variable type vs
        # requested operator?
        match self.name:
            case self.EQUALITY.name:
                return variable == value
            case self.INEQUALITY.name:
                return variable != value
            case self.GT_OR_EQ.name:
                return variable >= value
            case self.GT.name:
                return variable > value
            case self.LT_OR_EQ.name:
                return variable <= value
            case self.LT.name:
                return variable < value
            case self.PREFIX_MATCH.name:
                if isinstance(variable, str):
                    return variable.startswith(value)
                raise exc.TBNComparatorPrefixMatchTypeMismatch(
                    _("Prefix match can only be used with variables "
                      "of type string")
                )

    def __str__(self):
        return self.value


class Actions(enum.Enum):
    """Represents actions recognized by Trait Based Networking"""
    ATTACH_PORT = "attach_port"
    ATTACH_PORTGROUP = "attach_portgroup"
    BOND_PORTS = "bond_ports"
    GROUP_AND_ATTACH_PORTS = "group_and_attach_ports"


class Variables(enum.Enum):
    """Represents a variable (or function) used by FilterExpressions

    Values of variables are drawn from network-related objects like ports,
    portgroups, or networks (aka vifs).
    """
    NETWORK_NAME = "network.name"
    NETWORK_TAGS = "network.tags"

    PORT_ADDRESS = "port.address"
    PORT_CATEGORY = "port.category"
    PORT_IS_PORT = "port.is_port"
    PORT_IS_PORTGROUP = "port.is_portgroup"
    PORT_PHYSICAL_NETWORK = "port.physical_network"
    PORT_VENDOR = "port.vendor"

    def object_name(self):
        return str(self).split(".")[0]

    def attribute_name(self):
        return str(self).split(".")[1]

    def __str__(self):
        return self.value


def _retrieve_attribute(attribute_name, tbn_obj):
    """Helper method to get an attribute from a TBN related object"""
    attribute = getattr(tbn_obj, attribute_name, None)

    if attribute is None:
        raise exc.TBNAttributeRetrievalException(attr_name=attribute_name)

    return attribute


class FunctionExpression(object):
    """A callable function from within a FilterExpression

    Used to query objects to determine if they pass a FilterExpression or not.
    """
    def __init__(self, variable):
        self._variable = variable

    def eval(self, port, network):
        tbn_obj = port if self._variable.object_name() == "port" else network
        attr_name = self._variable.attribute_name()
        attr_func = _retrieve_attribute(attr_name, tbn_obj)
        return attr_func()

    def __str__(self):
        return f"{self._variable}"


class SingleExpression(object):
    """A single expression from within a FilterExpression

    A single expression consists of a variable name, a comparator, and a
    string literal. For example:
        port.vendor == "purple"
    In this example, When eval()ed against a port whose vendor is "purple"
    this expression will return True. Otherwise the expression will return
    False.
    """
    def __init__(self, variable, comparator, literal):
        self._variable = variable
        self._comparator = comparator
        self._literal = literal

    def eval(self, port, network):
        tbn_obj = port if self._variable.object_name() == "port" else network
        attr_name = self._variable.attribute_name()
        attribute = _retrieve_attribute(attr_name, tbn_obj)
        return self._comparator.eval(attribute, self._literal)

    def __str__(self):
        return f"{self._variable} {self._comparator} '{self._literal}'"


class CompoundExpression(object):
    """A compound expression found within a FilterExpression

    A compound expression consists of a left-hand expression and a right-hand
    expression joined by a boolean operator.
    """
    def __init__(self, left_expression, operator, right_expression):
        self._left_expression = left_expression
        self._operator = operator
        self._right_expression = right_expression

    def eval(self, port, network):
        left_result = self._left_expression.eval(port, network)
        right_result = self._right_expression.eval(port, network)
        match self._operator:
            case Operator.OR:
                return left_result or right_result
            case Operator.AND:
                return left_result and right_result

    def __str__(self):
        return (f"{self._left_expression} {self._operator} "
                f"{self._right_expression}")


class ParenExpression(object):
    """Represents an parentheses expression found in a FilterExpression

    Aids in logically grouping and evaluating expressions before others.
    """
    def __init__(self, expression):
        self._expression = expression

    def eval(self, port, network):
        return self._expression.eval(port, network)

    def __str__(self):
        return f"({self._expression})"


class FilterExpression(object):
    """Encompasses filters found in TraitActions

    Used to filter (port, network) pairs to apply actions which pass the
    filter.

    Use FilterExpression.parse to transform a string containing a
    grammatically correct expression into a fully parsed FilterExpression
    object.

    See FILTER_EXPRESSION_GRAMMAR in
    ironic.common.trait_based_networking.grammar.parser for full understanding
    of how these expressions are parsed.
    """
    def __init__(self, expression):
        self._expression = expression

    def eval(self, port, network):
        return self._expression.eval(port, network)

    def __str__(self):
        return f"{self._expression}"

    @classmethod
    def parse(cls, expression):
        tree = tbn_parser.FilterExpressionParser.parse(expression)
        return tbn_parser.FilterExpressionTransformer().transform(tree)

    def __eq__(self, other):
        return str(self) == str(other)


class TraitAction(object):
    """An action defined by a NetworkTrait

    Each action contains a filter (FilterExpression) that determines which
    (port, network) pairs the action can apply to.
    """
    NECESSARY_KEYS = [
        'action',
        'filter',
    ]
    OPTIONAL_KEYS = [
        'max_count',
        'min_count',
    ]
    ALL_KEYS = OPTIONAL_KEYS + NECESSARY_KEYS

    def __init__(self, trait_name, action, filter_expression,
                 min_count=None, max_count=None):
        """Init the TraitAction

        :param trait_name: Name of the trait this action belongs to.
        :param action: An Actions object
        :param filter_expression: A FilterExpression object
        :param min_count: An optional minimum number of matches this action
            must meet before it can be applied.
        :param max_count: An optional maximum number of matches this action
            can apply to.
        """
        self.trait_name = trait_name
        self.action = action
        self.filter_expression = filter_expression
        self.min_count = min_count
        self.max_count = max_count

    def matches(self, portlike, network):
        """Check if filter expression matches the port, network pairing."""
        return self.filter_expression.eval(portlike, network)

    def __eq__(self, other):
        return (self.trait_name == other.trait_name
                and self.action == other.action
                and self.filter_expression == other.filter_expression
                and self.min_count == other.min_count
                and self.max_count == other.max_count)


class NetworkTrait(object):
    """Represents an entire Trait for Trait Based Networking

    Each trait can have many actions. Traits can be ordered explicitly if so
    desired.
    """
    def __init__(self, name, actions, order=1):
        """Init a NetworkTrait

        :param name: The named of the trait
        :param actions: A list of TraitActions which belong to this trait
        :param order: An optional integer used to determine the explicit
        ordering of application of traits. Used to sort and apply traits in
        ascending order.
        """
        self.name = name
        self.actions = actions
        self.order = order

    def __eq__(self, other):
        if self.name != other.name:
            return False

        for action in self.actions:
            match_found = False
            for other_action in other.actions:
                if action == other_action:
                    match_found = True
                    break

            if not match_found:
                return False

        return self.order == other.order


class PrimordialPort(object):
    """A set of common attributes belonging to both Ports and Portgroups"""
    def __init__(self, ironic_port_like_obj):
        # NOTE(clif): Both ironic port and portgroups should support the
        # attributes below.
        self.id = ironic_port_like_obj.id
        self.uuid = ironic_port_like_obj.uuid
        self.address = ironic_port_like_obj.address
        self.category = ironic_port_like_obj.category
        self.physical_network = ironic_port_like_obj.physical_network
        self.vendor = ironic_port_like_obj.vendor


class Port(PrimordialPort):
    """A Port used internally to query and match to TraitActions"""
    @classmethod
    def from_ironic_port(cls, ironic_port):
        return Port(ironic_port)

    def is_port(self):
        return True

    def is_portgroup(self):
        return False


class Portgroup(PrimordialPort):
    """A Portgroup used internally to query and match to TraitActions"""
    @classmethod
    def from_ironic_portgroup(cls, ironic_portgroup):
        return Portgroup(ironic_portgroup)

    def is_port(self):
        return False

    def is_portgroup(self):
        return True


class Network(object):
    """A Network (aka vif)

    Used to match against TraitAction FilterExpressions
    """
    def __init__(self, network_id, name, tags):
        self.id = network_id
        self.name = name
        self.tags = tags

    @classmethod
    def from_vif_info(cls, vif_info):
        """Helper method to create Networks from vif_info dictionaries"""
        return Network(vif_info['id'], # vif_info is guaranteed to have 'id'.
                       vif_info.get('name'),
                       vif_info.get('tags'))


class RenderedAction(object):
    """A base class for Actions which are ready to apply"""
    def __init__(self, trait_action, node_uuid):
        self._trait_action = trait_action
        self._node_uuid = node_uuid

    def __eq__(self, other):
        return (self._trait_action == other._trait_action
                and self._node_uuid == other._node_uuid)


class AttachAction(RenderedAction):
    """Base class for actions which will attach objects to networks"""
    def __init__(self, trait_action, node_uuid):
        super().__init__(trait_action, node_uuid)

    def portlike_uuid(self):
        return self._get_portlike_uuid()

    def get_portlike_object(self, task):
        return self._get_portlike_object(task)


class AttachPort(AttachAction):
    """Attach a port to a network

    Contains all the necessary information to attach a port to a network (vif)
    """
    def __init__(self, trait_action, node_uuid, port_uuid, network_id):
        super().__init__(trait_action, node_uuid)
        self._port_uuid = port_uuid
        self._network_id = network_id

    def _get_portlike_object(self, task):
        for port in task.ports:
            if port.uuid == self._port_uuid:
                return port
        return None

    def _get_portlike_uuid(self):
        return self._port_uuid

    def __str__(self):
        return _(f"Attach port '{self._port_uuid}' on node "
                 f"'{self._node_uuid}' to network '{self._network_id}' "
                 f"via trait {self._trait_action.trait_name}")

    def __eq__(self, other):
        return (isinstance(other, AttachPort)
                and self._port_uuid == other._port_uuid
                and self._network_id == other._network_id
                and super().__eq__(other))


class AttachPortgroup(AttachAction):
    """Attach a portgroup to a network

    Contains all the necessary information to attach a portgroup to a network
    (vif)
    """
    def __init__(self, trait_action, node_uuid, portgroup_uuid, network_id):
        super().__init__(trait_action, node_uuid)
        self._portgroup_uuid = portgroup_uuid
        self._network_id = network_id

    def _get_portlike_object(self, task):
        for portgroup in task.portgroups:
            if portgroup.uuid == self._portgroup_uuid:
                return portgroup
        return None

    def _get_portlike_uuid(self):
        return self._portgroup_uuid

    def __str__(self):
        return _(f"Attach portgroup '{self._portgroup_uuid}' on node "
                 f"'{self._node_uuid}' to network '{self._network_id}'"
                 f"via trait {self._trait_action.trait_name}")

    def __eq__(self, other):
        return (isinstance(other, AttachPortgroup)
                and self._portgroup_uuid == other._portgroup_uuid
                and self._network_id == other._network_id
                and super().__eq__(other))


class NoMatch(RenderedAction):
    """Returned by network planning when a trait action finds no matches"""
    def __init__(self, trait_action, node_uuid, reason):
        super().__init__(trait_action, node_uuid)
        self._reason = reason

    def __str__(self):
        return _(f"No match found for action under trait "
                 f"'{self._trait_action.trait_name}' "
                 f"on node '{self._node_uuid}': {self._reason}")

    def __eq__(self, other):
        return (isinstance(other, NoMatch)
                and self._reason == other._reason
                and super().__eq__(other))


class NotImplementedAction(RenderedAction):
    """Returned by network planning if an action has not been implemented"""
    def __init__(self, action):
        self._action = action

    def __str__(self):
        return _(f"Action '{self._action.value}' not yet implemented.")
