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


_target_request_parameter = {
    'type': 'object',
    'properties': {
        'target_uuid': request_types.uuid,
    },
    'required': ['target_uuid'],
    'additionalProperties': False,
}
show_request_parameter = copy.deepcopy(_target_request_parameter)
update_request_parameter = copy.deepcopy(_target_request_parameter)
delete_request_parameter = copy.deepcopy(_target_request_parameter)

_target_fields = [
    'boot_index',
    'created_at',
    'extra',
    'links',
    'node_uuid',
    'properties',
    'updated_at',
    'uuid',
    'volume_id',
    'volume_type',
]

index_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {'enum': _target_fields},
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
            'items': {'enum': _target_fields},
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
        'boot_index': {'type': 'integer'},
        'extra': {'type': ['object', 'null']},
        'node_uuid': {'type': 'string'},
        # TODO(adamcarthur): Can we be more specific about what's allowed here?
        'properties': {'type': ['object', 'null']},
        'uuid': {'type': ['string', 'null']},
        'volume_id': {'type': 'string'},
        'volume_type': {'type': 'string'},
    },
    'required': ['boot_index', 'node_uuid', 'volume_id', 'volume_type'],
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

_target_response_body = {
    'type': 'object',
    'properties': {
        'boot_index': {'type': 'integer'},
        'created_at': {'type': 'string', 'format': 'date-time'},
        # TODO(adamcarthur): Can we be more specific about what's allowed here?
        'extra': {'type': ['object', 'null']},
        'links': response_types.links,
        'node_uuid': {'type': ['string', 'null'], 'format': 'uuid'},
        # TODO(adamcarthur): Can we be more specific about what's allowed here?
        'properties': {'type': ['object', 'null']},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': response_types.uuid,
        'volume_id': {'type': 'string'},
        'volume_type': {'type': 'string'},
    },
    # NOTE(adamcarthur): The 'fields' parameter means nothing is required
    'required': [],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'targets': {
            'type': 'array',
            'items': copy.deepcopy(_target_response_body),
        },
        'next': {'type': 'string'},
    },
    'required': ['targets'],
    'additionalProperties': False,
}

show_response_body = copy.deepcopy(_target_response_body)
create_response_body = copy.deepcopy(_target_response_body)
update_response_body = copy.deepcopy(_target_response_body)
