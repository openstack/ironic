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
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import agent
from ironic.drivers.modules.ilo import boot as ilo_boot
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules import iscsi_deploy
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


if six.PY3:
    import io
    file = io.BytesIO

INFO_DICT = db_utils.get_test_ilo_info()


class IloVirtualMediaIscsiDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaIscsiDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="iscsi_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='iscsi_ilo', driver_info=INFO_DICT)

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'validate', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, 'validate_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self,
                      mock_validate_driver_info,
                      iscsi_validate):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            mock_validate_driver_info.assert_called_once_with(task)
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

    @mock.patch.object(ilo_boot.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, 'exception', spec_set=True, autospec=True)
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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'continue_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', autospec=True)
    def test_continue_deploy(self,
                             func_update_boot_mode,
                             func_update_secure_boot_mode,
                             pxe_vendorpassthru_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            task.node.target_provision_state = states.ACTIVE
            task.driver.deploy.continue_deploy(task)
            func_update_boot_mode.assert_called_once_with(task)
            func_update_secure_boot_mode.assert_called_once_with(task, True)
            pxe_vendorpassthru_mock.assert_called_once_with(
                mock.ANY, task)


class IloVirtualMediaAgentDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloVirtualMediaAgentDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="agent_ilo")
        self.node = obj_utils.create_test_node(
            self.context, driver='agent_ilo', driver_info=INFO_DICT)

    @mock.patch.object(agent.AgentDeploy, 'validate', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_boot, 'validate_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self,
                      mock_validate_driver_info,
                      agent_validate):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            mock_validate_driver_info.assert_called_once_with(task)
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
    @mock.patch.object(ilo_boot.LOG, 'warning', spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, 'exception', spec_set=True, autospec=True)
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

    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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

    @mock.patch.object(agent.AgentDeploy, 'reboot_to_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'check_deploy_success',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_reboot_to_instance(self, func_update_secure_boot_mode,
                                func_update_boot_mode,
                                check_deploy_success_mock,
                                agent_reboot_to_instance_mock):
        check_deploy_success_mock.return_value = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.reboot_to_instance(task)
            check_deploy_success_mock.assert_called_once_with(
                mock.ANY, task.node)
            func_update_boot_mode.assert_called_once_with(task)
            func_update_secure_boot_mode.assert_called_once_with(task, True)
            agent_reboot_to_instance_mock.assert_called_once_with(
                mock.ANY, task)

    @mock.patch.object(agent.AgentDeploy, 'reboot_to_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent.AgentDeploy, 'check_deploy_success',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', spec_set=True,
                       autospec=True)
    def test_reboot_to_instance_deploy_fail(self, func_update_secure_boot_mode,
                                            func_update_boot_mode,
                                            check_deploy_success_mock,
                                            agent_reboot_to_instance_mock):
        check_deploy_success_mock.return_value = "Error"
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.reboot_to_instance(task)
            check_deploy_success_mock.assert_called_once_with(
                mock.ANY, task.node)
            self.assertFalse(func_update_boot_mode.called)
            self.assertFalse(func_update_secure_boot_mode.called)
            agent_reboot_to_instance_mock.assert_called_once_with(
                mock.ANY, task)


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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
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
    @mock.patch.object(ilo_boot, 'prepare_node_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare_whole_disk_image_uefi(self, prepare_node_for_deploy_mock,
                                           pxe_prepare_mock):
        CONF.set_override('default_boot_option', 'netboot', 'deploy')
        self.node.provision_state = states.DEPLOYING
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.properties['capabilities'] = 'boot_mode:uefi'
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.deploy.prepare(task)
            prepare_node_for_deploy_mock.assert_called_once_with(task)
            pxe_prepare_mock.assert_called_once_with(mock.ANY, task)

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

    @mock.patch.object(ilo_boot.LOG, 'warning',
                       spec_set=True, autospec=True)
    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'tear_down',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_boot, 'exception', spec_set=True, autospec=True)
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

    @mock.patch.object(iscsi_deploy.ISCSIDeploy, 'continue_deploy',
                       spec_set=True, autospec=True)
    @mock.patch.object(ilo_common, 'update_secure_boot_mode', autospec=True)
    @mock.patch.object(ilo_common, 'update_boot_mode', autospec=True)
    def test_continue_deploy(self,
                             func_update_boot_mode,
                             func_update_secure_boot_mode,
                             pxe_vendorpassthru_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            task.node.target_provision_state = states.ACTIVE
            task.driver.deploy.continue_deploy(task)
            func_update_boot_mode.assert_called_once_with(task)
            func_update_secure_boot_mode.assert_called_once_with(task, True)
            pxe_vendorpassthru_mock.assert_called_once_with(
                mock.ANY, task)
