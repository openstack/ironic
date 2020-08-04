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

import mock

from ironic.common import boot_modes
from ironic.drivers.modules import boot_mode_utils
from ironic.tests import base as tests_base
from ironic.tests.unit.objects import utils as obj_utils


class GetBootModeTestCase(tests_base.TestCase):

    def setUp(self):
        super(GetBootModeTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware')

    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospect=True)
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

    @mock.patch.object(boot_mode_utils, 'LOG', autospect=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode_for_deploy',
                       autospect=True)
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
