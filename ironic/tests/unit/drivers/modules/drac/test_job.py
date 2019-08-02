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
Test class for DRAC job specific methods
"""

from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracJobTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracJobTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)
        self.job_dict = {
            'id': 'JID_001436912645',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': '00000101000000',
            'until_time': 'TIME_NA',
            'message': 'Job in progress',
            'status': 'Running',
            'percent_complete': 34}
        self.job = test_utils.make_job(self.job_dict)

    def test_get_job(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.get_job.return_value = self.job

        job = drac_job.get_job(self.node, 'foo')

        mock_client.get_job.assert_called_once_with('foo')
        self.assertEqual(self.job, job)

    def test_get_job_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.get_job.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_job.get_job, self.node, 'foo')

    def test_list_unfinished_jobs(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [self.job]

        jobs = drac_job.list_unfinished_jobs(self.node)

        mock_client.list_jobs.assert_called_once_with(only_unfinished=True)
        self.assertEqual([self.job], jobs)

    def test_list_unfinished_jobs_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.list_jobs.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_job.list_unfinished_jobs, self.node)

    def test_validate_job_queue(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = []

        drac_job.validate_job_queue(self.node)

        mock_client.list_jobs.assert_called_once_with(only_unfinished=True)

    def test_validate_job_queue_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.list_jobs.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_job.validate_job_queue, self.node)

    def test_validate_job_queue_invalid(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [self.job]

        self.assertRaises(exception.DracOperationError,
                          drac_job.validate_job_queue, self.node)

    def test_validate_job_queue_name_prefix(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [self.job]

        drac_job.validate_job_queue(self.node, name_prefix='Fake')

        mock_client.list_jobs.assert_called_once_with(only_unfinished=True)

    def test_validate_job_queue_name_prefix_invalid(self,
                                                    mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [self.job]

        self.assertRaises(exception.DracOperationError,
                          drac_job.validate_job_queue, self.node,
                          name_prefix='ConfigBIOS')


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracVendorPassthruJobTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracVendorPassthruJobTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)
        self.job_dict = {
            'id': 'JID_001436912645',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': '00000101000000',
            'until_time': 'TIME_NA',
            'message': 'Job in progress',
            'status': 'Running',
            'percent_complete': 34}
        self.job = test_utils.make_job(self.job_dict)

    def test_list_unfinished_jobs(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_jobs.return_value = [self.job]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            resp = task.driver.vendor.list_unfinished_jobs(task)

        mock_client.list_jobs.assert_called_once_with(only_unfinished=True)
        self.assertEqual([self.job_dict], resp['unfinished_jobs'])

    def test_list_unfinished_jobs_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.list_jobs.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.vendor.list_unfinished_jobs, task)
