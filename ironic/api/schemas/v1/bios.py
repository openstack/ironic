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
from ironic.api.schemas.common import response_types


# request parameter schemas

show_request_parameter = {
    'type': 'object',
    'properties': {
        'setting_name': request_types.name,
    },
    'required': ['setting_name'],
    'additionalProperties': False,
}

# request query string schemas

index_request_query = {
    'type': 'object',
    'properties': {},
    'required': [],
    'additionalProperties': False,
}

index_request_query_v74 = copy.deepcopy(index_request_query)
index_request_query_v74['properties'] = {
    'fields': {
        'type': 'array',
        'items': {
            'enum': [
                'allowable_values',
                'attribute_type',
                'created_at',
                'lower_bound',
                'links',
                'max_length',
                'min_length',
                'name',
                'node_uuid',
                'read_only',
                'reset_required',
                'unique',
                'updated_at',
                'value',
            ],
        },
        # OpenAPI-specific properties
        # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
        'style': 'form',
        'explode': False,
    },
    'detail': request_types.detail,
}

show_request_query = {
    'type': 'object',
    'properties': {},
    'required': [],
    'additionalProperties': False,
}

# response body schemas

_bios_response_body = {
    'type': 'object',
    'properties': {
        'created_at': {'type': 'string', 'format': 'date-time'},
        'links': response_types.links,
        'name': {'type': 'string'},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'value': {'type': 'string'},
    },
    'required': ['created_at', 'links', 'name', 'value', 'updated_at'],
    'additionalProperties': False,
}

_bios_response_body_v74 = {
    'type': 'object',
    'properties': {
        'allowable_values': {
            'type': ['null', 'array'], 'items': {'type': 'string'}
        },
        'attribute_type': {'type': ['null', 'string']},
        'created_at': {'type': 'string', 'format': 'date-time'},
        'links': response_types.links,
        'lower_bound': {'type': ['null', 'integer'], 'minimum': 0},
        'max_length': {'type': ['null', 'integer'], 'minimum': 0},
        'min_length': {'type': ['null', 'integer'], 'minimum': 0},
        'name': {'type': 'string'},
        'read_only': {'type': ['null', 'boolean']},
        'reset_required': {'type': ['null', 'boolean']},
        'unique': {'type': ['null', 'boolean']},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'upper_bound': {'type': ['null', 'integer'], 'minimum': 0},
        'value': {'type': 'string'},
    },
    # NOTE(stephenfin): The 'fields' parameter means only a minimal set of
    # fields are required
    'required': ['created_at', 'links', 'updated_at'],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'bios': {
            'type': 'array',
            'items': copy.deepcopy(_bios_response_body),
        },
    },
    'required': ['bios'],
    'additionalProperties': False,
}
index_response_body_v74 = copy.deepcopy(index_response_body)
index_response_body_v74['properties']['bios']['items'] = copy.deepcopy(
    _bios_response_body_v74
)

show_response_body = {
    'type': 'object',
    'patternProperties': {
        r'(?i)^[A-Z0-9-._~]+$': copy.deepcopy(_bios_response_body),
    },
    'minProperties': 1,
    'maxProperties': 1,
}
show_response_body_v74 = copy.deepcopy(show_response_body)
show_response_body_v74['patternProperties'][
    r'(?i)^[A-Z0-9-._~]+$'
] = copy.deepcopy(_bios_response_body_v74)
