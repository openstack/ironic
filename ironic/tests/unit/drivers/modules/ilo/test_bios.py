# Copyright 2018 Hewlett-Packard Development Company, L.P.
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

"""Test class for IloPower module."""

import mock
from oslo_config import cfg
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import bios as ilo_bios
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic import objects
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.ilo import test_common

ilo_error = importutils.try_import('proliantutils.exception')

INFO_DICT = db_utils.get_test_ilo_info()
CONF = cfg.CONF


class IloBiosTestCase(test_common.BaseIloTest):

    def test_get_properties(self):
        expected = ilo_common.REQUIRED_PROPERTIES
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.bios.get_properties())

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.bios.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    def _test_ilo_error(self, exc_cls,
                        test_methods_not_called,
                        test_methods_called,
                        method_details, exception_mock):
        exception_mock.side_effect = exc_cls('error')
        method = method_details.get("name")
        args = method_details.get("args")
        self.assertRaises(exception.NodeCleaningFailure,
                          method,
                          *args)
        for test_method in test_methods_not_called:
            test_method.assert_not_called()
        for called_method in test_methods_called:
            called_method["name"].assert_called_once_with(
                *called_method["args"])

    @mock.patch.object(ilo_bios.IloBIOS, 'cache_bios_settings',
                       autospec=True)
    @mock.patch.object(ilo_bios.IloBIOS, '_execute_post_boot_bios_step',
                       autospec=True)
    @mock.patch.object(ilo_bios.IloBIOS, '_execute_pre_boot_bios_step',
                       autospec=True)
    def test_apply_configuration_pre_boot(self, exe_pre_boot_mock,
                                          exe_post_boot_mock,
                                          cache_settings_mock):
        settings = [
            {
                "name": "SET_A", "value": "VAL_A",
            },
            {
                "name": "SET_B", "value": "VAL_B",
            },
            {
                "name": "SET_C", "value": "VAL_C",
            },
            {
                "name": "SET_D", "value": "VAL_D",
            }
        ]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info.pop('apply_bios', None)
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            actual_settings = {'SET_A': 'VAL_A', 'SET_B': 'VAL_B',
                               'SET_C': 'VAL_C', 'SET_D': 'VAL_D'}
            task.driver.bios.apply_configuration(task, settings)

            exe_pre_boot_mock.assert_called_once_with(
                task.driver.bios, task, 'apply_configuration', actual_settings)
            self.assertFalse(exe_post_boot_mock.called)
            cache_settings_mock.assert_called_once_with(task.driver.bios, task)

    @mock.patch.object(ilo_bios.IloBIOS, 'cache_bios_settings',
                       autospec=True)
    @mock.patch.object(ilo_bios.IloBIOS, '_execute_post_boot_bios_step',
                       autospec=True)
    @mock.patch.object(ilo_bios.IloBIOS, '_execute_pre_boot_bios_step',
                       autospec=True)
    def test_apply_configuration_post_boot(self, exe_pre_boot_mock,
                                           exe_post_boot_mock,
                                           cache_settings_mock):
        settings = [
            {
                "name": "SET_A", "value": "VAL_A",
            },
            {
                "name": "SET_B", "value": "VAL_B",
            },
            {
                "name": "SET_C", "value": "VAL_C",
            },
            {
                "name": "SET_D", "value": "VAL_D",
            }
        ]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['apply_bios'] = True
            task.node.driver_internal_info = driver_internal_info
            task.node.save()
            task.driver.bios.apply_configuration(task, settings)

            exe_post_boot_mock.assert_called_once_with(
                task.driver.bios, task, 'apply_configuration')
            self.assertFalse(exe_pre_boot_mock.called)
            cache_settings_mock.assert_called_once_with(task.driver.bios, task)

    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_apply_configuration(
            self, get_ilo_object_mock, build_agent_mock,
            node_power_mock, prepare_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            step = 'apply_configuration'
            task.driver.bios._execute_pre_boot_bios_step(task, step, data)
            driver_info = task.node.driver_internal_info
            self.assertTrue(
                all(x in driver_info for x in (
                    'apply_bios', 'cleaning_reboot',
                    'skip_current_clean_step')))
            ilo_object_mock.set_bios_settings.assert_called_once_with(data)
            self.assertFalse(ilo_object_mock.reset_bios_to_default.called)
            build_agent_mock.assert_called_once_with(task.node)
            self.assertTrue(prepare_mock.called)
            self.assertTrue(node_power_mock.called)

    @mock.patch.object(ilo_boot.IloVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_factory_reset(
            self, get_ilo_object_mock, build_agent_mock,
            node_power_mock, prepare_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            step = 'factory_reset'
            task.driver.bios._execute_pre_boot_bios_step(task, step, data)
            driver_info = task.node.driver_internal_info
            self.assertTrue(
                all(x in driver_info for x in (
                    'reset_bios', 'cleaning_reboot',
                    'skip_current_clean_step')))
            ilo_object_mock.reset_bios_to_default.assert_called_once_with()
            self.assertFalse(ilo_object_mock.set_bios_settings.called)
            build_agent_mock.assert_called_once_with(task.node)
            self.assertTrue(prepare_mock.called)
            self.assertTrue(node_power_mock.called)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_invalid(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            step = 'invalid_step'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_iloobj_failed(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            get_ilo_object_mock.side_effect = exception.MissingParameterValue(
                'err')
            step = 'apply_configuration'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_set_bios_failed(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.set_bios_settings.side_effect = ilo_error.IloError(
                'err')
            step = 'apply_configuration'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_pre_boot_bios_step_reset_bios_failed(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            data = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.reset_bios_to_default.side_effect = (
                ilo_error.IloError('err'))
            step = 'factory_reset'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_step_apply_configuration(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'apply_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            step = 'apply_configuration'
            task.driver.bios._execute_post_boot_bios_step(task, step)
            driver_info = task.node.driver_internal_info
            self.assertTrue('apply_bios' not in driver_info)
            ilo_object_mock.get_bios_settings_result.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_step_factory_reset(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'reset_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            step = 'factory_reset'
            task.driver.bios._execute_post_boot_bios_step(task, step)
            driver_info = task.node.driver_internal_info
            self.assertTrue('reset_bios' not in driver_info)
            ilo_object_mock.get_bios_settings_result.assert_called_once_with()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_step_invalid(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'apply_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            step = 'invalid_step'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'apply_bios' not in task.node.driver_internal_info)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_step_iloobj_failed(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'apply_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            get_ilo_object_mock.side_effect = exception.MissingParameterValue(
                'err')
            step = 'apply_configuration'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'apply_bios' not in task.node.driver_internal_info)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_get_settings_error(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'apply_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value

            step = 'apply_configuration'
            mdobj = {
                "name": task.driver.bios._execute_post_boot_bios_step,
                "args": (task, step,)
            }

            self._test_ilo_error(ilo_error.IloCommandNotSupportedError,
                                 [],
                                 [], mdobj,
                                 ilo_object_mock.get_bios_settings_result)
            self.assertTrue(
                'apply_bios' not in task.node.driver_internal_info)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test__execute_post_boot_bios_get_settings_failed(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'reset_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.get_bios_settings_result.return_value = (
                {'status': 'failed', 'message': 'Some data'})
            step = 'factory_reset'
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'reset_bios' not in task.node.driver_internal_info)

    @mock.patch.object(objects.BIOSSettingList, 'create')
    @mock.patch.object(objects.BIOSSettingList, 'save')
    @mock.patch.object(objects.BIOSSettingList, 'delete')
    @mock.patch.object(objects.BIOSSettingList, 'sync_node_setting')
    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings(self, get_ilo_object_mock, sync_node_mock,
                                 delete_mock, save_mock, create_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            settings = {
                "SET_A": True,
                "SET_B": True,
                "SET_C": True,
                "SET_D": True
            }

            ilo_object_mock.get_current_bios_settings.return_value = settings
            expected_bios_settings = [
                {"name": "SET_A", "value": True},
                {"name": "SET_B", "value": True},
                {"name": "SET_C", "value": True},
                {"name": "SET_D", "value": True}
            ]
            sync_node_mock.return_value = ([], [], [], [])
            all_settings = (
                [
                    {"name": "C_1", "value": "C_1_VAL"},
                    {"name": "C_2", "value": "C_2_VAL"}
                ],
                [
                    {"name": "U_1", "value": "U_1_VAL"},
                    {"name": "U_2", "value": "U_2_VAL"}
                ],
                [
                    {"name": "D_1", "value": "D_1_VAL"},
                    {"name": "D_2", "value": "D_2_VAL"}
                ],
                []
            )
            sync_node_mock.return_value = all_settings
            task.driver.bios.cache_bios_settings(task)
            ilo_object_mock.get_current_bios_settings.assert_called_once_with()
            actual_arg = sorted(sync_node_mock.call_args[0][2],
                                key=lambda x: x.get("name"))
            expected_arg = sorted(expected_bios_settings,
                                  key=lambda x: x.get("name"))
            self.assertEqual(actual_arg, expected_arg)
            create_mock.assert_called_once_with(
                self.context, task.node.id, all_settings[0])
            save_mock.assert_called_once_with(
                self.context, task.node.id, all_settings[1])
            del_names = [setting.get("name") for setting in all_settings[2]]
            delete_mock.assert_called_once_with(
                self.context, task.node.id, del_names)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_missing_parameter(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error(exception.MissingParameterValue,
                                 [],
                                 [], mdobj, get_ilo_object_mock)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_invalid_parameter(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error(exception.InvalidParameterValue,
                                 [],
                                 [], mdobj, get_ilo_object_mock)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_with_ilo_error(self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error(ilo_error.IloError,
                                 [],
                                 [],
                                 mdobj,
                                 ilo_object_mock.get_current_bios_settings)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_with_unknown_error(self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value

            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error(ilo_error.IloCommandNotSupportedError,
                                 [],
                                 [],
                                 mdobj,
                                 ilo_object_mock.get_current_bios_settings)
