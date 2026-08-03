# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from ironic.api.schemas.common import request_types
from ironic.api.schemas.common import response_types


_chassis_fields = [
    'created_at',
    'description',
    'extra',
    'links',
    'nodes',
    'updated_at',
    'uuid',
]

# request parameter schemas

_chassis_request_parameter = {
    'type': 'object',
    'properties': {
        'chassis_uuid': request_types.uuid,
    },
    'required': ['chassis_uuid'],
    'additionalProperties': False,
}
show_request_parameter = _chassis_request_parameter
update_request_parameter = _chassis_request_parameter
delete_request_parameter = _chassis_request_parameter

# request query string schemas

index_request_query = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {'enum': _chassis_fields},
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        'limit': {'type': 'integer'},
        'marker': request_types.uuid,
        'sort_dir': request_types.sort_dir,
        # Sorting is constrained separately to preserve the existing error
        # handling and response behaviour.
        'sort_key': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

detail_request_query = {
    'type': 'object',
    'properties': {
        'limit': {'type': 'integer'},
        'marker': request_types.uuid,
        'sort_dir': request_types.sort_dir,
        'sort_key': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

show_request_query = {
    'type': 'object',
    'properties': {
        'fields': {
            'type': 'array',
            'items': {'enum': _chassis_fields},
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
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'extra': {'type': ['object', 'null']},
        'uuid': {'type': ['string', 'null'], 'format': 'uuid'},
    },
    'additionalProperties': False,
}

update_request_body = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'op': {'type': 'string', 'enum': ['add', 'replace', 'remove']},
            'path': {'type': 'string', 'pattern': '^(/[\\w-]+)+$'},
            'value': {},
        },
        'required': ['op', 'path'],
        'additionalProperties': False,
    },
}

# response body schemas

_chassis_response_body = {
    'type': 'object',
    'properties': {
        'created_at': {'type': 'string', 'format': 'date-time'},
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'extra': {'type': ['object', 'null']},
        'links': response_types.links,
        # ``convert_with_links`` emits a list containing the links list.
        'nodes': {
            'type': 'array',
            'items': response_types.links,
        },
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': response_types.uuid,
    },
    # The fields parameter and non-detail collection responses may omit any
    # resource property, but all returned properties must be known.
    'required': [],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'chassis': {
            'type': 'array',
            'items': _chassis_response_body,
        },
        'next': {'type': 'string'},
    },
    'required': ['chassis'],
    'additionalProperties': False,
}

show_response_body = _chassis_response_body
create_response_body = _chassis_response_body
update_response_body = _chassis_response_body
