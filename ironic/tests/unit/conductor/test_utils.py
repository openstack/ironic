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
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic import objects
from ironic.tests import base as tests_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils
from ironic.tests.unit.objects import utils as obj_utils


class NodeSetBootDeviceTestCase(base.DbTestCase):

    def test_node_set_boot_device_non_existent_device(self):
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")
        ipmi_info = utils.get_test_ipmi_info()
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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
            self.assertIn(node.uuid, node['last_error'])

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
                                          uuid=uuidutils.generate_uuid(),
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
                                          uuid=uuidutils.generate_uuid(),
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

    def test_node_power_action_in_same_state_db_not_in_sync(self):
        """Test setting node state to its present state if DB is out of sync.

        Under rare conditions (see bug #1403106) database might contain stale
        information, make sure we fix it.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            with mock.patch.object(self.driver.power,
                                   'set_power_state') as set_power_mock:
                conductor_utils.node_power_action(task, states.POWER_OFF)

                node.refresh()
                get_power_mock.assert_called_once_with(mock.ANY)
                self.assertFalse(set_power_mock.called,
                                 "set_power_state unexpectedly called")
                self.assertEqual(states.POWER_OFF, node['power_state'])
                self.assertIsNone(node['target_power_state'])
                self.assertIsNone(node['last_error'])

    def test_node_power_action_failed_getting_state(self):
        """Test for exception when we can't get the current power state."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
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
            self.assertIn(node.uuid, node['last_error'])

    def test_node_power_action_set_power_failure(self):
        """Test if an exception is thrown when the set_power call fails."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
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
                self.assertIn(node.uuid, node['last_error'])


class CleanupAfterTimeoutTestCase(tests_base.TestCase):
    def setUp(self):
        super(CleanupAfterTimeoutTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = mock.sentinel.context
        self.task.driver = mock.Mock(spec_set=['deploy'])
        self.task.shared = False
        self.task.node = mock.Mock(spec_set=objects.Node)
        self.node = self.task.node

    def test_cleanup_after_timeout(self):
        conductor_utils.cleanup_after_timeout(self.task)

        self.node.save.assert_called_once_with()
        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
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
        self.assertIn('moocow', self.node.last_error)

    def test_cleanup_after_timeout_cleanup_random_exception(self):
        clean_up_mock = self.task.driver.deploy.clean_up
        clean_up_mock.side_effect = Exception('moocow')

        conductor_utils.cleanup_after_timeout(self.task)

        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertIn('Deploy timed out', self.node.last_error)


class NodeCleaningStepsTestCase(base.DbTestCase):
    def setUp(self):
        super(NodeCleaningStepsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager()

        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy'}
        # Automated cleaning should be executed in this order
        self.clean_steps = [self.deploy_erase, self.power_update,
                            self.deploy_update]
        # Manual clean step
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy',
            'argsinfo': {'arg1': {'description': 'desc1', 'required': True},
                         'arg2': {'description': 'desc2'}}}

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps(self, mock_power_steps, mock_deploy_steps):
        # Test getting cleaning steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE)

        mock_power_steps.return_value = [self.power_update]
        mock_deploy_steps.return_value = [self.deploy_erase,
                                          self.deploy_update]

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            steps = conductor_utils._get_cleaning_steps(task, enabled=False)

        self.assertEqual(self.clean_steps, steps)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps_unsorted(self, mock_power_steps,
                                          mock_deploy_steps):
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE)

        mock_deploy_steps.return_value = [self.deploy_raid,
                                          self.deploy_update,
                                          self.deploy_erase]
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            steps = conductor_utils._get_cleaning_steps(task, enabled=False,
                                                        sort=False)
        self.assertEqual(mock_deploy_steps.return_value, steps)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.get_clean_steps')
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_clean_steps')
    def test__get_cleaning_steps_only_enabled(self, mock_power_steps,
                                              mock_deploy_steps):
        # Test getting only cleaning steps, with one driver returning None, two
        # conflicting priorities, and asserting they are ordered properly.
        # Should discard zero-priority (manual) clean step
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE)

        mock_power_steps.return_value = [self.power_update]
        mock_deploy_steps.return_value = [self.deploy_erase,
                                          self.deploy_update,
                                          self.deploy_raid]

        with task_manager.acquire(
                self.context, node.uuid, shared=True) as task:
            steps = conductor_utils._get_cleaning_steps(task, enabled=True)

        self.assertEqual(self.clean_steps, steps)

    @mock.patch.object(conductor_utils, '_validate_user_clean_steps')
    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test_set_node_cleaning_steps_automated(self, mock_steps,
                                               mock_validate_user_steps):
        mock_steps.return_value = self.clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None,
            clean_step=None)

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            conductor_utils.set_node_cleaning_steps(task)
            node.refresh()
            self.assertEqual(self.clean_steps,
                             node.driver_internal_info['clean_steps'])
            self.assertEqual({}, node.clean_step)
            mock_steps.assert_called_once_with(task, enabled=True)
            self.assertFalse(mock_validate_user_steps.called)

    @mock.patch.object(conductor_utils, '_validate_user_clean_steps')
    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test_set_node_cleaning_steps_manual(self, mock_steps,
                                            mock_validate_user_steps):
        clean_steps = [self.deploy_raid]
        mock_steps.return_value = self.clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            clean_step=None,
            driver_internal_info={'clean_steps': clean_steps})

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            conductor_utils.set_node_cleaning_steps(task)
            node.refresh()
            self.assertEqual(clean_steps,
                             node.driver_internal_info['clean_steps'])
            self.assertEqual({}, node.clean_step)
            self.assertFalse(mock_steps.called)
            mock_validate_user_steps.assert_called_once_with(task, clean_steps)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps

        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'erase_disks', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            conductor_utils._validate_user_clean_steps(task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps_no_steps(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps

        with task_manager.acquire(self.context, node.uuid) as task:
            conductor_utils._validate_user_clean_steps(task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps_get_steps_exception(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.side_effect = exception.NodeCleaningFailure('bad')

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.NodeCleaningFailure,
                              conductor_utils._validate_user_clean_steps,
                              task, [])
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps_not_supported(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = [self.power_update, self.deploy_raid]
        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'bad_step', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegexp(exception.InvalidParameterValue,
                                    "does not support.*bad_step",
                                    conductor_utils._validate_user_clean_steps,
                                    task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps_invalid_arg(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = self.clean_steps
        user_steps = [{'step': 'update_firmware', 'interface': 'power',
                       'args': {'arg1': 'val1', 'arg2': 'val2'}},
                      {'step': 'erase_disks', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegexp(exception.InvalidParameterValue,
                                    "update_firmware.*invalid.*arg1",
                                    conductor_utils._validate_user_clean_steps,
                                    task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

    @mock.patch.object(conductor_utils, '_get_cleaning_steps')
    def test__validate_user_clean_steps_missing_required_arg(self, mock_steps):
        node = obj_utils.create_test_node(self.context)
        mock_steps.return_value = [self.power_update, self.deploy_raid]
        user_steps = [{'step': 'update_firmware', 'interface': 'power'},
                      {'step': 'build_raid', 'interface': 'deploy'}]

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaisesRegexp(exception.InvalidParameterValue,
                                    "build_raid.*missing.*arg1",
                                    conductor_utils._validate_user_clean_steps,
                                    task, user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)


class ErrorHandlersTestCase(tests_base.TestCase):
    def setUp(self):
        super(ErrorHandlersTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.driver = mock.Mock(spec_set=['deploy'])
        self.task.node = mock.Mock(spec_set=objects.Node)
        self.node = self.task.node

    @mock.patch.object(conductor_utils, 'LOG')
    def test_provision_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.provisioning_error_handler(exc, self.node, 'state-one',
                                                   'state-two')
        self.node.save.assert_called_once_with()
        self.assertEqual('state-one', self.node.provision_state)
        self.assertEqual('state-two', self.node.target_provision_state)
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_provision_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.provisioning_error_handler(exc, self.node, 'state-one',
                                                   'state-two')
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    def test_cleaning_error_handler(self):
        self.node.provision_state = states.CLEANING
        target = 'baz'
        self.node.target_provision_state = target
        self.node.driver_internal_info = {}
        msg = 'error bar'
        conductor_utils.cleaning_error_handler(self.task, msg)
        self.node.save.assert_called_once_with()
        self.assertEqual({}, self.node.clean_step)
        self.assertFalse('clean_step_index' in self.node.driver_internal_info)
        self.assertEqual(msg, self.node.last_error)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(msg, self.node.maintenance_reason)
        driver = self.task.driver.deploy
        driver.tear_down_cleaning.assert_called_once_with(self.task)
        self.task.process_event.assert_called_once_with('fail',
                                                        target_state=None)

    def test_cleaning_error_handler_manual(self):
        target = states.MANAGEABLE
        self.node.target_provision_state = target
        conductor_utils.cleaning_error_handler(self.task, 'foo')
        self.task.process_event.assert_called_once_with('fail',
                                                        target_state=target)

    def test_cleaning_error_handler_no_teardown(self):
        target = states.MANAGEABLE
        self.node.target_provision_state = target
        conductor_utils.cleaning_error_handler(self.task, 'foo',
                                               tear_down_cleaning=False)
        self.assertFalse(self.task.driver.deploy.tear_down_cleaning.called)
        self.task.process_event.assert_called_once_with('fail',
                                                        target_state=target)

    def test_cleaning_error_handler_no_fail(self):
        conductor_utils.cleaning_error_handler(self.task, 'foo',
                                               set_fail_state=False)
        driver = self.task.driver.deploy
        driver.tear_down_cleaning.assert_called_once_with(self.task)
        self.assertFalse(self.task.process_event.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_cleaning_error_handler_tear_down_error(self, log_mock):
        driver = self.task.driver.deploy
        driver.tear_down_cleaning.side_effect = Exception('bar')
        conductor_utils.cleaning_error_handler(self.task, 'foo')
        self.assertTrue(log_mock.exception.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_spawn_cleaning_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.spawn_cleaning_error_handler(exc, self.node)
        self.node.save.assert_called_once_with()
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_spawn_cleaning_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.spawn_cleaning_error_handler(exc, self.node)
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_power_state_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.power_state_error_handler(exc, self.node, 'newstate')
        self.node.save.assert_called_once_with()
        self.assertEqual('newstate', self.node.power_state)
        self.assertEqual(states.NOSTATE, self.node.target_power_state)
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG')
    def test_power_state_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.power_state_error_handler(exc, self.node, 'foo')
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)
