# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from ironic.common import exception
from ironic.common import states
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils


class PowerActionTestCase(base.DbTestCase):

    def setUp(self):
        super(PowerActionTestCase, self).setUp()
        self.service = manager.ConductorManager('test-host', 'test-topic')
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager()

    def test_change_node_power_state_power_on(self):
        """Test if change_node_power_state to turn node power on
        is successful or not.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            self.service.change_node_power_state(self.context,
                                                 node['uuid'], states.POWER_ON)
            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_power_off(self):
        """Test if change_node_power_state to turn node power off
        is successful or not.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.service.change_node_power_state(self.context, node['uuid'],
                                                 states.POWER_OFF)
            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(node['power_state'], states.POWER_OFF)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_reboot(self):
        """Test for reboot a node."""
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'reboot') as reboot_mock:
            self.service.change_node_power_state(self.context, node['uuid'],
                                                 states.REBOOT)
            node.refresh(self.context)
            reboot_mock.assert_called_once()
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_invalid_state(self):
        """Test if an exception is thrown when changing to an invalid
        power state.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.assertRaises(exception.InvalidParameterValue,
                              self.service.change_node_power_state,
                              self.context,
                              node['uuid'],
                              "POWER")
            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertNotEqual(node['last_error'], None)

            # last_error is cleared when a new transaction happens
            self.service.change_node_power_state(self.context, node['uuid'],
                                                 states.POWER_OFF)
            node.refresh(self.context)
            self.assertEqual(node['power_state'], states.POWER_OFF)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_already_locked(self):
        """Test if an exception is thrown when applying an exclusive
        lock to the node failed.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        # check if the node is locked
        with task_manager.acquire(self.context, node['id'], shared=False):
            self.assertRaises(exception.NodeLocked,
                              self.service.change_node_power_state,
                              self.context,
                              node['uuid'],
                              states.POWER_ON)
            node.refresh(self.context)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_already_being_processed(self):
        """The target_power_state is expected to be None so it isn't
        checked in the code. This is what happens if it is not None.
        (Eg, if a conductor had died during a previous power-off
        attempt and left the target_power_state set to states.POWER_OFF,
        and the user is attempting to power-off again.)
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON,
                                    target_power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)

        self.service.change_node_power_state(self.context, node['uuid'],
                                             states.POWER_OFF)
        node.refresh(self.context)
        self.assertEqual(node['power_state'], states.POWER_OFF)
        self.assertEqual(node['target_power_state'], states.NOSTATE)
        self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_in_same_state(self):
        """Test that we don't try to set the power state if the requested
        state is the same as the current state.
        """
        ndict = utils.get_test_node(driver='fake',
                                    last_error='anything but None',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                set_power_mock.side_effect = exception.IronicException()

                self.service.change_node_power_state(self.context,
                                                     node['uuid'],
                                                     states.POWER_ON)
            node.refresh(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertFalse(set_power_mock.called)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertEqual(node['last_error'], None)

    def test_change_node_power_state_invalid_driver_info(self):
        """Test if an exception is thrown when the driver validation
        fails.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'validate') \
                as validate_mock:
            validate_mock.side_effect = exception.InvalidParameterValue(
                    'wrong power driver info')

            self.assertRaises(exception.InvalidParameterValue,
                              self.service.change_node_power_state,
                              self.context,
                              node['uuid'],
                              states.POWER_ON)
            node.refresh(self.context)
            validate_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)
            self.assertNotEqual(node['last_error'], None)

    def test_change_node_power_state_set_power_failure(self):
        """Test if an exception is thrown when the set_power call
        fails.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                get_power_mock.return_value = states.POWER_OFF
                set_power_mock.side_effect = exception.IronicException()

                self.assertRaises(exception.IronicException,
                                  self.service.change_node_power_state,
                                  self.context,
                                  node['uuid'],
                                  states.POWER_ON)
                node.refresh(self.context)
                get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
                set_power_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                       states.POWER_ON)
                self.assertEqual(node['power_state'], states.POWER_OFF)
                self.assertEqual(node['target_power_state'], None)
                self.assertNotEqual(node['last_error'], None)
