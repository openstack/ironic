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

from ironic.api.controllers.v1 import utils as api_utils
from ironic.api.schemas.common import request_types
from ironic.api.schemas.common import response_types


_template_fields = [
    'created_at', 'description', 'extra', 'links', 'name', 'steps',
    'updated_at', 'uuid',
]

_template_request_parameter = {
    'type': 'object',
    'properties': {'template_ident': request_types.uuid_or_name},
    'required': ['template_ident'],
    'additionalProperties': False,
}
show_request_parameter = _template_request_parameter
update_request_parameter = _template_request_parameter
delete_request_parameter = _template_request_parameter


def _fields_query():
    return {
        'type': 'array',
        'items': {'enum': _template_fields},
        'style': 'form',
        'explode': False,
    }


index_request_query = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': _fields_query(),
        'limit': {'type': 'integer'},
        'marker': request_types.name,
        'sort_dir': request_types.sort_dir,
        'sort_key': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

show_request_query = {
    'type': 'object',
    'properties': {'fields': _fields_query()},
    'required': [],
    'additionalProperties': False,
}

create_request_body = {
    'type': 'object',
    'properties': {
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'extra': {'type': ['object', 'null']},
        'name': api_utils.TRAITS_SCHEMA,
        'steps': {
            'type': 'array', 'items': api_utils.DEPLOY_STEP_SCHEMA,
            'minItems': 1,
        },
        'uuid': {'type': ['string', 'null'], 'format': 'uuid'},
    },
    'required': ['name', 'steps'],
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

_template_response_body = {
    'type': 'object',
    'properties': {
        'created_at': {'type': 'string', 'format': 'date-time'},
        'description': {'type': ['string', 'null'], 'maxLength': 255},
        'extra': {'type': ['object', 'null']},
        'links': response_types.links,
        'name': {'type': 'string'},
        'steps': {'type': 'array', 'items': api_utils.DEPLOY_STEP_SCHEMA},
        'updated_at': {'type': ['string', 'null'], 'format': 'date-time'},
        'uuid': response_types.uuid,
    },
    'required': [],
    'additionalProperties': False,
}

index_response_body = {
    'type': 'object',
    'properties': {
        'deploy_templates': {
            'type': 'array', 'items': _template_response_body,
        },
        'next': {'type': 'string'},
    },
    'required': ['deploy_templates'],
    'additionalProperties': False,
}

show_response_body = _template_response_body
create_response_body = _template_response_body
update_response_body = _template_response_body
