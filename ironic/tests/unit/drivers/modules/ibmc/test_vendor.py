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
"""Test class for iBMC vendor interface."""

from unittest import mock

from oslo_utils import importutils

from ironic.conductor import task_manager
from ironic.drivers.modules.ibmc import utils
from ironic.tests.unit.drivers.modules.ibmc import base

ibmc_client = importutils.try_import('ibmc_client')


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
class IBMCVendorTestCase(base.IBMCTestCase):

    def setUp(self):
        super(IBMCVendorTestCase, self).setUp()

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_list_boot_type_order(self, connect_ibmc):
        # Mocks
        conn = self.mock_ibmc_conn(connect_ibmc)
        boot_up_seq = ['Pxe', 'Hdd', 'Others', 'Cd']
        conn.system.get.return_value = mock.Mock(
            boot_sequence=['Pxe', 'Hdd', 'Others', 'Cd']
        )

        expected = {'boot_up_sequence': boot_up_seq}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            seq = task.driver.vendor.boot_up_seq(task)
            conn.system.get.assert_called_once_with()
            connect_ibmc.assert_called_once_with(**self.ibmc)
            self.assertEqual(expected, seq)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_list_raid_controller(self, connect_ibmc):
        # Mocks
        conn = self.mock_ibmc_conn(connect_ibmc)

        ctrl = mock.Mock()
        summary = ctrl.summary.return_value
        conn.system.storage.list.return_value = [ctrl]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            summries = task.driver.vendor.get_raid_controller_list(task)
            ctrl.summary.assert_called_once_with()
            conn.system.storage.list.assert_called_once_with()
            connect_ibmc.assert_called_once_with(**self.ibmc)
            self.assertEqual([summary], summries)
