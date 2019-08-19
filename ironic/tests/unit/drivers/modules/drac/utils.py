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
import os

from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils


INFO_DICT = db_utils.get_test_drac_info()

DCIM_NICEnumeration = ('http://schemas.dell.com/wbem/wscim/1/cim-schema/2/'
                       'DCIM_NICEnumeration')  # noqa

FAKE_ENDPOINT = {
    'host': '1.2.3.4',
    'port': '443',
    'path': '/wsman',
    'protocol': 'https',
    'username': 'admin',
    'password': 's3cr3t'
}


class BaseDracTest(db_base.DbTestCase):
    def setUp(self):
        super(BaseDracTest, self).setUp()
        self.config(enabled_hardware_types=['idrac', 'fake-hardware'],
                    enabled_power_interfaces=['idrac', 'fake'],
                    enabled_management_interfaces=['idrac', 'fake'],
                    enabled_inspect_interfaces=['idrac', 'fake', 'no-inspect'],
                    enabled_vendor_interfaces=['idrac', 'fake', 'no-vendor'],
                    enabled_raid_interfaces=['idrac', 'fake', 'no-raid'])


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


def load_wsman_xml(name):
    """Helper function to load a WSMan XML response from a file."""

    with open(os.path.join(os.path.dirname(__file__), 'wsman_mocks',
                           '%s.xml' % name), 'r') as f:
        xml_body = f.read()

    return xml_body


NICEnumerations = {
    DCIM_NICEnumeration: {
        'ok': load_wsman_xml('nic_enumeration-enum-ok'),
    }
}
