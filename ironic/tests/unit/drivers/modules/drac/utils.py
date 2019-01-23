#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import collections


class DictToObj(object):
    """Returns a dictionary into a class"""
    def __init__(self, dictionary):
        for key in dictionary:
            setattr(self, key, dictionary[key])


def dict_to_namedtuple(name='GenericNamedTuple', values=None):
    """Converts a dict to a collections.namedtuple"""

    if values is None:
        values = {}

    return collections.namedtuple(name, list(values))(**values)


def dict_of_object(data):
    """Create a dictionary object"""

    for k, v in data.items():
        if isinstance(v, dict):
            dict_obj = DictToObj(v)
            data[k] = dict_obj
    return data
