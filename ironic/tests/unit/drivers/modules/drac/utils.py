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

from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils


INFO_DICT = db_utils.get_test_drac_info()


class BaseDracTest(db_base.DbTestCase):
    def setUp(self):
        super(BaseDracTest, self).setUp()
        self.config(enabled_hardware_types=['idrac', 'fake-hardware'],
                    enabled_boot_interfaces=[
                        'idrac-redfish-virtual-media', 'fake'],
                    enabled_power_interfaces=['idrac-redfish', 'fake'],
                    enabled_management_interfaces=['idrac-redfish', 'fake'],
                    enabled_inspect_interfaces=[
                        'idrac-redfish', 'fake', 'no-inspect'],
                    enabled_vendor_interfaces=[
                        'idrac-redfish', 'fake', 'no-vendor'],
                    enabled_raid_interfaces=['idrac-redfish', 'fake',
                                             'no-raid'],
                    enabled_bios_interfaces=['idrac-redfish', 'no-bios'])


class DictToObj(object):
    """Returns a dictionary into a class"""
    def __init__(self, dictionary):
        for key in dictionary:
            setattr(self, key, dictionary[key])


def dict_to_namedtuple(name='GenericNamedTuple', values=None,
                       tuple_class=None):
    """Converts a dict to a collections.namedtuple"""

    if values is None:
        values = {}

    if tuple_class is None:
        tuple_class = collections.namedtuple(name, list(values))
    else:
        # Support different versions of the driver as fields change.
        values = {field: values.get(field) for field in tuple_class._fields}

    return tuple_class(**values)


def dict_of_object(data):
    """Create a dictionary object"""

    for k, v in data.items():
        if isinstance(v, dict):
            dict_obj = DictToObj(v)
            data[k] = dict_obj
    return data


def create_raid_setting(raid_settings_dict):
    """Returns the raid configuration tuple object"""
    return dict_to_namedtuple(values=raid_settings_dict)
