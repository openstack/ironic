# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from ironic.api.schemas.common import request_types
from ironic.common.inspection_rules import actions
from ironic.common.inspection_rules import operators

# request parameter schemas

_inspection_rule_request_parameter = {
    'type': 'object',
    'properties': {
        'inspection_rule_uuid': {'type': 'string', 'format': 'uuid'},
    },
    'required': ['inspection_rule_uuid'],
    'additionalProperties': False,
}


show_request_parameter = copy.deepcopy(_inspection_rule_request_parameter)
update_request_parameter = copy.deepcopy(_inspection_rule_request_parameter)
delete_request_parameter = copy.deepcopy(_inspection_rule_request_parameter)

# request query string schemas

index_request_query = {
    'type': 'object',
    'properties': {
        'detail': {'type': 'boolean'},
        # TODO(stephenfin): This should be much stricter. We allow anything
        # except versioned fields, which are irrelevant here since all
        # versioned fields require API microversions older than this API does.
        # As things stand, this will fail at the DB layer.
        'fields': {
            'type': 'array',
            'items': {
                'type': 'string',
            },
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        # TODO(stephenfin): We should restrict this to uuid_or_name, since that
        # would filter out obviously bad requests.
        'marker': {'type': 'string'},
        'limit': request_types.limit,
        # TODO(stephenfin): This should be much stricter. As things stand, this
        # will fail at the DB layer.
        'phase': {'type': 'string'},
        'sort_dir': request_types.sort_dir,
        # TODO(stephenfin): This is a bad check. We allow everything *except*
        # these fields. This includes invalid fields and versioned fields. We
        # should instead allowlist the ones we want to support.
        'sort_key': {
            'not': {
                'type': 'string',
                'enum': ['actions', 'conditions'],
            },
        },
    },
    'required': [],
    'additionalProperties': False,
}

show_request_query = {
    'type': 'object',
    'properties': {
        # TODO(stephenfin): This should be much stricter. We allow anything
        # except versioned fields, which are irrelevant here since all
        # versioned fields require API microversions older than this API does.
        # As things stand, this will fail at the DB layer.
        'fields': {
            'type': 'array',
            'items': {
                'type': 'string',
            },
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
    },
    'required': [],
    'additionalProperties': False,
}

# request body schemas

create_request_body = {
    'type': 'object',
    'properties': {
        'actions': {
            'type': 'array',
            'minItems': 1,
            'items': {
                'type': 'object',
                'required': ['op', 'args'],
                'properties': {
                    'op': {
                        'description': 'action operator',
                        'enum': list(actions.ACTIONS.keys())
                    },
                    'args': {
                        'description': 'Arguments for the action',
                        'type': ['array', 'object']
                    },
                    'loop': {
                        'description': 'Loop behavior for actions',
                        'type': ['array', 'object']
                    },
                },
                'additionalProperties': True
            },
        },
        'conditions': {
            'type': 'array',
            'minItems': 0,
            'items': {
                'type': 'object',
                'required': ['op', 'args'],
                'properties': {
                    'op': {
                        'description': 'Condition operator',
                        'enum': list(operators.OPERATORS) + [
                            f'!{op}' for op in list(operators.OPERATORS)
                        ],
                    },
                    'args': {
                        'description': 'Arguments for the condition',
                        'type': ['array', 'object'],
                    },
                    'multiple': {
                        'description': 'How to treat multiple values',
                        'enum': ['any', 'all', 'first', 'last'],
                    },
                    'loop': {
                        'description': 'Loop behavior for conditions',
                        'type': ['array', 'object'],
                    },
                },
                # other properties are validated by plugins
                'additionalProperties': True,
            },
        },
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        # TODO(stephenfin): We should move validation of this value here. It's
        # currently handled in validate_rule
        'phase': {'type': ['string', 'null'], 'maxLength': 16},
        'priority': {'type': 'integer', 'minimum': 0},
        'sensitive': {'type': ['boolean', 'null']},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['actions'],
    'additionalProperties': False
}

# TODO(stephenfin): This needs to be completed. We probably want a helper to
# generate these since they are superficially identical, with only the allowed
# patch fields changing
update_request_body = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'op': {'enum': ['add', 'replace', 'remove']},
            'path': {'type': 'string'},
            'value': {},
        },
        'required': ['op', 'path'],
        'additionalProperties': False,
    },
}
