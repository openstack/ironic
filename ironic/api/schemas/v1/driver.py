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

import copy
from typing import Any

from ironic.api.schemas.common import request_types
from ironic.api.schemas.common import response_types


_base_driver_fields = ['hosts', 'links', 'name']
_standard_interfaces = [
    'boot', 'console', 'deploy', 'inspect', 'management', 'network', 'power',
    'raid', 'vendor',
]


def _interface_fields(interfaces):
    fields = []
    for interface in interfaces:
        fields.extend([
            'default_%s_interface' % interface,
            'enabled_%s_interfaces' % interface,
        ])
    return fields


def _driver_fields(interfaces=(), properties=False, driver_type=False):
    fields = list(_base_driver_fields)
    fields.extend(_interface_fields(interfaces))
    if properties:
        fields.append('properties')
    if driver_type:
        fields.append('type')
    return fields


def _fields_query(fields=None):
    return {
        'type': 'array',
        'items': {'enum': fields} if fields else {'type': 'string'},
        'style': 'form',
        'explode': False,
    }


_driver_request_parameter = {
    'type': 'object',
    'properties': {'driver_name': {'type': 'string'}},
    'required': ['driver_name'],
    'additionalProperties': False,
}
show_request_parameter = _driver_request_parameter
properties_request_parameter = _driver_request_parameter
methods_request_parameter = _driver_request_parameter
raid_request_parameter = _driver_request_parameter

passthru_request_parameter = {
    'type': 'object',
    'properties': {
        'driver_name': {'type': 'string'},
        'method': {'type': 'string'},
    },
    'required': ['driver_name', 'method'],
    'additionalProperties': False,
}

index_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {
        'detail': request_types.detail,
        'fields': _fields_query(),
        'type': {'type': 'string'},
    },
    'required': [],
    'additionalProperties': False,
}

index_request_query_v77 = copy.deepcopy(index_request_query)
index_request_query_v77['properties']['fields'] = _fields_query(
    _driver_fields(
        _standard_interfaces + ['storage', 'rescue', 'bios'], True, True))

index_request_query_v86 = copy.deepcopy(index_request_query_v77)
index_request_query_v86['properties']['fields'] = _fields_query(
    _driver_fields(
        _standard_interfaces + ['storage', 'rescue', 'bios', 'firmware'],
        True, True))

show_request_query: dict[str, Any] = {
    'type': 'object',
    'properties': {'fields': _fields_query()},
    'required': [],
    'additionalProperties': False,
}

show_request_query_v77 = copy.deepcopy(show_request_query)
show_request_query_v77['properties']['fields'] = (
    index_request_query_v77['properties']['fields'])

show_request_query_v86 = copy.deepcopy(show_request_query_v77)
show_request_query_v86['properties']['fields'] = (
    index_request_query_v86['properties']['fields'])


def _driver_response_body(interfaces=(), properties=False, driver_type=False):
    response = {
        'type': 'object',
        'properties': {
            'hosts': {'type': 'array', 'items': {'type': 'string'}},
            'links': response_types.links,
            'name': {'type': 'string'},
        },
        'required': [],
        'additionalProperties': False,
    }
    if properties:
        response['properties']['properties'] = response_types.links
    if driver_type:
        response['properties']['type'] = {'type': 'string'}
    for interface in interfaces:
        response['properties']['default_%s_interface' % interface] = {
            'type': ['string', 'null'],
        }
        response['properties']['enabled_%s_interfaces' % interface] = {
            'type': 'array', 'items': {'type': 'string'},
        }
    return response


_driver_response_body_v1_13 = _driver_response_body()
_driver_response_body_v14_29 = _driver_response_body(properties=True)
_driver_response_body_v30_32 = _driver_response_body(
    _standard_interfaces, True, True)
_driver_response_body_v33_37 = _driver_response_body(
    _standard_interfaces + ['storage'], True, True)
_driver_response_body_v38_39 = _driver_response_body(
    _standard_interfaces + ['storage', 'rescue'], True, True)
_driver_response_body_v40_85 = _driver_response_body(
    _standard_interfaces + ['storage', 'rescue', 'bios'], True, True)
_driver_response_body_v86 = _driver_response_body(
    _standard_interfaces + ['storage', 'rescue', 'bios', 'firmware'],
    True, True)


def _index_response_body(item_schema):
    return {
        'type': 'object',
        'properties': {
            'drivers': {'type': 'array', 'items': item_schema},
        },
        'required': ['drivers'],
        'additionalProperties': False,
    }

index_response_body_v1_13 = _index_response_body(_driver_response_body_v1_13)
index_response_body_v14_29 = _index_response_body(_driver_response_body_v14_29)
index_response_body_v30_32 = _index_response_body(_driver_response_body_v30_32)
index_response_body_v33_37 = _index_response_body(_driver_response_body_v33_37)
index_response_body_v38_39 = _index_response_body(_driver_response_body_v38_39)
index_response_body_v40_85 = _index_response_body(_driver_response_body_v40_85)
index_response_body_v86 = _index_response_body(_driver_response_body_v86)

show_response_body_v1_13 = _driver_response_body_v1_13
show_response_body_v14_29 = _driver_response_body_v14_29
show_response_body_v30_32 = _driver_response_body_v30_32
show_response_body_v33_37 = _driver_response_body_v33_37
show_response_body_v38_39 = _driver_response_body_v38_39
show_response_body_v40_85 = _driver_response_body_v40_85
show_response_body_v86 = _driver_response_body_v86

# Driver implementations own the contracts for these extension payloads.
properties_response_body = {
    'type': 'object', 'additionalProperties': {'type': 'string'},
}
methods_response_body = {
    'type': 'object',
    'additionalProperties': {
        'type': 'object',
        'properties': {
            'async': {'type': 'boolean'},
            'attach': {'type': 'boolean'},
            'description': {'type': 'string'},
            'http_methods': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['async', 'attach', 'description', 'http_methods'],
        'additionalProperties': False,
    },
}
raid_response_body = properties_response_body
passthru_request_body = {}
passthru_response_body = {}
