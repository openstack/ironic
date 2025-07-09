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


index_request_query = {
    'type': 'object',
    'properties': {
        'fields': {
            'type': 'array',
            'items': {
                'enum': [
                    'created_at',
                    'updated_at',
                    'component',
                    'initial_version',
                    'current_version',
                    'last_version_flashed',
                ],
            },
            # OpenAPI-specific properties
            # https://swagger.io/docs/specification/v3_0/serialization/#query-parameters
            'style': 'form',
            'explode': False,
        },
        'detail': {'type': 'boolean'},
    },
    'required': [],
    'additionalProperties': False,
}

_firmware_response_body = {
    'type': 'object',
    'properties': {
        'component': {'type': 'string'},
        'initial_version': {'type': ['string', 'null']},
        'current_version': {'type': ['string', 'null']},
        'last_version_flashed': {'type': ['string', 'null']},
        'created_at': {'type': 'string', 'format': 'date-time'},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
    },
    # NOTE(adamcarthur) - These are always returned, regardless of the
    # value of the fields parameter
    'required': ['created_at', 'updated_at'],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'firmware': {
            'type': 'array',
            'items': _firmware_response_body,
        },
    },
    'required': ['firmware'],
    'additionalProperties': False,
}
index_response_body['properties'].update({
    'next': {'type': 'string'},
})
