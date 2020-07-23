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

import datetime
from unittest import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import agent_power
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as object_utils


@mock.patch('time.sleep', lambda _sec: None)
class AgentPowerTest(db_base.DbTestCase):

    def setUp(self):
        super(AgentPowerTest, self).setUp()
        self.config(fast_track=True, group='deploy')
        self.power = agent_power.AgentPower()
        dii = {
            'agent_last_heartbeat': datetime.datetime.now().strftime(
                "%Y-%m-%dT%H:%M:%S.%f"),
            'deployment_reboot': True,
            'agent_url': 'http://url',
            'agent_secret_token': 'very secret',
        }
        self.node = object_utils.create_test_node(
            self.context, driver_internal_info=dii,
            provision_state=states.DEPLOYING)
        self.task = mock.Mock(spec=task_manager.TaskManager, node=self.node)

    def test_basics(self):
        self.assertEqual({}, self.power.get_properties())
        self.assertFalse(self.power.supports_power_sync(self.task))
        self.assertEqual([states.REBOOT, states.SOFT_REBOOT],
                         self.power.get_supported_power_states(self.task))

    def test_validate(self):
        self.power.validate(self.task)

    def test_validate_fails(self):
        self.node.driver_internal_info['agent_last_heartbeat'] = \
            datetime.datetime(2010, 7, 19).strftime(
                "%Y-%m-%dT%H:%M:%S.%f")
        self.assertRaises(exception.InvalidParameterValue,
                          self.power.validate, self.task)

        del self.node.driver_internal_info['agent_last_heartbeat']
        self.assertRaises(exception.InvalidParameterValue,
                          self.power.validate, self.task)

    def test_get_power_state(self):
        self.assertEqual(states.POWER_ON,
                         self.power.get_power_state(self.task))

    def test_get_power_state_unknown(self):
        self.node.driver_internal_info['agent_last_heartbeat'] = \
            datetime.datetime(2010, 7, 19).strftime(
                "%Y-%m-%dT%H:%M:%S.%f")
        self.assertIsNone(self.power.get_power_state(self.task))

        del self.node.driver_internal_info['agent_last_heartbeat']
        self.assertIsNone(self.power.get_power_state(self.task))

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'reboot', autospec=True)
    def test_reboot(self, mock_reboot, mock_commands):
        mock_commands.side_effect = [
            [{'command_name': 'run_image', 'command_status': 'RUNNING'}],
            exception.AgentConnectionFailed,
            exception.AgentConnectionFailed,
            [{'command_name': 'get_deploy_steps', 'command_status': 'RUNNING'}]
        ]
        with task_manager.acquire(self.context, self.node.id) as task:
            # Save the node since the upgrade_lock call changes it
            node = task.node
            self.power.reboot(task)
            mock_reboot.assert_called_once_with(self.power._client, node)
            mock_commands.assert_called_with(self.power._client, node,
                                             retry_connection=False,
                                             expect_errors=True)
            self.assertEqual(4, mock_commands.call_count)

            node.refresh()
            self.assertNotIn('agent_secret_token', node.driver_internal_info)
            self.assertNotIn('agent_url', node.driver_internal_info)

    @mock.patch.object(agent_client.AgentClient, 'get_commands_status',
                       autospec=True)
    @mock.patch.object(agent_client.AgentClient, 'reboot', autospec=True)
    def test_reboot_timeout(self, mock_reboot, mock_commands):
        mock_commands.side_effect = exception.AgentConnectionFailed
        with task_manager.acquire(self.context, self.node.id) as task:
            node = task.node
            self.assertRaisesRegex(exception.PowerStateFailure,
                                   'Agent failed to come back',
                                   self.power.reboot, task, timeout=0.001)
            mock_commands.assert_called_with(self.power._client, node,
                                             retry_connection=False,
                                             expect_errors=True)

    @mock.patch.object(agent_client.AgentClient, 'reboot', autospec=True)
    def test_reboot_another_state(self, mock_reboot):
        with task_manager.acquire(self.context, self.node.id) as task:
            task.node.provision_state = states.DEPLOYWAIT
            self.power.reboot(task)
            mock_reboot.assert_called_once_with(self.power._client, task.node)

    @mock.patch.object(agent_client.AgentClient, 'reboot', autospec=True)
    def test_reboot_into_instance(self, mock_reboot):
        with task_manager.acquire(self.context, self.node.id) as task:
            del task.node.driver_internal_info['deployment_reboot']
            self.power.reboot(task)
            mock_reboot.assert_called_once_with(self.power._client, task.node)
