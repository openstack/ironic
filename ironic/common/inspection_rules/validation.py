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

from ironic.common import args
from ironic.common import exception
from ironic.common.i18n import _
from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import operators
from ironic.common.inspection_rules import utils


_CONDITIONS_SCHEMA = None
_ACTIONS_SCHEMA = None


class InspectionPhase(enum.Enum):
    MAIN = 'main'


def conditions_schema():
    global _CONDITIONS_SCHEMA
    if _CONDITIONS_SCHEMA is None:
        condition_plugins = list(operators.OPERATORS.keys())
        condition_plugins.extend(
            ["!%s" % op for op in list(condition_plugins)])
        _CONDITIONS_SCHEMA = {
            "title": "Inspection rule conditions schema",
            "type": "array",
            "minItems": 0,
            "items": {
                "type": "object",
                "required": ["op", "args"],
                "properties": {
                    "op": {
                        "description": "Condition operator",
                        "enum": condition_plugins
                    },
                    "args": {
                        "description": "Arguments for the condition",
                        "type": ["array", "object"]
                    },
                    "multiple": {
                        "description": "How to treat multiple values",
                        "enum": ["any", "all", "first", "last"]
                    },
                    "loop": {
                        "description": "Loop behavior for conditions",
                        "type": ["array", "object"]
                    },
                },
                # other properties are validated by plugins
                "additionalProperties": True
            }
        }

    return _CONDITIONS_SCHEMA


def actions_schema():
    global _ACTIONS_SCHEMA
    if _ACTIONS_SCHEMA is None:
        action_plugins = list(actions.ACTIONS.keys())
        _ACTIONS_SCHEMA = {
            "title": "Inspection rule actions schema",
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["op", "args"],
                "properties": {
                    "op": {
                        "description": "action operator",
                        "enum": action_plugins
                    },
                    "args": {
                        "description": "Arguments for the action",
                        "type": ["array", "object"]
                    },
                    "loop": {
                        "description": "Loop behavior for actions",
                        "type": ["array", "object"]
                    },
                },
                "additionalProperties": True
            }
        }

    return _ACTIONS_SCHEMA


SCHEMA = {
    'type': 'object',
    'properties': {
        'uuid': {'type': ['string', 'null']},
        'priority': {'type': 'integer', "minimum": 0},
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'sensitive': {'type': ['boolean', 'null']},
        'phase': {'type': ['string', 'null'], 'maxLength': 16},
        "conditions": conditions_schema(),
        "actions": actions_schema()
    },
    'required': ['actions'],
    "additionalProperties": False
}

VALIDATOR = args.and_valid(
    args.schema(SCHEMA),
    args.dict_valid(uuid=args.uuid)
)


def validate_rule(rule):
    """Validate an inspection rule using the JSON schema.

    :param rule: The inspection rule to validate.
    :raises: Invalid if the rule is invalid.
    """
    try:
        jsonschema.validate(rule, SCHEMA)
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
    if priority < 0 and not rule.get('built_in'):
        errors.append(
            _("Priority cannot be negative for user-defined rules."))
    if priority > 9999 and not rule.get('built_in'):
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
