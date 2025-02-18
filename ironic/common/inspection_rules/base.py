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

import inspect

from oslo_log import log

from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import utils
import ironic.conf


CONF = ironic.conf.CONF
LOG = log.getLogger(__name__)
SENSITIVE_FIELDS = ['password', 'auth_token', 'bmc_password']


class Base(object):

    REQUIRES_PLUGIN_DATA = False
    """Flag to indicate if this action needs plugin_data as an arg."""

    def _get_validation_signature(self):
        """Get the signature to validate against."""
        signature = inspect.signature(self.__call__)

        # Strip off 'task' parameter.
        parameters = list(signature.parameters.values())[1:]

        required_args = [p.name for p in parameters
                         if p.default is inspect.Parameter.empty]
        optional_args = [p.name for p in parameters
                         if p.default is not inspect.Parameter.empty]
        return required_args, optional_args

    def _normalize_list_args(self, required_args, optional_args, op_args):
        """Convert list arguments into dictionary format."""
        if not isinstance(op_args, list):
            # Initialize required context fields if needed
            if isinstance(op_args, dict) and self.REQUIRES_PLUGIN_DATA:
                op_args['plugin_data'] = {}
            return op_args

        # Initialize required context fields if needed
        if self.REQUIRES_PLUGIN_DATA:
            op_args.append({})

        if len(op_args) < len(required_args):
            missing = [p for p in required_args[len(op_args):]]
            msg = (_("Not enough arguments provided. Missing: %s"),
                   ", ".join(missing))
            raise exception.InspectionRuleValidationFailure(msg)

        normalized_args = {name: op_args[i]
                           for i, name in enumerate(required_args)}

        # Add optional args if they exist in the input
        normalized_args.update(
            zip(optional_args, op_args[len(required_args):])
        )

        return normalized_args

    def validate(self, op_args):
        """Validate args passed during creation.

        Default implementation checks for presence of required fields.

        :param op_args: Operator args as a dictionary
        :raises: InspectionRuleValidationFailure on validation failure
        """
        required_args, optional_args = self._get_validation_signature()
        normalized_args = self._normalize_list_args(
            required_args=required_args, optional_args=optional_args,
            op_args=op_args)

        # If after normalization attempt, we still do not have a dictionary,
        # then it was never a list, so, not a supported type.
        if isinstance(normalized_args, dict):
            provided = set(normalized_args)
            missing = set(required_args) - provided
            unexpected = provided - (set(required_args) | set(optional_args))

            msg = []
            if missing:
                msg.append(_('missing required argument(s): %s')
                           % ', '.join(missing))
            if unexpected:
                msg.append(_('unexpected argument(s): %s')
                           % ', '.join(unexpected))
            if msg:
                raise exception.InspectionRuleValidationFailure(
                    '; '.join(msg))
        else:
            raise exception.InspectionRuleValidationFailure(
                _("args must be either a list or dictionary"))

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
            raise exception.InspectionRuleExecutionFailure(
                _("Operation must contain 'op' key"))

        required_args, optional_args = self._get_validation_signature()

        op, invtd = utils.parse_inverted_operator(op)
        dict_args = self._normalize_list_args(
            required_args=required_args, optional_args=optional_args,
            op_args=operation.get('args', {}))

        # plugin-data becomes available during inspection,
        # we need to populate with the actual value.
        if self.REQUIRES_PLUGIN_DATA:
            dict_args['plugin_data'] = plugin_data

        node = task.node
        formatted_args = getattr(self, 'FORMATTED_ARGS', [])
        return {
            k: (Base.interpolate_variables(v, node, inventory, plugin_data)
                if k in formatted_args else v)
            for k, v in dict_args.items()
        }
