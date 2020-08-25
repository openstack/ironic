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

from unittest import mock

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
                        method_details, exception_mock,
                        operation='cleaning'):
        exception_mock.side_effect = exc_cls('error')
        method = method_details.get("name")
        args = method_details.get("args")
        if self.node.clean_step:
            self.assertRaises(exception.NodeCleaningFailure,
                              method,
                              *args)
        else:
            self.assertRaises(exception.InstanceDeployFailure,
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
                    'apply_bios', 'deployment_reboot',
                    'skip_current_deploy_step')))
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
    def _test__execute_pre_boot_bios_step(
            self, get_ilo_mock, build_agent_mock,
            node_power_mock, prepare_mock):
        if self.node.clean_step:
            step_data = self.node.clean_step
            check_fields = ['cleaning_reboot', 'skip_current_clean_step']
        else:
            step_data = self.node.deploy_step
            check_fields = ['deployment_reboot', 'skip_current_deploy_step']

        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        if step == 'factory_reset':
            check_fields.append('reset_bios')
        elif step == 'apply_configuration':
            check_fields.append('apply_bios')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_mock = get_ilo_mock.return_value
            task.driver.bios._execute_pre_boot_bios_step(task, step, data)
            drv_internal_info = task.node.driver_internal_info
            self.assertTrue(
                all(x in drv_internal_info for x in check_fields))

            if step == 'factory_reset':
                ilo_mock.reset_bios_to_default.assert_called_once_with()

            elif step == 'apply_configuration':
                ilo_mock.set_bios_settings.assert_called_once_with(data)

            build_agent_mock.assert_called_once_with(task.node)
            self.assertTrue(prepare_mock.called)
            self.assertTrue(node_power_mock.called)

    def test__execute_pre_boot_bios_step_apply_conf_cleaning(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step()

    def test__execute_pre_boot_bios_step_apply_conf_deploying(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step()

    def test__execute_pre_boot_bios_step_factory_reset_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_pre_boot_bios_step()

    def test__execute_pre_boot_bios_step_factory_reset_deploying(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_pre_boot_bios_step()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_pre_boot_bios_step_invalid(
            self, get_ilo_object_mock):
        if self.node.clean_step:
            step_data = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step_data = self.node.deploy_step
            exept = exception.InstanceDeployFailure

        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.set_bios_settings.side_effect = ilo_error.IloError(
                'err')
            if task.node.clean_step:
                exept = exception.NodeCleaningFailure
            else:
                exept = exception.InstanceDeployFailure
            self.assertRaises(exept,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    def test__execute_pre_boot_bios_step_invalid_cleaning(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'invalid_step',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step_invalid()

    def test__execute_pre_boot_bios_step_invalid_deploying(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'invalid_step',
                                 'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step_invalid()

    @mock.patch.object(ilo_common, 'get_ilo_object', autospec=True)
    def _test__execute_pre_boot_bios_step_ilo_fail(self, get_ilo_mock):
        if self.node.clean_step:
            step_data = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step_data = self.node.deploy_step
            exept = exception.InstanceDeployFailure

        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            get_ilo_mock.side_effect = exception.MissingParameterValue('err')
            self.assertRaises(exept,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    def test__execute_pre_boot_bios_step_iloobj_failed_cleaning(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step_ilo_fail()

    def test__execute_pre_boot_bios_step_iloobj_failed_deploying(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_pre_boot_bios_step_ilo_fail()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_pre_boot_bios_step_set_bios_failed(
            self, get_ilo_object_mock):
        if self.node.clean_step:
            step_data = self.node.clean_step
            exept = exception.NodeCleaningFailure
        else:
            step_data = self.node.deploy_step
            exept = exception.InstanceDeployFailure

        data = step_data['argsinfo'].get('settings', None)
        step = step_data['step']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_object_mock = get_ilo_object_mock.return_value
            ilo_object_mock.set_bios_settings.side_effect = ilo_error.IloError(
                'err')
            if task.node.clean_step:
                exept = exception.NodeCleaningFailure
            else:
                exept = exception.InstanceDeployFailure
            self.assertRaises(exept,
                              task.driver.bios._execute_pre_boot_bios_step,
                              task, step, data)

    def test__execute_pre_boot_bios_step_set_bios_failed_cleaning(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'apply_configuration',
                                'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

    def test__execute_pre_boot_bios_step_set_bios_failed_deploying(self):
        data = {"SET_A": "VAL_A",
                "SET_B": "VAL_B",
                "SET_C": "VAL_C",
                "SET_D": "VAL_D"}
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': data}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

    def test__execute_pre_boot_bios_step_reset_bios_failed_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

    def test__execute_pre_boot_bios_step_reset_bios_failed_deploying(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

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
    def _test__execute_post_boot_bios_step_invalid(
            self, get_ilo_object_mock):

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_internal_info
            driver_info.update({'apply_bios': True})
            task.node.driver_internal_info = driver_info
            task.node.save()
            step = 'invalid_step'
            if self.node.clean_step:
                exept = exception.NodeCleaningFailure
            else:
                exept = exception.InstanceDeployFailure
            self.assertRaises(exept,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'apply_bios' not in task.node.driver_internal_info)

    def test__execute_post_boot_bios_step_invalid_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': u'apply_configuration',
                                'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_step_invalid()

    def test__execute_post_boot_bios_step_invalid_deploy(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': u'apply_configuration',
                                 'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_step_invalid()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_post_boot_bios_step_iloobj_failed(
            self, get_ilo_object_mock):

        if self.node.clean_step:
            step = self.node.clean_step['step']
            exept = exception.NodeCleaningFailure
        if self.node.deploy_step:
            step = self.node.deploy_step['step']
            exept = exception.InstanceDeployFailure
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['apply_bios'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            get_ilo_object_mock.side_effect = exception.MissingParameterValue(
                'err')
            step = 'apply_configuration'
            self.assertRaises(exept,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'apply_bios' not in task.node.driver_internal_info)

    def test__execute_post_boot_bios_step_iloobj_failed_cleaning(self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': u'apply_configuration',
                                'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_step_iloobj_failed()

    def test__execute_post_boot_bios_step_iloobj_failed_deploy(self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': u'apply_configuration',
                                 'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_step_iloobj_failed()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_post_boot_bios_get_settings_error(
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

    def test__execute_post_boot_bios_get_settings_error_cleaning(
            self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': u'apply_configuration',
                                'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_error()

    def test__execute_post_boot_bios_get_settings_error_deploying(
            self):
        self.node.deploy_step = {'priority': 100, 'interface': 'bios',
                                 'step': 'apply_configuration',
                                 'argsinfo': {'settings': {'a': 1, 'b': 2}}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_error()

    @mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True,
                       autospec=True)
    def _test__execute_post_boot_bios_get_settings_failed(
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
            if task.node.clean_step:
                exept = exception.NodeCleaningFailure
            else:
                exept = exception.InstanceDeployFailure
            self.assertRaises(exept,
                              task.driver.bios._execute_post_boot_bios_step,
                              task, step)
            self.assertTrue(
                'reset_bios' not in task.node.driver_internal_info)

    def test__execute_post_boot_bios_get_settings_failed_cleaning(
            self):
        self.node.clean_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

    def test__execute_post_boot_bios_get_settings_failed_deploying(
            self):
        self.node.depoy_step = {'priority': 100, 'interface': 'bios',
                                'step': 'factory_reset', 'argsinfo': {}}
        self.node.save()
        self._test__execute_post_boot_bios_get_settings_failed()

    @mock.patch.object(objects.BIOSSettingList, 'create', autospec=True)
    @mock.patch.object(objects.BIOSSettingList, 'save', autospec=True)
    @mock.patch.object(objects.BIOSSettingList, 'delete', autospec=True)
    @mock.patch.object(objects.BIOSSettingList, 'sync_node_setting',
                       autospec=True)
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
