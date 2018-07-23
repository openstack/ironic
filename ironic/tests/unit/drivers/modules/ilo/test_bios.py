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

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test_ilo_error(self, error_type,
                        test_methods_not_called, method_details, ilo_mock):
        error_dict = {
            "missing_parameter": exception.MissingParameterValue,
            "invalid_parameter": exception.InvalidParameterValue
        }

        exc = error_dict.get(error_type)('error')
        ilo_mock.side_effect = exc
        method = method_details.get("name")
        args = method_details.get("args")
        self.assertRaises(exception.NodeCleaningFailure,
                          method,
                          *args)
        for test_method in test_methods_not_called:
            eval("ilo_mock.return_value.%s.assert_not_called()" % (
                test_method))

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_apply_configuration(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            data = [
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
            task.driver.bios.apply_configuration(task, data)
            expected = {
                "SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"
            }
            ilo_object_mock.set_bios_settings.assert_called_once_with(expected)

    def test_apply_configuration_missing_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.apply_configuration,
                "args": (task, [])
            }
            self._test_ilo_error("missing_parameter", ["set_bios_settings"],
                                 mdobj)

    def test_apply_configuration_invalid_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.apply_configuration,
                "args": (task, [])
            }
            self._test_ilo_error("invalid_parameter", ["set_bios_settings"],
                                 mdobj)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_apply_configuration_with_ilo_error(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            data = [
                {
                    "name": "SET_A", "value": "VAL_A",
                },
                {
                    "name": "SET_B", "value": "VAL_B",
                },
            ]
            exc = ilo_error.IloError('error')
            ilo_object_mock.set_bios_settings.side_effect = exc
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios.apply_configuration,
                              task, data)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_factory_reset(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            task.driver.bios.factory_reset(task)
            ilo_object_mock.reset_bios_to_default.assert_called_once_with()

    def test_factory_reset_missing_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.factory_reset,
                "args": (task,)
            }
            self._test_ilo_error("missing_parameter",
                                 ["reset_bios_to_default"], mdobj)

    def test_factory_reset_invalid_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.factory_reset,
                "args": (task,)
            }
            self._test_ilo_error("invalid_parameter",
                                 ["reset_bios_to_default"], mdobj)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_factory_reset_with_ilo_error(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            exc = ilo_error.IloError('error')
            ilo_object_mock.reset_bios_to_default.side_effect = exc
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios.factory_reset, task)

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def test_factory_reset_with_unknown_error(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            exc = ilo_error.IloCommandNotSupportedError('error')
            ilo_object_mock.reset_bios_to_default.side_effect = exc
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios.factory_reset, task)

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

            ilo_object_mock.get_pending_bios_settings.return_value = settings
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
            ilo_object_mock.get_pending_bios_settings.assert_called_once_with()
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

    def test_cache_bios_settings_missing_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error("missing_parameter",
                                 ["get_pending_bios_settings"], mdobj)

    def test_cache_bios_settings_invalid_parameter(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mdobj = {
                "name": task.driver.bios.cache_bios_settings,
                "args": (task,)
            }
            self._test_ilo_error("invalid_parameter",
                                 ["get_pending_bios_settings"], mdobj)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_with_ilo_error(self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            exc = ilo_error.IloError('error')
            ilo_object_mock.get_pending_bios_settings.side_effect = exc
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios.cache_bios_settings, task)

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def test_cache_bios_settings_with_unknown_error(self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            exc = ilo_error.IloCommandNotSupportedError('error')
            ilo_object_mock.get_pending_bios_settings.side_effect = exc
            self.assertRaises(exception.NodeCleaningFailure,
                              task.driver.bios.cache_bios_settings, task)
