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
from typing import Any

from ironic.api.schemas.common import request_types
from ironic.api.schemas.common import response_types


_connector_request_parameter = {
    'type': 'object',
    'properties': {
        'connector_uuid': request_types.uuid,
    },
    'required': ['connector_uuid'],
    'additionalProperties': False,
}
show_request_parameter = copy.deepcopy(_connector_request_parameter)
update_request_parameter = copy.deepcopy(_connector_request_parameter)
delete_request_parameter = copy.deepcopy(_connector_request_parameter)

_connector_fields = [
    'connector_id',
    'created_at',
    'extra',
    'links',
    'node_uuid',
    'type',
    'updated_at',
    'uuid',
]

index_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {'enum': _connector_fields},
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        'limit': {'type': 'integer'},
        'marker': {'type': 'string', 'format': 'uuid'},
        'node': request_types.uuid_or_name,
        'sort_dir': request_types.sort_dir,
        # TODO(adamcarthur): This could probably be narrower but we need to be
        # careful not to change the response type. If we do, a new microversion
        # will be needed.
        'sort_key': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

show_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {'enum': _connector_fields},
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
    },
    'required': [],
    'additionalProperties': False,
}

create_request_body = {
    'type': 'object',
    'properties': {
        'connector_id': {'type': 'string'},
        'extra': {'type': ['object', 'null']},
        'node_uuid': {'type': 'string'},
        'type': {'type': 'string'},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['connector_id', 'node_uuid', 'type'],
    'additionalProperties': False,
}

update_request_body = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'path': {'type': 'string', 'pattern': '^(/[\\w-]+)+$'},
            'op': {'type': 'string', 'enum': ['add', 'replace', 'remove']},
            'value': {},
        },
        'additionalProperties': False,
        'required': ['op', 'path'],
    },
}

_connector_response_body = {
    'type': 'object',
    'properties': {
        'connector_id': {'type': 'string'},
        'created_at': {'type': 'string', 'format': 'date-time'},
        # TODO(adamcarthur): Can we be more specific about what's allowed here?
        'extra': {'type': ['object', 'null']},
        'links': response_types.links,
        'node_uuid': {'type': ['string', 'null'], 'format': 'uuid'},
        'type': {'type': 'string'},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': response_types.uuid,
    },
    # NOTE(adamcarthur): The 'fields' parameter means nothing is required
    'required': [],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'connectors': {
            'type': 'array',
            'items': copy.deepcopy(_connector_response_body),
        },
        'next': {'type': 'string'},
    },
    'required': ['connectors'],
    'additionalProperties': False,
}

show_response_body = copy.deepcopy(_connector_response_body)
create_response_body = copy.deepcopy(_connector_response_body)
update_response_body = copy.deepcopy(_connector_response_body)
