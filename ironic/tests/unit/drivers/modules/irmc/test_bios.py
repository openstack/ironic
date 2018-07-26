# Copyright 2018 FUJITSU LIMITED
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
Test class for IRMC BIOS configuration
"""

import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.irmc import bios as irmc_bios
from ironic.drivers.modules.irmc import common as irmc_common
from ironic import objects
from ironic.tests.unit.drivers.modules.irmc import test_common


class IRMCBIOSTestCase(test_common.BaseIRMCTest):

    def setUp(self):
        super(IRMCBIOSTestCase, self).setUp()

    @mock.patch.object(irmc_common, 'parse_driver_info',
                       autospec=True)
    def test_validate(self, parse_driver_info_mock):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.bios.validate(task)
            parse_driver_info_mock.assert_called_once_with(task.node)

    @mock.patch.object(irmc_bios.irmc.elcm, 'set_bios_configuration',
                       autospec=True)
    @mock.patch.object(irmc_bios.irmc.elcm, 'get_bios_settings',
                       autospec=True)
    def test_apply_configuration(self, get_bios_settings_mock,
                                 set_bios_configuration_mock):
        settings = [{
            "name": "launch_csm_enabled",
            "value": True
        }, {
            "name": "hyper_threading_enabled",
            "value": True
        }, {
            "name": "cpu_vt_enabled",
            "value": True
        }]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_info = irmc_common.parse_driver_info(task.node)
            task.node.save = mock.Mock()
            get_bios_settings_mock.return_value = settings
            task.driver.bios.apply_configuration(task, settings)
            set_bios_configuration_mock.assert_called_once_with(irmc_info,
                                                                settings)

    @mock.patch.object(irmc_bios.irmc.elcm, 'set_bios_configuration',
                       autospec=True)
    def test_apply_configuration_failed(self, set_bios_configuration_mock):
        settings = [{
            "name": "launch_csm_enabled",
            "value": True
        }, {
            "name": "hyper_threading_enabled",
            "value": True
        }, {
            "name": "setting",
            "value": True
        }]
        irmc_bios.irmc.scci.SCCIError = Exception
        set_bios_configuration_mock.side_effect = Exception
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IRMCOperationError,
                              task.driver.bios.apply_configuration,
                              task, settings)

    def test_factory_reset(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.UnsupportedDriverExtension,
                              task.driver.bios.factory_reset, task)

    @mock.patch.object(objects.BIOSSettingList, 'sync_node_setting')
    @mock.patch.object(objects.BIOSSettingList, 'create')
    @mock.patch.object(objects.BIOSSettingList, 'save')
    @mock.patch.object(objects.BIOSSettingList, 'delete')
    @mock.patch.object(irmc_bios.irmc.elcm, 'get_bios_settings',
                       autospec=True)
    def test_cache_bios_settings(self, get_bios_settings_mock,
                                 delete_mock, save_mock, create_mock,
                                 sync_node_setting_mock):
        settings = [{
            "name": "launch_csm_enabled",
            "value": True
        }, {
            "name": "hyper_threading_enabled",
            "value": True
        }, {
            "name": "cpu_vt_enabled",
            "value": True
        }]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            irmc_info = irmc_common.parse_driver_info(task.node)
            get_bios_settings_mock.return_value = settings
            sync_node_setting_mock.return_value = \
                (
                    [
                        {
                            "name": "launch_csm_enabled",
                            "value": True
                        }],
                    [
                        {
                            "name": "hyper_threading_enabled",
                            "value": True
                        }],
                    [
                        {
                            "name": "cpu_vt_enabled",
                            "value": True
                        }],
                    []
                )
            task.driver.bios.cache_bios_settings(task)
            get_bios_settings_mock.assert_called_once_with(irmc_info)
            sync_node_setting_mock.assert_called_once_with(task.context,
                                                           task.node.id,
                                                           settings)
            create_mock.assert_called_once_with(
                task.context, task.node.id,
                sync_node_setting_mock.return_value[0])
            save_mock.assert_called_once_with(
                task.context, task.node.id,
                sync_node_setting_mock.return_value[1])
            delete_names = \
                [setting['name'] for setting in
                 sync_node_setting_mock.return_value[2]]
            delete_mock.assert_called_once_with(task.context, task.node.id,
                                                delete_names)

    @mock.patch.object(irmc_bios.irmc.elcm, 'get_bios_settings',
                       autospec=True)
    def test_cache_bios_settings_failed(self, get_bios_settings_mock):
        irmc_bios.irmc.scci.SCCIError = Exception
        get_bios_settings_mock.side_effect = Exception
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IRMCOperationError,
                              task.driver.bios.cache_bios_settings,
                              task)
