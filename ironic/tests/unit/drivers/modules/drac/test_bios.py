# -*- coding: utf-8 -*-
#
# Copyright (c) 2015-2021 Dell Inc. or its subsidiaries.
# All Rights Reserved.
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
Test class for DRAC BIOS configuration specific methods
"""

from unittest import mock

from dracclient import exceptions as drac_exceptions

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import bios as drac_bios
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic import objects
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


class DracWSManBIOSConfigurationTestCase(test_utils.BaseDracTest):
    def setUp(self):
        super(DracWSManBIOSConfigurationTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

        patch_get_drac_client = mock.patch.object(
            drac_common, 'get_drac_client', spec_set=True, autospec=True)
        mock_get_drac_client = patch_get_drac_client.start()
        self.mock_client = mock_get_drac_client.return_value
        self.addCleanup(patch_get_drac_client.stop)

        proc_virt_attr = {
            'current_value': 'Enabled',
            'pending_value': None,
            'read_only': False,
            'possible_values': ['Enabled', 'Disabled']}
        mock_proc_virt_attr = mock.NonCallableMock(spec=[], **proc_virt_attr)
        mock_proc_virt_attr.name = 'ProcVirtualization'
        self.bios_attrs = {'ProcVirtualization': mock_proc_virt_attr}

        self.mock_client.set_lifecycle_settings.return_value = {
            "is_commit_required": True
        }
        self.mock_client.commit_pending_lifecycle_changes.return_value = \
            "JID_1234"

        self.mock_client.set_bios_settings.return_value = {
            "is_commit_required": True,
            "is_reboot_required": True
        }
        self.mock_client.commit_pending_bios_changes.return_value = \
            "JID_5678"

    @mock.patch.object(drac_common, 'parse_driver_info',
                       autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.bios.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            test_properties = task.driver.bios.get_properties()
            for each_property in drac_common.COMMON_PROPERTIES:
                self.assertIn(each_property, test_properties)

    @mock.patch.object(objects, 'BIOSSettingList', autospec=True)
    def test_cache_bios_settings_noop(self, mock_BIOSSettingList):
        create_list = []
        update_list = []
        delete_list = []
        nochange_list = [{'name': 'ProcVirtualization', 'value': 'Enabled'}]
        mock_BIOSSettingList.sync_node_setting.return_value = (
            create_list, update_list, delete_list, nochange_list)

        self.mock_client.list_bios_settings.return_value = self.bios_attrs

        with task_manager.acquire(self.context, self.node.uuid) as task:
            kwsettings = self.mock_client.list_bios_settings()
            settings = [{"name": name,
                         "value": attrib.__dict__['current_value']}
                        for name, attrib in kwsettings.items()]
            self.mock_client.list_bios_settings.reset_mock()
            task.driver.bios.cache_bios_settings(task)

            self.mock_client.list_bios_settings.assert_called_once_with()
            mock_BIOSSettingList.sync_node_setting.assert_called_once_with(
                task.context, task.node.id, settings)

            mock_BIOSSettingList.create.assert_not_called()
            mock_BIOSSettingList.save.assert_not_called()
            mock_BIOSSettingList.delete.assert_not_called()

    def test_cache_bios_settings_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.list_bios_settings.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.bios.cache_bios_settings, task)

    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(drac_bios.DracWSManBIOS, 'cache_bios_settings',
                       spec_set=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def _test_step(self, mock_validate_job_queue, mock_cache_bios_settings,
                   mock_set_async_step_flags,
                   mock_get_async_step_return_state):
        if self.node.clean_step:
            step_data = self.node.clean_step
            expected_state = states.CLEANWAIT
            mock_get_async_step_return_state.return_value = states.CLEANWAIT
        else:
            step_data = self.node.deploy_step
            expected_state = states.DEPLOYWAIT
            mock_get_async_step_return_state.return_value = states.DEPLOYWAIT

        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        if step == 'apply_configuration':
            attributes = {s['name']: s['value'] for s in data}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            info = task.node.driver_internal_info
            if step == 'factory_reset':
                ret_state = task.driver.bios.factory_reset(task)

                attrib = {"BIOS Reset To Defaults Requested": "True"}
                self.mock_client.set_lifecycle_settings.\
                    assert_called_once_with(attrib)
                self.mock_client.commit_pending_lifecycle_changes.\
                    assert_called_once_with(reboot=True)
                job_id = self.mock_client.commit_pending_lifecycle_changes()
                self.assertIn(job_id, info['bios_config_job_ids'])

            if step == 'apply_configuration':
                ret_state = task.driver.bios.apply_configuration(task, data)

                self.mock_client.set_bios_settings.assert_called_once_with(
                    attributes)
                self.mock_client.commit_pending_bios_changes.\
                    assert_called_once_with(reboot=True)
                job_id = self.mock_client.commit_pending_bios_changes()
                self.assertIn(job_id, info['bios_config_job_ids'])

            mock_validate_job_queue.assert_called_once_with(task.node)
            mock_set_async_step_flags.assert_called_once_with(
                task.node, reboot=True, skip_current_step=True, polling=True)
            mock_get_async_step_return_state.assert_called_once_with(
                task.node)
            self.assertEqual(expected_state, ret_state)

    def test_factory_reset_clean(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test_step()

    def test_factory_reset_deploy(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test_step()

    def test_apply_configuration_clean(self):
        settings = [{'name': 'ProcVirtualization', 'value': 'Enabled'}]
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': settings}}
        self.node.save()
        self._test_step()

    def test_apply_configuration_deploy(self):
        settings = [{'name': 'ProcVirtualization', 'value': 'Enabled'}]
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': settings}}
        self.node.save()
        self._test_step()

    def test_apply_conf_set_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.set_bios_settings.side_affect = exc
        settings = [{'name': 'ProcVirtualization', 'value': 'Enabled'}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.bios.apply_configuration, task,
                              settings)

    def test_apply_conf_commit_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.commit_pending_bios_changes.side_affect = exc
        settings = [{'name': 'ProcVirtualization', 'value': 'Enabled'}]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.bios.apply_configuration, task,
                              settings)

    def test_factory_reset_set_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.set_lifecycle_settings.side_affect = exc

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.bios.factory_reset, task)

    def test_factory_reset_commit_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.commit_pending_lifecycle_changes.side_affect = exc

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.bios.factory_reset, task)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(drac_job, 'get_job', spec_set=True,
                       autospec=True)
    def test__check_node_bios_jobs(self, mock_get_job,
                                   mock_notify_conductor_resume_clean):
        mock_job = mock.Mock()
        mock_job.status = 'Completed'
        mock_get_job.return_value = mock_job

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['bios_config_job_ids'] = ['123', '789']
            task.node.driver_internal_info = driver_internal_info
            task.node.clean_step = {'priority': 100, 'interface': 'bios',
                                    'step': 'factory_reset', 'argsinfo': {}}
            task.node.save()
            mock_cache = mock.Mock()
            task.driver.bios.cache_bios_settings = mock_cache

            task.driver.bios._check_node_bios_jobs(task)

            self.assertEqual([], task.node.driver_internal_info.get(
                'bios_config_job_ids'))
            mock_cache.assert_called_once_with(task)
            mock_notify_conductor_resume_clean.assert_called_once_with(task)

    @mock.patch.object(drac_job, 'get_job', spec_set=True,
                       autospec=True)
    def test__check_node_bios_jobs_still_running(self, mock_get_job):
        mock_job = mock.Mock()
        mock_job.status = 'Running'
        mock_get_job.return_value = mock_job

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['bios_config_job_ids'] = ['123']
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            mock_resume = mock.Mock()
            task.driver.bios._resume_current_operation = mock_resume
            mock_cache = mock.Mock()
            task.driver.bios.cache_bios_settings = mock_cache

            task.driver.bios._check_node_bios_jobs(task)

            self.assertEqual(['123'],
                             task.node.driver_internal_info.get(
                                 'bios_config_job_ids'))
            mock_cache.assert_not_called()
            mock_resume.assert_not_called()

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(drac_job, 'get_job', spec_set=True,
                       autospec=True)
    def test__check_node_bios_jobs_failed(self, mock_get_job,
                                          mock_cleaning_error_handler):
        mock_job = mock.Mock()
        mock_job.status = 'Failed'
        mock_job.id = '123'
        mock_job.message = 'Invalid'
        mock_get_job.return_value = mock_job

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['bios_config_job_ids'] = ['123']
            task.node.driver_internal_info = driver_internal_info
            task.node.clean_step = {'priority': 100, 'interface': 'bios',
                                    'step': 'factory_reset', 'argsinfo': {}}
            task.node.save()

            task.driver.bios._check_node_bios_jobs(task)

            self.assertEqual([],
                             task.node.driver_internal_info.get(
                                 'bios_config_job_ids'))
            mock_cleaning_error_handler.assert_called_once_with(
                task, mock.ANY, "Failed config job: 123. Message: 'Invalid'.")


class DracBIOSConfigurationTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracBIOSConfigurationTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

        patch_get_drac_client = mock.patch.object(
            drac_common, 'get_drac_client', spec_set=True, autospec=True)
        mock_get_drac_client = patch_get_drac_client.start()
        self.mock_client = mock.Mock()
        mock_get_drac_client.return_value = self.mock_client
        self.addCleanup(patch_get_drac_client.stop)

        proc_virt_attr = {
            'current_value': 'Enabled',
            'pending_value': None,
            'read_only': False,
            'possible_values': ['Enabled', 'Disabled']}
        mock_proc_virt_attr = mock.NonCallableMock(spec=[], **proc_virt_attr)
        mock_proc_virt_attr.name = 'ProcVirtualization'
        self.bios_attrs = {'ProcVirtualization': mock_proc_virt_attr}

    def test_get_config(self):
        self.mock_client.list_bios_settings.return_value = self.bios_attrs

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            bios_config = task.driver.vendor.get_bios_config(task)

        self.mock_client.list_bios_settings.assert_called_once_with()
        self.assertIn('ProcVirtualization', bios_config)

    def test_get_config_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.list_bios_settings.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.vendor.get_bios_config, task)

        self.mock_client.list_bios_settings.assert_called_once_with()

    def test_set_config(self):
        self.mock_client.list_jobs.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.set_bios_config(task,
                                               ProcVirtualization='Enabled')

        self.mock_client.list_jobs.assert_called_once_with(
            only_unfinished=True)
        self.mock_client.set_bios_settings.assert_called_once_with(
            {'ProcVirtualization': 'Enabled'})

    def test_set_config_fail(self):
        self.mock_client.list_jobs.return_value = []
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.set_bios_settings.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.vendor.set_bios_config, task,
                              ProcVirtualization='Enabled')

        self.mock_client.set_bios_settings.assert_called_once_with(
            {'ProcVirtualization': 'Enabled'})

    def test_commit_config(self):
        self.mock_client.list_jobs.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.commit_bios_config(task)

        self.mock_client.list_jobs.assert_called_once_with(
            only_unfinished=True)
        self.mock_client.commit_pending_bios_changes.assert_called_once_with(
            False)

    def test_commit_config_with_reboot(self):
        self.mock_client.list_jobs.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.commit_bios_config(task, reboot=True)

        self.mock_client.list_jobs.assert_called_once_with(
            only_unfinished=True)
        self.mock_client.commit_pending_bios_changes.assert_called_once_with(
            True)

    def test_commit_config_fail(self):
        self.mock_client.list_jobs.return_value = []
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.commit_pending_bios_changes.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.vendor.commit_bios_config, task)

        self.mock_client.list_jobs.assert_called_once_with(
            only_unfinished=True)
        self.mock_client.commit_pending_bios_changes.assert_called_once_with(
            False)

    def test_abandon_config(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.abandon_bios_config(task)

        self.mock_client.abandon_pending_bios_changes.assert_called_once_with()

    def test_abandon_config_fail(self):
        exc = drac_exceptions.BaseClientException('boom')
        self.mock_client.abandon_pending_bios_changes.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.DracOperationError,
                              task.driver.vendor.abandon_bios_config, task)

        self.mock_client.abandon_pending_bios_changes.assert_called_once_with()
