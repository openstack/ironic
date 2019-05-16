#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Test base class for iBMC Driver."""

from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class IntelIPMITestCase(db_base.DbTestCase):

    def setUp(self):
        super(IntelIPMITestCase, self).setUp()
        self.driver_info = db_utils.get_test_ipmi_info()
        self.config(enabled_hardware_types=['intel-ipmi'],
                    enabled_management_interfaces=['intel-ipmitool'],
                    enabled_power_interfaces=['ipmitool'])
        self.node = obj_utils.create_test_node(
            self.context, driver='intel-ipmi', driver_info=self.driver_info)
