# Copyright 2015 FUJITSU LIMITED
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
Test class for iRMC Deploy Driver
"""

import mock

from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.irmc import boot as irmc_boot
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


INFO_DICT = db_utils.get_test_irmc_info()


class IRMCVirtualMediaAgentDeployTestCase(db_base.DbTestCase):

    def setUp(self):
        irmc_boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc_boot.check_share_fs_mounted_patcher.stop)
        super(IRMCVirtualMediaAgentDeployTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="agent_irmc")
        self.node = obj_utils.create_test_node(
            self.context, driver='agent_irmc', driver_info=INFO_DICT)

    @mock.patch.object(deploy_utils, 'validate_capabilities',
                       spec_set=True, autospec=True)
    @mock.patch.object(irmc_boot, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, parse_driver_info_mock,
                      validate_capabilities_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.validate(task)
            parse_driver_info_mock.assert_called_once_with(task.node)
            validate_capabilities_mock.assert_called_once_with(task.node)

    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    @mock.patch.object(irmc_boot, 'setup_deploy_iso',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', spec_set=True,
                       autospec=True)
    def test_deploy(self, build_agent_options_mock,
                    setup_deploy_iso_mock, node_power_action_mock):
        deploy_ramdisk_opts = build_agent_options_mock.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = task.driver.deploy.deploy(task)
            build_agent_options_mock.assert_called_once_with(task.node)
            setup_deploy_iso_mock.assert_called_once_with(
                task, deploy_ramdisk_opts)
            node_power_action_mock.assert_called_once_with(
                task, states.REBOOT)
            self.assertEqual(states.DEPLOYWAIT, returned_state)

    @mock.patch.object(manager_utils, 'node_power_action', spec_set=True,
                       autospec=True)
    def test_tear_down(self, node_power_action_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            returned_state = task.driver.deploy.tear_down(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_OFF)
            self.assertEqual(states.DELETED, returned_state)

    @mock.patch.object(agent, 'build_instance_info_for_deploy', spec_set=True,
                       autospec=True)
    def test_prepare(self, build_instance_info_for_deploy_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node.save = mock.MagicMock(sepc_set=[])
            task.driver.deploy.prepare(task)
            build_instance_info_for_deploy_mock.assert_called_once_with(
                task)
            task.node.save.assert_called_once_with()

    @mock.patch.object(irmc_boot, 'cleanup_vmedia_boot', spec_set=True,
                       autospec=True)
    def test_clean_up(self, cleanup_vmedia_boot_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.clean_up(task)
            cleanup_vmedia_boot_mock.assert_called_once_with(task)


class IRMCVirtualMediaAgentVendorInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        irmc_boot.check_share_fs_mounted_patcher.start()
        self.addCleanup(irmc_boot.check_share_fs_mounted_patcher.stop)
        super(IRMCVirtualMediaAgentVendorInterfaceTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="agent_irmc")
        self.node = obj_utils.create_test_node(
            self.context, driver='agent_irmc', driver_info=INFO_DICT)

    @mock.patch.object(agent.AgentVendorInterface, 'reboot_to_instance',
                       spec_set=True, autospec=True)
    @mock.patch.object(irmc_boot, 'cleanup_vmedia_boot', autospec=True)
    def test_reboot_to_instance(self,
                                cleanup_vmedia_boot_mock,
                                agent_reboot_to_instance_mock):
        kwargs = {}
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.vendor.reboot_to_instance(task, **kwargs)

            cleanup_vmedia_boot_mock.assert_called_once_with(task)
            agent_reboot_to_instance_mock.assert_called_once_with(
                mock.ANY, task, **kwargs)
