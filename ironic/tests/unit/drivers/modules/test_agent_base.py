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
from unittest import mock

from oslo_config import cfg
from testtools import matchers

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import image_service
from ironic.common import states
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import agent
from ironic.drivers.modules import agent_base
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import boot_mode_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules import pxe
from ironic.drivers import utils as driver_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as object_utils

CONF = cfg.CONF

INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()
DRIVER_INTERNAL_INFO = db_utils.get_test_agent_driver_internal_info()


class FakeAgentDeploy(agent_base.AgentBaseMixin, agent_base.AgentDeployMixin,
                      fake.FakeDeploy):
    pass


class AgentDeployMixinBaseTest(db_base.DbTestCase):

    def setUp(self):
        super(AgentDeployMixinBaseTest, self).setUp()
        for iface in drivers_base.ALL_INTERFACES:
            impl = 'fake'
            if iface == 'deploy':
                impl = 'direct'
            if iface == 'boot':
                impl = 'pxe'
            if iface == 'rescue':
                impl = 'agent'
            if iface == 'network':
                continue
            config_kwarg = {'enabled_%s_interfaces' % iface: [impl],
                            'default_%s_interface' % iface: impl}
            self.config(**config_kwarg)
        self.config(enabled_hardware_types=['fake-hardware'])
        self.deploy = FakeAgentDeploy()
        n = {
            'driver': 'fake-hardware',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
            'network_interface': 'noop'
        }
        self.node = object_utils.create_test_node(self.context, **n)


class HeartbeatMixinTest(AgentDeployMixinBaseTest):

    def setUp(self):
        super(HeartbeatMixinTest, self).setUp()
        self.deploy = agent_base.HeartbeatMixin()

    @mock.patch.object(agent_base.HeartbeatMixin,
                       'refresh_steps', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'process_next_step', autospec=True)
    def test_heartbeat_continue_deploy_first_run(self, next_step_mock,
                                                 refresh_steps_mock):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, 'url', '3.2.0')
            self.assertFalse(task.shared)
            self.assertEqual(
                'url', task.node.driver_internal_info['agent_url'])
            self.assertEqual(
                '3.2.0',
                task.node.driver_internal_info['agent_version'])
            refresh_steps_mock.assert_called_once_with(self.deploy,
                                                       task, 'deploy')
            next_step_mock.assert_called_once_with(self.deploy,
                                                   task, 'deploy')

    @mock.patch.object(agent_base.HeartbeatMixin,
                       'refresh_steps', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'process_next_step', autospec=True)
    def test_heartbeat_continue_deploy_second_run(self, next_step_mock,
                                                  refresh_steps_mock):
        dii = self.node.driver_internal_info
        dii['agent_cached_deploy_steps'] = ['step']
        self.node.driver_internal_info = dii
        self.node.provision_state = states.DEPLOYWAIT
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, 'url', '3.2.0')
            self.assertFalse(task.shared)
            self.assertEqual(
                'url', task.node.driver_internal_info['agent_url'])
            self.assertEqual(
                '3.2.0',
                task.node.driver_internal_info['agent_version'])
            self.assertFalse(refresh_steps_mock.called)
            next_step_mock.assert_called_once_with(self.deploy,
                                                   task, 'deploy')

    @mock.patch.object(agent_base.HeartbeatMixin,
                       'process_next_step', autospec=True)
    def test_heartbeat_polling(self, next_step_mock):
        self.node.provision_state = states.DEPLOYWAIT
        info = self.node.driver_internal_info
        info['agent_cached_deploy_steps'] = ['step1']
        info['deployment_polling'] = True
        self.node.driver_internal_info = info
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.deploy.heartbeat(task, 'url', '3.2.0')
            self.assertFalse(task.shared)
            self.assertEqual(
                'url', task.node.driver_internal_info['agent_url'])
            self.assertEqual(
                '3.2.0',
                task.node.driver_internal_info['agent_version'])
            self.assertFalse(next_step_mock.called)

    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_in_maintenance(self, next_step_mock):
        # NOTE(pas-ha) checking only for states that are not noop
        for state in (states.DEPLOYWAIT, states.CLEANWAIT):
            next_step_mock.reset_mock()
            self.node.provision_state = state
            self.node.maintenance = True
            self.node.save()
            agent_url = 'url-%s' % state
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                self.deploy.heartbeat(task, agent_url, '3.2.0')
                self.assertFalse(task.shared)
                self.assertEqual(
                    agent_url,
                    task.node.driver_internal_info['agent_url'])
                self.assertEqual(
                    '3.2.0',
                    task.node.driver_internal_info['agent_version'])
                self.assertEqual(state, task.node.provision_state)
                self.assertIsNone(task.node.last_error)
            next_step_mock.assert_not_called()

    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_in_maintenance_abort(self, next_step_mock):
        CONF.set_override('allow_provisioning_in_maintenance', False,
                          group='conductor')
        for state, expected in [(states.DEPLOYWAIT, states.DEPLOYFAIL),
                                (states.CLEANWAIT, states.CLEANFAIL),
                                (states.RESCUEWAIT, states.RESCUEFAIL)]:
            next_step_mock.reset_mock()
            self.node.provision_state = state
            self.node.maintenance = True
            self.node.save()
            agent_url = 'url-%s' % state
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                self.deploy.heartbeat(task, agent_url, '3.2.0')
                self.assertFalse(task.shared)
                self.assertIsNone(
                    task.node.driver_internal_info.get('agent_url', None))
                self.assertEqual(
                    '3.2.0',
                    task.node.driver_internal_info['agent_version'])
            self.node.refresh()
            self.assertEqual(expected, self.node.provision_state)
            self.assertIn('aborted', self.node.last_error)
            next_step_mock.assert_not_called()

    @mock.patch('time.sleep', lambda _t: None)
    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_with_reservation(self, next_step_mock):
        # NOTE(pas-ha) checking only for states that are not noop
        for state in (states.DEPLOYWAIT, states.CLEANWAIT):
            next_step_mock.reset_mock()
            self.node.provision_state = state
            self.node.reservation = 'localhost'
            self.node.save()
            old_drv_info = self.node.driver_internal_info.copy()
            agent_url = 'url-%s' % state
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                self.deploy.heartbeat(task, agent_url, '3.2.0')
                self.assertTrue(task.shared)
                self.assertEqual(old_drv_info, task.node.driver_internal_info)
                self.assertIsNone(task.node.last_error)
            next_step_mock.assert_not_called()

    @mock.patch.object(agent_base.LOG, 'error', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_noops_in_wrong_state(self, next_step_mock, log_mock):
        allowed = {states.DEPLOYWAIT, states.CLEANWAIT, states.RESCUEWAIT,
                   states.DEPLOYING, states.CLEANING, states.RESCUING}
        for state in set(states.machine.states) - allowed:
            for m in (next_step_mock, log_mock):
                m.reset_mock()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                task.node.provision_state = state
                self.deploy.heartbeat(task, 'url', '1.0.0')
                self.assertTrue(task.shared)
                self.assertNotIn('agent_last_heartbeat',
                                 task.node.driver_internal_info)
            next_step_mock.assert_not_called()
            log_mock.assert_called_once_with(mock.ANY,
                                             {'node': self.node.uuid,
                                              'state': state})

    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_noops_in_wrong_state2(self, next_step_mock):
        CONF.set_override('allow_provisioning_in_maintenance', False,
                          group='conductor')
        allowed = {states.DEPLOYWAIT, states.CLEANWAIT}
        for state in set(states.machine.states) - allowed:
            next_step_mock.reset_mock()
            with task_manager.acquire(self.context, self.node.uuid,
                                      shared=True) as task:
                self.node.provision_state = state
                self.deploy.heartbeat(task, 'url', '1.0.0')
                self.assertTrue(task.shared)
            next_step_mock.assert_not_called()

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(agent_base.LOG, 'exception', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_deploy_fails(self, next_step_mock, log_mock,
                                    failed_mock):
        next_step_mock.side_effect = Exception('LlamaException')
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            task.node.provision_state = states.DEPLOYWAIT
            task.node.target_provision_state = states.ACTIVE
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')
            failed_mock.assert_called_once_with(
                task, mock.ANY, collect_logs=True)
            log_mock.assert_called_once_with(
                'Asynchronous exception for node %(node)s: %(err)s',
                {'err': 'Failed to process the next deploy step. '
                 'Error: LlamaException',
                 'node': task.node.uuid})

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(agent_base.LOG, 'exception', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin, 'process_next_step',
                       autospec=True)
    def test_heartbeat_deploy_done_raises_with_event(self, next_step_mock,
                                                     log_mock, failed_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:

            def driver_failure(*args, **kwargs):
                # simulate driver failure that both advances the FSM
                # and raises an exception
                task.node.provision_state = states.DEPLOYFAIL
                raise Exception('LlamaException')

            task.node.provision_state = states.DEPLOYWAIT
            task.node.target_provision_state = states.ACTIVE
            next_step_mock.side_effect = driver_failure
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')
            # task.node.provision_state being set to DEPLOYFAIL
            # within the driver_failue, hearbeat should not call
            # deploy_utils.set_failed_state anymore
            self.assertFalse(failed_mock.called)
            log_mock.assert_called_once_with(
                'Asynchronous exception for node %(node)s: %(err)s',
                {'err': 'Failed to process the next deploy step. '
                 'Error: LlamaException',
                 'node': task.node.uuid})

    @mock.patch.object(objects.node.Node, 'touch_provisioning', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'refresh_steps', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    def test_heartbeat_resume_clean(self, mock_notify, mock_set_steps,
                                    mock_refresh, mock_touch):
        self.node.clean_step = {}
        self.node.provision_state = states.CLEANWAIT
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_touch.assert_called_once_with(mock.ANY)
        mock_refresh.assert_called_once_with(mock.ANY, task, 'clean')
        mock_notify.assert_called_once_with(task, 'clean')
        mock_set_steps.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(objects.node.Node, 'touch_provisioning', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'refresh_steps', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    def test_heartbeat_resume_clean_fails(self, mock_notify, mock_set_steps,
                                          mock_refresh, mock_touch,
                                          mock_handler):
        mocks = [mock_refresh, mock_set_steps, mock_notify]
        self.node.clean_step = {}
        self.node.provision_state = states.CLEANWAIT
        self.node.save()
        for i in range(len(mocks)):
            before_failed_mocks = mocks[:i]
            failed_mock = mocks[i]
            after_failed_mocks = mocks[i + 1:]
            failed_mock.side_effect = Exception()
            with task_manager.acquire(
                    self.context, self.node.uuid, shared=False) as task:
                self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

            mock_touch.assert_called_once_with(mock.ANY)
            mock_handler.assert_called_once_with(task, mock.ANY, mock.ANY)
            for called in before_failed_mocks + [failed_mock]:
                self.assertTrue(called.called)
            for not_called in after_failed_mocks:
                self.assertFalse(not_called.called)

            # Reset mocks for the next interaction
            for m in mocks + [mock_touch, mock_handler]:
                m.reset_mock()
            failed_mock.side_effect = None

    @mock.patch.object(objects.node.Node, 'touch_provisioning', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'continue_cleaning', autospec=True)
    def test_heartbeat_continue_cleaning(self, mock_continue, mock_touch):
        self.node.clean_step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'foo',
            'reboot_requested': False
        }
        self.node.provision_state = states.CLEANWAIT
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_touch.assert_called_once_with(mock.ANY)
        mock_continue.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(objects.node.Node, 'touch_provisioning', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'continue_cleaning', autospec=True)
    def test_heartbeat_continue_cleaning_polling(self, mock_continue,
                                                 mock_touch):
        info = self.node.driver_internal_info
        info['cleaning_polling'] = True
        self.node.driver_internal_info = info
        self.node.clean_step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'foo',
            'reboot_requested': False
        }
        self.node.provision_state = states.CLEANWAIT
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_touch.assert_called_once_with(mock.ANY)
        self.assertFalse(mock_continue.called)

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin,
                       'continue_cleaning', autospec=True)
    def test_heartbeat_continue_cleaning_fails(self, mock_continue,
                                               mock_handler):
        self.node.clean_step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'foo',
            'reboot_requested': False
        }

        mock_continue.side_effect = Exception()

        self.node.provision_state = states.CLEANWAIT
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_continue.assert_called_once_with(mock.ANY, task)
        mock_handler.assert_called_once_with(task, mock.ANY, mock.ANY)

    @mock.patch.object(manager_utils, 'rescuing_error_handler', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin, '_finalize_rescue',
                       autospec=True)
    def test_heartbeat_rescue(self, mock_finalize_rescue,
                              mock_rescue_err_handler):
        self.node.provision_state = states.RESCUEWAIT
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_finalize_rescue.assert_called_once_with(mock.ANY, task)
        self.assertFalse(mock_rescue_err_handler.called)

    @mock.patch.object(manager_utils, 'rescuing_error_handler', autospec=True)
    @mock.patch.object(agent_base.HeartbeatMixin, '_finalize_rescue',
                       autospec=True)
    def test_heartbeat_rescue_fails(self, mock_finalize,
                                    mock_rescue_err_handler):
        self.node.provision_state = states.RESCUEWAIT
        self.node.save()
        mock_finalize.side_effect = Exception('some failure')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '1.0.0')

        mock_finalize.assert_called_once_with(mock.ANY, task)
        mock_rescue_err_handler.assert_called_once_with(
            task, 'Node failed to perform '
            'rescue operation. Error: some failure')

    @mock.patch.object(agent_base.LOG, 'error', autospec=True)
    def test_heartbeat_records_cleaning_deploying(self, log_mock):
        for provision_state in (states.CLEANING, states.DEPLOYING):
            self.node.driver_internal_info = {}
            self.node.provision_state = provision_state
            self.node.save()
            with task_manager.acquire(
                    self.context, self.node.uuid, shared=False) as task:
                self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '3.2.0')
                self.assertEqual('http://127.0.0.1:8080',
                                 task.node.driver_internal_info['agent_url'])
                self.assertEqual('3.2.0',
                                 task.node.driver_internal_info[
                                     'agent_version'])
                self.assertIsNotNone(
                    task.node.driver_internal_info['agent_last_heartbeat'])
                self.assertEqual(provision_state, task.node.provision_state)
            self.assertFalse(log_mock.called)

    def test_heartbeat_records_fast_track(self):
        self.config(fast_track=True, group='deploy')
        for provision_state in [states.ENROLL, states.MANAGEABLE,
                                states.AVAILABLE]:
            self.node.driver_internal_info = {}
            self.node.provision_state = provision_state
            self.node.save()
            with task_manager.acquire(
                    self.context, self.node.uuid, shared=False) as task:
                self.deploy.heartbeat(task, 'http://127.0.0.1:8080', '3.2.0')
                self.assertEqual('http://127.0.0.1:8080',
                                 task.node.driver_internal_info['agent_url'])
                self.assertEqual('3.2.0',
                                 task.node.driver_internal_info[
                                     'agent_version'])
                self.assertIsNotNone(
                    task.node.driver_internal_info['agent_last_heartbeat'])
                self.assertEqual(provision_state, task.node.provision_state)


class AgentRescueTests(AgentDeployMixinBaseTest):

    def setUp(self):
        super(AgentRescueTests, self).setUp()

    @mock.patch.object(agent.AgentRescue, 'clean_up',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'finalize_rescue',
                       spec=types.FunctionType)
    def test__finalize_rescue(self, mock_finalize_rescue,
                              mock_clean_up):
        node = self.node
        node.provision_state = states.RESCUEWAIT
        node.save()
        mock_finalize_rescue.return_value = {'command_status': 'SUCCEEDED'}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.driver.network.configure_tenant_networks = mock.Mock()
            task.process_event = mock.Mock()
            self.deploy._finalize_rescue(task)
            mock_finalize_rescue.assert_called_once_with(task.node)
            task.process_event.assert_has_calls([mock.call('resume'),
                                                 mock.call('done')])
            mock_clean_up.assert_called_once_with(mock.ANY, task)

    @mock.patch.object(agent_client.AgentClient, 'finalize_rescue',
                       spec=types.FunctionType)
    def test__finalize_rescue_bad_command_result(self, mock_finalize_rescue):
        node = self.node
        node.provision_state = states.RESCUEWAIT
        node.save()
        mock_finalize_rescue.return_value = {'command_status': 'FAILED',
                                             'command_error': 'bad'}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceRescueFailure,
                              self.deploy._finalize_rescue, task)
            mock_finalize_rescue.assert_called_once_with(task.node)

    @mock.patch.object(agent_client.AgentClient, 'finalize_rescue',
                       spec=types.FunctionType)
    def test__finalize_rescue_exc(self, mock_finalize_rescue):
        node = self.node
        node.provision_state = states.RESCUEWAIT
        node.save()
        mock_finalize_rescue.side_effect = exception.IronicException("No pass")
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceRescueFailure,
                              self.deploy._finalize_rescue, task)
            mock_finalize_rescue.assert_called_once_with(task.node)

    @mock.patch.object(agent_client.AgentClient, 'finalize_rescue',
                       spec=types.FunctionType)
    def test__finalize_rescue_missing_command_result(self,
                                                     mock_finalize_rescue):
        node = self.node
        node.provision_state = states.RESCUEWAIT
        node.save()
        mock_finalize_rescue.return_value = {}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceRescueFailure,
                              self.deploy._finalize_rescue, task)
            mock_finalize_rescue.assert_called_once_with(task.node)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed',
                       autospec=True)
    @mock.patch.object(agent.AgentRescue, 'clean_up',
                       spec_set=True, autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'finalize_rescue',
                       spec=types.FunctionType)
    def test__finalize_rescue_with_smartnic_port(
            self, mock_finalize_rescue, mock_clean_up,
            power_on_node_if_needed_mock, restore_power_state_mock):
        node = self.node
        node.provision_state = states.RESCUEWAIT
        node.save()
        mock_finalize_rescue.return_value = {'command_status': 'SUCCEEDED'}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.driver.network.configure_tenant_networks = mock.Mock()
            task.process_event = mock.Mock()
            power_on_node_if_needed_mock.return_value = states.POWER_OFF
            self.deploy._finalize_rescue(task)
            mock_finalize_rescue.assert_called_once_with(task.node)
            task.process_event.assert_has_calls([mock.call('resume'),
                                                 mock.call('done')])
            mock_clean_up.assert_called_once_with(mock.ANY, task)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)


class AgentDeployMixinTest(AgentDeployMixinBaseTest):
    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock, collect_mock,
            power_on_node_if_needed_mock):
        cfg.CONF.set_override('deploy_logs_collect', 'always', 'agent')
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.side_effect = [states.POWER_ON,
                                                states.POWER_OFF]

            power_on_node_if_needed_mock.return_value = None
            self.deploy.tear_down_agent(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(2, get_power_state_mock.call_count)
            self.assertFalse(node_power_action_mock.called)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            collect_mock.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent_soft_poweroff_doesnt_complete(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock, mock_collect):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.return_value = states.POWER_ON
            self.deploy.tear_down_agent(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(7, get_power_state_mock.call_count)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent_soft_poweroff_fails(
            self, power_off_mock, get_power_state_mock, node_power_action_mock,
            mock_collect):
        power_off_mock.side_effect = RuntimeError("boom")
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.return_value = states.POWER_ON
            self.deploy.tear_down_agent(task)
            power_off_mock.assert_called_once_with(task.node)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent_soft_poweroff_race(
            self, power_off_mock, get_power_state_mock, node_power_action_mock,
            mock_collect):
        # Test the situation when soft power off works, but ironic doesn't
        # learn about it.
        power_off_mock.side_effect = RuntimeError("boom")
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.side_effect = [states.POWER_ON,
                                                states.POWER_OFF]
            self.deploy.tear_down_agent(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertFalse(node_power_action_mock.called)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent_get_power_state_fails(
            self, power_off_mock, get_power_state_mock, node_power_action_mock,
            mock_collect, power_on_node_if_needed_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.return_value = RuntimeError("boom")
            power_on_node_if_needed_mock.return_value = None
            self.deploy.tear_down_agent(task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(7, get_power_state_mock.call_count)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state',
                       spec=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'power_off',
                       spec=types.FunctionType)
    def test_tear_down_agent_power_off_fails(
            self, power_off_mock, get_power_state_mock,
            node_power_action_mock, mock_collect):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            get_power_state_mock.return_value = states.POWER_ON
            node_power_action_mock.side_effect = RuntimeError("boom")
            self.assertRaises(exception.InstanceDeployFailure,
                              self.deploy.tear_down_agent,
                              task)
            power_off_mock.assert_called_once_with(task.node)
            self.assertEqual(7, get_power_state_mock.call_count)
            node_power_action_mock.assert_called_with(task, states.POWER_OFF)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            mock_collect.assert_called_once_with(task.node)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'sync',
                       spec=types.FunctionType)
    def test_tear_down_agent_power_action_oob_power_off(
            self, sync_mock, node_power_action_mock, mock_collect):
        # Enable force power off
        driver_info = self.node.driver_info
        driver_info['deploy_forces_oob_reboot'] = True
        self.node.driver_info = driver_info

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.tear_down_agent(task)

            sync_mock.assert_called_once_with(task.node)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(agent_base.LOG, 'warning', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'sync',
                       spec=types.FunctionType)
    def test_tear_down_agent_power_action_oob_power_off_failed(
            self, sync_mock, node_power_action_mock, log_mock, mock_collect):
        # Enable force power off
        driver_info = self.node.driver_info
        driver_info['deploy_forces_oob_reboot'] = True
        self.node.driver_info = driver_info

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            log_mock.reset_mock()

            sync_mock.return_value = {'faultstring': 'Unknown command: blah'}
            self.deploy.tear_down_agent(task)

            sync_mock.assert_called_once_with(task.node)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_OFF)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            log_error = ('The version of the IPA ramdisk used in the '
                         'deployment do not support the command "sync"')
            log_mock.assert_called_once_with(
                'Failed to flush the file system prior to hard rebooting the '
                'node %(node)s. Error: %(error)s',
                {'node': task.node.uuid, 'error': log_error})
            self.assertFalse(mock_collect.called)

    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_supported_power_states',
                       lambda self, task: [states.REBOOT])
    @mock.patch.object(agent_client.AgentClient, 'sync', autospec=True)
    def test_tear_down_agent_no_power_on_support(
            self, sync_mock, node_power_action_mock, collect_mock,
            power_on_node_if_needed_mock):
        cfg.CONF.set_override('deploy_logs_collect', 'always', 'agent')
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.tear_down_agent(task)
            node_power_action_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)
            collect_mock.assert_called_once_with(task.node)
            self.assertFalse(power_on_node_if_needed_mock.called)
            sync_mock.assert_called_once_with(agent_client.get_client(task),
                                              task.node)

    @mock.patch.object(manager_utils, 'restore_power_state_if_needed',
                       autospec=True)
    @mock.patch.object(manager_utils, 'power_on_node_if_needed', autospec=True)
    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'remove_provisioning_network', spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'configure_tenant_networks', spec_set=True, autospec=True)
    def test_switch_to_tenant_network(self, configure_tenant_net_mock,
                                      remove_provisioning_net_mock,
                                      power_on_node_if_needed_mock,
                                      restore_power_state_mock):
        power_on_node_if_needed_mock.return_value = states.POWER_OFF
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.switch_to_tenant_network(task)
            remove_provisioning_net_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            configure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            power_on_node_if_needed_mock.assert_called_once_with(task)
            restore_power_state_mock.assert_called_once_with(
                task, states.POWER_OFF)

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'remove_provisioning_network', spec_set=True, autospec=True)
    @mock.patch('ironic.drivers.modules.network.noop.NoopNetwork.'
                'configure_tenant_networks', spec_set=True, autospec=True)
    def test_switch_to_tenant_network_fails(self, configure_tenant_net_mock,
                                            remove_provisioning_net_mock,
                                            mock_collect):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            configure_tenant_net_mock.side_effect = exception.NetworkError(
                "boom")
            self.assertRaises(exception.InstanceDeployFailure,
                              self.deploy.switch_to_tenant_network, task)
            remove_provisioning_net_mock.assert_called_once_with(mock.ANY,
                                                                 task)
            configure_tenant_net_mock.assert_called_once_with(mock.ANY, task)
            self.assertFalse(mock_collect.called)

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_boot_instance(self, node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.boot_instance(task)
            node_power_action_mock.assert_called_once_with(task,
                                                           states.POWER_ON)

    @mock.patch.object(fake.FakePower, 'get_supported_power_states',
                       lambda self, task: [states.REBOOT])
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test_boot_instance_no_power_on(self, node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.deploy.boot_instance(task)
            self.assertFalse(node_power_action_mock.called)

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode', autospec=True,
                       return_value='whatever')
    def test_configure_local_boot(self, boot_mode_mock,
                                  try_set_boot_device_mock,
                                  install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task, root_uuid='some-root-uuid')
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            boot_mode_mock.assert_called_once_with(task.node)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None, prep_boot_part_uuid=None,
                target_boot_mode='whatever', software_raid=False
            )

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode', autospec=True,
                       return_value='whatever')
    def test_configure_local_boot_with_prep(self, boot_mode_mock,
                                            try_set_boot_device_mock,
                                            install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task, root_uuid='some-root-uuid',
                                             prep_boot_part_uuid='fake-prep')
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            boot_mode_mock.assert_called_once_with(task.node)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None, prep_boot_part_uuid='fake-prep',
                target_boot_mode='whatever', software_raid=False
            )

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode', autospec=True,
                       return_value='uefi')
    def test_configure_local_boot_uefi(self, boot_mode_mock,
                                       try_set_boot_device_mock,
                                       install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(
                task, root_uuid='some-root-uuid',
                efi_system_part_uuid='efi-system-part-uuid')
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            boot_mode_mock.assert_called_once_with(task.node)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid='efi-system-part-uuid',
                prep_boot_part_uuid=None,
                target_boot_mode='uefi', software_raid=False
            )

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_whole_disk_image(
            self, install_bootloader_mock, try_set_boot_device_mock):

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_no_root_uuid(
            self, install_bootloader_mock, try_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(boot_mode_utils, 'get_boot_mode',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_no_root_uuid_whole_disk(
            self, install_bootloader_mock, try_set_boot_device_mock,
            boot_mode_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            boot_mode_mock.return_value = 'uefi'
            self.deploy.configure_local_boot(
                task, root_uuid=None,
                efi_system_part_uuid='efi-system-part-uuid')
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid=None,
                efi_system_part_uuid='efi-system-part-uuid',
                prep_boot_part_uuid=None, target_boot_mode='uefi',
                software_raid=False)

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_on_software_raid(
            self, install_bootloader_mock, try_set_boot_device_mock,
            GlanceImageService_mock):
        image = GlanceImageService_mock.return_value.show.return_value
        image.get.return_value = {'rootfs_uuid': 'rootfs'}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "size_gb": 100,
                        "raid_level": "1",
                        "controller": "software",
                    },
                    {
                        "size_gb": 'MAX',
                        "raid_level": "0",
                        "controller": "software",
                    }
                ]
            }
            self.deploy.configure_local_boot(task)
            self.assertTrue(GlanceImageService_mock.called)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node,
                root_uuid='rootfs',
                efi_system_part_uuid=None,
                prep_boot_part_uuid=None,
                target_boot_mode='bios',
                software_raid=True)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_on_software_raid_explicit_uuid(
            self, install_bootloader_mock, try_set_boot_device_mock,
            GlanceImageService_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            task.node.instance_info['image_rootfs_uuid'] = 'rootfs'
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "size_gb": 100,
                        "raid_level": "1",
                        "controller": "software",
                    },
                    {
                        "size_gb": 'MAX',
                        "raid_level": "0",
                        "controller": "software",
                    }
                ]
            }
            self.deploy.configure_local_boot(task)
            self.assertFalse(GlanceImageService_mock.called)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node,
                root_uuid='rootfs',
                efi_system_part_uuid=None,
                prep_boot_part_uuid=None,
                target_boot_mode='bios',
                software_raid=True)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(image_service, 'GlanceImageService', autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_on_software_raid_exception(
            self, install_bootloader_mock, try_set_boot_device_mock,
            GlanceImageService_mock):
        GlanceImageService_mock.side_effect = Exception('Glance not found')
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = True
            root_uuid = "1efecf88-2b58-4d4e-8fbd-7bef1a40a1b0"
            task.node.driver_internal_info['root_uuid_or_disk_id'] = root_uuid
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "size_gb": 100,
                        "raid_level": "1",
                        "controller": "software",
                    },
                    {
                        "size_gb": 'MAX',
                        "raid_level": "0",
                        "controller": "software",
                    }
                ]
            }
            self.deploy.configure_local_boot(task)
            self.assertTrue(GlanceImageService_mock.called)
            # check if the root_uuid comes from the driver_internal_info
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid=root_uuid,
                efi_system_part_uuid=None, prep_boot_part_uuid=None,
                target_boot_mode='bios', software_raid=True)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_on_non_software_raid(
            self, install_bootloader_mock, try_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            task.node.target_raid_config = {
                "logical_disks": [
                    {
                        "size_gb": 100,
                        "raid_level": "1",
                    },
                    {
                        "size_gb": 'MAX',
                        "raid_level": "0",
                    }
                ]
            }
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_enforce_persistent_boot_device_default(
            self, install_bootloader_mock, try_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            driver_info = task.node.driver_info
            driver_info['force_persistent_boot_device'] = 'Default'
            task.node.driver_info = driver_info
            driver_info['force_persistent_boot_device'] = 'Always'
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_enforce_persistent_boot_device_always(
            self, install_bootloader_mock, try_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            driver_info = task.node.driver_info
            driver_info['force_persistent_boot_device'] = 'Always'
            task.node.driver_info = driver_info
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)

    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    def test_configure_local_boot_enforce_persistent_boot_device_never(
            self, install_bootloader_mock, try_set_boot_device_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            driver_info = task.node.driver_info
            driver_info['force_persistent_boot_device'] = 'Never'
            task.node.driver_info = driver_info
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.deploy.configure_local_boot(task)
            self.assertFalse(install_bootloader_mock.called)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=False)

    @mock.patch.object(agent_client.AgentClient, 'collect_system_logs',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode', autospec=True,
                       return_value='whatever')
    def test_configure_local_boot_boot_loader_install_fail(
            self, boot_mode_mock, install_bootloader_mock,
            collect_logs_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'FAILED', 'command_error': 'boom'}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.assertRaises(exception.InstanceDeployFailure,
                              self.deploy.configure_local_boot,
                              task, root_uuid='some-root-uuid')
            boot_mode_mock.assert_called_once_with(task.node)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None, prep_boot_part_uuid=None,
                target_boot_mode='whatever', software_raid=False
            )
            collect_logs_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(agent_client.AgentClient, 'collect_system_logs',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'try_set_boot_device', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader',
                       autospec=True)
    @mock.patch.object(boot_mode_utils, 'get_boot_mode', autospec=True,
                       return_value='whatever')
    def test_configure_local_boot_set_boot_device_fail(
            self, boot_mode_mock, install_bootloader_mock,
            try_set_boot_device_mock, collect_logs_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        try_set_boot_device_mock.side_effect = RuntimeError('error')
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.driver_internal_info['is_whole_disk_image'] = False
            self.assertRaises(exception.InstanceDeployFailure,
                              self.deploy.configure_local_boot,
                              task, root_uuid='some-root-uuid',
                              prep_boot_part_uuid=None)
            boot_mode_mock.assert_called_once_with(task.node)
            install_bootloader_mock.assert_called_once_with(
                mock.ANY, task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None, prep_boot_part_uuid=None,
                target_boot_mode='whatever', software_raid=False)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK, persistent=True)
            collect_logs_mock.assert_called_once_with(mock.ANY, task.node)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    def test_prepare_instance_to_boot_netboot(self, configure_mock,
                                              boot_option_mock,
                                              prepare_instance_mock,
                                              failed_state_mock):
        boot_option_mock.return_value = 'netboot'
        prepare_instance_mock.return_value = None
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        root_uuid = 'root_uuid'
        efi_system_part_uuid = 'efi_sys_uuid'
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.prepare_instance_to_boot(task, root_uuid,
                                                 efi_system_part_uuid)
            self.assertFalse(configure_mock.called)
            boot_option_mock.assert_called_once_with(task.node)
            prepare_instance_mock.assert_called_once_with(task.driver.boot,
                                                          task)
            self.assertFalse(failed_state_mock.called)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    def test_prepare_instance_to_boot_localboot(self, configure_mock,
                                                boot_option_mock,
                                                prepare_instance_mock,
                                                failed_state_mock):
        boot_option_mock.return_value = 'local'
        prepare_instance_mock.return_value = None
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        root_uuid = 'root_uuid'
        efi_system_part_uuid = 'efi_sys_uuid'
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.prepare_instance_to_boot(task, root_uuid,
                                                 efi_system_part_uuid)
            configure_mock.assert_called_once_with(
                self.deploy, task,
                root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid,
                prep_boot_part_uuid=None)
            boot_option_mock.assert_called_once_with(task.node)
            prepare_instance_mock.assert_called_once_with(task.driver.boot,
                                                          task)
            self.assertFalse(failed_state_mock.called)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    def test_prepare_instance_to_boot_localboot_prep_partition(
            self, configure_mock, boot_option_mock,
            prepare_instance_mock, failed_state_mock):
        boot_option_mock.return_value = 'local'
        prepare_instance_mock.return_value = None
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        root_uuid = 'root_uuid'
        efi_system_part_uuid = 'efi_sys_uuid'
        prep_boot_part_uuid = 'prep_boot_part_uuid'
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.prepare_instance_to_boot(task, root_uuid,
                                                 efi_system_part_uuid,
                                                 prep_boot_part_uuid)
            configure_mock.assert_called_once_with(
                self.deploy, task,
                root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid,
                prep_boot_part_uuid=prep_boot_part_uuid)
            boot_option_mock.assert_called_once_with(task.node)
            prepare_instance_mock.assert_called_once_with(task.driver.boot,
                                                          task)
            self.assertFalse(failed_state_mock.called)

    @mock.patch.object(deploy_utils, 'set_failed_state', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_instance', autospec=True)
    @mock.patch.object(deploy_utils, 'get_boot_option', autospec=True)
    @mock.patch.object(agent_base.AgentDeployMixin,
                       'configure_local_boot', autospec=True)
    def test_prepare_instance_to_boot_configure_fails(self, configure_mock,
                                                      boot_option_mock,
                                                      prepare_mock,
                                                      failed_state_mock):
        boot_option_mock.return_value = 'local'
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        root_uuid = 'root_uuid'
        efi_system_part_uuid = 'efi_sys_uuid'
        reason = 'reason'
        configure_mock.side_effect = (
            exception.InstanceDeployFailure(reason=reason))
        prepare_mock.side_effect = (
            exception.InstanceDeployFailure(reason=reason))

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              self.deploy.prepare_instance_to_boot, task,
                              root_uuid, efi_system_part_uuid)
            configure_mock.assert_called_once_with(
                self.deploy, task,
                root_uuid=root_uuid,
                efi_system_part_uuid=efi_system_part_uuid,
                prep_boot_part_uuid=None)
            boot_option_mock.assert_called_once_with(task.node)
            self.assertFalse(prepare_mock.called)
            self.assertFalse(failed_state_mock.called)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning(self, status_mock, notify_mock):
        # Test a successful execute clean step on the agent
        self.node.clean_step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'erase_devices',
            'reboot_requested': False
        }
        self.node.save()
        status_mock.return_value = [{
            'command_status': 'SUCCEEDED',
            'command_name': 'execute_clean_step',
            'command_result': {
                'clean_step': self.node.clean_step
            }
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            notify_mock.assert_called_once_with(task, 'clean')

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test__post_step_reboot(self, mock_reboot, mock_prepare,
                               mock_build_opt):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            i_info = task.node.driver_internal_info
            i_info['agent_secret_token'] = 'magicvalue01'
            task.node.driver_internal_info = i_info
            agent_base._post_step_reboot(task, 'clean')
            self.assertTrue(mock_build_opt.called)
            self.assertTrue(mock_prepare.called)
            mock_reboot.assert_called_once_with(task, states.REBOOT)
            self.assertTrue(task.node.driver_internal_info['cleaning_reboot'])
            self.assertNotIn('agent_secret_token',
                             task.node.driver_internal_info)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test__post_step_reboot_deploy(self, mock_reboot, mock_prepare,
                                      mock_build_opt):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            i_info = task.node.driver_internal_info
            i_info['agent_secret_token'] = 'magicvalue01'
            task.node.driver_internal_info = i_info
            agent_base._post_step_reboot(task, 'deploy')
            self.assertTrue(mock_build_opt.called)
            self.assertTrue(mock_prepare.called)
            mock_reboot.assert_called_once_with(task, states.REBOOT)
            self.assertTrue(
                task.node.driver_internal_info['deployment_reboot'])
            self.assertNotIn('agent_secret_token',
                             task.node.driver_internal_info)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test__post_step_reboot_pregenerated_token(
            self, mock_reboot, mock_prepare, mock_build_opt):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            i_info = task.node.driver_internal_info
            i_info['agent_secret_token'] = 'magicvalue01'
            i_info['agent_secret_token_pregenerated'] = True
            task.node.driver_internal_info = i_info
            agent_base._post_step_reboot(task, 'clean')
            self.assertTrue(mock_build_opt.called)
            self.assertTrue(mock_prepare.called)
            mock_reboot.assert_called_once_with(task, states.REBOOT)
            self.assertIn('agent_secret_token',
                          task.node.driver_internal_info)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test__post_step_reboot_fail(self, mock_reboot, mock_handler,
                                    mock_prepare, mock_build_opt):
        mock_reboot.side_effect = RuntimeError("broken")

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            agent_base._post_step_reboot(task, 'clean')
            mock_reboot.assert_called_once_with(task, states.REBOOT)
            mock_handler.assert_called_once_with(task, mock.ANY,
                                                 traceback=True)
            self.assertNotIn('cleaning_reboot',
                             task.node.driver_internal_info)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'deploying_error_handler', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    def test__post_step_reboot_fail_deploy(self, mock_reboot, mock_handler,
                                           mock_prepare, mock_build_opt):
        mock_reboot.side_effect = RuntimeError("broken")

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            agent_base._post_step_reboot(task, 'deploy')
            mock_reboot.assert_called_once_with(task, states.REBOOT)
            mock_handler.assert_called_once_with(task, mock.ANY,
                                                 traceback=True)
            self.assertNotIn('deployment_reboot',
                             task.node.driver_internal_info)

    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(pxe.PXEBoot, 'prepare_ramdisk', spec_set=True,
                       autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_reboot(
            self, status_mock, reboot_mock, mock_prepare, mock_build_opt):
        # Test a successful execute clean step on the agent, with reboot
        self.node.clean_step = {
            'priority': 42,
            'interface': 'deploy',
            'step': 'reboot_me_afterwards',
            'reboot_requested': True
        }
        self.node.save()
        status_mock.return_value = [{
            'command_status': 'SUCCEEDED',
            'command_name': 'execute_clean_step',
            'command_result': {
                'clean_step': self.node.clean_step
            }
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            reboot_mock.assert_called_once_with(task, states.REBOOT)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_after_reboot(self, status_mock, notify_mock):
        # Test a successful execute clean step on the agent, with reboot
        self.node.clean_step = {
            'priority': 42,
            'interface': 'deploy',
            'step': 'reboot_me_afterwards',
            'reboot_requested': True
        }
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['cleaning_reboot'] = True
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        # Represents a freshly booted agent with no commands
        status_mock.return_value = []

        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            notify_mock.assert_called_once_with(task, 'clean')
            self.assertNotIn('cleaning_reboot',
                             task.node.driver_internal_info)

    @mock.patch.object(agent_base,
                       '_get_post_step_hook', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_with_hook(
            self, status_mock, notify_mock, get_hook_mock):
        self.node.clean_step = {
            'priority': 10,
            'interface': 'raid',
            'step': 'create_configuration',
        }
        self.node.save()
        command_status = {
            'command_status': 'SUCCEEDED',
            'command_name': 'execute_clean_step',
            'command_result': {'clean_step': self.node.clean_step}}
        status_mock.return_value = [command_status]
        hook_mock = mock.MagicMock(spec=types.FunctionType, __name__='foo')
        get_hook_mock.return_value = hook_mock
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)

            get_hook_mock.assert_called_once_with(task.node, 'clean')
            hook_mock.assert_called_once_with(task, command_status)
            notify_mock.assert_called_once_with(task, 'clean')

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_base,
                       '_get_post_step_hook', autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_with_hook_fails(
            self, status_mock, error_handler_mock, get_hook_mock,
            notify_mock, collect_logs_mock):
        self.node.clean_step = {
            'priority': 10,
            'interface': 'raid',
            'step': 'create_configuration',
        }
        self.node.save()
        command_status = {
            'command_status': 'SUCCEEDED',
            'command_name': 'execute_clean_step',
            'command_result': {'clean_step': self.node.clean_step}}
        status_mock.return_value = [command_status]
        hook_mock = mock.MagicMock(spec=types.FunctionType, __name__='foo')
        hook_mock.side_effect = RuntimeError('error')
        get_hook_mock.return_value = hook_mock
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)

            get_hook_mock.assert_called_once_with(task.node, 'clean')
            hook_mock.assert_called_once_with(task, command_status)
            error_handler_mock.assert_called_once_with(task, mock.ANY,
                                                       traceback=True)
            self.assertFalse(notify_mock.called)
            collect_logs_mock.assert_called_once_with(task.node,
                                                      label='cleaning')

    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_old_command(self, status_mock, notify_mock):
        # Test when a second execute_clean_step happens to the agent, but
        # the new step hasn't started yet.
        self.node.clean_step = {
            'priority': 10,
            'interface': 'deploy',
            'step': 'erase_devices',
            'reboot_requested': False
        }
        self.node.save()
        status_mock.return_value = [{
            'command_status': 'SUCCEEDED',
            'command_name': 'execute_clean_step',
            'command_result': {
                'priority': 20,
                'interface': 'deploy',
                'step': 'update_firmware',
                'reboot_requested': False
            }
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            self.assertFalse(notify_mock.called)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_running(self, status_mock, notify_mock):
        # Test that no action is taken while a clean step is executing
        status_mock.return_value = [{
            'command_status': 'RUNNING',
            'command_name': 'execute_clean_step',
            'command_result': None
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            self.assertFalse(notify_mock.called)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_no_step_running(self, status_mock, notify_mock):
        status_mock.return_value = [{
            'command_status': 'SUCCEEDED',
            'command_name': 'get_clean_steps',
            'command_result': []
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            notify_mock.assert_called_once_with(task, 'clean')

    @mock.patch.object(driver_utils, 'collect_ramdisk_logs', autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_fail(self, status_mock, error_mock,
                                    collect_logs_mock):
        # Test that a failure puts the node in CLEANFAIL
        status_mock.return_value = [{
            'command_status': 'FAILED',
            'command_name': 'execute_clean_step',
            'command_result': {}
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            task.node.clean_step = {
                'step': 'erase_devices',
                'interface': 'deploy',
            }
            self.deploy.continue_cleaning(task)
            error_mock.assert_called_once_with(task, mock.ANY, traceback=False)
            collect_logs_mock.assert_called_once_with(task.node,
                                                      label='cleaning')

    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_base.AgentBaseMixin, 'refresh_steps',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def _test_continue_cleaning_clean_version_mismatch(
            self, status_mock, refresh_steps_mock, notify_mock, steps_mock,
            manual=False):
        status_mock.return_value = [{
            'command_status': 'CLEAN_VERSION_MISMATCH',
            'command_name': 'execute_clean_step',
        }]
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        self.node.provision_state = states.CLEANWAIT
        self.node.target_provision_state = tgt_prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            notify_mock.assert_called_once_with(task, 'clean')
            refresh_steps_mock.assert_called_once_with(mock.ANY, task, 'clean')
            if manual:
                self.assertFalse(
                    task.node.driver_internal_info['skip_current_clean_step'])
                self.assertFalse(steps_mock.called)
            else:
                steps_mock.assert_called_once_with(task)
                self.assertNotIn('skip_current_clean_step',
                                 task.node.driver_internal_info)

    def test_continue_cleaning_automated_clean_version_mismatch(self):
        self._test_continue_cleaning_clean_version_mismatch()

    def test_continue_cleaning_manual_clean_version_mismatch(self):
        self._test_continue_cleaning_clean_version_mismatch(manual=True)

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_cleaning_steps',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    @mock.patch.object(agent_base.AgentBaseMixin, 'refresh_steps',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_clean_version_mismatch_fail(
            self, status_mock, refresh_steps_mock, notify_mock, steps_mock,
            error_mock, manual=False):
        status_mock.return_value = [{
            'command_status': 'CLEAN_VERSION_MISMATCH',
            'command_name': 'execute_clean_step',
            'command_result': {'hardware_manager_version': {'Generic': '1'}}
        }]
        refresh_steps_mock.side_effect = exception.NodeCleaningFailure("boo")
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        self.node.provision_state = states.CLEANWAIT
        self.node.target_provision_state = tgt_prov_state
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)

            status_mock.assert_called_once_with(mock.ANY, task.node)
            refresh_steps_mock.assert_called_once_with(mock.ANY, task, 'clean')
            error_mock.assert_called_once_with(task, mock.ANY, traceback=True)
            self.assertFalse(notify_mock.called)
            self.assertFalse(steps_mock.called)

    @mock.patch.object(manager_utils, 'cleaning_error_handler', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    def test_continue_cleaning_unknown(self, status_mock, error_mock):
        # Test that unknown commands are treated as failures
        status_mock.return_value = [{
            'command_status': 'UNKNOWN',
            'command_name': 'execute_clean_step',
            'command_result': {}
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.deploy.continue_cleaning(task)
            error_mock.assert_called_once_with(task, mock.ANY, traceback=False)

    def _test_clean_step_hook(self):
        """Helper method for unit tests related to clean step hooks."""
        some_function_mock = mock.MagicMock()

        @agent_base.post_clean_step_hook(
            interface='raid', step='delete_configuration')
        @agent_base.post_clean_step_hook(
            interface='raid', step='create_configuration')
        def hook_method():
            some_function_mock('some-arguments')

        return hook_method

    @mock.patch.object(agent_base, '_POST_STEP_HOOKS',
                       {'clean': {}, 'deploy': {}})
    def test_post_clean_step_hook(self):
        # This unit test makes sure that hook methods are registered
        # properly and entries are made in
        # agent_base.POST_CLEAN_STEP_HOOKS
        hook_method = self._test_clean_step_hook()
        hooks = agent_base._POST_STEP_HOOKS['clean']
        self.assertEqual(hook_method, hooks['raid']['create_configuration'])
        self.assertEqual(hook_method, hooks['raid']['delete_configuration'])

    @mock.patch.object(agent_base, '_POST_STEP_HOOKS',
                       {'clean': {}, 'deploy': {}})
    def test__get_post_step_hook(self):
        # Check if agent_base._get_post_step_hook can get
        # clean step for which hook is registered.
        hook_method = self._test_clean_step_hook()
        self.node.clean_step = {'step': 'create_configuration',
                                'interface': 'raid'}
        self.node.save()
        hook_returned = agent_base._get_post_step_hook(self.node, 'clean')
        self.assertEqual(hook_method, hook_returned)

    @mock.patch.object(agent_base, '_POST_STEP_HOOKS',
                       {'clean': {}, 'deploy': {}})
    def test__get_post_step_hook_no_hook_registered(self):
        # Make sure agent_base._get_post_step_hook returns
        # None when no clean step hook is registered for the clean step.
        self._test_clean_step_hook()
        self.node.clean_step = {'step': 'some-clean-step',
                                'interface': 'some-other-interface'}
        self.node.save()
        hook_returned = agent_base._get_post_step_hook(self.node, 'clean')
        self.assertIsNone(hook_returned)


class TestRefreshCleanSteps(AgentDeployMixinBaseTest):

    def setUp(self):
        super(TestRefreshCleanSteps, self).setUp()
        self.deploy = agent_base.AgentBaseMixin()
        self.node.driver_internal_info['agent_url'] = 'http://127.0.0.1:9999'
        self.ports = [object_utils.create_test_port(self.context,
                                                    node_id=self.node.id)]

        self.clean_steps = {
            'hardware_manager_version': '1',
            'clean_steps': {
                'GenericHardwareManager': [
                    {'interface': 'deploy',
                     'step': 'erase_devices',
                     'priority': 20},
                ],
                'SpecificHardwareManager': [
                    {'interface': 'deploy',
                     'step': 'update_firmware',
                     'priority': 30},
                    {'interface': 'raid',
                     'step': 'create_configuration',
                     'priority': 10},
                ]
            }
        }
        # NOTE(dtantsur): deploy steps are structurally identical to clean
        # steps, reusing self.clean_steps for simplicity
        self.deploy_steps = {
            'hardware_manager_version': '1',
            'deploy_steps': self.clean_steps['clean_steps'],
        }

    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_refresh_steps(self, client_mock):
        client_mock.return_value = {
            'command_result': self.clean_steps}

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.refresh_steps(task, 'clean')

            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                task.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])
            self.assertIn('agent_cached_clean_steps_refreshed',
                          task.node.driver_internal_info)
            steps = task.node.driver_internal_info['agent_cached_clean_steps']
            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertEqual(2, len(steps))
            self.assertIn(self.clean_steps['clean_steps'][
                'GenericHardwareManager'][0], steps['deploy'])
            self.assertIn(self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][0], steps['deploy'])
            self.assertEqual([self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][1]], steps['raid'])

    @mock.patch.object(agent_client.AgentClient, 'get_deploy_steps',
                       autospec=True)
    def test_refresh_steps_deploy(self, client_mock):
        client_mock.return_value = {
            'command_result': self.deploy_steps}

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.deploy.refresh_steps(task, 'deploy')

            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                task.ports)
            self.assertEqual('1', task.node.driver_internal_info[
                'hardware_manager_version'])
            self.assertIn('agent_cached_deploy_steps_refreshed',
                          task.node.driver_internal_info)
            steps = task.node.driver_internal_info['agent_cached_deploy_steps']
            self.assertEqual({'deploy', 'raid'}, set(steps))
            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertIn(self.clean_steps['clean_steps'][
                'GenericHardwareManager'][0], steps['deploy'])
            self.assertIn(self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][0], steps['deploy'])
            self.assertEqual([self.clean_steps['clean_steps'][
                'SpecificHardwareManager'][1]], steps['raid'])

    @mock.patch.object(agent_base.LOG, 'warning', autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'get_deploy_steps',
                       autospec=True)
    def test_refresh_steps_busy(self, client_mock, log_mock):
        client_mock.side_effect = exception.AgentInProgress(
            node="node", error='Agent is busy : maximum meowing')

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            log_mock.reset_mock()
            self.deploy.refresh_steps(task, 'deploy')

            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                task.ports)
            self.assertNotIn('agent_cached_deploy_steps_refreshed',
                             task.node.driver_internal_info)
            self.assertIsNone(task.node.driver_internal_info.get(
                'agent_cached_deploy_steps'))
            log_mock.assert_not_called()

    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_refresh_steps_missing_steps(self, client_mock):
        del self.clean_steps['clean_steps']
        client_mock.return_value = {
            'command_result': self.clean_steps}

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaisesRegex(exception.NodeCleaningFailure,
                                   'invalid result',
                                   self.deploy.refresh_steps,
                                   task, 'clean')
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                task.ports)

    @mock.patch.object(agent_client.AgentClient, 'get_clean_steps',
                       autospec=True)
    def test_refresh_steps_missing_interface(self, client_mock):
        step = self.clean_steps['clean_steps']['SpecificHardwareManager'][1]
        del step['interface']
        client_mock.return_value = {
            'command_result': self.clean_steps}

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertRaisesRegex(exception.NodeCleaningFailure,
                                   'invalid clean step',
                                   self.deploy.refresh_steps,
                                   task, 'clean')
            client_mock.assert_called_once_with(mock.ANY, task.node,
                                                task.ports)


class StepMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(StepMethodsTestCase, self).setUp()

        self.clean_steps = {
            'deploy': [
                {'interface': 'deploy',
                 'step': 'erase_devices',
                 'priority': 20},
                {'interface': 'deploy',
                 'step': 'update_firmware',
                 'priority': 30}
            ],
            'raid': [
                {'interface': 'raid',
                 'step': 'create_configuration',
                 'priority': 10}
            ]
        }
        n = {'boot_interface': 'pxe',
             'deploy_interface': 'direct',
             'driver_internal_info': {
                 'agent_cached_clean_steps': self.clean_steps}}
        self.node = object_utils.create_test_node(self.context, **n)
        self.ports = [object_utils.create_test_port(self.context,
                                                    node_id=self.node.id)]
        self.deploy = FakeAgentDeploy()

    def test_agent_get_steps(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.get_steps(task, 'clean')

            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertThat(response, matchers.HasLength(3))
            self.assertIn(self.clean_steps['deploy'][0], response)
            self.assertIn(self.clean_steps['deploy'][1], response)
            self.assertIn(self.clean_steps['raid'][0], response)

    def test_agent_get_steps_deploy(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            task.node.driver_internal_info = {
                'agent_cached_deploy_steps': self.clean_steps
            }
            response = agent_base.get_steps(task, 'deploy')

            # Since steps are returned in dicts, they have non-deterministic
            # ordering
            self.assertThat(response, matchers.HasLength(3))
            self.assertIn(self.clean_steps['deploy'][0], response)
            self.assertIn(self.clean_steps['deploy'][1], response)
            self.assertIn(self.clean_steps['raid'][0], response)

    def test_get_steps_custom_interface(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.get_steps(task, 'clean', interface='raid')
            self.assertThat(response, matchers.HasLength(1))
            self.assertEqual(self.clean_steps['raid'], response)

    def test_get_steps_override_priorities(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            new_priorities = {'create_configuration': 42}
            response = agent_base.get_steps(
                task, 'clean', interface='raid',
                override_priorities=new_priorities)
            self.assertEqual(42, response[0]['priority'])

    def test_get_steps_override_priorities_none(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            # this is simulating the default value of a configuration option
            new_priorities = {'create_configuration': None}
            response = agent_base.get_steps(
                task, 'clean', interface='raid',
                override_priorities=new_priorities)
            self.assertEqual(10, response[0]['priority'])

    def test_get_steps_missing_steps(self):
        info = self.node.driver_internal_info
        del info['agent_cached_clean_steps']
        self.node.driver_internal_info = info
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertEqual([], agent_base.get_steps(task, 'clean'))

    def test_find_step(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            step = agent_base.find_step(task, 'clean', 'deploy',
                                        'erase_devices')
            self.assertEqual(self.clean_steps['deploy'][0], step)

    def test_find_step_not_found(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertIsNone(agent_base.find_step(
                task, 'clean', 'non-deploy', 'erase_devices'))
            self.assertIsNone(agent_base.find_step(
                task, 'clean', 'deploy', 'something_else'))
            self.assertIsNone(agent_base.find_step(
                task, 'deploy', 'deploy', 'erase_devices'))

    def test_get_deploy_steps(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            task.node.driver_internal_info = {
                'agent_cached_deploy_steps': self.clean_steps
            }
            steps = self.deploy.get_deploy_steps(task)
            # 2 in-band steps + 3 out-of-band
            expected = [
                {'step': 'deploy', 'priority': 100, 'argsinfo': None,
                 'interface': 'deploy'},
                {'step': 'tear_down_agent', 'priority': 40, 'argsinfo': None,
                 'interface': 'deploy'},
                {'step': 'switch_to_tenant_network', 'priority': 30,
                 'argsinfo': None, 'interface': 'deploy'},
                {'step': 'boot_instance', 'priority': 20, 'argsinfo': None,
                 'interface': 'deploy'},
            ] + self.clean_steps['deploy']
            self.assertCountEqual(expected, steps)

    def test_get_deploy_steps_only_oob(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            steps = self.deploy.get_deploy_steps(task)
            # three base out-of-band steps
            expected = [
                {'step': 'deploy', 'priority': 100, 'argsinfo': None,
                 'interface': 'deploy'},
                {'step': 'tear_down_agent', 'priority': 40, 'argsinfo': None,
                 'interface': 'deploy'},
                {'step': 'switch_to_tenant_network', 'priority': 30,
                 'argsinfo': None, 'interface': 'deploy'},
                {'step': 'boot_instance', 'priority': 20, 'argsinfo': None,
                 'interface': 'deploy'},
            ]
            self.assertCountEqual(expected, steps)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'SUCCEEDED'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.execute_step(
                task, self.clean_steps['deploy'][0], 'clean')
            self.assertEqual(states.CLEANWAIT, response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_deploy_step',
                       autospec=True)
    def test_execute_deploy_step(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'SUCCEEDED'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.execute_step(
                task, self.clean_steps['deploy'][0], 'deploy')
            self.assertEqual(states.DEPLOYWAIT, response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step_running(self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'RUNNING'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.execute_step(
                task, self.clean_steps['deploy'][0], 'clean')
            self.assertEqual(states.CLEANWAIT, response)

    @mock.patch('ironic.objects.Port.list_by_node_id',
                spec_set=types.FunctionType)
    @mock.patch.object(agent_client.AgentClient, 'execute_clean_step',
                       autospec=True)
    def test_execute_clean_step_version_mismatch(
            self, client_mock, list_ports_mock):
        client_mock.return_value = {
            'command_status': 'RUNNING'}
        list_ports_mock.return_value = self.ports

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            response = agent_base.execute_step(
                task, self.clean_steps['deploy'][0], 'clean')
            self.assertEqual(states.CLEANWAIT, response)
