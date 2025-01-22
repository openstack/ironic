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

from oslo_log import log

from ironic.common.i18n import _
from ironic.common import utils as common_utils
import ironic.conf


CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
SENSITIVE_FIELDS = ['password', 'auth_token', 'bmc_password']


class Base(object):

    USES_PLUGIN_DATA = False
    """Flag to indicate if this action needs plugin_data as an arg."""

    OPTIONAL_ARGS = set()
    """Set with names of optional parameters."""

    @classmethod
    @abc.abstractmethod
    def get_arg_names(cls):
        """Return list of argument names in order expected."""
        raise NotImplementedError

    def _normalize_list_args(self, *args, **kwargs):
        """Convert list arguments into dictionary format.

        """
        op_name = kwargs['op']
        arg_list = kwargs['args']
        if not isinstance(arg_list, list):
            if isinstance(arg_list, dict) and 'plugin-data' in op_name:
                arg_list['plugin_data'] = {}
            return arg_list

        # plugin_data is a required argument during validation but since
        # it comes from the inspection data and added later, we need to
        # make sure validation does not fail for that sake.
        if 'plugin-data' in op_name:
            arg_list.append('{}')

        arg_names = set(self.__class__.get_arg_names())
        if len(arg_list) < len(arg_names):
            missing = arg_names[len(arg_list):]
            msg = (_("Not enough arguments provided. Missing: %s"),
                   ", ".join(missing))
            LOG.error(msg)
            raise ValueError(msg)

        arg_list = {name: arg_list[i] for i, name in enumerate(arg_names)}

        # Add optional args if they exist in the input
        start_idx = len(arg_names)
        for i, opt_arg in enumerate(self.OPTIONAL_ARGS):
            if start_idx + i < len(arg_list):
                arg_list[opt_arg] = arg_list[start_idx + i]

        return arg_list

    def validate(self, *args, **kwargs):
        """Validate args passed during creation.

        Default implementation checks for presence of required fields.

        :param args: args as a dictionary
        :param kwargs: used for extensibility without breaking existing plugins
        :raises: ValueError on validation failure
        """
        required_args = set(self.__class__.get_arg_names())
        normalized_args = self._normalize_list_args(
            args=kwargs.get('args', {}), op=kwargs['op'])

        if isinstance(normalized_args, dict):
            provided = set(normalized_args.keys())
            missing = required_args - provided
            unexpected = provided - (required_args | self.OPTIONAL_ARGS)

            msg = []
            if missing:
                msg.append(_('missing required argument(s): %s')
                           % ', '.join(missing))
            if unexpected:
                msg.append(_('unexpected argument(s): %s')
                           % ', '.join(unexpected))
            if msg:
                raise ValueError('; '.join(msg))
        else:
            raise ValueError(_("args must be either a list or dictionary"))

    @staticmethod
    def interpolate_variables(value, node, inventory, plugin_data):
        if isinstance(value, str):
            try:
                return value.format(node=node, inventory=inventory,
                                    plugin_data=plugin_data)
            except (AttributeError, KeyError, ValueError, IndexError,
                    TypeError) as e:
                LOG.warning(
                    "Interpolation failed: %(value)s: %(error_class)s, "
                    "%(error)s", {'value': value,
                                  'error_class': e.__class__.__name__,
                                  'error': e})
                return value
        elif isinstance(value, dict):
            return {
                Base.interpolate_variables(k, node, inventory, plugin_data):
                Base.interpolate_variables(v, node, inventory, plugin_data)
                for k, v in value.items()}
        elif isinstance(value, list):
            return [Base.interpolate_variables(
                v, node, inventory, plugin_data) for v in value]
        return value

    def _process_args(self, task, operation, inventory, plugin_data):
        "Normalize and process args based on the operator."

        op = operation.get('op')
        if not op:
            raise ValueError("Operation must contain 'op' key")

        op, invtd = common_utils.parse_inverted_operator(op)
        dict_args = self._normalize_list_args(args=operation.get('args', {}),
                                              op=op)

        # plugin-data becomes available during inspection,
        # we need to populate with the actual value.
        if 'plugin_data' in dict_args or 'plugin-data' in op:
            dict_args['plugin_data'] = plugin_data

        node = task.node
        formatted_args = getattr(self, 'FORMATTED_ARGS', [])
        return {
            k: (self.interpolate_variables(v, node, inventory, plugin_data)
                if k in formatted_args else v)
            for k, v in dict_args.items()
        }
