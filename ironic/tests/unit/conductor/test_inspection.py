
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

from unittest import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import inspection
from ironic.conductor import task_manager
from ironic.drivers.modules import inspect_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


@mock.patch('ironic.drivers.modules.fake.FakeInspect.inspect_hardware',
            autospec=True)
class TestInspectHardware(db_base.DbTestCase):

    def test_inspect_hardware_ok(self, mock_inspect):
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.INSPECTING,
            driver_internal_info={'agent_url': 'url',
                                  'agent_secret_token': 'token'})
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = states.MANAGEABLE
        inspection.inspect_hardware(task)
        node.refresh()
        self.assertEqual(states.MANAGEABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_inspect.assert_called_once_with(task.driver.inspect, task)
        task.node.refresh()
        self.assertNotIn('agent_url', task.node.driver_internal_info)
        self.assertNotIn('agent_secret_token', task.node.driver_internal_info)

    def test_inspect_hardware_return_inspecting(self, mock_inspect):
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = states.INSPECTING
        self.assertRaises(exception.HardwareInspectionFailure,
                          inspection.inspect_hardware, task)

        node.refresh()
        self.assertIn('driver returned unexpected state', node.last_error)
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        mock_inspect.assert_called_once_with(task.driver.inspect, task)

    def test_inspect_hardware_return_inspect_wait(self, mock_inspect):
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = states.INSPECTWAIT
        inspection.inspect_hardware(task)
        node.refresh()
        self.assertEqual(states.INSPECTWAIT, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_inspect.assert_called_once_with(task.driver.inspect, task)

    @mock.patch.object(inspection, 'LOG', autospec=True)
    def test_inspect_hardware_return_other_state(self, log_mock, mock_inspect):
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = None
        self.assertRaises(exception.HardwareInspectionFailure,
                          inspection.inspect_hardware, task)
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_inspect.assert_called_once_with(task.driver.inspect, task)
        self.assertTrue(log_mock.error.called)

    def test_inspect_hardware_raises_error(self, mock_inspect):
        mock_inspect.side_effect = exception.HardwareInspectionFailure('test')
        state = states.MANAGEABLE
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.INSPECTING,
                                          target_provision_state=state)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaisesRegex(exception.HardwareInspectionFailure, '^test$',
                               inspection.inspect_hardware, task)
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertEqual('test', node.last_error)
        self.assertTrue(mock_inspect.called)

    def test_inspect_hardware_unexpected_error(self, mock_inspect):
        mock_inspect.side_effect = RuntimeError('x')
        state = states.MANAGEABLE
        node = obj_utils.create_test_node(self.context, driver='fake-hardware',
                                          provision_state=states.INSPECTING,
                                          target_provision_state=state)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaisesRegex(exception.HardwareInspectionFailure,
                               'Unexpected exception of type RuntimeError: x',
                               inspection.inspect_hardware, task)
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertEqual('Unexpected exception of type RuntimeError: x',
                         node.last_error)
        self.assertTrue(mock_inspect.called)


@mock.patch('ironic.drivers.modules.fake.FakeInspect.continue_inspection',
            autospec=True)
class TestContinueInspection(db_base.DbTestCase):

    def setUp(self):
        super().setUp()
        self.node = obj_utils.create_test_node(
            self.context, provision_state=states.INSPECTING)
        self.inventory = {"test": "inventory"}
        self.plugin_data = {"plugin": "data"}

    @mock.patch.object(inspect_utils, 'store_inspection_data', autospec=True)
    def test_ok(self, mock_store, mock_continue):
        with task_manager.acquire(self.context, self.node.id) as task:
            inspection.continue_inspection(task, self.inventory,
                                           self.plugin_data)
            mock_continue.assert_called_once_with(task.driver.inspect,
                                                  task, self.inventory,
                                                  self.plugin_data)
            mock_store.assert_called_once_with(task.node, self.inventory,
                                               self.plugin_data, self.context)
        self.node.refresh()
        self.assertEqual(states.MANAGEABLE, self.node.provision_state)

    @mock.patch.object(inspect_utils, 'store_inspection_data', autospec=True)
    def test_ok_asynchronous(self, mock_store, mock_continue):
        mock_continue.return_value = states.INSPECTWAIT
        with task_manager.acquire(self.context, self.node.id) as task:
            inspection.continue_inspection(task, self.inventory,
                                           self.plugin_data)
            mock_continue.assert_called_once_with(task.driver.inspect,
                                                  task, self.inventory,
                                                  self.plugin_data)
            mock_store.assert_not_called()
            self.assertEqual(states.INSPECTWAIT, task.node.provision_state)

    @mock.patch.object(inspect_utils, 'store_inspection_data', autospec=True)
    def test_failure(self, mock_store, mock_continue):
        mock_continue.side_effect = exception.HardwareInspectionFailure("boom")
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              inspection.continue_inspection,
                              task, self.inventory, self.plugin_data)
            mock_continue.assert_called_once_with(task.driver.inspect,
                                                  task, self.inventory,
                                                  self.plugin_data)

        mock_store.assert_not_called()
        self.node.refresh()
        self.assertEqual(states.INSPECTFAIL, self.node.provision_state)
        self.assertIn("boom", self.node.last_error)
