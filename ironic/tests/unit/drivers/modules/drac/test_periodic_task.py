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

"""
Test class for DRAC periodic tasks
"""

import mock

from ironic.common import driver_factory
from ironic.conductor import task_manager
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import raid as drac_raid
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracPeriodicTaskTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracPeriodicTaskTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)
        self.driver = driver_factory.get_driver("fake_drac")
        self.job = {
            'id': 'JID_001436912645',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': '00000101000000',
            'until_time': 'TIME_NA',
            'message': 'Job in progress',
            'state': 'Running',
            'percent_complete': 34}
        self.virtual_disk = {
            'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
            'name': 'disk 0',
            'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
            'controller': 'RAID.Integrated.1-1',
            'raid_level': '1',
            'size_mb': 571776,
            'state': 'ok',
            'raid_state': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None
        }

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_job_status(self, mock_acquire):
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock manager
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'pxe_drac',
                      {'raid_config_job_ids': ['42']})]
        mock_manager.iter_nodes.return_value = node_list
        # mock task_manager.acquire
        task = mock.Mock(node=self.node,
                         driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        # mock _check_node_raid_jobs
        self.driver.raid._check_node_raid_jobs = mock.Mock()

        self.driver.raid._query_raid_config_job_status(mock_manager,
                                                       self.context)

        self.driver.raid._check_node_raid_jobs.assert_called_once_with(task)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_config_job_status_no_config_jobs(self, mock_acquire):
        # mock manager
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'pxe_drac', {})]
        mock_manager.iter_nodes.return_value = node_list
        # mock task_manager.acquire
        task = mock.Mock(node=self.node,
                         driver=self.driver)
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        # mock _check_node_raid_jobs
        self.driver.raid._check_node_raid_jobs = mock.Mock()

        self.driver.raid._query_raid_config_job_status(mock_manager, None)

        self.assertEqual(0, self.driver.raid._check_node_raid_jobs.call_count)

    def test__query_raid_config_job_status_no_nodes(self):
        # mock manager
        mock_manager = mock.Mock()
        node_list = []
        mock_manager.iter_nodes.return_value = node_list
        # mock _check_node_raid_jobs
        self.driver.raid._check_node_raid_jobs = mock.Mock()

        self.driver.raid._query_raid_config_job_status(mock_manager, None)

        self.assertEqual(0, self.driver.raid._check_node_raid_jobs.call_count)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    def test__check_node_raid_jobs_without_update(self, mock_get_drac_client):
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node)
        # mock dracclient.get_job
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = test_utils.dict_to_namedtuple(
            values=self.job)

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_called_once_with('42')
        self.assertEqual(0, mock_client.list_virtual_disks.call_count)
        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual({}, self.node.raid_config)
        self.assertIs(False, self.node.maintenance)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid.DracRAID, 'get_logical_disks',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_base_vendor, '_notify_conductor_resume_clean')
    def test__check_node_raid_jobs_with_completed_job(
            self, mock_notify_conductor_resume_clean,
            mock_get_logical_disks, mock_get_drac_client):
        expected_logical_disk = {'size_gb': 558,
                                 'raid_level': '1',
                                 'name': 'disk 0'}
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node, context=self.context)
        # mock dracclient.get_job
        self.job['state'] = 'Completed'
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = test_utils.dict_to_namedtuple(
            values=self.job)
        # mock driver.raid.get_logical_disks
        mock_get_logical_disks.return_value = {
            'logical_disks': [expected_logical_disk]
        }

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_called_once_with('42')
        self.node.refresh()
        self.assertEqual([],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual([expected_logical_disk],
                         self.node.raid_config['logical_disks'])
        mock_notify_conductor_resume_clean.assert_called_once_with(task)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    def test__check_node_raid_jobs_with_failed_job(self, mock_get_drac_client):
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node, context=self.context)
        # mock dracclient.get_job
        self.job['state'] = 'Failed'
        self.job['message'] = 'boom'
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = test_utils.dict_to_namedtuple(
            values=self.job)
        # mock dracclient.list_virtual_disks
        mock_client.list_virtual_disks.return_value = [
            test_utils.dict_to_namedtuple(values=self.virtual_disk)]

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_called_once_with('42')
        self.assertEqual(0, mock_client.list_virtual_disks.call_count)
        self.node.refresh()
        self.assertEqual([],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual({}, self.node.raid_config)
        task.process_event.assert_called_once_with('fail')

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid.DracRAID, 'get_logical_disks',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_base_vendor, '_notify_conductor_resume_clean')
    def test__check_node_raid_jobs_with_completed_job_already_failed(
            self, mock_notify_conductor_resume_clean,
            mock_get_logical_disks, mock_get_drac_client):
        expected_logical_disk = {'size_gb': 558,
                                 'raid_level': '1',
                                 'name': 'disk 0'}
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42'],
                                'raid_config_job_failure': True}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node, context=self.context)
        # mock dracclient.get_job
        self.job['state'] = 'Completed'
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = test_utils.dict_to_namedtuple(
            values=self.job)
        # mock driver.raid.get_logical_disks
        mock_get_logical_disks.return_value = {
            'logical_disks': [expected_logical_disk]
        }

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_called_once_with('42')
        self.node.refresh()
        self.assertEqual([],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertNotIn('raid_config_job_failure',
                         self.node.driver_internal_info)
        self.assertNotIn('logical_disks', self.node.raid_config)
        task.process_event.assert_called_once_with('fail')

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid.DracRAID, 'get_logical_disks',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_base_vendor, '_notify_conductor_resume_clean')
    def test__check_node_raid_jobs_with_multiple_jobs_completed(
            self, mock_notify_conductor_resume_clean,
            mock_get_logical_disks, mock_get_drac_client):
        expected_logical_disk = {'size_gb': 558,
                                 'raid_level': '1',
                                 'name': 'disk 0'}
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42', '36']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node, context=self.context)
        # mock dracclient.get_job
        self.job['state'] = 'Completed'
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = test_utils.dict_to_namedtuple(
            values=self.job)
        # mock driver.raid.get_logical_disks
        mock_get_logical_disks.return_value = {
            'logical_disks': [expected_logical_disk]
        }

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_has_calls([mock.call('42'),
                                              mock.call('36')])
        self.node.refresh()
        self.assertEqual([],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertNotIn('raid_config_job_failure',
                         self.node.driver_internal_info)
        self.assertEqual([expected_logical_disk],
                         self.node.raid_config['logical_disks'])
        mock_notify_conductor_resume_clean.assert_called_once_with(task)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid.DracRAID, 'get_logical_disks',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_base_vendor, '_notify_conductor_resume_clean')
    def test__check_node_raid_jobs_with_multiple_jobs_failed(
            self, mock_notify_conductor_resume_clean,
            mock_get_logical_disks, mock_get_drac_client):
        expected_logical_disk = {'size_gb': 558,
                                 'raid_level': '1',
                                 'name': 'disk 0'}
        # mock node.driver_internal_info
        driver_internal_info = {'raid_config_job_ids': ['42', '36']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # mock task
        task = mock.Mock(node=self.node, context=self.context)
        # mock dracclient.get_job
        self.job['state'] = 'Completed'
        failed_job = self.job.copy()
        failed_job['state'] = 'Failed'
        failed_job['message'] = 'boom'
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.side_effect = [
            test_utils.dict_to_namedtuple(values=failed_job),
            test_utils.dict_to_namedtuple(values=self.job)]
        # mock driver.raid.get_logical_disks
        mock_get_logical_disks.return_value = {
            'logical_disks': [expected_logical_disk]
        }

        self.driver.raid._check_node_raid_jobs(task)

        mock_client.get_job.assert_has_calls([mock.call('42'),
                                              mock.call('36')])
        self.node.refresh()
        self.assertEqual([],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertNotIn('raid_config_job_failure',
                         self.node.driver_internal_info)
        self.assertNotIn('logical_disks', self.node.raid_config)
        task.process_event.assert_called_once_with('fail')
