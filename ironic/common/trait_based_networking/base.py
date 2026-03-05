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

from abc import abstractmethod
from dataclasses import dataclass
from dataclasses import fields
from dataclasses import MISSING
import enum
from typing import ClassVar

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


# Allows special case FilterExpression evaluations where Port does not
# matter. In these cases a port  with this name will always evaluate to
# True.
UNIVERSAL_PORT_CATEGORY = "__UNIVERSAL_PORT"


def _is_universal_port(port):
    """Check if the port is a special Port that always passes filter"""
    return isinstance(port, Port) \
        and port.category == UNIVERSAL_PORT_CATEGORY


# Allows special case FilterExpression evaluations where Network does not
# matter. In these cases a network  with this name will always evaluate to
# True.
UNIVERSAL_NETWORK_NAME = "__UNIVERSAL_NETWORK"


def _is_universal_network(network):
    """Check if the network is a special Network that always passes filter"""
    return isinstance(network, Network) \
        and network.name == UNIVERSAL_NETWORK_NAME


def _is_universal_tbn_obj(tbn_obj):
    """Check if the TBN object is a special one that always passes filter"""
    return _is_universal_port(tbn_obj) or _is_universal_network(tbn_obj)


class FunctionExpression(object):
    """A callable function from within a FilterExpression

    Used to query objects to determine if they pass a FilterExpression or not.
    """
    def __init__(self, variable):
        self._variable = variable

    def eval(self, port, network):
        tbn_obj = port if self._variable.object_name() == "port" else network

        if _is_universal_tbn_obj(tbn_obj):
            return True

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

        if _is_universal_tbn_obj(tbn_obj):
            return True

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


DEFAULT_GROUP_AND_ATTACH_MIN_COUNT: int = 2


@dataclass(frozen=True)
class TraitAction:
    """An action defined by a NetworkTrait

    Each action contains a filter (FilterExpression) that determines which
    (port, network) pairs the action can apply to.
    """
    NECESSARY_KEYS: ClassVar[list[str]]
    ALL_KEYS: ClassVar[list[str]]

    trait_name: str
    action: Actions
    filter: 'FilterExpression'
    min_count: int | None = None
    max_count: int | None = None

    def matches(self, portlike, network):
        """Check if filter expression matches the port, network pairing."""
        return self.filter.eval(portlike, network)

    def validate(self):
        """Check that the action is valid."""
        match self.action:
            case Actions.GROUP_AND_ATTACH_PORTS:
                if self.min_count is None \
                        or self.min_count < DEFAULT_GROUP_AND_ATTACH_MIN_COUNT:
                    return (False,
                            _(f"{self.action.value} must have a min_count of "
                              f"{DEFAULT_GROUP_AND_ATTACH_MIN_COUNT} or "
                              f"greater. Got '{self.min_count}'."))
                if self.max_count is not None and \
                        self.max_count < self.min_count:
                    return (False,
                            _(f"{self.action.value} must have a max_count "
                              "greater or equal to it's min_count. min_count "
                              f"is '{self.min_count}' while max_count is "
                              f"'{self.max_count}'."))
            case _:
                return (True, "")

        return (True, "")


# Keys from the config file action dict (excludes trait_name, which comes
# from the parent trait key rather than the action dict itself).
TraitAction.NECESSARY_KEYS = [
    f.name for f in fields(TraitAction)
    if f.name != 'trait_name'
    and f.default is MISSING
    and f.default_factory is MISSING
]
TraitAction.ALL_KEYS = [
    f.name for f in fields(TraitAction)
    if f.name != 'trait_name'
]


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


@dataclass(frozen=True)
class PrimordialPort:
    """A set of common attributes belonging to both Ports and Portgroups"""
    id: int
    uuid: str
    address: str
    category: str | None
    physical_network: str | None
    vendor: str | None


@dataclass(frozen=True)
class Port(PrimordialPort):
    """A Port used internally to query and match to TraitActions"""
    available_for_dynamic_portgroup: bool

    @classmethod
    def from_ironic_port(cls, ironic_port):
        return cls(
            id=ironic_port.id,
            uuid=ironic_port.uuid,
            address=ironic_port.address,
            category=ironic_port.category,
            physical_network=ironic_port.physical_network,
            vendor=ironic_port.vendor,
            available_for_dynamic_portgroup=\
            ironic_port.available_for_dynamic_portgroup
        )

    @classmethod
    def universal_port(cls):
        return cls(
            id=0,
            uuid="UNIVERSAL",
            address="UNIVERSAL",
            category=UNIVERSAL_PORT_CATEGORY
        )

    def is_port(self):
        return True

    def is_portgroup(self):
        return False


@dataclass(frozen=True)
class Portgroup(PrimordialPort):
    """A Portgroup used internally to query and match to TraitActions"""
    dynamic_portgroup: bool

    @classmethod
    def from_ironic_portgroup(cls, ironic_portgroup):
        return cls(
            id=ironic_portgroup.id,
            uuid=ironic_portgroup.uuid,
            address=ironic_portgroup.address,
            category=ironic_portgroup.category,
            physical_network=ironic_portgroup.physical_network,
            vendor=ironic_portgroup.vendor,
            dynamic_portgroup=ironic_portgroup.dynamic_portgroup
        )

    def is_port(self):
        return False

    def is_portgroup(self):
        return True

@dataclass(frozen=True)
class Network:
    """A Network (aka vif)

    Used to match against TraitAction FilterExpressions
    """
    id: str
    name: str
    tags: frozenset[str]

    @classmethod
    def from_vif_info(cls, vif_info):
        """Helper method to create Networks from vif_info dictionaries"""
        return cls(vif_info['id'], # vif_info is guaranteed to have 'id'.
                   vif_info.get('name'),
                   vif_info.get('tags'))

    @classmethod
    def universal_network(cls):
        return cls(
            id=0,
            name=UNIVERSAL_NETWORK_NAME,
            tags=[]
        )


@dataclass(frozen=True)
class RenderedAction:
    """A base class for Actions which are ready to apply"""
    trait_action: TraitAction
    node_uuid: str

@dataclass(frozen=True)
class AttachAction(RenderedAction):
    """Base class for actions which will attach objects to networks"""

    @abstractmethod
    def portlike_uuid(self):
        ...

    @abstractmethod
    def get_portlike_object(self, task):
        ...


@dataclass(frozen=True)
class AttachPort(AttachAction):
    """Attach a port to a network

    Contains all the necessary information to attach a port to a network (vif)
    """
    port_uuid: str
    network_id: str

    def get_portlike_object(self, task):
        for port in task.ports:
            if port.uuid == self.port_uuid:
                return port
        return None

    def portlike_uuid(self):
        return self.port_uuid

    def __str__(self):
        return _(f"Attach port '{self.port_uuid}' on node "
                 f"'{self.node_uuid}' to network '{self.network_id}' "
                 f"via trait {self.trait_action.trait_name}")


@dataclass(frozen=True)
class AttachPortgroup(AttachAction):
    """Attach a portgroup to a network

    Contains all the necessary information to attach a portgroup to a network
    (vif)
    """
    portgroup_uuid: str
    network_id: str

    def get_portlike_object(self, task):
        for portgroup in task.portgroups:
            if portgroup.uuid == self.portgroup_uuid:
                return portgroup
        return None

    def portlike_uuid(self):
        return self.portgroup_uuid

    def __str__(self):
        return _(f"Attach portgroup '{self.portgroup_uuid}' on node "
                 f"'{self.node_uuid}' to network '{self.network_id}'"
                 f"via trait {self.trait_action.trait_name}")


@dataclass(frozen=True)
class GroupAndAttachPorts(RenderedAction):
    """Assemble a group of ports as a dynamic portgroup and attach it

    Contains all necessary information to assemble the new portgroup and
    attach it to a network (vif).
    """
    port_uuids: list[str]
    network_id: str

    def __str__(self):
        return _(f"Assemble node '{self.node_uuid}' ports into a dynamic "
                 f"portgroup and attach it to network '{self.network_id}'. "
                 f"Selected Port UUIDs: {self.port_uuids}.")

@dataclass(frozen=True)
class NoMatch(RenderedAction):
    """Returned by network planning when a trait action finds no matches"""
    reason: str

    def __str__(self):
        return _(f"No match found for action under trait "
                 f"'{self.trait_action.trait_name}' "
                 f"on node '{self.node_uuid}': {self._reason}")


@dataclass(frozen=True)
class NotImplementedAction(RenderedAction):
    """Returned by network planning if an action has not been implemented"""
    action: Actions

    def __str__(self):
        return _(f"Action '{self.action.value}' not yet implemented.")
