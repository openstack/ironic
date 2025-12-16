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

import jsonschema

from ironic.api.schemas.v1 import inspection_rule as schema
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import operators
from ironic.common.inspection_rules import utils


class InspectionPhase(enum.Enum):
    MAIN = 'main'


# TODO(stephenfin): Everything here can and should be moved to the jsonschema
# schemas, but doing so will change responses.
def validate_rule(rule, built_in=False):
    """Validate an inspection rule using the JSON schema.

    :param rule: The inspection rule to validate.
    :param built_in: Should this rule be treated as built in for validation
    :raises: Invalid if the rule is invalid.
    """
    try:
        jsonschema.validate(rule, schema.create_request_body)
    except jsonschema.ValidationError as e:
        raise exception.Invalid(
            _('Validation failed for inspection rule: %s') % e)

    errors = []

    phase = rule.get('phase', InspectionPhase.MAIN.value)
    if phase not in (p.value for p in InspectionPhase):
        errors.append(
            _('Invalid phase: %(phase)s. Valid phases are: %(valid)s') % {
                'phase': phase, 'valid': ', '.join(
                    [p.value for p in InspectionPhase])
            })

    priority = rule.get('priority', 0)
    if priority < 0 and not built_in:
        errors.append(
            _("Priority cannot be negative for user-defined rules."))
    if priority > 9999 and not built_in:
        errors.append(
            _("Priority must be between 0 and 9999 for user-defined rules."))

    # Additional plugin-specific validation
    for condition in rule.get('conditions', []):
        op, invtd = utils.parse_inverted_operator(
            condition['op'])
        plugin = operators.get_operator(op)
        if not plugin or not callable(plugin):
            errors.append(
                _('Unsupported condition operator: %s') % op)
        try:
            plugin().validate(condition.get('args', {}))
        except ValueError as exc:
            errors.append(_('Invalid parameters for condition operator '
                            '%(op)s: %(error)s') % {'op': op,
                                                    'error': exc})

    for action in rule['actions']:
        plugin = actions.get_action(action['op'])
        if not plugin or not callable(plugin):
            errors.append(_('Unsupported action operator: %s') % action['op'])
        try:
            plugin().validate(action.get('args', {}))
        except ValueError as exc:
            errors.append(_('Invalid parameters for action operator %(op)s: '
                            '%(error)s') % {'op': action['op'], 'error': exc})

    if errors:
        if len(errors) == 1:
            raise exception.Invalid(errors[0])
        else:
            raise exception.Invalid(_('Multiple validation errors occurred: '
                                      '%s') % '; '.join(errors))
