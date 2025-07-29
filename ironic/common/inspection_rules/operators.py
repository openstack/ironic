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

import abc
import operator
import re

import netaddr
from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import base
from ironic.common.inspection_rules import utils


LOG = log.getLogger(__name__)
OPERATORS = {
    "eq": "EqOperator",
    "lt": "LtOperator",
    "gt": "GtOperator",
    "is-empty": "EmptyOperator",
    "in-net": "NetOperator",
    "matches": "MatchesOperator",
    "contains": "ContainsOperator",
    "one-of": "OneOfOperator",
    "is-none": "IsNoneOperator",
    "is-true": "IsTrueOperator",
    "is-false": "IsFalseOperator",
}


def get_operator(op_name):
    """Get operator class by name."""
    if op_name not in OPERATORS:
        raise exception.Invalid(
            _("Unsupported operator '%s'.") % op_name
        )
    class_name = OPERATORS[op_name]
    return globals()[class_name]


class OperatorBase(base.Base, metaclass=abc.ABCMeta):
    """Abstract base class for rule condition plugins."""

    @abc.abstractmethod
    def __call__(self, task, *args, **kwargs):
        """Checks if condition holds for a given field."""

    def check_with_loop(self, task, condition, inventory, plugin_data):
        loop_items = None
        if condition.get('loop', []):
            loop_items = condition['loop']
            multiple = condition.get('multiple', 'any')

        results = []
        if isinstance(loop_items, (list, dict)):
            if isinstance(loop_items, dict):
                loop_context = {'item': loop_items}
                condition_copy = condition.copy()
                result = self.check_condition(task, condition_copy,
                                              inventory, plugin_data,
                                              loop_context)
                results.append(result)
                if multiple in ('first', 'last'):
                    return result

            elif isinstance(loop_items, list):
                for item in loop_items:
                    loop_context = {'item': item}
                    condition_copy = condition.copy()
                    result = self.check_condition(task, condition_copy,
                                                  inventory, plugin_data,
                                                  loop_context)
                    results.append(result)

                    if multiple == 'first' and result:
                        return True
                    elif multiple == 'last':
                        results = [result]

            if multiple == 'any':
                return any(results)
            elif multiple == 'all':
                return all(results)
            return results[0] if results else False
        return self.check_condition(task, condition, inventory, plugin_data)

    def check_condition(self, task, condition, inventory, plugin_data,
                        loop_context=None):
        """Process condition arguments and apply the check logic.

        :param task: TaskManger instance
        :param condition: condition to check
        :param inventory: Node inventory data with hardware information
        :param plugin_data: Data from inspection plugins
        :param loop_context: Current loop item when called from check_with_loop
        :raises InspectionRuleExecutionFailure: on unacceptable field value
        :returns: True if check succeeded, otherwise False
        """
        op, is_inverted = utils.parse_inverted_operator(
            condition['op'])

        processed_args = self._process_args(task, condition, inventory,
                                            plugin_data, loop_context)

        required_args, optional_args = self.get_validation_signature()
        if loop_context and 'force_strings' in optional_args:
            # When in a loop context, variable interpolation might convert
            # numbers to strings. Setting force_strings ensures consistent
            # comparison by converting all values to strings before
            # comparison.
            processed_args['force_strings'] = True

        result = self(task, **processed_args)
        return not result if is_inverted else result


class SimpleOperator(OperatorBase):

    op = None

    def __call__(self, task, values, force_strings=False):
        if not isinstance(values, list):
            msg = _("Failed to check condition: '%(op)s' on values: "
                    "%(values)s: Expected list for 'values', got: "
                    "%(invalid_type)s") % {
                        'op': self.op.__name__, 'values': values,
                        "invalid_type": type(values).__name__}
            LOG.error(msg)
            raise exception.RuleConditionCheckFailure(reason=msg)

        if len(values) < 2:
            return True

        if force_strings:
            values = [str(value) for value in values]

        return all(self.op(values[i], values[i + 1])
                   for i in range(len(values) - 1))


class LeOperator(SimpleOperator):
    op = operator.le


class GeOperator(SimpleOperator):
    op = operator.ge


class NeOperator(SimpleOperator):
    op = operator.ne


class EqOperator(SimpleOperator):
    op = operator.eq


class LtOperator(SimpleOperator):
    op = operator.lt


class GtOperator(SimpleOperator):
    op = operator.gt


class EmptyOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, value):
        return str(value) in ("", 'None', '[]', '{}')


class NetOperator(OperatorBase):

    FORMATTED_ARGS = ['address', 'subnet']

    def __call__(self, task, address, subnet):
        try:
            network = netaddr.IPNetwork(subnet)
        except netaddr.AddrFormatError as exc:
            raise exception.InspectionRuleExecutionFailure(
                _('invalid value: %s') % exc)
        return netaddr.IPAddress(address) in network


class IsTrueOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('yes', 'true')
        return False


class IsFalseOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return not bool(value)
        if isinstance(value, str):
            return value.lower() in ('no', 'false')
        return value is None


class IsNoneOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, value):
        return value is None


class OneOfOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def __call__(self, task, value, values=[]):
        return value in values


class ReOperator(OperatorBase):

    FORMATTED_ARGS = ['value']

    def validate_regex(self, regex):
        try:
            re.compile(regex)
        except re.error as exc:
            raise exception.InspectionRuleExecutionFailure(
                _('invalid regular expression: %s') % exc)


class MatchesOperator(ReOperator):

    def __call__(self, task, value, regex):
        self.validate_regex(regex)
        if regex[-1] != '$':
            regex += '$'
        return re.match(regex, str(value)) is not None


class ContainsOperator(ReOperator):

    def __call__(self, task, value, regex):
        self.validate_regex(regex)
        return re.search(regex, str(value)) is not None
