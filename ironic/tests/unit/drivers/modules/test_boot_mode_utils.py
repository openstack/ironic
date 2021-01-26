# Copyright 2018 FUJITSU LIMITED.
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

from unittest import mock

from ironic.common import boot_modes
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import fake
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class GetBootModeTestCase(tests_base.TestCase):

    def setUp(self):
        super(GetBootModeTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware')

    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_get_boot_mode_bios(self, mock_for_deploy):
        mock_for_deploy.return_value = boot_modes.LEGACY_BIOS
        boot_mode = boot_mode_utils.get_boot_mode(self.node)
        self.assertEqual(boot_modes.LEGACY_BIOS, boot_mode)

    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_get_boot_mode_uefi(self, mock_for_deploy):
        mock_for_deploy.return_value = boot_modes.UEFI
        boot_mode = boot_mode_utils.get_boot_mode(self.node)
        self.assertEqual(boot_modes.UEFI, boot_mode)

    @mock.patch.object(boot_mode_utils, 'LOG', autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_get_boot_mode_default(self, mock_for_deploy, mock_log):
        boot_mode_utils.warn_about_default_boot_mode = False
        mock_for_deploy.return_value = None
        boot_mode = boot_mode_utils.get_boot_mode(self.node)
        self.assertEqual(boot_modes.LEGACY_BIOS, boot_mode)
        boot_mode = boot_mode_utils.get_boot_mode(self.node)
        self.assertEqual(boot_modes.LEGACY_BIOS, boot_mode)
        self.assertEqual(1, mock_log.warning.call_count)

    @mock.patch.object(boot_mode_utils, 'LOG', autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospec=True)
    def test_get_boot_mode_default_set(self, mock_for_deploy, mock_log):
        self.config(default_boot_mode='uefi', group='deploy')
        boot_mode_utils.warn_about_default_boot_mode = False
        mock_for_deploy.return_value = None
        boot_mode = boot_mode_utils.get_boot_mode(self.node)
        self.assertEqual(boot_modes.UEFI, boot_mode)
        self.assertEqual(0, mock_log.warning.call_count)


@mock.patch.object(fake.FakeManagement, 'set_secure_boot_state', autospec=True)
class SecureBootTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SecureBootTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            instance_info={'capabilities': {'secure_boot': 'true'}})
        self.task = task_manager.TaskManager(self.context, self.node.id)

    def test_configure_none_requested(self, mock_set_state):
        self.task.node.instance_info = {}
        boot_mode_utils.configure_secure_boot_if_needed(self.task)
        self.assertFalse(mock_set_state.called)

    @mock.patch.object(boot_mode_utils.LOG, 'warning', autospec=True)
    def test_configure_unsupported(self, mock_warn, mock_set_state):
        mock_set_state.side_effect = exception.UnsupportedDriverExtension
        # Will become a failure in Xena
        boot_mode_utils.configure_secure_boot_if_needed(self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, True)
        self.assertTrue(mock_warn.called)

    def test_configure_exception(self, mock_set_state):
        mock_set_state.side_effect = RuntimeError('boom')
        self.assertRaises(RuntimeError,
                          boot_mode_utils.configure_secure_boot_if_needed,
                          self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, True)

    def test_configure(self, mock_set_state):
        boot_mode_utils.configure_secure_boot_if_needed(self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, True)

    def test_deconfigure_none_requested(self, mock_set_state):
        self.task.node.instance_info = {}
        boot_mode_utils.deconfigure_secure_boot_if_needed(self.task)
        self.assertFalse(mock_set_state.called)

    @mock.patch.object(boot_mode_utils.LOG, 'warning', autospec=True)
    def test_deconfigure_unsupported(self, mock_warn, mock_set_state):
        mock_set_state.side_effect = exception.UnsupportedDriverExtension
        boot_mode_utils.deconfigure_secure_boot_if_needed(self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, False)
        self.assertFalse(mock_warn.called)

    def test_deconfigure(self, mock_set_state):
        boot_mode_utils.deconfigure_secure_boot_if_needed(self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, False)

    def test_deconfigure_exception(self, mock_set_state):
        mock_set_state.side_effect = RuntimeError('boom')
        self.assertRaises(RuntimeError,
                          boot_mode_utils.deconfigure_secure_boot_if_needed,
                          self.task)
        mock_set_state.assert_called_once_with(self.task.driver.management,
                                               self.task, False)
