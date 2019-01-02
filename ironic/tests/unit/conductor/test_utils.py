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
from oslo_config import cfg
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import network
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base as tests_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class NodeSetBootDeviceTestCase(db_base.DbTestCase):

    def test_node_set_boot_device_non_existent_device(self):
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")
        ipmi_info = db_utils.get_test_ipmi_info()
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
        ipmi_info = db_utils.get_test_ipmi_info()
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

    def test_node_set_boot_device_adopting(self):
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")
        ipmi_info = db_utils.get_test_ipmi_info()
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_ipmitool',
                                          driver_info=ipmi_info,
                                          provision_state=states.ADOPTING)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.management,
                               'set_boot_device') as mock_sbd:
            conductor_utils.node_set_boot_device(task,
                                                 device='pxe')
            self.assertFalse(mock_sbd.called)


class NodePowerActionTestCase(db_base.DbTestCase):
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

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification')
    def test_node_power_action_power_on_notify(self, mock_notif):
        """Test node_power_action to power on node and send notification."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
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
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNone(node.last_error)

            # 2 notifications should be sent: 1 .start and 1 .end
            self.assertEqual(2, mock_notif.call_count)
            self.assertEqual(2, mock_notif.return_value.emit.call_count)

            first_notif_args = mock_notif.call_args_list[0][1]
            second_notif_args = mock_notif.call_args_list[1][1]

            self.assertNotificationEqual(first_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.start',
                                         obj_fields.NotificationLevel.INFO)
            self.assertNotificationEqual(second_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.end',
                                         obj_fields.NotificationLevel.INFO)

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
            with mock.patch.object(self.driver.power,
                                   'get_power_state') as get_power_mock:
                conductor_utils.node_power_action(task, states.REBOOT)
                self.assertFalse(get_power_mock.called)

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
            self.assertFalse(get_power_mock.called)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNotNone(node['last_error'])

            # last_error is cleared when a new transaction happens
            conductor_utils.node_power_action(task, states.POWER_OFF)
            node.refresh()
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification')
    def test_node_power_action_invalid_state_notify(self, mock_notif):
        """Test for notification when changing to an invalid power state."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
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
            self.assertFalse(get_power_mock.called)
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNotNone(node.last_error)

            # 2 notifications should be sent: 1 .start and 1 .error
            self.assertEqual(2, mock_notif.call_count)
            self.assertEqual(2, mock_notif.return_value.emit.call_count)

            first_notif_args = mock_notif.call_args_list[0][1]
            second_notif_args = mock_notif.call_args_list[1][1]

            self.assertNotificationEqual(first_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.start',
                                         obj_fields.NotificationLevel.INFO)
            self.assertNotificationEqual(second_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.error',
                                         obj_fields.NotificationLevel.ERROR)

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

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_node_power_action_in_same_state(self, log_mock):
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
                log_mock.warning.assert_called_once_with(
                    u"Not going to change node %(node)s power state because "
                    u"current state = requested state = '%(state)s'.",
                    {'state': states.POWER_ON, 'node': node.uuid})

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

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification')
    def test_node_power_action_failed_getting_state_notify(self, mock_notif):
        """Test for notification when we can't get the current power state."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
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
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNotNone(node.last_error)

            # 2 notifications should be sent: 1 .start and 1 .error
            self.assertEqual(2, mock_notif.call_count)
            self.assertEqual(2, mock_notif.return_value.emit.call_count)

            first_notif_args = mock_notif.call_args_list[0][1]
            second_notif_args = mock_notif.call_args_list[1][1]

            self.assertNotificationEqual(first_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.start',
                                         obj_fields.NotificationLevel.INFO)
            self.assertNotificationEqual(second_notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.error',
                                         obj_fields.NotificationLevel.ERROR)

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

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification')
    def test_node_power_action_set_power_failure_notify(self, mock_notif):
        """Test if a notification is sent when the set_power call fails."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
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
                self.assertEqual(states.POWER_OFF, node.power_state)
                self.assertIsNone(node.target_power_state)
                self.assertIsNotNone(node.last_error)

                # 2 notifications should be sent: 1 .start and 1 .error
                self.assertEqual(2, mock_notif.call_count)
                self.assertEqual(2, mock_notif.return_value.emit.call_count)

                first_notif_args = mock_notif.call_args_list[0][1]
                second_notif_args = mock_notif.call_args_list[1][1]

                self.assertNotificationEqual(first_notif_args,
                                             'ironic-conductor', CONF.host,
                                             'baremetal.node.power_set.start',
                                             obj_fields.NotificationLevel.INFO)
                self.assertNotificationEqual(
                    second_notif_args, 'ironic-conductor', CONF.host,
                    'baremetal.node.power_set.error',
                    obj_fields.NotificationLevel.ERROR)

    def test_node_power_action_power_on_storage_attach(self):
        """Test node_power_action to turn node power on and attach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_OFF,
                                          storage_interface="cinder",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(task.driver.storage,
                               'attach_volumes',
                               autospec=True) as attach_mock:
            conductor_utils.node_power_action(task, states.POWER_ON)

            node.refresh()
            attach_mock.assert_called_once_with(task)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_reboot_storage_attach(self):
        """Test node_power_action to reboot the node and attach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON,
                                          storage_interface="cinder",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(task.driver.storage,
                               'attach_volumes',
                               autospec=True) as attach_mock:
            conductor_utils.node_power_action(task, states.REBOOT)

            node.refresh()
            attach_mock.assert_called_once_with(task)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_off_storage_detach(self):
        """Test node_power_action to turn node power off and detach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake',
                                          power_state=states.POWER_ON,
                                          storage_interface="cinder",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(task.driver.storage,
                               'detach_volumes',
                               autospec=True) as detach_mock:
            conductor_utils.node_power_action(task, states.POWER_OFF)

            node.refresh()
            detach_mock.assert_called_once_with(task)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test__calculate_target_state(self):
        for new_state in (states.POWER_ON, states.REBOOT, states.SOFT_REBOOT):
            self.assertEqual(
                states.POWER_ON,
                conductor_utils._calculate_target_state(new_state))
        for new_state in (states.POWER_OFF, states.SOFT_POWER_OFF):
            self.assertEqual(
                states.POWER_OFF,
                conductor_utils._calculate_target_state(new_state))
        self.assertIsNone(conductor_utils._calculate_target_state('bad_state'))

    def test__can_skip_state_change_different_state(self):
        """Test setting node state to different state.

        Test that we should change state if requested state is different from
        current state.
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

            result = conductor_utils._can_skip_state_change(
                task, states.POWER_OFF)

            self.assertFalse(result)
            get_power_mock.assert_called_once_with(mock.ANY)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test__can_skip_state_change_same_state(self, mock_log):
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

            result = conductor_utils._can_skip_state_change(
                task, states.POWER_ON)

            self.assertTrue(result)
            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertEqual(states.NOSTATE, node['target_power_state'])
            self.assertIsNone(node['last_error'])
            mock_log.warning.assert_called_once_with(
                u"Not going to change node %(node)s power state because "
                u"current state = requested state = '%(state)s'.",
                {'state': states.POWER_ON, 'node': node.uuid})

    def test__can_skip_state_change_db_not_in_sync(self):
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

            result = conductor_utils._can_skip_state_change(
                task, states.POWER_OFF)

            self.assertTrue(result)

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertEqual(states.NOSTATE, node['target_power_state'])
            self.assertIsNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification')
    def test__can_skip_state_change_failed_getting_state_notify(
            self, mock_notif):
        """Test for notification & exception when can't get power state.

        Test to make sure we generate a notification and also that an exception
        is raised when we can't get the current power state.
        """
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
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
                              conductor_utils._can_skip_state_change,
                              task,
                              states.POWER_ON)

            node.refresh()
            get_power_state_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertEqual(states.NOSTATE, node['target_power_state'])
            self.assertIsNotNone(node.last_error)

            # 1 notification should be sent for the error
            self.assertEqual(1, mock_notif.call_count)
            self.assertEqual(1, mock_notif.return_value.emit.call_count)

            notif_args = mock_notif.call_args_list[0][1]

            self.assertNotificationEqual(notif_args,
                                         'ironic-conductor', CONF.host,
                                         'baremetal.node.power_set.error',
                                         obj_fields.NotificationLevel.ERROR)


class NodeSoftPowerActionTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NodeSoftPowerActionTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_soft_power")
        self.driver = driver_factory.get_driver("fake_soft_power")

    def test_node_power_action_power_soft_reboot(self):
        """Test for soft reboot a node."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_soft_power',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, states.SOFT_REBOOT)

            node.refresh()
            self.assertFalse(get_power_mock.called)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_power_soft_reboot_timeout(self):
        """Test for soft reboot a node."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_soft_power',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, states.SOFT_REBOOT,
                                              timeout=2)

            node.refresh()
            self.assertFalse(get_power_mock.called)
            self.assertEqual(states.POWER_ON, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_soft_power_off(self):
        """Test node_power_action to turn node soft power off."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_soft_power',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, states.SOFT_POWER_OFF)

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_soft_power_off_timeout(self):
        """Test node_power_action to turn node soft power off."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_soft_power',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            conductor_utils.node_power_action(task, states.SOFT_POWER_OFF,
                                              timeout=2)

            node.refresh()
            get_power_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])

    def test_node_power_action_soft_power_off_storage_detach(self):
        """Test node_power_action to soft power off node and detach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake_soft_power',
                                          power_state=states.POWER_ON,
                                          storage_interface="cinder",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        with mock.patch.object(task.driver.storage,
                               'detach_volumes',
                               autospec=True) as detach_mock:
            conductor_utils.node_power_action(task, states.SOFT_POWER_OFF)

            node.refresh()
            detach_mock.assert_called_once_with(task)
            self.assertEqual(states.POWER_OFF, node['power_state'])
            self.assertIsNone(node['target_power_state'])
            self.assertIsNone(node['last_error'])


class CleanupAfterTimeoutTestCase(tests_base.TestCase):
    def setUp(self):
        super(CleanupAfterTimeoutTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = self.context
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


class NodeCleaningStepsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(NodeCleaningStepsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager()

        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy',
            'abortable': True}
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
        mock_validate_user_steps.return_value = clean_steps

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
            result = conductor_utils._validate_user_clean_steps(task,
                                                                user_steps)
            mock_steps.assert_called_once_with(task, enabled=False, sort=False)

        expected = [{'step': 'update_firmware', 'interface': 'power',
                     'priority': 10, 'abortable': False},
                    {'step': 'erase_disks', 'interface': 'deploy',
                     'priority': 20, 'abortable': True}]
        self.assertEqual(expected, result)

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
            self.assertRaisesRegex(exception.InvalidParameterValue,
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
            self.assertRaisesRegex(exception.InvalidParameterValue,
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
            self.assertRaisesRegex(exception.InvalidParameterValue,
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
        # NOTE(mariojv) Some of the test cases that use the task below require
        # strict typing of the node power state fields and would fail if passed
        # a Mock object in constructors. A task context is also required for
        # notifications.
        power_attrs = {'power_state': states.POWER_OFF,
                       'target_power_state': states.POWER_ON}
        self.node.configure_mock(**power_attrs)
        self.task.context = self.context

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

    @mock.patch.object(conductor_utils, 'cleaning_error_handler')
    def test_cleanup_cleanwait_timeout_handler_call(self, mock_error_handler):
        self.node.clean_step = {}
        conductor_utils.cleanup_cleanwait_timeout(self.task)

        mock_error_handler.assert_called_once_with(
            self.task,
            msg="Timeout reached while cleaning the node. Please "
                "check if the ramdisk responsible for the cleaning is "
                "running on the node. Failed on step {}.",
            set_fail_state=False)

    def test_cleanup_cleanwait_timeout(self):
        self.node.provision_state = states.CLEANFAIL
        target = 'baz'
        self.node.target_provision_state = target
        self.node.driver_internal_info = {}
        self.node.clean_step = {'key': 'val'}
        clean_error = ("Timeout reached while cleaning the node. Please "
                       "check if the ramdisk responsible for the cleaning is "
                       "running on the node. Failed on step {'key': 'val'}.")
        self.node.driver_internal_info = {
            'cleaning_reboot': True,
            'clean_step_index': 0}
        conductor_utils.cleanup_cleanwait_timeout(self.task)
        self.assertEqual({}, self.node.clean_step)
        self.assertNotIn('clean_step_index', self.node.driver_internal_info)
        self.assertFalse(self.task.process_event.called)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(clean_error, self.node.maintenance_reason)

    def _test_cleaning_error_handler(self, prov_state=states.CLEANING):
        self.node.provision_state = prov_state
        target = 'baz'
        self.node.target_provision_state = target
        self.node.clean_step = {'key': 'val'}
        self.node.driver_internal_info = {
            'cleaning_reboot': True,
            'clean_step_index': 0}
        msg = 'error bar'
        conductor_utils.cleaning_error_handler(self.task, msg)
        self.node.save.assert_called_once_with()
        self.assertEqual({}, self.node.clean_step)
        self.assertNotIn('clean_step_index', self.node.driver_internal_info)
        self.assertEqual(msg, self.node.last_error)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(msg, self.node.maintenance_reason)
        driver = self.task.driver.deploy
        driver.tear_down_cleaning.assert_called_once_with(self.task)
        if prov_state == states.CLEANFAIL:
            self.assertFalse(self.task.process_event.called)
        else:
            self.task.process_event.assert_called_once_with('fail',
                                                            target_state=None)

    def test_cleaning_error_handler(self):
        self._test_cleaning_error_handler()

    def test_cleaning_error_handler_cleanwait(self):
        self._test_cleaning_error_handler(prov_state=states.CLEANWAIT)

    def test_cleaning_error_handler_cleanfail(self):
        self._test_cleaning_error_handler(prov_state=states.CLEANFAIL)

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


class ValidatePortPhysnetTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ValidatePortPhysnetTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context, driver='fake')

    @mock.patch.object(objects.Port, 'obj_what_changed')
    def test_validate_port_physnet_no_portgroup_create(self, mock_owc):
        port = obj_utils.get_test_port(self.context, node_id=self.node.id)
        # NOTE(mgoddard): The port object passed to the conductor will not have
        # a portgroup_id attribute in this case.
        del port.portgroup_id
        with task_manager.acquire(self.context, self.node.uuid) as task:
            conductor_utils.validate_port_physnet(task, port)
        # Verify the early return in the non-portgroup case.
        self.assertFalse(mock_owc.called)

    @mock.patch.object(network, 'get_ports_by_portgroup_id')
    def test_validate_port_physnet_no_portgroup_update(self, mock_gpbpi):
        port = obj_utils.create_test_port(self.context, node_id=self.node.id)
        port.extra = {'foo': 'bar'}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            conductor_utils.validate_port_physnet(task, port)
        # Verify the early return in the no portgroup update case.
        self.assertFalse(mock_gpbpi.called)

    def test_validate_port_physnet_inconsistent_physnets(self):
        # NOTE(mgoddard): This *shouldn't* happen, but let's make sure we can
        # handle it.
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   portgroup_id=portgroup.id,
                                   address='00:11:22:33:44:55',
                                   physical_network='physnet1',
                                   uuid=uuidutils.generate_uuid())
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   portgroup_id=portgroup.id,
                                   address='00:11:22:33:44:56',
                                   physical_network='physnet2',
                                   uuid=uuidutils.generate_uuid())
        port = obj_utils.get_test_port(self.context, node_id=self.node.id,
                                       portgroup_id=portgroup.id,
                                       address='00:11:22:33:44:57',
                                       physical_network='physnet2',
                                       uuid=uuidutils.generate_uuid())

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PortgroupPhysnetInconsistent,
                              conductor_utils.validate_port_physnet,
                              task, port)

    def test_validate_port_physnet_inconsistent_physnets_fix(self):
        # NOTE(mgoddard): This *shouldn't* happen, but let's make sure that if
        # we do get into this state that it is possible to resolve by setting
        # the physical_network correctly.
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        obj_utils.create_test_port(self.context, node_id=self.node.id,
                                   portgroup_id=portgroup.id,
                                   address='00:11:22:33:44:55',
                                   physical_network='physnet1',
                                   uuid=uuidutils.generate_uuid())
        port = obj_utils.create_test_port(self.context, node_id=self.node.id,
                                          portgroup_id=portgroup.id,
                                          address='00:11:22:33:44:56',
                                          physical_network='physnet2',
                                          uuid=uuidutils.generate_uuid())
        port.physical_network = 'physnet1'

        with task_manager.acquire(self.context, self.node.uuid) as task:
            conductor_utils.validate_port_physnet(task, port)

    def _test_validate_port_physnet(self,
                                    num_current_ports,
                                    current_physnet,
                                    new_physnet,
                                    operation,
                                    valid=True):
        """Helper method for testing validate_port_physnet.

        :param num_current_ports: Number of existing ports in the portgroup.
        :param current_physnet: Physical network of existing ports in the
                                portgroup.
        :param new_physnet: Physical network to set on the port that is being
                            created or updated.
        :param operation: The operation to perform. One of 'create', 'update',
                          or 'update_add'. 'create' creates a new port and adds
                          it to the portgroup. 'update' updates one of the
                          existing ports. 'update_add' updates a port and adds
                          it to the portgroup.
        :param valid: Whether the operation is expected to succeed.
        """
        # Prepare existing resources - a node, and a portgroup with optional
        # existing ports.
        port = None
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=self.node.id)
        macs = ("00:11:22:33:44:%02x" % index
                for index in range(num_current_ports + 1))
        for _ in range(num_current_ports):
            # NOTE: When operation == 'update' we update the last port in the
            # portgroup.
            port = obj_utils.create_test_port(
                self.context, node_id=self.node.id, portgroup_id=portgroup.id,
                address=next(macs), physical_network=current_physnet,
                uuid=uuidutils.generate_uuid())

        # Prepare the port on which we are performing the operation.
        if operation == 'create':
            # NOTE(mgoddard): We use db_utils here rather than obj_utils as it
            # allows us to create a Port without a physical_network field, more
            # closely matching what happens during creation of a port when a
            # physical_network is not specified.
            port = db_utils.get_test_port(
                node_id=self.node.id, portgroup_id=portgroup.id,
                address=next(macs), uuid=uuidutils.generate_uuid(),
                physical_network=new_physnet)
            if new_physnet is None:
                del port["physical_network"]
            port = objects.Port(self.context, **port)
        elif operation == 'update_add':
            port = obj_utils.create_test_port(
                self.context, node_id=self.node.id, portgroup_id=None,
                address=next(macs), physical_network=current_physnet,
                uuid=uuidutils.generate_uuid())
            port.portgroup_id = portgroup.id

        if operation != 'create' and new_physnet != current_physnet:
            port.physical_network = new_physnet

        # Perform the validation.
        with task_manager.acquire(self.context, self.node.uuid) as task:
            if valid:
                conductor_utils.validate_port_physnet(task, port)
            else:
                self.assertRaises(exception.Conflict,
                                  conductor_utils.validate_port_physnet,
                                  task, port)

    def _test_validate_port_physnet_create(self, **kwargs):
        self._test_validate_port_physnet(operation='create', **kwargs)

    def _test_validate_port_physnet_update(self, **kwargs):
        self._test_validate_port_physnet(operation='update', **kwargs)

    def _test_validate_port_physnet_update_add(self, **kwargs):
        self._test_validate_port_physnet(operation='update_add', **kwargs)

    # Empty portgroup

    def test_validate_port_physnet_empty_portgroup_create_1(self):
        self._test_validate_port_physnet_create(
            num_current_ports=0,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_empty_portgroup_create_2(self):
        self._test_validate_port_physnet_create(
            num_current_ports=0,
            current_physnet=None,
            new_physnet='physnet1')

    def test_validate_port_physnet_empty_portgroup_update_1(self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=0,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_empty_portgroup_update_2(self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=0,
            current_physnet=None,
            new_physnet='physnet1')

    # 1-port portgroup, no physnet.

    def test_validate_port_physnet_1_port_portgroup_no_physnet_create_1(self):
        self._test_validate_port_physnet_create(
            num_current_ports=1,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_1_port_portgroup_no_physnet_create_2(self):
        self._test_validate_port_physnet_create(
            num_current_ports=1,
            current_physnet=None,
            new_physnet='physnet1',
            valid=False)

    def test_validate_port_physnet_1_port_portgroup_no_physnet_update_1(self):
        self._test_validate_port_physnet_update(
            num_current_ports=1,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_1_port_portgroup_no_physnet_update_2(self):
        self._test_validate_port_physnet_update(
            num_current_ports=1,
            current_physnet=None,
            new_physnet='physnet1')

    def test_validate_port_physnet_1_port_portgroup_no_physnet_update_add_1(
            self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=1,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_1_port_portgroup_no_physnet_update_add_2(
            self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=1,
            current_physnet=None,
            new_physnet='physnet1',
            valid=False)

    # 1-port portgroup, with physnet 'physnet1'.

    def test_validate_port_physnet_1_port_portgroup_w_physnet_create_1(self):
        self._test_validate_port_physnet_create(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet1')

    def test_validate_port_physnet_1_port_portgroup_w_physnet_create_2(self):
        self._test_validate_port_physnet_create(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet2',
            valid=False)

    def test_validate_port_physnet_1_port_portgroup_w_physnet_create_3(self):
        self._test_validate_port_physnet_create(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet=None,
            valid=False)

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_1(self):
        self._test_validate_port_physnet_update(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet1')

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_2(self):
        self._test_validate_port_physnet_update(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet2')

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_3(self):
        self._test_validate_port_physnet_update(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet=None)

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_add_1(
            self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet1')

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_add_2(
            self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet='physnet2',
            valid=False)

    def test_validate_port_physnet_1_port_portgroup_w_physnet_update_add_3(
            self):
        self._test_validate_port_physnet_update_add(
            num_current_ports=1,
            current_physnet='physnet1',
            new_physnet=None,
            valid=False)

    # 2-port portgroup, no physnet

    def test_validate_port_physnet_2_port_portgroup_no_physnet_update_1(self):
        self._test_validate_port_physnet_update(
            num_current_ports=2,
            current_physnet=None,
            new_physnet=None)

    def test_validate_port_physnet_2_port_portgroup_no_physnet_update_2(self):
        self._test_validate_port_physnet_update(
            num_current_ports=2,
            current_physnet=None,
            new_physnet='physnet1',
            valid=False)

    # 2-port portgroup, with physnet 'physnet1'

    def test_validate_port_physnet_2_port_portgroup_w_physnet_update_1(self):
        self._test_validate_port_physnet_update(
            num_current_ports=2,
            current_physnet='physnet1',
            new_physnet='physnet1')

    def test_validate_port_physnet_2_port_portgroup_w_physnet_update_2(self):
        self._test_validate_port_physnet_update(
            num_current_ports=2,
            current_physnet='physnet1',
            new_physnet='physnet2',
            valid=False)

    def test_validate_port_physnet_2_port_portgroup_w_physnet_update_3(self):
        self._test_validate_port_physnet_update(
            num_current_ports=2,
            current_physnet='physnet1',
            new_physnet=None,
            valid=False)
