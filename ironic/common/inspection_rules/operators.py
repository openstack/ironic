# Copyright 2013 Red Hat, Inc.
# All Rights Reserved.
#
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

from ironic.common.i18n import _
from ironic.common.inspection_rules import base
from ironic.common import utils as common_utils


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
    class_name = OPERATORS[op_name]
    return globals()[class_name]


def coerce(value, expected):
    if isinstance(expected, float):
        return float(value)
    elif isinstance(expected, int):
        return int(value)
    else:
        return value


class OperatorBase(base.Base, metaclass=abc.ABCMeta):
    """Abstract base class for rule condition plugins."""

    OPTIONAL_ARGS = set()
    """Set with names of optional parameters."""

    @abc.abstractmethod
    def check(self, *args, **kwargs):
        """Check if condition holds for a given field."""

    def _check_with_loop(self, task, condition, inventory, plugin_data):
        loop_items = condition.get('loop', [])
        multiple = condition.get('multiple', 'any')
        results = []

        if isinstance(loop_items, (list, dict)):
            for item in loop_items:
                condition_copy = condition.copy()
                condition_copy['args'] = item
                result = self._check_condition(task, condition_copy,
                                               inventory, plugin_data)
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
        return self._check_condition(task, condition, inventory, plugin_data)

    def _check_condition(self, task, condition, inventory, plugin_data):
        """Process condition arguments and apply the check logic.

        :param task: TaskManger instance
        :param condition: condition to check
        :param args: parameters as a dictionary, changing it here will change
                     what will be stored in database
        :param kwargs: used for extensibility without breaking existing plugins
        :raises ValueError: on unacceptable field value
        :returns: True if check succeeded, otherwise False
        """
        op, is_inverted = common_utils.parse_inverted_operator(
            condition['op'])

        processed_args = self._process_args(task, condition, inventory,
                                            plugin_data)
        arg_values = [processed_args[arg_name]
                      for arg_name in self.get_arg_names()]

        for optional_arg in self.OPTIONAL_ARGS:
            arg_values.append(processed_args.get(optional_arg, False))

        result = self.check(*arg_values)
        return not result if is_inverted else result


class SimpleOperator(OperatorBase):

    op = None
    OPTIONAL_ARGS = {'force_strings'}

    @classmethod
    def get_arg_names(cls):
        return ['values']

    def check(self, values, force_strings=False):
        if force_strings:
            values = [coerce(value, str) for value in values]
        return self.op(values)


class EqOperator(SimpleOperator):
    op = operator.eq


class LtOperator(SimpleOperator):
    op = operator.lt


class GtOperator(SimpleOperator):
    op = operator.gt


class EmptyOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value']

    def check(self, value):
        return str(value) in ("", 'None', '[]', '{}')


class NetOperator(OperatorBase):
    FORMATTED_ARGS = ['address', 'subnet']

    @classmethod
    def get_arg_names(cls):
        return ['address', 'subnet']

    def validate(self, address, subnet):
        try:
            netaddr.IPNetwork(subnet)
        except netaddr.AddrFormatError as exc:
            LOG.error(_('invalid value: %s'), exc)

    def check(self, address, subnet):
        network = netaddr.IPNetwork(subnet)
        return netaddr.IPAddress(address) in network


class IsTrueOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value']

    def check(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ('yes', 'true')
        return False


class IsFalseOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value']

    def check(self, value):
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return not bool(value)
        if isinstance(value, str):
            return value.lower() in ('no', 'false')
        return value is None


class IsNoneOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value']

    def check(self, value):
        return str(value) == 'None'


class OneOfOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value', 'values']

    def check(self, value, values=[]):
        return value in values


class ReOperator(OperatorBase):
    FORMATTED_ARGS = ['value']

    @classmethod
    def get_arg_names(cls):
        return ['value', 'regex']

    def validate_regex(self, regex):
        try:
            re.compile(regex)
        except re.error as exc:
            raise ValueError(_('invalid regular expression: %s') % exc)


class MatchesOperator(ReOperator):

    def check(self, value, regex):
        self.validate_regex(regex)
        if regex[-1] != '$':
            regex += '$'
        return re.match(regex, str(value)) is not None


class ContainsOperator(ReOperator):

    def check(self, value, regex):
        self.validate_regex(regex)
        return re.search(regex, str(value)) is not None
