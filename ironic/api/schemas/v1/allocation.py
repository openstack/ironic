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

_allocation_request_parameter = {
    'type': 'object',
    'properties': {
        'allocation_ident': {'type': 'string'},
    },
    'required': ['allocation_ident'],
    'additionalProperties': False,
}
show_request_parameter = copy.deepcopy(_allocation_request_parameter)
update_request_parameter = copy.deepcopy(_allocation_request_parameter)
delete_request_parameter = copy.deepcopy(_allocation_request_parameter)

# request query string schemas

index_request_query = {
    'type': 'object',
    'properties': {
        'fields': {
            'type': 'array',
            'items': {
                'enum': [
                    'candidate_nodes',
                    'created_at',
                    'extra',
                    'last_error',
                    'links',
                    'name',
                    'node_uuid',
                    'resource_class',
                    'state',
                    'traits',
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
        'owner': {'type': 'string'},
        'resource_class': {'type': 'string'},
        'sort_dir': request_types.sort_dir,
        # TODO(stephenfin): This could probably be narrower but we need to be
        # careful not to change the response type. If we do, a new microversion
        # will be needed.
        'sort_key': {'type': 'string'},
        'state': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

index_request_query_v60 = copy.deepcopy(index_request_query)
index_request_query_v60['properties']['fields']['items']['enum'].append(
    'owner'
)

show_request_query = {
    'type': 'object',
    'properties': {
        'fields': {
            'type': 'array',
            'items': {
                'enum': [
                    'candidate_nodes',
                    'created_at',
                    'extra',
                    'last_error',
                    'links',
                    'name',
                    'node_uuid',
                    'resource_class',
                    'state',
                    'traits',
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

show_request_query_v60 = copy.deepcopy(show_request_query)
show_request_query_v60['properties']['fields']['items']['enum'].append(
    'owner'
)

# request body schemas

create_request_body = {
    'type': 'object',
    'properties': {
        'candidate_nodes': {
            'type': ['array', 'null'],
            'items': request_types.uuid_or_name,
        },
        'extra': {'type': ['object', 'null']},
        # TODO(stephenfin): We'd like to use request_types.uuid_or_name here
        # but doing so will change the error response
        'name': {'type': ['string', 'null']},
        # TODO(stephenfin): The docs say that owner is only present in v1.60+,
        # but I can't see anything in the code to prevent this in the POST
        # request, only in the GET request and all responses
        'owner': {'type': ['string', 'null']},
        'resource_class': {'type': ['string', 'null'], 'maxLength': 80},
        'traits': {
            'type': ['array', 'null'],
            'items': response_types.traits,
        },
        'uuid': {'type': ['string', 'null']},
    },
    # TODO(stephenfin): The resource_class field is required when node is not
    # provided. We'd like to express this here, but doing so will change the
    # error response.
    'required': [],
    'additionalProperties': False,
}

create_request_body_v58 = copy.deepcopy(create_request_body)
create_request_body_v58['properties'].update({
    'node': {'type': ['string', 'null']},
})

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
            'value': {
                'type': ['string', 'object', 'null', 'integer', 'boolean']
            },
        },
        'required': ['op', 'path'],
        'additionalProperties': False,
    },
}

# TODO(stephenfin): The code suggests that we should be allowing 'owner' here,
# but it's not included in PATCH_ALLOWED_FIELDS so I have ignored it for now
update_request_body_v60 = copy.deepcopy(update_request_body)

# response body schemas

_allocation_response_body = {
    'type': 'object',
    'properties': {
        'candidate_nodes': {
            'type': ['array', 'null'],
            'items': {'type': 'string'}
        },
        'created_at': {'type': 'string', 'format': 'date-time'},
        # TODO(stephenfin): I assume this can be stricter?
        'extra': {'type': ['object', 'null']},
        'last_error': {'type': ['string', 'null']},
        'links': response_types.links,
        'name': {'type': ['string', 'null']},
        'node_uuid': {'type': ['string', 'null'], 'format': 'uuid'},
        'resource_class': {'type': ['string', 'null'], 'maxLength': 80},
        'state': {
            'type': 'string',
            'enum': ['allocating', 'active', 'error']
        },
        'traits': {
            'type': ['array', 'null'],
            'items': response_types.traits,
        },
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': {'type': ['string', 'null'], 'format': 'uuid'},
    },
    # NOTE(stephenfin): The 'fields' parameter means nothing is required
    'required': [],
    'additionalProperties': False,
}

_allocation_response_body_v60 = copy.deepcopy(_allocation_response_body)
_allocation_response_body_v60['properties'].update({
    'owner': {'type': ['string', 'null']},
})

index_response_body = {
    'type': 'object',
    'properties': {
        'allocations': {
            'type': 'array',
            'items': copy.deepcopy(_allocation_response_body),
        },
    },
    'required': ['allocations'],
    'additionalProperties': False,
}
index_response_body['properties'].update({
    'next': {'type': 'string'},
})

index_response_body_v60 = copy.deepcopy(index_response_body)
index_response_body_v60['properties']['allocations']['items'] = (
    _allocation_response_body_v60
)

show_response_body = copy.deepcopy(_allocation_response_body)
show_response_body_v60 = copy.deepcopy(_allocation_response_body_v60)

create_response_body = copy.deepcopy(_allocation_response_body)
create_response_body_v60 = copy.deepcopy(_allocation_response_body_v60)

update_response_body = copy.deepcopy(_allocation_response_body)
update_response_body_v60 = copy.deepcopy(_allocation_response_body_v60)
