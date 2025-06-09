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
