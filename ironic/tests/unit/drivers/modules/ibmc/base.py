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

from unittest import mock

from ironic.drivers.modules.ibmc import utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class IBMCTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IBMCTestCase, self).setUp()
        self.driver_info = db_utils.get_test_ibmc_info()
        self.config(enabled_hardware_types=['ibmc'],
                    enabled_power_interfaces=['ibmc'],
                    enabled_management_interfaces=['ibmc'],
                    enabled_vendor_interfaces=['ibmc'],
                    enabled_raid_interfaces=['ibmc'])
        self.node = obj_utils.create_test_node(
            self.context, driver='ibmc', driver_info=self.driver_info)
        self.ibmc = utils.parse_driver_info(self.node)

    @staticmethod
    def mock_ibmc_conn(ibmc_client_connect):
        conn = mock.Mock(system=mock.PropertyMock())
        conn.__enter__ = mock.Mock(return_value=conn)
        conn.__exit__ = mock.Mock(return_value=None)
        ibmc_client_connect.return_value = conn
        return conn
