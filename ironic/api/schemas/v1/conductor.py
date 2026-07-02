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

from ironic.api.schemas.common import request_types
from ironic.api.schemas.common import response_types


_conductor_fields = [
    'alive',
    'conductor_group',
    'created_at',
    'drivers',
    'hostname',
    'links',
    'updated_at',
]

show_request_parameter = {
    'type': 'object',
    'properties': {
        # Conductors may be addressed by host, host:port, or bracketed IPv6
        # host:port. Keep this broad to match the existing args.host_port
        # validator.
        'hostname': {'type': 'string'},
    },
    'required': ['hostname'],
    'additionalProperties': False,
}

index_request_query = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {'enum': _conductor_fields},
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        'limit': {'type': 'integer'},
        'marker': {'type': 'string'},
        'sort_dir': request_types.sort_dir,
        # TODO(adamcarthur): This could probably be narrower but we need to be
        # careful not to change the response type. If we do, a new microversion
        # will be needed.
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
            'items': {'enum': _conductor_fields},
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
    },
    'required': [],
    'additionalProperties': False,
}

_conductor_response_body = {
    'type': 'object',
    'properties': {
        'alive': {'type': 'boolean'},
        'conductor_group': {'type': 'string'},
        'created_at': {'type': 'string', 'format': 'date-time'},
        'drivers': {
            'type': 'array',
            'items': {'type': 'string'},
        },
        'hostname': {'type': 'string'},
        'links': response_types.links,
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
    },
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'conductors': {
            'type': 'array',
            'items': _conductor_response_body,
        },
        'next': {'type': 'string'},
    },
    'required': ['conductors'],
    'additionalProperties': False,
}

show_response_body = _conductor_response_body
