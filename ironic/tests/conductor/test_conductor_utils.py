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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils as cmn_utils
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic import objects
from ironic.tests import base as tests_base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils
from ironic.tests.objects import utils as obj_utils


class NodeSetBootDeviceTestCase(base.DbTestCase):

    def test_node_set_boot_device_non_existent_device(self):
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")
        ipmi_info = utils.get_test_ipmi_info()
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake_ipmitool',
                                          driver_info=ipmi_info)
        task = task_manager.TaskManager(self.context, node.uuid)
        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.node_set_boot_device,
                          task,
                          device='fake')

    def test_node_set_boot_device_valid(self):
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")
        ipmi_info = utils.get_test_ipmi_info()
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake_ipmitool',
                                          driver_info=ipmi_info)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.management,
                               'set_boot_device') as mock_sbd:
            conductor_utils.node_set_boot_device(task,
                                                 device='pxe')
            mock_sbd.assert_called_once_with(task,
                                             device='pxe',
                                             persistent=False)


class NodePowerActionTestCase(base.DbTestCase):

    def setUp(self):
        super(NodePowerActionTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")

    def test_node_power_action_power_on(self):
        """Test node_power_action to turn node power on."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            conductor_utils.node_power_action(task, states.POWER_ON)

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_off(self):
        """Test node_power_action to turn node power off."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, states.POWER_OFF)

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_reboot(self):
        """Test for reboot a node."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'reboot') as reboot_mock:
            conductor_utils.node_power_action(task, states.REBOOT)

            node.refresh()
            reboot_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_invalid_state(self):
        """Test for exception when changing to an invalid power state."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.assertRaises(exception.InvalidParameterValue,
                              conductor_utils.node_power_action,
                              task,
                              "INVALID_POWER_STATE")

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNotNone(node['last_error'])

            # last_error is cleared when a new transaction happens
            conductor_utils.node_power_action(task, states.POWER_OFF)
            node.refresh()
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_already_being_processed(self):
        """Test node power action after aborted power action.

        The target_power_state is expected to be None so it isn't
        checked in the code. This is what happens if it is not None.
        (Eg, if a conductor had died during a previous power-off
        attempt and left the target_power_state set to states.POWER_OFF,
        and the user is attempting to power-off again.)
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON,
                                          target_power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertEqual(states.NOSTATE, node['target_power_state'])
        self.assertIsNone(node['last_error'])

    def test_node_power_action_in_same_state(self):
        """Test setting node state to its present state.

        Test that we don't try to set the power state if the requested
        state is the same as the current state.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            with mock.patch.object(self.driver.power,
                                   'set_power_state') as set_power_mock:
                conductor_utils.node_power_action(task, states.POWER_ON)

                node.refresh()
                get_power_mock.assert_called_once_with(mock.ANY)
                self.assertFalse(set_power_mock.called,
                                 "set_power_state unexpectedly called")
                self.assertEqual(states.POWER_ON, node['power_state'])
                self.assertIsNone(node['target_power_state'])
                self.assertIsNone(node['last_error'])

    def test_node_power_action_failed_getting_state(self):
        """Test for exception when we can't get the current power state."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_state_mock:
            get_power_state_mock.side_effect = (
                exception.InvalidParameterValue('failed getting power state'))

            self.assertRaises(exception.InvalidParameterValue,
                              conductor_utils.node_power_action,
                              task,
                              states.POWER_ON)

            node.refresh()
            get_power_state_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNotNone(node['last_error'])

    def test_node_power_action_set_power_failure(self):
        """Test if an exception is thrown when the set_power call fails."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=cmn_utils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            with mock.patch.object(self.driver.power,
                                   'set_power_state') as set_power_mock:
                get_power_mock.return_value = states.POWER_OFF
                set_power_mock.side_effect = exception.IronicException()

                self.assertRaises(
                    exception.IronicException,
                    conductor_utils.node_power_action,
                    task,
                    states.POWER_ON)

                node.refresh()
                get_power_mock.assert_called_once_with(mock.ANY)
                set_power_mock.assert_called_once_with(mock.ANY,
                                                       states.POWER_ON)
                self.assertEqual(states.POWER_OFF, node['power_state'])
                self.assertIsNone(node['target_power_state'])
                self.assertIsNotNone(node['last_error'])


class CleanupAfterTimeoutTestCase(tests_base.TestCase):
    def setUp(self):
        super(CleanupAfterTimeoutTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = mock.sentinel.context
        self.task.driver = mock.Mock(spec_set=['deploy'])
        self.task.shared = False
        self.task.node = mock.Mock(spec_set=objects.Node)
        self.node = self.task.node

        def set_state(state):
            self.node.provision_state = states.DEPLOYFAIL
            self.node.target_provision_state = states.NOSTATE
        process_event_mock = self.task.process_event
        process_event_mock.side_effect = set_state

    def test_cleanup_after_timeout(self):
        conductor_utils.cleanup_after_timeout(self.task)

        self.node.save.assert_called_once_with()
        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)
        self.assertIn('Timeout reached', self.node.last_error)

    def test_cleanup_after_timeout_shared_lock(self):
        self.task.shared = True

        self.assertRaises(exception.ExclusiveLockRequired,
                          conductor_utils.cleanup_after_timeout,
                          self.task)

    def test_cleanup_after_timeout_cleanup_ironic_exception(self):
        clean_up_mock = self.task.driver.deploy.clean_up
        clean_up_mock.side_effect = exception.IronicException('moocow')

        conductor_utils.cleanup_after_timeout(self.task)

        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)
        self.assertIn('moocow', self.node.last_error)

    def test_cleanup_after_timeout_cleanup_random_exception(self):
        clean_up_mock = self.task.driver.deploy.clean_up
        clean_up_mock.side_effect = Exception('moocow')

        conductor_utils.cleanup_after_timeout(self.task)

        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertEqual(states.DEPLOYFAIL, self.node.provision_state)
        self.assertEqual(states.NOSTATE, self.node.target_provision_state)
        self.assertIn('Deploy timed out', self.node.last_error)
