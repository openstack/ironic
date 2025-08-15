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

import os_traits


STANDARD_TRAITS = os_traits.get_traits()
CUSTOM_TRAIT_PATTERN = "^%s[A-Z0-9_]+$" % os_traits.CUSTOM_NAMESPACE

traits = {
    'type': 'string',
    'minLength': 1,
    'maxLength': 255,
    'anyOf': [
        {'pattern': CUSTOM_TRAIT_PATTERN},
        {'enum': STANDARD_TRAITS},
    ]
}

links = {
    'type': 'array',
    'items': {
        'type': 'object',
        'properties': {
            'rel': {
                'type': 'string',
                'enum': ['self', 'bookmark'],
            },
            'href': {
                'type': 'string',
                'format': 'uri',
            },
        },
        'required': ['rel', 'href'],
        'additionalProperties': False,
    },
}
