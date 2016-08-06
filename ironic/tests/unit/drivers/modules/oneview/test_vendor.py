# -*- coding: utf-8 -*-
#
# Copyright 2015 Red Hat, Inc.
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

import time
import types

import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules.oneview import vendor
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


GET_POWER_STATE_RETRIES = 5


class TestBaseAgentVendor(db_base.DbTestCase):

    def setUp(self):
        super(TestBaseAgentVendor, self).setUp()
        self.config(
            post_deploy_get_power_state_retries=GET_POWER_STATE_RETRIES,
            group='agent')
        mgr_utils.mock_the_extension_manager(driver="agent_pxe_oneview")
        self.passthru = vendor.AgentVendorInterface()

        self.node = obj_utils.create_test_node(
            self.context, driver='agent_pxe_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch('ironic.conductor.utils.node_set_boot_device', autospec=True)
    def test_reboot_and_finish_deploy(self, set_bootdev_mock, power_off_mock,
                                      get_power_state_mock,
                                      node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.side_effect = [states.POWER_ON,
                                                states.POWER_OFF]
            self.passthru.reboot_and_finish_deploy(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(2, get_power_state_mock.call_count)
            set_bootdev_mock.assert_called_once_with(task, 'disk',
                                                     persistent=True)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_reboot_and_finish_deploy_soft_poweroff_doesnt_complete(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_ON
            self.passthru.reboot_and_finish_deploy(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(GET_POWER_STATE_RETRIES + 1,
                             get_power_state_mock.call_count)
            node_power_action_mock.assert_has_calls([
                mock.call(task, states.POWER_OFF),
                mock.call(task, states.POWER_ON)
            ])
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_reboot_and_finish_deploy_soft_poweroff_fails(
            self, power_off_mock, node_power_action_mock):
        power_off_mock.side_effect = RuntimeError("boom")
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.passthru.reboot_and_finish_deploy(task)
            power_off_mock.assert_called_once_with(task.node)
            node_power_action_mock.assert_has_calls([
                mock.call(task, states.POWER_OFF),
                mock.call(task, states.POWER_ON)
            ])
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_reboot_and_finish_deploy_get_power_state_fails(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.side_effect = RuntimeError("boom")
            self.passthru.reboot_and_finish_deploy(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(GET_POWER_STATE_RETRIES + 1,
                             get_power_state_mock.call_count)
            node_power_action_mock.assert_has_calls([
                mock.call(task, states.POWER_OFF),
                mock.call(task, states.POWER_ON)
            ])
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_reboot_and_finish_deploy_power_action_fails(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock, collect_ramdisk_logs_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_ON
            node_power_action_mock.side_effect = RuntimeError("boom")
            self.assertRaises(exception.InstanceDeployFailure,
                              self.passthru.reboot_and_finish_deploy,
                              task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(GET_POWER_STATE_RETRIES + 1,
                             get_power_state_mock.call_count)
            node_power_action_mock.assert_has_calls([
                mock.call(task, states.POWER_OFF),
                mock.call(task, states.POWER_OFF)])
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            collect_ramdisk_logs_mock.assert_called_once_with(task.node)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance(self, clean_pxe_mock, check_deploy_mock,
                                power_off_mock, get_power_state_mock,
                                node_power_action_mock):
        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True

            self.passthru.reboot_to_instance(task)

            clean_pxe_mock.assert_called_once_with(task.driver.boot, task)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(power.OneViewPower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_boot_none(self, clean_pxe_mock,
                                          check_deploy_mock,
                                          power_off_mock,
                                          get_power_state_mock,
                                          node_power_action_mock):
        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot = None

            self.passthru.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
