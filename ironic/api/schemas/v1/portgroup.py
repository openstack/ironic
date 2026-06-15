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

# request parameter schemas

_portgroup_request_parameter = {
    'type': 'object',
    'properties': {
        'portgroup_ident': request_types.uuid_or_name,
    },
    'required': ['portgroup_ident'],
    'additionalProperties': False,
}
show_request_parameter = copy.deepcopy(_portgroup_request_parameter)
update_request_parameter = copy.deepcopy(_portgroup_request_parameter)
delete_request_parameter = copy.deepcopy(_portgroup_request_parameter)

# request query string schemas

index_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'address': request_types.mac_address,
        'conductor_groups': {
            'type': 'array',
            'items': {
                'type': 'string',
            },
        },
        'detail': request_types.detail,
        'fields': {
            'type': 'array',
            'items': {
                'enum': [
                    'address',
                    'category',
                    'created_at',
                    'dynamic_portgroup',
                    'extra',
                    'internal_info',
                    'links',
                    'mode',
                    'name',
                    'node_uuid',
                    'physical_network',
                    'ports',
                    'properties',
                    'standalone_ports_supported',
                    'updated_at',
                    'uuid',
                ],
            },
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        'limit': {'type': 'integer'},
        'marker': {'type': 'string', 'format': 'uuid'},
        'node': request_types.uuid_or_name,
        'shard': {
            'type': 'array',
            'items': {
                'type': 'string',
            },
        },
        'sort_dir': request_types.sort_dir,
        # TODO(stephenfin): This could probably be narrower but we need to be
        # careful not to change the response type. If we do, a new microversion
        # will be needed.
        'sort_key': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

index_request_query_v26 = copy.deepcopy(index_request_query)

show_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'fields': {
            'type': 'array',
            'items': {
                'enum': [
                    'address',
                    'category',
                    'created_at',
                    'dynamic_portgroup',
                    'extra',
                    'internal_info',
                    'links',
                    'mode',
                    'name',
                    'node_uuid',
                    'physical_network',
                    'ports',
                    'properties',
                    'standalone_ports_supported',
                    'updated_at',
                    'uuid',
                ],
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

show_request_query_v26 = copy.deepcopy(show_request_query)

# request body schemas

create_request_body = {
    'type': 'object',
    'properties': {
        'address': {'type': ['string', 'null']},
        'category': {'type': ['string', 'null'], 'maxLength': 80},
        # TODO(stephenfin): Can we be more specific about what's allowed here?
        'extra': {'type': ['object', 'null']},
        'mode': {'type': ['string', 'null']},
        'name': {'type': ['string', 'null']},
        'node_uuid': {'type': 'string'},
        'physical_network': {'type': ['string', 'null'], 'maxLength': 64},
        'properties': {'type': ['object', 'null']},
        'standalone_ports_supported': {'type': ['string', 'boolean', 'null']},
        'uuid': {'type': ['string', 'null']},
    },
    'required': ['node_uuid'],
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

# response body schemas

_portgroup_response_body = {
    'type': 'object',
    'properties': {
        'address': response_types.nullable_mac_address,
        'category': {'type': ['string', 'null'], 'maxLength': 80},
        'created_at': {'type': 'string', 'format': 'date-time'},
        # TODO(stephenfin): Can we be more specific about what's allowed here?
        'extra': {'type': ['object', 'null']},
        # TODO(stephenfin): Can we be more specific about what's allowed here?
        'internal_info': {'type': ['object', 'null']},
        'links': response_types.links,
        'mode': {'type': ['string', 'null']},
        'name': {'type': ['string', 'null'], 'maxLength': 255},
        'node_uuid': {'type': ['string', 'null'], 'format': 'uuid'},
        'ports': response_types.links,
        'physical_network': {'type': ['string', 'null'], 'maxLength': 64},
        # TODO(stephenfin): Can we be more specific about what's allowed here?
        'properties': {'type': ['object', 'null']},
        'standalone_ports_supported': {'type': 'boolean'},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': response_types.uuid,
        'dynamic_portgroup': {'type': 'boolean'},
    },
    # NOTE(stephenfin): The 'fields' parameter means nothing is required
    'required': [],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'portgroups': {
            'type': 'array',
            'items': copy.deepcopy(_portgroup_response_body),
        },
        'next': {'type': 'string'},
    },
    'required': ['portgroups'],
    'additionalProperties': False,
}

show_response_body = copy.deepcopy(_portgroup_response_body)

create_response_body = copy.deepcopy(_portgroup_response_body)

update_response_body = copy.deepcopy(_portgroup_response_body)
