# -*- coding: utf-8 -*-
#
# Copyright (c) 2015-2016 Dell Inc. or its subsidiaries.
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

from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = test_utils.INFO_DICT


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
