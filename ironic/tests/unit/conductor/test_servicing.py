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

"""Tests for service bits."""

from unittest import mock

from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.common import faults
from ironic.common import states
from ironic.conductor import servicing
from ironic.conductor import steps as conductor_steps
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.drivers.modules import fake
from ironic.drivers.modules.network import flat as n_flat
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF

# NOTE(TheJulia): This file is based upon test_cleaning.py with logic
# for automated cleaning out and switched over for the service steps
# framework. It *largely* exists to ensure we have similar consistency
# between the frameworks, similar was done for deploy steps in the past.


class DoNodeServiceTestCase(db_base.DbTestCase):
    def setUp(self):
        super(DoNodeServiceTestCase, self).setUp()
        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_magic = {
            'step': 'magic_firmware', 'priority': 10, 'interface': 'deploy'}
        self.next_service_step_index = 1
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy'}
        self.service_steps = [self.deploy_update,
                              self.power_update,
                              self.deploy_magic]

    def __do_node_service_validate_fail(self, mock_validate,
                                        service_steps=None):
        tgt_prov_state = states.ACTIVE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps)
        node.refresh()
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertFalse(node.maintenance)
        self.assertIsNone(node.fault)
        mock_validate.assert_called_once_with(mock.ANY, mock.ANY)

    def __do_node_service_validate_fail_invalid(self, mock_validate,
                                                service_steps=None):
        # InvalidParameterValue should cause node to go to SERVICEFAIL
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        self.__do_node_service_validate_fail(mock_validate,
                                             service_steps=service_steps)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_service_automated_power_validate_fail(self,
                                                            mock_validate):
        self.__do_node_service_validate_fail_invalid(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def test__do_node_service_manual_power_validate_fail(self, mock_validate):
        self.__do_node_service_validate_fail_invalid(mock_validate,
                                                     service_steps=[])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_service_automated_network_validate_fail(self,
                                                              mock_validate):
        self.__do_node_service_validate_fail_invalid(mock_validate)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_service_manual_network_validate_fail(self,
                                                           mock_validate):
        self.__do_node_service_validate_fail_invalid(mock_validate,
                                                     service_steps=[])

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    def test__do_node_service_network_error_fail(self, mock_validate):
        # NetworkError should cause node to go to CLEANFAIL
        mock_validate.side_effect = exception.NetworkError()
        self.__do_node_service_validate_fail(mock_validate)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_service',
                autospec=True)
    def test__do_node_service_prepare_service_fail(self, mock_prep,
                                                   mock_validate,
                                                   service_steps=None):
        # Exception from task.driver.deploy.prepare_cleaning should cause node
        # to go to SERVICEFAIL
        mock_prep.side_effect = exception.InvalidParameterValue('error')
        tgt_prov_state = states.ACTIVE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps)
            node.refresh()
            self.assertEqual(states.SERVICEFAIL, node.provision_state)
            self.assertEqual(tgt_prov_state, node.target_provision_state)
            mock_prep.assert_called_once_with(mock.ANY, task)
            mock_validate.assert_called_once_with(mock.ANY, task)
            self.assertFalse(node.maintenance)
            self.assertIsNone(node.fault)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_service',
                autospec=True)
    def test__do_node_service_prepare_service_wait(self, mock_prep,
                                                   mock_validate):
        service_steps = [
            {'step': 'trigger_servicewait', 'priority': 10,
             'interface': 'vendor'}
        ]

        mock_prep.return_value = states.SERVICEWAIT
        tgt_prov_state = states.ACTIVE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            vendor_interface='fake')
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps)
        node.refresh()
        self.assertEqual(states.SERVICEWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_prep.assert_called_once_with(mock.ANY, mock.ANY)
        mock_validate.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_service',
                autospec=True)
    def test__do_node_service_prepare_service_active(self, mock_prep,
                                                     mock_validate):
        service_steps = [
            {'step': 'log_passthrough', 'priority': 10, 'interface': 'vendor'}
        ]

        mock_prep.return_value = states.SERVICEWAIT
        tgt_prov_state = states.ACTIVE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            vendor_interface='fake')
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps,
                                      disable_ramdisk=True)
        # Validate we went back to active, and did not trigger a ramdisk.
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        mock_prep.assert_not_called()
        mock_validate.assert_not_called()

    @mock.patch.object(n_flat.FlatNetwork, 'validate', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_service_steps',
                       autospec=True)
    def __do_node_service_steps_fail(self, mock_steps, mock_validate,
                                     service_steps=None, invalid_exc=True):
        if invalid_exc:
            mock_steps.side_effect = exception.InvalidParameterValue('invalid')
        else:
            mock_steps.side_effect = exception.NodeCleaningFailure('failure')
        tgt_prov_state = states.ACTIVE
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid(),
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps)
            mock_validate.assert_called_once_with(mock.ANY, task)
        node.refresh()
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_steps.assert_called_once_with(mock.ANY, disable_ramdisk=False)
        self.assertFalse(node.maintenance)
        self.assertIsNone(node.fault)

    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch.object(n_flat.FlatNetwork, 'validate', autospec=True)
    @mock.patch.object(conductor_steps, 'set_node_service_steps',
                       autospec=True)
    def test_do_node_service_steps_fail_poweroff(self, mock_steps,
                                                 mock_validate,
                                                 mock_power,
                                                 service_steps=None,
                                                 invalid_exc=True):
        if invalid_exc:
            mock_steps.side_effect = exception.InvalidParameterValue('invalid')
        else:
            mock_steps.side_effect = exception.NodeCleaningFailure('failure')
        tgt_prov_state = states.ACTIVE
        self.config(poweroff_in_cleanfail=True, group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid(),
            provision_state=states.SERVICING,
            power_state=states.POWER_ON,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps)
            mock_validate.assert_called_once_with(mock.ANY, task)
        node.refresh()
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_steps.assert_called_once_with(mock.ANY, disable_ramdisk=False)
        self.assertFalse(mock_power.called)

    def test__do_node_service_steps_fail(self):
        for invalid in (True, False):
            self.__do_node_service_steps_fail(service_steps=[self.deploy_raid],
                                              invalid_exc=invalid)

    @mock.patch.object(conductor_steps, 'set_node_service_steps',
                       autospec=True)
    @mock.patch.object(servicing, 'do_next_service_step', autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    def __do_node_service(self, mock_power_valid, mock_network_valid,
                          mock_next_step, mock_steps, service_steps=None,
                          disable_ramdisk=False):
        tgt_prov_state = states.ACTIVE

        if not service_steps:
            service_steps = self.service_steps

        def set_steps(task, disable_ramdisk=None):
            dii = task.node.driver_internal_info
            dii['service_steps'] = service_steps
            task.node.driver_internal_info = dii
            task.node.save()

        mock_steps.side_effect = set_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            power_state=states.POWER_OFF,
            driver_internal_info={'agent_secret_token': 'old'})

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_node_service(task, service_steps=service_steps,
                                      disable_ramdisk=disable_ramdisk)

            node.refresh()

            mock_power_valid.assert_called_once_with(mock.ANY, task)
            if disable_ramdisk:
                mock_network_valid.assert_not_called()
            else:
                mock_network_valid.assert_called_once_with(mock.ANY, task)

            mock_next_step.assert_called_once_with(
                task, 0, disable_ramdisk=disable_ramdisk)
            mock_steps.assert_called_once_with(
                task, disable_ramdisk=disable_ramdisk)
            if service_steps:
                self.assertEqual(service_steps,
                                 node.driver_internal_info['service_steps'])
            self.assertFalse(node.maintenance)
            self.assertNotIn('agent_secret_token', node.driver_internal_info)

        # Check that state didn't change
        self.assertEqual(states.SERVICING, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)

    def test__do_node_service(self):
        self.__do_node_service()

    def test__do_node_service_disable_ramdisk(self):
        self.__do_node_service(service_steps=[self.deploy_raid],
                               disable_ramdisk=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def _do_next_service_step_first_step_async(self, return_state,
                                               mock_execute,
                                               service_steps=None):
        # Execute the first async clean step on a node
        driver_internal_info = {'service_step_index': None}
        tgt_prov_state = states.ACTIVE
        if service_steps:
            driver_internal_info['service_steps'] = service_steps
        else:
            driver_internal_info['service_steps'] = self.service_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=driver_internal_info,
            clean_step={})
        mock_execute.return_value = return_state
        expected_first_step = node.driver_internal_info['service_steps'][0]

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()
        self.assertEqual(states.SERVICEWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(expected_first_step, node.service_step)
        self.assertEqual(0, node.driver_internal_info['service_step_index'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, expected_first_step)

    def test_do_next_service_step_automated_first_step_async(self):
        self._do_next_service_step_first_step_async(states.SERVICEWAIT)

    def test_do_next_service_step_manual_first_step_async(self):
        self._do_next_service_step_first_step_async(
            states.SERVICEWAIT, service_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    def _do_next_clean_step_continue_from_last_cleaning(self, return_state,
                                                        mock_execute,
                                                        manual=False):
        # Resume an in-progress servicing after the first async step
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': 0},
            service_step=self.service_steps[0])
        mock_execute.return_value = return_state

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, self.next_service_step_index)

        node.refresh()

        self.assertEqual(states.SERVICEWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.service_steps[1], node.service_step)
        self.assertEqual(1, node.driver_internal_info['service_step_index'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.service_steps[1])

    def test_do_next_clean_step_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(
            states.SERVICEWAIT)

    def test_do_next_clean_step_manual_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(
            states.SERVICEWAIT, manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def _do_next_service_step_last_step_noop(self, mock_execute,
                                             manual=False):
        # Resume where last_step is the last cleaning step, should be noop
        tgt_prov_state = states.ACTIVE
        info = {'service_steps': self.service_steps,
                'service_step_index': len(self.service_steps) - 1,
                'agent_url': 'test-url',
                'agent_secret_token': 'token'}

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=info,
            service_step=self.service_steps[-1])

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, None)

        node.refresh()

        # Cleaning should be complete without calling additional steps
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['service_steps'])
        self.assertFalse(mock_execute.called)
        self.assertNotIn('agent_url', node.driver_internal_info)
        self.assertNotIn('agent_secret_token',
                         node.driver_internal_info)

    def test__do_next_service_step_automated_last_step_noop(self):
        self._do_next_service_step_last_step_noop()

    def test__do_next_service_step_manual_last_step_noop(self):
        self._do_next_service_step_last_step_noop(manual=True)

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down_service',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def _do_next_service_step_all(self, mock_deploy_execute,
                                  mock_power_execute, mock_tear_down,
                                  mock_collect_logs,
                                  disable_ramdisk=False):
        # Run all steps from start to finish (all synchronous)
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            clean_step={})

        def fake_deploy(conductor_obj, task, step):
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['goober'] = 'test'
            task.node.driver_internal_info = driver_internal_info
            task.node.save()

        mock_deploy_execute.side_effect = fake_deploy
        mock_power_execute.return_value = None

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(
                task, 0, disable_ramdisk=disable_ramdisk)

            mock_power_execute.assert_called_once_with(task.driver.power, task,
                                                       self.service_steps[1])
            mock_deploy_execute.assert_has_calls(
                [mock.call(task.driver.deploy, task, self.service_steps[0]),
                 mock.call(task.driver.deploy, task, self.service_steps[2])])
            if disable_ramdisk:
                mock_tear_down.assert_not_called()
            else:
                mock_tear_down.assert_called_once_with(
                    task.driver.deploy, task)

        node.refresh()

        # Servicing should be complete
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertEqual('test', node.driver_internal_info['goober'])
        self.assertIsNone(node.driver_internal_info['service_steps'])
        self.assertFalse(mock_collect_logs.called)

    def test_do_next_clean_step_all(self):
        self._do_next_service_step_all()

    def test_do_next_clean_step_all_disable_ramdisk(self):
        self._do_next_service_step_all(disable_ramdisk=True)

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_clean_step_collect_logs(self, mock_deploy_execute,
                                             mock_power_execute,
                                             mock_collect_logs):
        CONF.set_override('deploy_logs_collect', 'always', group='agent')
        # Run all steps from start to finish (all synchronous)
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            clean_step={})

        def fake_deploy(conductor_obj, task, step):
            driver_internal_info = task.node.driver_internal_info
            driver_internal_info['goober'] = 'test'
            task.node.driver_internal_info = driver_internal_info
            task.node.save()

        mock_deploy_execute.side_effect = fake_deploy
        mock_power_execute.return_value = None

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()

        # Cleaning should be complete
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertEqual('test', node.driver_internal_info['goober'])
        self.assertIsNone(node.driver_internal_info['service_steps'])
        mock_power_execute.assert_called_once_with(mock.ANY, mock.ANY,
                                                   self.service_steps[1])
        mock_deploy_execute.assert_has_calls(
            [mock.call(mock.ANY, mock.ANY, self.service_steps[0]),
             mock.call(mock.ANY, mock.ANY, self.service_steps[2])])
        mock_collect_logs.assert_called_once_with(mock.ANY, label='service')

    @mock.patch('ironic.drivers.utils.collect_ramdisk_logs', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def _do_next_service_step_execute_fail(self, tear_mock, mock_execute,
                                           mock_collect_logs):
        # When a clean step fails, go to CLEANFAIL
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            clean_step={})
        mock_execute.side_effect = Exception()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)
            tear_mock.assert_called_once_with(task.driver.deploy, task)

        node.refresh()

        # Make sure we go to SERVICEFAIL, clear service_steps
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        self.assertEqual(faults.SERVICE_FAILURE, node.fault)
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.service_steps[0])
        mock_collect_logs.assert_called_once_with(mock.ANY, label='service')

    def test__do_next_clean_step_automated_execute_fail(self):
        self._do_next_service_step_execute_fail()

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_service_step_oob_reboot(self, mock_execute):
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None,
                                  'service_reboot': True},
            service_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()

        # Make sure we go to SERVICEWAIT
        self.assertEqual(states.SERVICEWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.service_steps[0], node.service_step)
        self.assertEqual(0, node.driver_internal_info['service_step_index'])
        self.assertFalse(
            node.driver_internal_info['skip_current_service_step'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.service_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_service_step_agent_busy(self, mock_execute):
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None,
                                  'service_reboot': True},
            service_step={})
        mock_execute.side_effect = exception.AgentInProgress(
            reason='still meowing')
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()
        # Make sure we go to SERVICEWAIT
        self.assertEqual(states.SERVICEWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.service_steps[0], node.service_step)
        self.assertEqual(0, node.driver_internal_info['service_step_index'])
        self.assertFalse(
            node.driver_internal_info['skip_current_service_step'])
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.service_steps[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_service_step_oob_reboot_last_step(self, mock_execute):
        # Resume where last_step is the last service step
        tgt_prov_state = states.ACTIVE
        info = {'service_steps': self.service_steps,
                'service_reboot': True,
                'service_step_index': len(self.service_steps) - 1}

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=info,
            service_step=self.service_steps[-1])

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, None)

        node.refresh()

        # Servicing should be complete without calling additional steps
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertNotIn('service_reboot', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['service_steps'])
        self.assertFalse(mock_execute.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def test_do_next_service_step_oob_reboot_fail(self, tear_mock,
                                                  mock_execute):
        # When a service step fails with no reboot requested go to SERVICEFAIL
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            service_step={})
        mock_execute.side_effect = exception.AgentConnectionFailed(
            reason='failed')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)
            tear_mock.assert_called_once_with(task.driver.deploy, task)

        node.refresh()

        # Make sure we go to SERVICEFAIL, clear service_steps
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertNotIn('skip_current_service_step',
                         node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        mock_execute.assert_called_once_with(
            mock.ANY, mock.ANY, self.service_steps[0])

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def _do_next_service_step_fail_in_tear_down_service(
            self, tear_mock, power_exec_mock, deploy_exec_mock, log_mock):
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            service_step={})

        deploy_exec_mock.return_value = None
        power_exec_mock.return_value = None
        tear_mock.side_effect = Exception('boom')

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()

        # Make sure we go to SERVICEFAIL, clear service_steps
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertEqual(1, tear_mock.call_count)
        self.assertFalse(node.maintenance)  # no step is running
        deploy_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.service_steps[0]),
            mock.call(mock.ANY, mock.ANY, self.service_steps[2]),
        ]
        self.assertEqual(deploy_exec_calls, deploy_exec_mock.call_args_list)

        power_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.service_steps[1]),
        ]
        self.assertEqual(power_exec_calls, power_exec_mock.call_args_list)
        log_mock.error.assert_called_once_with(
            'Failed to tear down from service for node {}, reason: boom'
            .format(node.uuid), exc_info=True)

    def test__do_next_service_step_automated_fail_in_tear_down_service(self):
        self._do_next_service_step_fail_in_tear_down_service()

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def _do_next_service_step_no_steps(self, mock_execute, manual=False):
        for info in ({'service_steps': None, 'service_step_index': None,
                      'agent_url': 'test-url', 'agent_secret_token': 'magic'},
                     {'service_steps': None, 'agent_url': 'test-url',
                      'agent_secret_token': 'it_is_a_kind_of_magic'}):
            # Resume where there are no steps, should be a noop
            tgt_prov_state = states.ACTIVE

            node = obj_utils.create_test_node(
                self.context, driver='fake-hardware',
                uuid=uuidutils.generate_uuid(),
                provision_state=states.SERVICING,
                target_provision_state=tgt_prov_state,
                last_error=None,
                driver_internal_info=info,
                service_step={})

            with task_manager.acquire(
                    self.context, node.uuid, shared=False) as task:
                servicing.do_next_service_step(task, None)

            node.refresh()

            # Cleaning should be complete without calling additional steps
            self.assertEqual(tgt_prov_state, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertEqual({}, node.clean_step)
            self.assertNotIn('service_step_index', node.driver_internal_info)
            self.assertFalse(mock_execute.called)
            self.assertNotIn('agent_url', node.driver_internal_info)
            self.assertNotIn('agent_secret_token',
                             node.driver_internal_info)
            mock_execute.reset_mock()

    def test__do_next_service_step_automated_no_steps(self):
        self._do_next_service_step_no_steps()

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test__do_next_service_step_bad_step_return_value(
            self, deploy_exec_mock, power_exec_mock, manual=False):
        # When a service step fails, go to CLEANFAIL
        tgt_prov_state = states.ACTIVE

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'service_steps': self.service_steps,
                                  'service_step_index': None},
            service_step={})
        deploy_exec_mock.return_value = "foo"

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)

        node.refresh()

        # Make sure we go to SERVICEFAIL, clear service_steps
        self.assertEqual(states.SERVICEFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.service_step)
        self.assertNotIn('service_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)  # the 1st clean step was running
        deploy_exec_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                 self.service_steps[0])
        # Make sure we don't execute any other step and return
        self.assertFalse(power_exec_mock.called)

    def _test_do_next_service_step_handles_hold(self, start_state):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=start_state,
            driver_internal_info={
                'service_steps': [
                    {
                        'step': 'hold',
                        'priority': 10,
                        'interface': 'power'
                    }
                ],
                'service_step_index': None},
            service_step=None)

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            servicing.do_next_service_step(task, 0)
        node.refresh()
        self.assertEqual(states.SERVICEHOLD, node.provision_state)

    def test_do_next_service_step_handles_hold_from_active(self):
        # Start is from the conductor
        self._test_do_next_service_step_handles_hold(states.SERVICING)

    def test_do_next_service_step_handles_hold_from_wait(self):
        # Start is the continuation from a heartbeat.
        self._test_do_next_service_step_handles_hold(states.SERVICEWAIT)

    @mock.patch.object(servicing, 'do_next_service_step', autospec=True)
    def _continue_node_service(self, mock_next_step, skip=True):
        # test that skipping current step mechanism works
        driver_info = {'service_steps': self.service_steps,
                       'service_step_index': 0,
                       'servicing_polling': 'value'}
        if not skip:
            driver_info['skip_current_service_step'] = skip
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=states.ACTIVE,
            driver_internal_info=driver_info,
            service_step=self.service_steps[0])
        with task_manager.acquire(self.context, node.uuid) as task:
            servicing.continue_node_service(task)
            expected_step_index = 1 if skip else 0
            self.assertNotIn(
                'skip_current_service_step', task.node.driver_internal_info)
            self.assertNotIn(
                'cleaning_polling', task.node.driver_internal_info)
            mock_next_step.assert_called_once_with(task, expected_step_index)

    def test_continue_node_service(self):
        self._continue_node_service(skip=True)

    def test_continue_node_service_no_skip_step(self):
        self._continue_node_service(skip=False)


class DoNodeServiceAbortTestCase(db_base.DbTestCase):
    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def _test_do_node_service_abort(self, service_step,
                                    tear_mock=None):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICEWAIT,
            target_provision_state=states.AVAILABLE,
            service_step=service_step,
            driver_internal_info={
                'agent_url': 'some url',
                'agent_secret_token': 'token',
                'service_step_index': 2,
                'service_reboot': True,
                'service_polling': True,
                'skip_current_service_step': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            servicing.do_node_service_abort(task)
            self.assertIsNotNone(task.node.last_error)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            task.node.refresh()
            if service_step:
                self.assertIn(service_step['step'], task.node.last_error)
            # assert node's clean_step and metadata was cleaned up
            self.assertEqual({}, task.node.service_step)
            self.assertNotIn('service_step_index',
                             task.node.driver_internal_info)
            self.assertNotIn('service_reboot',
                             task.node.driver_internal_info)
            self.assertNotIn('service_polling',
                             task.node.driver_internal_info)
            self.assertNotIn('skip_current_service_step',
                             task.node.driver_internal_info)
            self.assertNotIn('agent_url',
                             task.node.driver_internal_info)
            self.assertNotIn('agent_secret_token',
                             task.node.driver_internal_info)

    def test_do_node_service_abort_early(self):
        self._test_do_node_service_abort(None)

    def test_do_node_service_abort_with_step(self):
        self._test_do_node_service_abort({'step': 'foo', 'interface': 'deploy',
                                          'abortable': True})

    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def test__do_node_service_abort_tear_down_fail(self, tear_mock):
        tear_mock.side_effect = Exception('Surprise')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICEFAIL,
            target_provision_state=states.ACTIVE,
            service_step={'step': 'foo', 'abortable': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            servicing.do_node_service_abort(task)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            self.assertIsNotNone(task.node.last_error)
            self.assertIsNotNone(task.node.maintenance_reason)
            self.assertTrue(task.node.maintenance)
            self.assertEqual('service failure', task.node.fault)

    @mock.patch.object(fake.FakeDeploy, 'tear_down_service', autospec=True)
    def test__do_node_cleanhold_abort_tear_down_fail(self, tear_mock):
        tear_mock.side_effect = Exception('Surprise')

        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICEHOLD,
            target_provision_state=states.ACTIVE,
            service_step={'step': 'hold', 'abortable': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            servicing.do_node_service_abort(task)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            self.assertIsNotNone(task.node.last_error)
            self.assertIsNotNone(task.node.maintenance_reason)
            self.assertTrue(task.node.maintenance)
            self.assertEqual('service failure', task.node.fault)


class DoNodeCleanTestChildNodes(db_base.DbTestCase):
    def setUp(self):
        super(DoNodeCleanTestChildNodes, self).setUp()
        self.power_off_parent = {
            'step': 'power_off', 'priority': 4, 'interface': 'power'}
        self.power_on_children = {
            'step': 'power_on', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True}
        self.update_firmware_on_children = {
            'step': 'update_firmware', 'priority': 10,
            'interface': 'management', 'execute_on_child_nodes': True}
        self.reboot_children = {
            'step': 'reboot', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True}
        self.power_on_parent = {
            'step': 'power_on', 'priority': 15, 'interface': 'power'}
        self.service_steps = [
            self.power_off_parent,
            self.power_on_children,
            self.update_firmware_on_children,
            self.reboot_children,
            self.power_on_parent]
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.SERVICING,
            target_provision_state=states.ACTIVE,
            last_error=None,
            power_state=states.POWER_ON,
            driver_internal_info={'agent_secret_token': 'old',
                                  'service_steps': self.service_steps})

    @mock.patch('ironic.drivers.modules.fake.FakePower.reboot',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.'
                'execute_service_step', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_clean_step_with_children(
            self, mock_deploy, mock_mgmt, mock_power, mock_pv, mock_nv,
            mock_sps, mock_reboot):
        child_node1 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            power_state=states.POWER_OFF,
            parent_node=self.node.uuid)
        child_node2 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            power_state=states.POWER_OFF,
            parent_node=self.node.uuid)

        mock_deploy.return_value = None
        mock_mgmt.return_value = None
        mock_power.return_value = None
        child1_updated_at = str(child_node1.updated_at)
        child2_updated_at = str(child_node2.updated_at)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            servicing.do_next_service_step(task, 0,
                                           disable_ramdisk=True)
        self.node.refresh()
        child_node1.refresh()
        child_node2.refresh()

        # Confirm the objects *did* receive locks.
        self.assertNotEqual(child1_updated_at, child_node1.updated_at)
        self.assertNotEqual(child2_updated_at, child_node2.updated_at)

        # Confirm the child nodes have no errors
        self.assertFalse(child_node1.maintenance)
        self.assertFalse(child_node2.maintenance)
        self.assertIsNone(child_node1.last_error)
        self.assertIsNone(child_node2.last_error)
        self.assertIsNone(self.node.last_error)

        # Confirm the call counts expected
        self.assertEqual(0, mock_deploy.call_count)
        self.assertEqual(2, mock_mgmt.call_count)
        self.assertEqual(0, mock_power.call_count)
        self.assertEqual(0, mock_nv.call_count)
        self.assertEqual(0, mock_pv.call_count)
        self.assertEqual(4, mock_sps.call_count)
        self.assertEqual(2, mock_reboot.call_count)
        mock_sps.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'power off', timeout=None),
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None),
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None)])

    @mock.patch('ironic.drivers.modules.fake.FakePower.set_power_state',
                autospec=True)
    @mock.patch('ironic.drivers.modules.network.flat.FlatNetwork.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_service_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeManagement.'
                'execute_service_step', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_service_step',
                autospec=True)
    def test_do_next_clean_step_with_children_by_uuid(
            self, mock_deploy, mock_mgmt, mock_power, mock_pv, mock_nv,
            mock_sps):
        child_node1 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            parent_node=self.node.uuid)
        child_node2 = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            last_error=None,
            parent_node=self.node.uuid)
        power_on_children = {
            'step': 'power_on', 'priority': 5, 'interface': 'power',
            'execute_on_child_nodes': True,
            'limit_child_node_execution': [child_node1.uuid]}
        update_firmware_on_children = {
            'step': 'update_firmware', 'priority': 10,
            'interface': 'management',
            'execute_on_child_nodes': True,
            'limit_child_node_execution': [child_node1.uuid]}
        power_on_parent = {
            'step': 'not_power', 'priority': 15, 'interface': 'power'}
        service_steps = [power_on_children, update_firmware_on_children,
                         power_on_parent]
        dii = self.node.driver_internal_info
        dii['service_steps'] = service_steps
        self.node.driver_internal_info = dii
        self.node.save()

        mock_deploy.return_value = None
        mock_mgmt.return_value = None
        mock_power.return_value = None
        child1_updated_at = str(child_node1.updated_at)

        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:

            servicing.do_next_service_step(task, 0,
                                           disable_ramdisk=True)
        self.node.refresh()
        child_node1.refresh()
        child_node2.refresh()

        # Confirm the objects *did* receive locks.
        self.assertNotEqual(child1_updated_at, child_node1.updated_at)
        self.assertIsNone(child_node2.updated_at)

        # Confirm the child nodes have no errors
        self.assertFalse(child_node1.maintenance)
        self.assertFalse(child_node2.maintenance)
        self.assertIsNone(child_node1.last_error)
        self.assertIsNone(child_node2.last_error)
        self.assertIsNone(self.node.last_error)

        # Confirm the call counts expected
        self.assertEqual(0, mock_deploy.call_count)
        self.assertEqual(1, mock_mgmt.call_count)
        self.assertEqual(1, mock_power.call_count)
        self.assertEqual(0, mock_nv.call_count)
        self.assertEqual(0, mock_pv.call_count)
        mock_sps.assert_has_calls([
            mock.call(mock.ANY, mock.ANY, 'power on', timeout=None)])
