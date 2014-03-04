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
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils


class NodePowerActionTestCase(base.DbTestCase):

    def setUp(self):
        super(NodePowerActionTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")

    def test_node_power_action_power_on(self):
        """Test node_power_action to turn node power on."""
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            conductor_utils.node_power_action(task, task.node,
                                              states.POWER_ON)

            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_off(self):
        """Test node_power_action to turn node power off."""
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, task.node,
                                              states.POWER_OFF)

            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_reboot(self):
        """Test for reboot a node."""
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'reboot') as reboot_mock:
            conductor_utils.node_power_action(task, task.node,
                                              states.REBOOT)

            node.refresh(self.context)
            reboot_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_invalid_state(self):
        """Test if an exception is thrown when changing to an invalid
        power state.
        """
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.assertRaises(exception.InvalidParameterValue,
                              conductor_utils.node_power_action,
                              task,
                              task.node,
                              "INVALID_POWER_STATE")

            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNotNone(node['last_error'])

            # last_error is cleared when a new transaction happens
            conductor_utils.node_power_action(task, task.node,
                                              states.POWER_OFF)
            node.refresh(self.context)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_already_being_processed(self):
        """The target_power_state is expected to be None so it isn't
        checked in the code. This is what happens if it is not None.
        (Eg, if a conductor had died during a previous power-off
        attempt and left the target_power_state set to states.POWER_OFF,
        and the user is attempting to power-off again.)
        """
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_ON,
                                    target_power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, task.node,
                                          states.POWER_OFF)

        node.refresh(self.context)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertEqual(states.NOSTATE, node['target_power_state'])
        self.assertIsNone(node['last_error'])

    def test_node_power_action_in_same_state(self):
        """Test that we don't try to set the power state if the requested
        state is the same as the current state.
        """
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    last_error='anything but None',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                conductor_utils.node_power_action(task, task.node,
                                                  states.POWER_ON)

                node.refresh(self.context)
                get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
                self.assertFalse(set_power_mock.called,
                                 "set_power_state unexpectedly called")
                self.assertEqual(states.POWER_ON, node['power_state'])
                self.assertIsNone(node['target_power_state'])
                self.assertIsNone(node['last_error'])

    def test_node_power_action_invalid_driver_info(self):
        """Test if an exception is thrown when the driver validation
        fails.
        """
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'validate') \
                as validate_mock:
            validate_mock.side_effect = exception.InvalidParameterValue(
                'wrong power driver info')

            self.assertRaises(exception.InvalidParameterValue,
                              conductor_utils.node_power_action,
                              task,
                              task.node,
                              states.POWER_ON)

            node.refresh(self.context)
            validate_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNotNone(node['last_error'])

    def test_node_power_action_set_power_failure(self):
        """Test if an exception is thrown when the set_power call
        fails.
        """
        ndict = utils.get_test_node(uuid=cmn_utils.generate_uuid(),
                                    driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                get_power_mock.return_value = states.POWER_OFF
                set_power_mock.side_effect = exception.IronicException()

                self.assertRaises(
                    exception.IronicException,
                    conductor_utils.node_power_action,
                    task,
                    task.node,
                    states.POWER_ON)

                node.refresh(self.context)
                get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
                set_power_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                       states.POWER_ON)
                self.assertEqual(states.POWER_OFF, node['power_state'])
                self.assertIsNone(node['target_power_state'])
                self.assertIsNotNone(node['last_error'])
