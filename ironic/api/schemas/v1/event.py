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

# request body schemas

_event_types = [
    'network.bind_port', 'network.unbind_port', 'network.delete_port',
]

create_request_body = {
    'type': 'object',
    'properties': {
        'events': {
            'type': 'array',
            'minItems': 1,
            # NOTE(stephenfin): This will likely need to be much more
            # complicated (lots of oneOf) if/when we need to support other
            # types of event
            'items': {
                'type': 'object',
                'properties': {
                    'event': {'type': 'string', 'enum': _event_types},
                    'port_id': {'type': 'string', 'format': 'uuid'},
                    'mac_address': {'type': 'string', 'format': 'mac-address'},
                    'status': {'type': 'string'},
                    'device_id': {
                        'type': ['string', 'null'], 'format': 'uuid'
                    },
                    'binding:host_id': {
                        'type': ['string', 'null'], 'format': 'uuid'
                    },
                    'binding:vnic_type': {'type': ['string', 'null']},
                },
                'required': ['event', 'port_id', 'mac_address', 'status'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['events'],
    'additionalProperties': False,
}
