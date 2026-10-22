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

"""
Test class for DRAC firmware utilities
"""

from unittest import mock

import sushy
from sushy.oem.dell.resources.manager import (
    job_collection as sushy_job_collection)

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import firmware as drac_fw
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


# Mirrors sushy's DellJob.FAILED_JOB_STATES and TERMINAL_JOB_STATES, so
# that the mocked is_failed/is_finished behave like the real ones.
_FAILED_JOB_STATES = frozenset({'CompletedWithErrors', 'Failed',
                                'RebootFailed'})
_TERMINAL_JOB_STATES = _FAILED_JOB_STATES | {'Completed'}


def _dell_job(identity, job_state=None, message=None):
    """Build a mock sushy DellJob object.

    is_finished and is_failed are derived from the job state the same
    way sushy derives them, and are always set: the code under test
    relies on them, and a bare Mock attribute would be truthy.
    """
    job = mock.Mock(spec=['identity', 'job_state', 'job_type',
                          'message', 'message_id', 'percent_complete',
                          'is_finished', 'is_failed'])
    job.identity = identity
    job.job_state = job_state
    job.message = message
    job.is_failed = job_state in _FAILED_JOB_STATES
    job.is_finished = job_state in _TERMINAL_JOB_STATES
    return job


class JidFromTaskMonitorTestCase(test_utils.BaseDracTest):

    def test_jid(self):
        self.assertEqual(
            'JID_839968767020',
            drac_fw.jid_from_task_monitor(
                '/redfish/v1/TaskService/TaskMonitors/JID_839968767020'))

    def test_trailing_slash(self):
        self.assertEqual(
            'JID_839968767020',
            drac_fw.jid_from_task_monitor(
                '/redfish/v1/TaskService/TaskMonitors/JID_839968767020/'))

    def test_not_a_jid(self):
        self.assertIsNone(drac_fw.jid_from_task_monitor(
            '/redfish/v1/TaskService/TaskMonitors/1234'))

    def test_empty(self):
        self.assertIsNone(drac_fw.jid_from_task_monitor(''))
        self.assertIsNone(drac_fw.jid_from_task_monitor(None))


class _LcJobsTestBase(test_utils.BaseDracTest):

    def setUp(self):
        super(_LcJobsTestBase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

    def _mock_job_collection(self, get_system_mock, jobs=None,
                             get_jobs_side_effect=None):
        """Mock manager.get_oem_extension('Dell').job_collection.

        :param jobs: DellJob objects get_jobs() should return
        :param get_jobs_side_effect: if given, get_jobs() raises this
        """
        manager_mock = mock.Mock()
        oem_mock = manager_mock.get_oem_extension.return_value
        job_collection = mock.Mock(spec=['get_jobs'])
        if get_jobs_side_effect is not None:
            job_collection.get_jobs.side_effect = get_jobs_side_effect
        else:
            job_collection.get_jobs.return_value = jobs or []
        oem_mock.job_collection = job_collection
        get_system_mock.return_value.managers = [manager_mock]
        return job_collection


class CheckLcJobsTestCase(_LcJobsTestBase):

    def test_check_lc_jobs_empty_jids(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(task, [])

        self.assertEqual((drac_fw.LCJobStatus.DONE, None), result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_oem_unavailable(self, get_system_mock):
        get_system_mock.return_value.managers = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111'])

        self.assertEqual(drac_fw.LCJobStatus.UNAVAILABLE, status)
        self.assertIsNone(detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_all_done(self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Completed',
                      'Job completed successfully.'),
            _dell_job('JID_222222222222', 'Completed',
                      'Job completed successfully.'),
        ]
        job_collection = self._mock_job_collection(
            get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_222222222222'])

        self.assertEqual((drac_fw.LCJobStatus.DONE, None), result)
        job_collection.get_jobs.assert_called_once_with(
            job_ids=['JID_111111111111', 'JID_222222222222'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_with_real_sushy_collection(self, get_system_mock):
        """Exercise the public Sushy DellJobCollection contract."""
        if not hasattr(sushy_job_collection.DellJobCollection, 'get_jobs'):
            self.skipTest('requires sushy 5.14.0 DellJobCollection.get_jobs')

        path = '/redfish/v1/Managers/iDRAC.Embedded.1/Oem/Dell/Jobs'
        collection_response = mock.Mock()
        collection_response.json.return_value = {'@odata.id': path}
        jobs_response = mock.Mock()
        jobs_response.json.return_value = {
            'Members': [
                {'Id': 'JID_111111111111', 'JobState': 'Completed'},
                {'Id': 'JID_222222222222', 'JobState': 'Running'},
            ],
        }
        connector = mock.Mock()
        connector.get.side_effect = [collection_response, jobs_response]
        job_collection = sushy_job_collection.DellJobCollection(
            connector, path)
        manager = mock.Mock()
        manager.get_oem_extension.return_value.job_collection = job_collection
        get_system_mock.return_value.managers = [manager]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_222222222222'])

        self.assertEqual(
            (drac_fw.LCJobStatus.RUNNING, 'JID_222222222222'), result)
        connector.get.assert_any_call(path + '?$expand=.($levels=1)')

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_one_running(self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Completed',
                      'Job completed successfully.'),
            _dell_job('JID_222222222222', 'Running',
                      'Job in progress.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_222222222222'])

        self.assertEqual(drac_fw.LCJobStatus.RUNNING, status)
        self.assertEqual('JID_222222222222', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_one_failed(self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Failed',
                      'Unable to apply firmware.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111'])

        self.assertEqual(drac_fw.LCJobStatus.ERROR, status)
        self.assertIn('JID_111111111111', detail)
        self.assertIn('Unable to apply firmware.', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_mixed_failed_and_running(self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Failed',
                      'Unable to apply firmware.'),
            _dell_job('JID_222222222222', 'Running',
                      'Job in progress.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_222222222222'])

        # The failure is only reported once nothing is running any more.
        self.assertEqual(drac_fw.LCJobStatus.RUNNING, status)
        self.assertEqual('JID_222222222222', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_failed_and_completed(self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Failed',
                      'Unable to apply firmware.'),
            _dell_job('JID_222222222222', 'Completed',
                      'Job completed successfully.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_222222222222'])

        self.assertEqual(drac_fw.LCJobStatus.ERROR, status)
        self.assertIn('JID_111111111111', detail)
        self.assertNotIn('JID_222222222222', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_missing_from_members_is_error(
            self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'Completed',
                      'Job completed successfully.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(
                task, ['JID_111111111111', 'JID_999999999999'])

        status, detail = result
        self.assertEqual(drac_fw.LCJobStatus.ERROR, status)
        self.assertIn('JID_999999999999: not found', detail)
        self.assertNotIn('JID_111111111111', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_unknown_state_treated_as_running(
            self, get_system_mock):
        jobs = [
            _dell_job('JID_111111111111', 'SomeNewState', 'Unknown.'),
        ]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111'])

        self.assertEqual(drac_fw.LCJobStatus.RUNNING, status)
        self.assertEqual('JID_111111111111', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_missing_job_state_treated_as_running(
            self, get_system_mock):
        jobs = [_dell_job('JID_111111111111', None, None)]
        self._mock_job_collection(get_system_mock, jobs=jobs)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111'])

        self.assertEqual(drac_fw.LCJobStatus.RUNNING, status)
        self.assertEqual('JID_111111111111', detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_get_jobs_fails(self, get_system_mock):
        # A read failure says nothing about the jobs, so it is not turned
        # into a status.
        job_collection = self._mock_job_collection(
            get_system_mock,
            get_jobs_side_effect=sushy.exceptions.ConnectionError(
                url='http://bmc', error='connection error'))

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(sushy.exceptions.ConnectionError,
                              drac_fw.check_lc_jobs, task,
                              ['JID_111111111111'])

        job_collection.get_jobs.assert_called_once_with(
            job_ids=['JID_111111111111'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_get_system_fails(self, get_system_mock):
        get_system_mock.side_effect = exception.RedfishError(
            error='BMC unreachable')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.RedfishError,
                              drac_fw.check_lc_jobs, task,
                              ['JID_111111111111'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_managers_unreadable(self, get_system_mock):
        type(get_system_mock.return_value).managers = mock.PropertyMock(
            side_effect=sushy.exceptions.MissingAttributeError(
                attribute='Links/ManagedBy', resource='/redfish/v1/Systems/1'))

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(sushy.exceptions.MissingAttributeError,
                              drac_fw.check_lc_jobs, task,
                              ['JID_111111111111'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_oem_extension_not_found(self, get_system_mock):
        manager_mock = mock.Mock()
        manager_mock.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError(
                resource='Manager', name='Dell'))
        get_system_mock.return_value.managers = [manager_mock]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            status, detail = drac_fw.check_lc_jobs(
                task, ['JID_111111111111'])

        self.assertEqual(drac_fw.LCJobStatus.UNAVAILABLE, status)
        self.assertIsNone(detail)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_oem_extension_on_second_manager(
            self, get_system_mock):
        job_collection = self._mock_job_collection(
            get_system_mock,
            jobs=[_dell_job('JID_111111111111', 'Completed')])
        other_manager = mock.Mock()
        other_manager.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError(
                resource='Manager', name='Dell'))
        managers = get_system_mock.return_value.managers
        get_system_mock.return_value.managers = [other_manager] + managers

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(task, ['JID_111111111111'])

        self.assertEqual((drac_fw.LCJobStatus.DONE, None), result)
        job_collection.get_jobs.assert_called_once_with(
            job_ids=['JID_111111111111'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_check_lc_jobs_job_collection_not_linked(self, get_system_mock):
        manager_mock = mock.Mock()
        type(manager_mock.get_oem_extension.return_value).job_collection = (
            mock.PropertyMock(side_effect=(
                sushy.exceptions.MissingAttributeError(
                    attribute='Links/Oem/Dell/Jobs', resource='Manager'))))
        get_system_mock.return_value.managers = [manager_mock]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_lc_jobs(task, ['JID_111111111111'])

        self.assertEqual((drac_fw.LCJobStatus.UNAVAILABLE, None), result)


class CheckScheduledIdracJobTestCase(_LcJobsTestBase):

    UPDATE = {'task_monitor': '/redfish/v1/TaskService/TaskMonitors/'
                              'JID_839968767020'}

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_scheduled(self, get_system_mock):
        job = _dell_job('JID_839968767020', 'Scheduled')
        self._mock_job_collection(get_system_mock, jobs=[job])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(task, self.UPDATE)

        self.assertIs(result, True)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_finished(self, get_system_mock):
        job = _dell_job('JID_839968767020', 'Completed',
                        'Job completed successfully.')
        self._mock_job_collection(get_system_mock, jobs=[job])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(task, self.UPDATE)

        self.assertIs(result, False)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_failed(self, get_system_mock):
        job = _dell_job('JID_839968767020', 'Failed',
                        'Unable to download the image.')
        self._mock_job_collection(get_system_mock, jobs=[job])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(task, self.UPDATE)

        self.assertIs(result, False)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_absent(self, get_system_mock):
        self._mock_job_collection(get_system_mock, jobs=[])

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(task, self.UPDATE)

        self.assertIs(result, False)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_oem_unavailable(self, get_system_mock):
        manager_mock = mock.Mock()
        manager_mock.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError(
                resource='Manager', name='Dell'))
        get_system_mock.return_value.managers = [manager_mock]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(task, self.UPDATE)

        self.assertIsNone(result)

    def test_no_task_monitor(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(
                task, {'task_monitor': ''})

        self.assertIsNone(result)

    def test_task_monitor_not_a_jid(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = drac_fw.check_scheduled_idrac_job(
                task, {'task_monitor': '/redfish/v1/TaskMonitors/1234'})

        self.assertIsNone(result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_read_error(self, get_system_mock):
        self._mock_job_collection(
            get_system_mock,
            get_jobs_side_effect=sushy.exceptions.ConnectionError(
                url='http://bmc', error='connection error'))

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(sushy.exceptions.ConnectionError,
                              drac_fw.check_scheduled_idrac_job,
                              task, self.UPDATE)
