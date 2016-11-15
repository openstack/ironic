# Copyright 2016 Hewlett Packard Enterprise Development LP.
# Copyright 2016 Universidade Federal de Campina Grande
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
import time
import types

from oslo_utils import importutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_client
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import power
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

oneview_models = importutils.try_import('oneview_client.models')

METHODS = ['iter_nodes', 'update_node', 'do_provisioning_action']

oneview_error = common.SERVER_HARDWARE_ALLOCATION_ERROR
maintenance_reason = common.NODE_IN_USE_BY_ONEVIEW

driver_internal_info = {'oneview_error': oneview_error}
nodes_taken_by_oneview = [(1, 'fake_oneview')]
nodes_freed_by_oneview = [(1, 'fake_oneview', maintenance_reason)]
nodes_taken_on_cleanfail = [(1, 'fake_oneview', driver_internal_info)]
nodes_taken_on_cleanfail_no_info = [(1, 'fake_oneview', {})]

GET_POWER_STATE_RETRIES = 5


def _setup_node_in_available_state(node):
    node.provision_state = states.AVAILABLE
    node.maintenance = False
    node.maintenance_reason = None
    node.save()


def _setup_node_in_manageable_state(node):
    node.provision_state = states.MANAGEABLE
    node.maintenance = True
    node.maintenance_reason = common.NODE_IN_USE_BY_ONEVIEW
    node.save()


def _setup_node_in_cleanfailed_state_with_oneview_error(node):
    node.provision_state = states.CLEANFAIL
    node.maintenance = False
    node.maintenance_reason = None
    driver_internal_info = node.driver_internal_info
    oneview_error = common.SERVER_HARDWARE_ALLOCATION_ERROR
    driver_internal_info['oneview_error'] = oneview_error
    node.driver_internal_info = driver_internal_info
    node.save()


def _setup_node_in_cleanfailed_state_without_oneview_error(node):
    node.provision_state = states.CLEANFAIL
    node.maintenance = False
    node.maintenance_reason = None
    node.save()


class OneViewDriverDeploy(deploy.OneViewPeriodicTasks):
    oneview_driver = 'fake_oneview'


@mock.patch('ironic.objects.Node', spec_set=True, autospec=True)
@mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview',
                   spec_set=True, autospec=True)
class OneViewPeriodicTasks(db_base.DbTestCase):

    def setUp(self):
        super(OneViewPeriodicTasks, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver='fake_oneview')

        self.driver = driver_factory.get_driver('fake_oneview')
        self.deploy = OneViewDriverDeploy()
        self.manager = mock.MagicMock(spec=METHODS)
        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )

    def test_node_manageable_maintenance_when_in_use_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_available_state(self.node)
        self.manager.iter_nodes.return_value = nodes_taken_by_oneview
        mock_is_node_in_use_by_oneview.return_value = True
        self.deploy._periodic_check_nodes_taken_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertTrue(self.manager.update_node.called)
        self.assertTrue(self.manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)

    def test_node_stay_available_when_not_in_use_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_available_state(self.node)
        mock_node_get.return_value = self.node
        mock_is_node_in_use_by_oneview.return_value = False
        self.manager.iter_nodes.return_value = nodes_taken_by_oneview
        self.deploy._periodic_check_nodes_taken_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertFalse(self.manager.update_node.called)
        self.assertFalse(self.manager.do_provisioning_action.called)
        self.assertFalse(self.node.maintenance)
        self.assertIsNone(self.node.maintenance_reason)

    def test_node_stay_available_when_raise_exception(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_available_state(self.node)
        side_effect = exception.OneViewError('boom')
        mock_is_node_in_use_by_oneview.side_effect = side_effect
        self.manager.iter_nodes.return_value = nodes_taken_by_oneview
        self.deploy._periodic_check_nodes_taken_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertFalse(self.manager.update_node.called)
        self.assertFalse(self.manager.do_provisioning_action.called)
        self.assertFalse(self.node.maintenance)
        self.assertNotEqual(common.NODE_IN_USE_BY_ONEVIEW,
                            self.node.maintenance_reason)

    def test_node_available_when_not_in_use_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_manageable_state(self.node)
        self.manager.iter_nodes.return_value = nodes_freed_by_oneview
        mock_is_node_in_use_by_oneview.return_value = False
        self.deploy._periodic_check_nodes_freed_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertTrue(self.manager.update_node.called)
        self.assertTrue(self.manager.do_provisioning_action.called)
        self.assertFalse(self.node.maintenance)
        self.assertIsNone(self.node.maintenance_reason)

    def test_node_stay_manageable_when_in_use_by_oneview(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_manageable_state(self.node)
        mock_is_node_in_use_by_oneview.return_value = True
        self.manager.iter_nodes.return_value = nodes_freed_by_oneview
        self.deploy._periodic_check_nodes_freed_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertFalse(self.manager.update_node.called)
        self.assertFalse(self.manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)

    def test_node_stay_manageable_maintenance_when_raise_exception(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_manageable_state(self.node)
        side_effect = exception.OneViewError('boom')
        mock_is_node_in_use_by_oneview.side_effect = side_effect
        self.manager.iter_nodes.return_value = nodes_freed_by_oneview
        self.deploy._periodic_check_nodes_freed_by_oneview(
            self.manager, self.context
        )
        mock_is_node_in_use_by_oneview.assert_called_once_with(self.node)
        self.assertFalse(self.manager.update_node.called)
        self.assertFalse(self.manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)

    def test_node_manageable_maintenance_when_oneview_error(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_cleanfailed_state_with_oneview_error(self.node)
        self.manager.iter_nodes.return_value = nodes_taken_on_cleanfail
        self.deploy._periodic_check_nodes_taken_on_cleanfail(
            self.manager, self.context
        )
        self.assertTrue(self.manager.update_node.called)
        self.assertTrue(self.manager.do_provisioning_action.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(common.NODE_IN_USE_BY_ONEVIEW,
                         self.node.maintenance_reason)
        self.assertFalse('oneview_error' in self.node.driver_internal_info)

    def test_node_stay_clean_failed_when_no_oneview_error(
        self, mock_is_node_in_use_by_oneview, mock_node_get
    ):
        mock_node_get.get.return_value = self.node
        _setup_node_in_cleanfailed_state_without_oneview_error(self.node)
        self.manager.iter_nodes.return_value = nodes_taken_on_cleanfail_no_info
        self.deploy._periodic_check_nodes_taken_on_cleanfail(
            self.manager, self.context
        )
        self.assertFalse(self.manager.update_node.called)
        self.assertFalse(self.manager.do_provisioning_action.called)
        self.assertFalse(self.node.maintenance)
        self.assertNotEqual(common.NODE_IN_USE_BY_ONEVIEW,
                            self.node.maintenance_reason)
        self.assertFalse('oneview_error' in self.node.driver_internal_info)


@mock.patch.object(common, 'get_oneview_client', spec_set=True, autospec=True)
class TestOneViewAgentDeploy(db_base.DbTestCase):

    def setUp(self):
        super(TestOneViewAgentDeploy, self).setUp()
        self.config(
            post_deploy_get_power_state_retries=GET_POWER_STATE_RETRIES,
            group='agent')
        mgr_utils.mock_the_extension_manager(driver="agent_pxe_oneview")

        self.node = obj_utils.create_test_node(
            self.context, driver='agent_pxe_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
            driver_internal_info={'agent_url': 'http://1.2.3.4:5678'},
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
                                      node_power_action_mock,
                                      mock_get_ov_client):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.side_effect = [states.POWER_ON,
                                                states.POWER_OFF]
            task.driver.deploy.reboot_and_finish_deploy(task)
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
            node_power_action_mock, mock_get_ov_client):
        client = mock_get_ov_client.return_value
        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = 'any/applied_sp_uri/'
        client.get_server_hardware_by_uuid.return_value = fake_server_hardware
        mock_get_ov_client.return_value = client

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_ON
            task.driver.deploy.reboot_and_finish_deploy(task)
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
            self, power_off_mock, node_power_action_mock,
            mock_get_ov_client):
        client = mock_get_ov_client.return_value
        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = 'any/applied_sp_uri/'
        client.get_server_hardware_by_uuid.return_value = fake_server_hardware
        mock_get_ov_client.return_value = client

        power_off_mock.side_effect = RuntimeError("boom")
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.deploy.reboot_and_finish_deploy(task)
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
            node_power_action_mock, mock_get_ov_client):
        client = mock_get_ov_client.return_value
        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = 'any/applied_sp_uri/'
        client.get_server_hardware_by_uuid.return_value = fake_server_hardware
        mock_get_ov_client.return_value = client

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.side_effect = RuntimeError("boom")
            task.driver.deploy.reboot_and_finish_deploy(task)
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
            node_power_action_mock, collect_ramdisk_logs_mock,
            mock_get_ov_client):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_ON
            node_power_action_mock.side_effect = RuntimeError("boom")
            self.assertRaises(exception.InstanceDeployFailure,
                              task.driver.deploy.reboot_and_finish_deploy,
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
    @mock.patch('ironic.drivers.modules.agent.AgentDeploy'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance(self, clean_pxe_mock, check_deploy_mock,
                                power_off_mock, get_power_state_mock,
                                node_power_action_mock, mock_get_ov_client):
        check_deploy_mock.return_value = None

        client = mock_get_ov_client.return_value
        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = 'any/applied_sp_uri/'
        client.get_server_hardware_by_uuid.return_value = fake_server_hardware
        mock_get_ov_client.return_value = client

        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True

            task.driver.deploy.reboot_to_instance(task)

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
    @mock.patch('ironic.drivers.modules.agent.AgentDeploy'
                '.check_deploy_success', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'clean_up_ramdisk', autospec=True)
    def test_reboot_to_instance_boot_none(self, clean_pxe_mock,
                                          check_deploy_mock,
                                          power_off_mock,
                                          get_power_state_mock,
                                          node_power_action_mock,
                                          mock_get_ov_client):
        client = mock_get_ov_client.return_value
        fake_server_hardware = oneview_models.ServerHardware()
        fake_server_hardware.server_profile_uri = 'any/applied_sp_uri/'
        client.get_server_hardware_by_uuid.return_value = fake_server_hardware
        mock_get_ov_client.return_value = client

        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        driver_info = self.node.driver_info
        driver_info['applied_server_profile_uri'] = 'any/applied_sp_uri/'
        self.node.driver_info = driver_info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            get_power_state_mock.return_value = states.POWER_OFF
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.driver.boot = None

            task.driver.deploy.reboot_to_instance(task)

            self.assertFalse(clean_pxe_mock.called)
            check_deploy_mock.assert_called_once_with(mock.ANY, task.node)
            power_off_mock.assert_called_once_with(task.node)
            get_power_state_mock.assert_called_once_with(task)
            node_power_action_mock.assert_called_once_with(
                task, states.POWER_ON)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)
