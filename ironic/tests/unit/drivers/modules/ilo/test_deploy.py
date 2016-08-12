# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""Test class for deploy methods used by iLO modules."""

import mock
import six

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common.glance_service import service_utils
from ironic.common import image_service
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules import iscsi_deploy
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


if six.PY3:
    import io
    file = io.BytesIO

INFO_DICT = db_utils.get_test_ilo_info()


class IloDeployPrivateMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloDeployPrivateMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_false(self,
                                        func_get_secure_boot_mode,
                                        func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_deploy._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            self.assertFalse(func_set_secure_boot_mode.called)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'set_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_true(self,
                                       func_get_secure_boot_mode,
                                       func_set_secure_boot_mode):
        func_get_secure_boot_mode.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = ilo_deploy._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            func_set_secure_boot_mode.assert_called_once_with(task, False)
        self.assertTrue(returned_state)

    @mock.patch.object(ilo_deploy.LOG, 'debug', spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'get_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test__disable_secure_boot_exception(self,
                                            func_get_secure_boot_mode,
                                            exception_mock,
                                            mock_log):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            exception_mock.IloOperationNotSupported = Exception
            func_get_secure_boot_mode.side_effect = Exception
            returned_state = ilo_deploy._disable_secure_boot(task)
            func_get_secure_boot_mode.assert_called_once_with(task)
            self.assertTrue(mock_log.called)
        self.assertFalse(returned_state)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test__prepare_node_for_deploy(self,
                                      func_node_power_action,
                                      func_disable_secure_boot,
                                      func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            ilo_deploy._prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test__prepare_node_for_deploy_sec_boot_on(self,
                                                  func_node_power_action,
                                                  func_disable_secure_boot,
                                                  func_update_boot_mode):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            ilo_deploy._prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            ret_boot_mode = task.node.instance_info['deploy_boot_mode']
            self.assertEqual('uefi', ret_boot_mode)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test__prepare_node_for_deploy_inst_info(self,
                                                func_node_power_action,
                                                func_disable_secure_boot,
                                                func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = False
            task.node.instance_info = instance_info
            ilo_deploy._prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            func_update_boot_mode.assert_called_once_with(task)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode', task.node.instance_info)

    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_disable_secure_boot', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test__prepare_node_for_deploy_sec_boot_on_inst_info(
            self, func_node_power_action, func_disable_secure_boot,
            func_update_boot_mode):
        instance_info = {'capabilities': '{"secure_boot": "true"}'}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            func_disable_secure_boot.return_value = True
            task.node.instance_info = instance_info
            ilo_deploy._prepare_node_for_deploy(task)
            func_node_power_action.assert_called_once_with(task,
                                                           states.POWER_OFF)
            func_disable_secure_boot.assert_called_once_with(task)
            self.assertFalse(func_update_boot_mode.called)
            bootmode = driver_utils.get_node_capability(task.node, "boot_mode")
            self.assertIsNone(bootmode)
            self.assertNotIn('deploy_boot_mode', task.node.instance_info)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_MissingParam(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaisesRegex(exception.MissingParameterValue,
                                   "Missing 'ilo_deploy_iso'",
                                   ilo_deploy._validate, task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_valid_uuid(self, mock_parse_driver_info,
                                  mock_is_glance_image):
        mock_is_glance_image.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            deploy_iso = '8a81759a-f29b-454b-8ab3-161c6ca1882c'
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            ilo_deploy._validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_is_glance_image.assert_called_once_with(deploy_iso)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_InvalidParam(self, mock_parse_driver_info,
                                    mock_is_glance_image,
                                    mock_validate_href):
        deploy_iso = 'http://abc.org/image/qcow2'
        mock_validate_href.side_effect = exception.ImageRefValidationFailed(
            image_href='http://abc.org/image/qcow2', reason='fail')
        mock_is_glance_image.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   "Virtual media deploy accepts",
                                   ilo_deploy._validate, task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_validate_href.assert_called_once_with(mock.ANY, deploy_iso)

    @mock.patch.object(image_service.HttpImageService, 'validate_href',
                       spec_set=True, autospec=True)
    @mock.patch.object(service_utils, 'is_glance_image', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test__validate_valid_url(self, mock_parse_driver_info,
                                 mock_is_glance_image,
                                 mock_validate_href):
        deploy_iso = 'http://abc.org/image/deploy.iso'
        mock_is_glance_image.return_value = False
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.driver_info['ilo_deploy_iso'] = deploy_iso
            ilo_deploy._validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)
            mock_validate_href.assert_called_once_with(mock.ANY, deploy_iso)


class IloVirtualMediaIscsiDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaIscsiDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'validate', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_validate', spec_set=True,
                       autospec=True)
    def test_validate(self,
                      mock_validate,
                      iscsi_validate):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            mock_validate.assert_called_once_with(task)
            iscsi_validate.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'tear_down', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down(self,
                       node_power_action_mock,
                       iscsi_tear_down_mock,
                       update_secure_boot_mode_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            iscsi_tear_down_mock.return_value = states.DELETED
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            iscsi_tear_down_mock.assert_called_once_with(mock.ANY, task)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(ilo_deploy.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'tear_down', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down_handle_exception(self,
                                        node_power_action_mock,
                                        update_secure_boot_mode_mock,
                                        iscsi_tear_down_mock,
                                        exception_mock,
                                        mock_log):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            iscsi_tear_down_mock.return_value = states.DELETED
            exception_mock.IloOperationNotSupported = Exception
            update_secure_boot_mode_mock.side_effect = Exception
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            iscsi_tear_down_mock.assert_called_once_with(mock.ANY, task)
            self.assertTrue(mock_log.called)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'deploy',
                       spec_set=True, autospec=True)
    def test_deploy(self, iscsi_deploy_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.deploy(task)
            iscsi_deploy_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare(self, func_prepare_node_for_deploy,
                     iscsi_deploy_prepare_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.prepare(task)
            func_prepare_node_for_deploy.assert_called_once_with(task)
            iscsi_deploy_prepare_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare_active_node(self, func_prepare_node_for_deploy,
                                 iscsi_deploy_prepare_mock):
        """Ensure nodes in running states are not inadvertently changed"""
        test_states = list(states.STABLE_STATES)
        test_states.extend([states.CLEANING,
                           states.CLEANWAIT,
                           states.INSPECTING])
        for state in test_states:
            self.node.provision_state = state
            self.node.save()
            func_prepare_node_for_deploy.reset_mock()
            iscsi_deploy_prepare_mock.reset_mock()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                task.driver.deploy.prepare(task)
                self.assertFalse(func_prepare_node_for_deploy.called)
                iscsi_deploy_prepare_mock.assert_called_once_with(
                    mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare_cleaning',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning(self, node_power_action_mock,
                              iscsi_prep_clean_mock):
        iscsi_prep_clean_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, ret)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            iscsi_prep_clean_mock.assert_called_once_with(mock.ANY, task)


class IloVirtualMediaAgentDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaAgentDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="agent_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='agent_ilo', driver_info=INFO_DICT)

    @mock.patch.object(agent.AgentDeploy, 'validate', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_validate', spec_set=True,
                       autospec=True)
    def test_validate(self,
                      mock_validate,
                      agent_validate):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            mock_validate.assert_called_once_with(task)
            agent_validate.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(agent.AgentDeploy, 'tear_down', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down(self,
                       node_power_action_mock,
                       update_secure_boot_mode_mock,
                       agent_teardown_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            agent_teardown_mock.return_value = states.DELETED
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(agent.AgentDeploy, 'tear_down', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down_handle_exception(self,
                                        node_power_action_mock,
                                        update_secure_boot_mode_mock,
                                        exception_mock,
                                        mock_log,
                                        agent_teardown_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            agent_teardown_mock.return_value = states.DELETED
            exception_mock.IloOperationNotSupported = Exception
            update_secure_boot_mode_mock.side_effect = Exception
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            agent_teardown_mock.assert_called_once_with(mock.ANY, task)
            self.assertTrue(mock_log.called)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'prepare', spec_set=True,
                       autospec=True)
    def test_prepare(self,
                     agent_prepare_mock,
                     func_prepare_node_for_deploy):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.prepare(task)
            func_prepare_node_for_deploy.assert_called_once_with(task)
            agent_prepare_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(agent.AgentDeploy, 'prepare', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare_active_node(self,
                                 func_prepare_node_for_deploy,
                                 agent_prepare_mock):
        """Ensure nodes in running states are not inadvertently changed"""
        test_states = list(states.STABLE_STATES)
        test_states.extend([states.CLEANING,
                           states.CLEANWAIT,
                           states.INSPECTING])
        for state in test_states:
            self.node.provision_state = state
            self.node.save()
            func_prepare_node_for_deploy.reset_mock()
            agent_prepare_mock.reset_mock()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                task.driver.deploy.prepare(task)
                self.assertFalse(func_prepare_node_for_deploy.called)
                agent_prepare_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(deploy_utils, 'agent_get_clean_steps', spec_set=True,
                       autospec=True)
    def test_get_clean_steps_with_conf_option(self, get_clean_step_mock):
        self.config(clean_priority_erase_devices=20, group='ilo')
        self.config(erase_devices_metadata_priority=10, group='deploy')
        get_clean_step_mock.return_value = [{
            'step': 'erase_devices',
            'priority': 10,
            'interface': 'deploy',
            'reboot_requested': False
        }]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.get_clean_steps(task)
            get_clean_step_mock.assert_called_once_with(
                task, interface='deploy',
                override_priorities={'erase_devices': 20,
                                     'erase_devices_metadata': 10})

    @mock.patch.object(deploy_utils, 'agent_get_clean_steps', spec_set=True,
                       autospec=True)
    def test_get_clean_steps_erase_devices_disable(self, get_clean_step_mock):
        self.config(clean_priority_erase_devices=0, group='ilo')
        self.config(erase_devices_metadata_priority=0, group='deploy')
        get_clean_step_mock.return_value = [{
            'step': 'erase_devices',
            'priority': 10,
            'interface': 'deploy',
            'reboot_requested': False
        }]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.get_clean_steps(task)
            get_clean_step_mock.assert_called_once_with(
                task, interface='deploy',
                override_priorities={'erase_devices': 0,
                                     'erase_devices_metadata': 0})

    @mock.patch.object(deploy_utils, 'agent_get_clean_steps', spec_set=True,
                       autospec=True)
    def test_get_clean_steps_without_conf_option(self, get_clean_step_mock):
        get_clean_step_mock.return_value = [{
            'step': 'erase_devices',
            'priority': 10,
            'interface': 'deploy',
            'reboot_requested': False
        }]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.get_clean_steps(task)
            get_clean_step_mock.assert_called_once_with(
                task, interface='deploy',
                override_priorities={'erase_devices': None,
                                     'erase_devices_metadata': None})

    @mock.patch.object(agent.AgentDeploy, 'prepare_cleaning', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning(self, node_power_action_mock,
                              agent_prep_clean_mock):
        agent_prep_clean_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, ret)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            agent_prep_clean_mock.assert_called_once_with(mock.ANY, task)


class IloPXEDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPXEDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="pxe_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='pxe_ilo', driver_info=INFO_DICT)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'validate', spec_set=True,
                       autospec=True)
    def test_validate(self, pxe_validate_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            pxe_validate_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare(self,
                     prepare_node_for_deploy_mock,
                     pxe_prepare_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            task.driver.deploy.prepare(task)
            prepare_node_for_deploy_mock.assert_called_once_with(task)
            pxe_prepare_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare_active_node(self,
                                 prepare_node_for_deploy_mock,
                                 pxe_prepare_mock):
        """Ensure nodes in running states are not inadvertently changed"""
        test_states = list(states.STABLE_STATES)
        test_states.extend([states.CLEANING,
                           states.CLEANWAIT,
                           states.INSPECTING])
        for state in test_states:
            self.node.provision_state = state
            self.node.save()
            prepare_node_for_deploy_mock.reset_mock()
            pxe_prepare_mock.reset_mock()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
                task.node.properties['capabilities'] = 'boot_mode:uefi'
                task.driver.deploy.prepare(task)
                self.assertFalse(prepare_node_for_deploy_mock.called)
                pxe_prepare_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_deploy, '_prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare_uefi_whole_disk_image_fail(self,
                                                prepare_node_for_deploy_mock,
                                                pxe_prepare_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            task.node.driver_internal_info['is_whole_disk_image'] = True
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.deploy.prepare, task)
            prepare_node_for_deploy_mock.assert_called_once_with(task)
            self.assertFalse(pxe_prepare_mock.called)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'deploy', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    def test_deploy_boot_mode_exists(self, set_persistent_mock,
                                     pxe_deploy_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.deploy(task)
            set_persistent_mock.assert_called_with(task, boot_devices.PXE)
            pxe_deploy_mock.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'tear_down',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down(self, node_power_action_mock,
                       update_secure_boot_mode_mock, pxe_tear_down_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            pxe_tear_down_mock.return_value = states.DELETED
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_tear_down_mock.assert_called_once_with(mock.ANY, task)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(ilo_deploy.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'tear_down',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_deploy, 'exception', spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down_handle_exception(self, node_power_action_mock,
                                        update_secure_boot_mode_mock,
                                        exception_mock, pxe_tear_down_mock,
                                        mock_log):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            pxe_tear_down_mock.return_value = states.DELETED
            exception_mock.IloOperationNotSupported = Exception
            update_secure_boot_mode_mock.side_effect = Exception
            returned_state = task.driver.deploy.tear_down(task)
            update_secure_boot_mode_mock.assert_called_once_with(task, False)
            pxe_tear_down_mock.assert_called_once_with(mock.ANY, task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertTrue(mock_log.called)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'prepare_cleaning',
                       spec_set=True, autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_prepare_cleaning(self, node_power_action_mock,
                              iscsi_prep_clean_mock):
        iscsi_prep_clean_mock.return_value = states.CLEANWAIT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            ret = task.driver.deploy.prepare_cleaning(task)
            self.assertEqual(states.CLEANWAIT, ret)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            iscsi_prep_clean_mock.assert_called_once_with(mock.ANY, task)
