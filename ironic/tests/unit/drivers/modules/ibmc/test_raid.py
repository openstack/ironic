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

"""Test class for iBMC RAID interface."""

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.ilo import raid as ilo_raid
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.ibmc import base

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')
ibmc_error = importutils.try_import('ibmc_client.exceptions')

INFO_DICT = db_utils.get_test_ilo_info()


class IbmcRAIDTestCase(base.IBMCTestCase):

    def setUp(self):
        super(IbmcRAIDTestCase, self).setUp()
        self.driver = mock.Mock(raid=ilo_raid.Ilo5RAID())
        self.target_raid_config = {
            "logical_disks": [
                {
                    'size_gb': 200,
                    'raid_level': 0,
                    'is_root_volume': True
                },
                {
                    'size_gb': 'MAX',
                    'raid_level': 5
                }
            ]
        }
        self.node.target_raid_config = self.target_raid_config
        self.node.save()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_create_configuration_without_delete(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.apply_raid_configuration.return_value = None

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)
            self.assertIsNone(result, "synchronous create raid configuration "
                                      "should return None")

        conn.system.storage.apply_raid_configuration.assert_called_once_with(
            self.node.target_raid_config.get('logical_disks')
        )

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_create_configuration_with_delete(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.return_value = None
        conn.system.storage.apply_raid_configuration.return_value = None

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=True)
            self.assertIsNone(result, "synchronous create raid configuration "
                                      "should return None")

        conn.system.storage.delete_all_raid_configuration.assert_called_once()
        conn.system.storage.apply_raid_configuration.assert_called_once_with(
            self.node.target_raid_config.get('logical_disks')
        )

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_create_configuration_without_nonroot(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.return_value = None
        conn.system.storage.apply_raid_configuration.return_value = None

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=False,
                delete_existing=True)
            self.assertIsNone(result, "synchronous create raid configuration "
                                      "should return None")

        conn.system.storage.delete_all_raid_configuration.assert_called_once()
        conn.system.storage.apply_raid_configuration.assert_called_once_with(
            [{'size_gb': 200, 'raid_level': 0, 'is_root_volume': True}]
        )

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_create_configuration_without_root(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.return_value = None
        conn.system.storage.apply_raid_configuration.return_value = None

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.raid.create_configuration(
                task, create_root_volume=False, create_nonroot_volumes=True,
                delete_existing=True)
            self.assertIsNone(result, "synchronous create raid configuration "
                                      "should return None")

        conn.system.storage.delete_all_raid_configuration.assert_called_once()
        conn.system.storage.apply_raid_configuration.assert_called_once_with(
            [{'size_gb': 'MAX', 'raid_level': 5}]
        )

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_create_configuration_failed(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.return_value = None
        conn.system.storage.apply_raid_configuration.side_effect = (
            ibmc_error.IBMCClientError
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(
                exception.IBMCError, 'create iBMC RAID configuration',
                task.driver.raid.create_configuration, task,
                create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=True)

        conn.system.storage.delete_all_raid_configuration.assert_called_once()
        conn.system.storage.apply_raid_configuration.assert_called_once_with(
            self.node.target_raid_config.get('logical_disks')
        )

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_delete_configuration_success(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.return_value = None

        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = task.driver.raid.delete_configuration(task)
            self.assertIsNone(result, "synchronous delete raid configuration "
                                      "should return None")

        conn.system.storage.delete_all_raid_configuration.assert_called_once()

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_sync_delete_configuration_failed(self, connect_ibmc):
        conn = self.mock_ibmc_conn(connect_ibmc)
        conn.system.storage.delete_all_raid_configuration.side_effect = (
            ibmc_error.IBMCClientError
        )

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(
                exception.IBMCError, 'delete iBMC RAID configuration',
                task.driver.raid.delete_configuration, task)

        conn.system.storage.delete_all_raid_configuration.assert_called_once()
