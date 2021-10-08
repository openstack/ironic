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

import os
import tempfile
import time
from unittest import mock

from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import boot_modes
from ironic.common import exception
from ironic.common import network
from ironic.common import neutron
from ironic.common import nova
from ironic.common import states
from ironic.conductor import rpcapi
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import fake
from ironic import objects
from ironic.objects import fields as obj_fields
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


class TestPowerNoTimeout(drivers_base.PowerInterface):
    """Missing 'timeout' parameter for get_power_state & reboot"""

    def get_properties(self):
        return {}

    def validate(self, task):
        pass

    def get_power_state(self, task):
        return task.node.power_state

    def set_power_state(self, task, power_state, timeout=None):
        task.node.power_state = power_state

    def reboot(self, task):
        pass


class NodeSetBootDeviceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NodeSetBootDeviceTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               uuid=uuidutils.generate_uuid())
        self.task = task_manager.TaskManager(self.context, self.node.uuid)

    def test_node_set_boot_device_non_existent_device(self):
        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.node_set_boot_device,
                          self.task,
                          device='fake')

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    def test_node_set_boot_device_valid(self, mock_sbd):
        conductor_utils.node_set_boot_device(self.task, device='pxe')
        mock_sbd.assert_called_once_with(mock.ANY, self.task,
                                         device='pxe', persistent=False)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    def test_node_set_boot_device_adopting(self, mock_sbd):
        self.task.node.provision_state = states.ADOPTING
        conductor_utils.node_set_boot_device(self.task, device='pxe')
        self.assertFalse(mock_sbd.called)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    def test_node_set_boot_device_force_default(self, mock_sbd):
        # Boolean value False was equivalent to the default
        for value in ('false', False, 'Default'):
            self.task.node.driver_info['force_persistent_boot_device'] = value
            for request in (True, False):
                mock_sbd.reset_mock()
                conductor_utils.node_set_boot_device(self.task, device='pxe',
                                                     persistent=request)
                mock_sbd.assert_called_once_with(mock.ANY, self.task,
                                                 device='pxe',
                                                 persistent=request)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    def test_node_set_boot_device_force_always(self, mock_sbd):
        for value in ('true', True, 'Always'):
            mock_sbd.reset_mock()
            self.task.node.driver_info['force_persistent_boot_device'] = value
            conductor_utils.node_set_boot_device(self.task, device='pxe',
                                                 persistent=False)
            mock_sbd.assert_called_once_with(mock.ANY, self.task,
                                             device='pxe', persistent=True)

    @mock.patch.object(fake.FakeManagement, 'set_boot_device', autospec=True)
    def test_node_set_boot_device_force_never(self, mock_sbd):
        self.task.node.driver_info['force_persistent_boot_device'] = 'Never'
        conductor_utils.node_set_boot_device(self.task, device='pxe',
                                             persistent=True)
        mock_sbd.assert_called_once_with(mock.ANY, self.task,
                                         device='pxe', persistent=False)


class NodeGetBootModeTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NodeGetBootModeTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               uuid=uuidutils.generate_uuid())
        self.task = task_manager.TaskManager(self.context, self.node.uuid)

    @mock.patch.object(fake.FakeManagement, 'get_boot_mode', autospec=True)
    def test_node_get_boot_mode_valid(self, mock_gbm):
        mock_gbm.return_value = 'bios'
        boot_mode = conductor_utils.node_get_boot_mode(self.task)
        self.assertEqual(boot_mode, 'bios')
        mock_gbm.assert_called_once_with(mock.ANY, self.task)

    @mock.patch.object(fake.FakeManagement, 'get_boot_mode', autospec=True)
    def test_node_get_boot_mode_unsupported(self, mock_gbm):
        mock_gbm.side_effect = exception.UnsupportedDriverExtension(
            driver=self.task.node.driver, extension='get_boot_mode')
        self.assertRaises(exception.UnsupportedDriverExtension,
                          conductor_utils.node_get_boot_mode, self.task)


class NodeSetBootModeTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NodeSetBootModeTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               uuid=uuidutils.generate_uuid())
        self.task = task_manager.TaskManager(self.context, self.node.uuid)

    @mock.patch.object(fake.FakeManagement, 'get_supported_boot_modes',
                       autospec=True)
    def test_node_set_boot_mode_non_existent_mode(self, mock_gsbm):

        mock_gsbm.return_value = [boot_modes.LEGACY_BIOS]

        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.node_set_boot_mode,
                          self.task,
                          mode='non-existing')

    @mock.patch.object(fake.FakeManagement, 'set_boot_mode', autospec=True)
    @mock.patch.object(fake.FakeManagement, 'get_supported_boot_modes',
                       autospec=True)
    def test_node_set_boot_mode_valid(self, mock_gsbm, mock_sbm):
        mock_gsbm.return_value = [boot_modes.LEGACY_BIOS]

        conductor_utils.node_set_boot_mode(self.task,
                                           mode=boot_modes.LEGACY_BIOS)
        mock_sbm.assert_called_once_with(mock.ANY, self.task,
                                         mode=boot_modes.LEGACY_BIOS)

    @mock.patch.object(fake.FakeManagement, 'set_boot_mode', autospec=True)
    @mock.patch.object(fake.FakeManagement, 'get_supported_boot_modes',
                       autospec=True)
    def test_node_set_boot_mode_adopting(self, mock_gsbm, mock_sbm):
        mock_gsbm.return_value = [boot_modes.LEGACY_BIOS]

        old_provision_state = self.task.node.provision_state
        self.task.node.provision_state = states.ADOPTING
        try:
            conductor_utils.node_set_boot_mode(self.task,
                                               mode=boot_modes.LEGACY_BIOS)

        finally:
            self.task.node.provision_state = old_provision_state

        self.assertFalse(mock_sbm.called)


class NodePowerActionTestCase(db_base.DbTestCase):
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_on(self, get_power_mock):
        """Test node_power_action to turn node power on."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF

        conductor_utils.node_power_action(task, states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification',
                autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    @mock.patch.object(nova, 'power_update', autospec=True)
    def test_node_power_action_power_on_notify(self, mock_power_update,
                                               get_power_mock,
                                               mock_notif):
        """Test node_power_action to power on node and send notification."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          instance_uuid=uuidutils.uuid,
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF

        conductor_utils.node_power_action(task, states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
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
        mock_power_update.assert_called_once_with(
            task.context, node.instance_uuid, states.POWER_ON)

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_off(self, get_power_mock):
        """Test node_power_action to turn node power off."""
        dii = {'agent_secret_token': 'token',
               'agent_cached_deploy_steps': ['steps']}
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          driver_internal_info=dii)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])
        self.assertNotIn('agent_secret_token', node['driver_internal_info'])
        self.assertNotIn('agent_cached_deploy_steps',
                         node['driver_internal_info'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_off_pregenerated_token(self,
                                                            get_power_mock):
        dii = {'agent_secret_token': 'token',
               'agent_secret_token_pregenerated': True}
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          driver_internal_info=dii)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])
        self.assertEqual('token',
                         node['driver_internal_info']['agent_secret_token'])

    @mock.patch.object(fake.FakePower, 'reboot', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_reboot(self, get_power_mock, reboot_mock):
        """Test for reboot a node."""
        dii = {'agent_secret_token': 'token',
               'agent_cached_deploy_steps': ['steps']}
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          driver_internal_info=dii)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.REBOOT)
        self.assertFalse(get_power_mock.called)

        node.refresh()
        reboot_mock.assert_called_once_with(mock.ANY, mock.ANY, timeout=None)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])
        self.assertNotIn('agent_secret_token', node['driver_internal_info'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_invalid_state(self, get_power_mock):
        """Test for exception when changing to an invalid power state."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

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

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification',
                autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_invalid_state_notify(self, get_power_mock,
                                                    mock_notif):
        """Test for notification when changing to an invalid power state."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

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
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          target_power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertEqual(states.NOSTATE, node['target_power_state'])
        self.assertIsNone(node['last_error'])
        self.assertNotIn('agent_secret_token', node['driver_internal_info'])

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(fake.FakePower, 'set_power_state', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_in_same_state(self, get_power_mock,
                                             set_power_mock, log_mock):
        """Test setting node state to its present state.

        Test that we don't try to set the power state if the requested
        state is the same as the current state.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertFalse(set_power_mock.called,
                         "set_power_state unexpectedly called")
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])
        log_mock.debug.assert_called_once_with(
            u"Not going to change node %(node)s power state because "
            u"current state = requested state = '%(state)s'.",
            {'state': states.POWER_ON, 'node': node.uuid})

    @mock.patch.object(fake.FakePower, 'set_power_state', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_in_same_state_db_not_in_sync(self,
                                                            get_power_mock,
                                                            set_power_mock):
        """Test setting node state to its present state if DB is out of sync.

        Under rare conditions (see bug #1403106) database might contain stale
        information, make sure we fix it.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertFalse(set_power_mock.called,
                         "set_power_state unexpectedly called")
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_failed_getting_state(self, get_power_mock):
        """Test for exception when we can't get the current power state."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.side_effect = (
            exception.InvalidParameterValue('failed getting power state'))

        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.node_power_action,
                          task,
                          states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNotNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification',
                autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_failed_getting_state_notify(self,
                                                           get_power_mock,
                                                           mock_notif):
        """Test for notification when we can't get the current power state."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.side_effect = (
            exception.InvalidParameterValue('failed getting power state'))

        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.node_power_action,
                          task,
                          states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
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

    @mock.patch.object(fake.FakePower, 'set_power_state', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_set_power_failure(self, get_power_mock,
                                                 set_power_mock):
        """Test if an exception is thrown when the set_power call fails."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF
        set_power_mock.side_effect = exception.IronicException()

        self.assertRaises(
            exception.IronicException,
            conductor_utils.node_power_action,
            task,
            states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        set_power_mock.assert_called_once_with(
            mock.ANY, mock.ANY, states.POWER_ON, timeout=None)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNotNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification',
                autospec=True)
    @mock.patch.object(fake.FakePower, 'set_power_state', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_set_power_failure_notify(self, get_power_mock,
                                                        set_power_mock,
                                                        mock_notif):
        """Test if a notification is sent when the set_power call fails."""
        self.config(notification_level='info')
        self.config(host='my-host')
        # Required for exception handling
        mock_notif.__name__ = 'NodeSetPowerStateNotification'
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_OFF)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF
        set_power_mock.side_effect = exception.IronicException()

        self.assertRaises(
            exception.IronicException,
            conductor_utils.node_power_action,
            task,
            states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        set_power_mock.assert_called_once_with(
            mock.ANY, mock.ANY, states.POWER_ON, timeout=None)
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

    @mock.patch.object(fake.FakeStorage, 'attach_volumes', autospec=True)
    def test_node_power_action_power_on_storage_attach(self, attach_mock):
        """Test node_power_action to turn node power on and attach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_OFF,
                                          storage_interface="fake",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.POWER_ON)

        node.refresh()
        attach_mock.assert_called_once_with(mock.ANY, task)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakeStorage, 'attach_volumes', autospec=True)
    def test_node_power_action_reboot_storage_attach(self, attach_mock):
        """Test node_power_action to reboot the node and attach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          storage_interface="fake",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.REBOOT)

        node.refresh()
        attach_mock.assert_called_once_with(mock.ANY, task)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakeStorage, 'detach_volumes', autospec=True)
    def test_node_power_action_power_off_storage_detach(self, detach_mock):
        """Test node_power_action to turn node power off and detach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          storage_interface="fake",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.POWER_OFF)

        node.refresh()
        detach_mock.assert_called_once_with(mock.ANY, task)
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

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test__can_skip_state_change_different_state(self, get_power_mock):
        """Test setting node state to different state.

        Test that we should change state if requested state is different from
        current state.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        result = conductor_utils._can_skip_state_change(
            task, states.POWER_OFF)

        self.assertFalse(result)
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test__can_skip_state_change_same_state(self, get_power_mock, mock_log):
        """Test setting node state to its present state.

        Test that we don't try to set the power state if the requested
        state is the same as the current state.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        result = conductor_utils._can_skip_state_change(
            task, states.POWER_ON)

        self.assertTrue(result)
        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertEqual(states.NOSTATE, node['target_power_state'])
        self.assertIsNone(node['last_error'])
        mock_log.debug.assert_called_once_with(
            u"Not going to change node %(node)s power state because "
            u"current state = requested state = '%(state)s'.",
            {'state': states.POWER_ON, 'node': node.uuid})

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test__can_skip_state_change_db_not_in_sync(self, get_power_mock):
        """Test setting node state to its present state if DB is out of sync.

        Under rare conditions (see bug #1403106) database might contain stale
        information, make sure we fix it.
        """
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          last_error='anything but None',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_OFF

        result = conductor_utils._can_skip_state_change(task, states.POWER_OFF)

        self.assertTrue(result)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertEqual(states.NOSTATE, node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch('ironic.objects.node.NodeSetPowerStateNotification',
                autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test__can_skip_state_change_failed_getting_state_notify(
            self, get_power_mock, mock_notif):
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
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.side_effect = (
            exception.InvalidParameterValue('failed getting power state'))

        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils._can_skip_state_change,
                          task,
                          states.POWER_ON)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
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

    def test_node_power_action_reboot_no_timeout(self):
        """Test node reboot using Power Interface with no timeout arg."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          console_interface='no-console',
                                          inspect_interface='no-inspect',
                                          raid_interface='no-raid',
                                          rescue_interface='no-rescue',
                                          vendor_interface='no-vendor',
                                          bios_interface='no-bios',
                                          power_state=states.POWER_ON)
        self.config(enabled_boot_interfaces=['fake'])
        self.config(enabled_deploy_interfaces=['fake'])
        self.config(enabled_management_interfaces=['fake'])
        self.config(enabled_power_interfaces=['fake'])

        task = task_manager.TaskManager(self.context, node.uuid)
        task.driver.power = TestPowerNoTimeout()
        self.assertRaisesRegex(TypeError,
                               'unexpected keyword argument',
                               conductor_utils.node_power_action,
                               task, states.REBOOT)
        node.refresh()
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIn('unexpected keyword argument', node['last_error'])


class NodeSoftPowerActionTestCase(db_base.DbTestCase):

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_soft_reboot(self, get_power_mock):
        """Test for soft reboot a node."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.SOFT_REBOOT)

        node.refresh()
        self.assertFalse(get_power_mock.called)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_power_soft_reboot_timeout(self, get_power_mock):
        """Test for soft reboot a node."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.SOFT_REBOOT,
                                          timeout=2)

        node.refresh()
        self.assertFalse(get_power_mock.called)
        self.assertEqual(states.POWER_ON, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_soft_power_off(self, get_power_mock):
        """Test node_power_action to turn node soft power off."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.SOFT_POWER_OFF)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    def test_node_power_action_soft_power_off_timeout(self, get_power_mock):
        """Test node_power_action to turn node soft power off."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON)
        task = task_manager.TaskManager(self.context, node.uuid)

        get_power_mock.return_value = states.POWER_ON

        conductor_utils.node_power_action(task, states.SOFT_POWER_OFF,
                                          timeout=2)

        node.refresh()
        get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])

    @mock.patch.object(fake.FakeStorage, 'detach_volumes', autospec=True)
    def test_node_power_action_soft_power_off_storage_detach(self,
                                                             detach_mock):
        """Test node_power_action to soft power off node and detach storage."""
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver='fake-hardware',
                                          power_state=states.POWER_ON,
                                          storage_interface="fake",
                                          provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        conductor_utils.node_power_action(task, states.SOFT_POWER_OFF)

        node.refresh()
        detach_mock.assert_called_once_with(mock.ANY, task)
        self.assertEqual(states.POWER_OFF, node['power_state'])
        self.assertIsNone(node['target_power_state'])
        self.assertIsNone(node['last_error'])


class DeployingErrorHandlerTestCase(db_base.DbTestCase):
    def setUp(self):
        super(DeployingErrorHandlerTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.context = self.context
        self.task.driver = mock.Mock(spec_set=['deploy'])
        self.task.shared = False
        self.task.node = mock.Mock(spec_set=objects.Node)
        self.node = self.task.node
        self.node.provision_state = states.DEPLOYING
        self.node.last_error = None
        self.node.deploy_step = None
        self.node.driver_internal_info = {}
        self.node.id = obj_utils.create_test_node(self.context,
                                                  driver='fake-hardware').id
        self.logmsg = "log message"
        self.errmsg = "err message"

    @mock.patch.object(conductor_utils, 'deploying_error_handler',
                       autospec=True)
    def test_cleanup_after_timeout(self, mock_handler):
        conductor_utils.cleanup_after_timeout(self.task)
        mock_handler.assert_called_once_with(self.task, mock.ANY, mock.ANY)

    def test_cleanup_after_timeout_shared_lock(self):
        self.task.shared = True

        self.assertRaises(exception.ExclusiveLockRequired,
                          conductor_utils.cleanup_after_timeout,
                          self.task)

    def test_deploying_error_handler(self):
        info = self.node.driver_internal_info
        info['deploy_step_index'] = 2
        info['deployment_reboot'] = True
        info['deployment_polling'] = True
        info['skip_current_deploy_step'] = True
        info['agent_url'] = 'url'
        conductor_utils.deploying_error_handler(self.task, self.logmsg,
                                                self.errmsg)

        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual(self.errmsg, self.node.last_error)
        self.assertEqual({}, self.node.deploy_step)
        self.assertNotIn('deploy_step_index', self.node.driver_internal_info)
        self.assertNotIn('deployment_reboot', self.node.driver_internal_info)
        self.assertNotIn('deployment_polling', self.node.driver_internal_info)
        self.assertNotIn('skip_current_deploy_step',
                         self.node.driver_internal_info)
        self.assertNotIn('agent_url', self.node.driver_internal_info)
        self.task.process_event.assert_called_once_with('fail')

    def _test_deploying_error_handler_cleanup(self, exc, expected_str):
        clean_up_mock = self.task.driver.deploy.clean_up
        clean_up_mock.side_effect = exc

        conductor_utils.deploying_error_handler(self.task, self.logmsg,
                                                self.errmsg)

        self.task.driver.deploy.clean_up.assert_called_once_with(self.task)
        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertIn(expected_str, self.node.last_error)
        self.assertEqual({}, self.node.deploy_step)
        self.assertNotIn('deploy_step_index', self.node.driver_internal_info)
        self.task.process_event.assert_called_once_with('fail')
        self.assertIsNotNone(self.node.last_error)

    def test_deploying_error_handler_cleanup_ironic_exception(self):
        self._test_deploying_error_handler_cleanup(
            exception.IronicException('moocow'), 'moocow')

    def test_deploying_error_handler_cleanup_random_exception(self):
        self._test_deploying_error_handler_cleanup(
            Exception('moocow'), 'unhandled exception')

    def test_deploying_error_handler_no_cleanup(self):
        conductor_utils.deploying_error_handler(
            self.task, self.logmsg, self.errmsg, clean_up=False)

        self.assertFalse(self.task.driver.deploy.clean_up.called)
        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertEqual(self.errmsg, self.node.last_error)
        self.assertEqual({}, self.node.deploy_step)
        self.assertNotIn('deploy_step_index', self.node.driver_internal_info)
        self.task.process_event.assert_called_once_with('fail')

    def test_deploying_error_handler_not_deploy(self):
        # Not in a deploy state
        self.node.provision_state = states.AVAILABLE
        self.node.driver_internal_info['deploy_step_index'] = 2

        conductor_utils.deploying_error_handler(
            self.task, self.logmsg, self.errmsg, clean_up=False)

        self.assertEqual([mock.call()] * 2, self.node.save.call_args_list)
        self.assertEqual(self.errmsg, self.node.last_error)
        self.assertIsNone(self.node.deploy_step)
        self.assertIn('deploy_step_index', self.node.driver_internal_info)
        self.task.process_event.assert_called_once_with('fail')


class ErrorHandlersTestCase(db_base.DbTestCase):
    def setUp(self):
        super(ErrorHandlersTestCase, self).setUp()
        self.task = mock.Mock(spec=task_manager.TaskManager)
        self.task.driver = mock.Mock(spec_set=['deploy', 'network', 'rescue'])
        self.task.node = mock.Mock(spec_set=objects.Node)
        self.task.shared = False
        self.node = self.task.node
        # NOTE(mariojv) Some of the test cases that use the task below require
        # strict typing of the node power state fields and would fail if passed
        # a Mock object in constructors. A task context is also required for
        # notifications.
        fake_node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')

        self.node.configure_mock(power_state=states.POWER_OFF,
                                 target_power_state=states.POWER_ON,
                                 maintenance=False, maintenance_reason=None,
                                 id=fake_node.id)
        self.task.context = self.context

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_provision_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.provisioning_error_handler(exc, self.node, 'state-one',
                                                   'state-two')
        self.node.save.assert_called_once_with()
        self.assertEqual('state-one', self.node.provision_state)
        self.assertEqual('state-two', self.node.target_provision_state)
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_provision_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.provisioning_error_handler(exc, self.node, 'state-one',
                                                   'state-two')
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'cleaning_error_handler',
                       autospec=True)
    def test_cleanup_cleanwait_timeout_handler_call(self, mock_error_handler):
        self.task.node.uuid = '18c95393-b775-4887-a274-c45be47509d5'
        self.node.clean_step = {}
        conductor_utils.cleanup_cleanwait_timeout(self.task)

        mock_error_handler.assert_called_once_with(
            self.task,
            logmsg="Cleaning for node 18c95393-b775-4887-a274-c45be47509d5 "
                   "failed. Timeout reached while cleaning the node. Please "
                   "check if the ramdisk responsible for the cleaning is "
                   "running on the node. Failed on step {}.",
            errmsg="Timeout reached while cleaning the node. Please "
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
        self.assertEqual('clean failure', self.node.fault)

    @mock.patch.object(conductor_utils.LOG, 'error', autospec=True)
    def _test_cleaning_error_handler(self, mock_log_error,
                                     prov_state=states.CLEANING):
        self.node.provision_state = prov_state
        target = 'baz'
        self.node.target_provision_state = target
        self.node.clean_step = {'key': 'val'}
        self.node.driver_internal_info = {
            'cleaning_reboot': True,
            'cleaning_polling': True,
            'skip_current_clean_step': True,
            'clean_step_index': 0,
            'agent_url': 'url'}
        msg = 'error bar'
        last_error = "last error"
        conductor_utils.cleaning_error_handler(self.task, msg,
                                               errmsg=last_error)
        self.node.save.assert_called_once_with()
        self.assertEqual({}, self.node.clean_step)
        self.assertNotIn('clean_step_index', self.node.driver_internal_info)
        self.assertNotIn('cleaning_reboot', self.node.driver_internal_info)
        self.assertNotIn('cleaning_polling', self.node.driver_internal_info)
        self.assertNotIn('skip_current_clean_step',
                         self.node.driver_internal_info)
        self.assertEqual(last_error, self.node.last_error)
        self.assertTrue(self.node.maintenance)
        self.assertEqual(last_error, self.node.maintenance_reason)
        self.assertEqual('clean failure', self.node.fault)
        driver = self.task.driver.deploy
        driver.tear_down_cleaning.assert_called_once_with(self.task)
        if prov_state == states.CLEANFAIL:
            self.assertFalse(self.task.process_event.called)
        else:
            self.task.process_event.assert_called_once_with('fail',
                                                            target_state=None)
        self.assertNotIn('agent_url', self.node.driver_internal_info)
        mock_log_error.assert_called_once_with(msg, exc_info=False)

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

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_cleaning_error_handler_tear_down_error(self, log_mock):
        def _side_effect(task):
            # simulate overwriting last error by another operation (e.g. power)
            task.node.last_error = None
            raise Exception('bar')

        driver = self.task.driver.deploy
        msg = 'foo'
        driver.tear_down_cleaning.side_effect = _side_effect
        conductor_utils.cleaning_error_handler(self.task, msg)
        log_mock.error.assert_called_once_with(msg, exc_info=False)
        self.assertTrue(log_mock.exception.called)
        self.assertIn(msg, self.node.last_error)
        self.assertIn(msg, self.node.maintenance_reason)
        self.assertEqual('clean failure', self.node.fault)

    def test_abort_on_conductor_take_over_cleaning(self):
        self.node.provision_state = states.CLEANFAIL
        conductor_utils.abort_on_conductor_take_over(self.task)
        self.assertTrue(self.node.maintenance)
        self.assertIn('take over', self.node.maintenance_reason)
        self.assertIn('take over', self.node.last_error)
        self.assertEqual('clean failure', self.node.fault)
        self.task.driver.deploy.tear_down_cleaning.assert_called_once_with(
            self.task)
        self.node.save.assert_called_once_with()

    def test_abort_on_conductor_take_over_deploying(self):
        self.node.provision_state = states.DEPLOYFAIL
        conductor_utils.abort_on_conductor_take_over(self.task)
        self.assertFalse(self.node.maintenance)
        self.assertIn('take over', self.node.last_error)
        self.node.save.assert_called_once_with()

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_cleaning_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.spawn_cleaning_error_handler(exc, self.node)
        self.node.save.assert_called_once_with()
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_cleaning_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.spawn_cleaning_error_handler(exc, self.node)
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_deploying_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.spawn_deploying_error_handler(exc, self.node)
        self.node.save.assert_called_once_with()
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_deploying_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.spawn_deploying_error_handler(exc, self.node)
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_rescue_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        self.node.instance_info = {'rescue_password': 'pass',
                                   'hashed_rescue_password': '12'}
        conductor_utils.spawn_rescue_error_handler(exc, self.node)
        self.node.save.assert_called_once_with()
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)
        self.assertNotIn('rescue_password', self.node.instance_info)
        self.assertNotIn('hashed_rescue_password', self.node.instance_info)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_spawn_rescue_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        self.node.instance_info = {'rescue_password': 'pass',
                                   'hashed_rescue_password': '12'}
        conductor_utils.spawn_rescue_error_handler(exc, self.node)
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)
        self.assertIn('rescue_password', self.node.instance_info)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_power_state_error_handler_no_worker(self, log_mock):
        exc = exception.NoFreeConductorWorker()
        conductor_utils.power_state_error_handler(exc, self.node, 'newstate')
        self.node.save.assert_called_once_with()
        self.assertEqual('newstate', self.node.power_state)
        self.assertEqual(states.NOSTATE, self.node.target_power_state)
        self.assertIn('No free conductor workers', self.node.last_error)
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    def test_power_state_error_handler_other_error(self, log_mock):
        exc = Exception('foo')
        conductor_utils.power_state_error_handler(exc, self.node, 'foo')
        self.assertFalse(self.node.save.called)
        self.assertFalse(log_mock.warning.called)

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_cleanup_rescuewait_timeout(self, node_power_mock, log_mock):
        conductor_utils.cleanup_rescuewait_timeout(self.task)
        self.assertTrue(log_mock.error.called)
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        self.assertIn('Timeout reached', self.node.last_error)
        self.node.save.assert_called_once_with()

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_cleanup_rescuewait_timeout_known_exc(
            self, node_power_mock, log_mock):
        clean_up_mock = self.task.driver.rescue.clean_up
        clean_up_mock.side_effect = exception.IronicException('moocow')
        conductor_utils.cleanup_rescuewait_timeout(self.task)
        self.assertEqual(2, log_mock.error.call_count)
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        self.assertIn('moocow', self.node.last_error)
        self.node.save.assert_called_once_with()

    @mock.patch.object(conductor_utils, 'LOG', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_cleanup_rescuewait_timeout_unknown_exc(
            self, node_power_mock, log_mock):
        clean_up_mock = self.task.driver.rescue.clean_up
        clean_up_mock.side_effect = Exception('moocow')
        conductor_utils.cleanup_rescuewait_timeout(self.task)
        self.assertTrue(log_mock.error.called)
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        self.assertIn('Rescue failed', self.node.last_error)
        self.node.save.assert_called_once_with()
        self.assertTrue(log_mock.exception.called)

    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def _test_rescuing_error_handler(self, node_power_mock,
                                     set_state=True):
        self.node.provision_state = states.RESCUEWAIT
        self.node.driver_internal_info.update({'agent_url': 'url'})
        conductor_utils.rescuing_error_handler(self.task,
                                               'some exception for node',
                                               set_fail_state=set_state)
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        self.node.save.assert_called_once_with()
        self.assertNotIn('agent_url', self.node.driver_internal_info)
        if set_state:
            self.assertTrue(self.task.process_event.called)
        else:
            self.assertFalse(self.task.process_event.called)

    def test_rescuing_error_handler(self):
        self._test_rescuing_error_handler()

    def test_rescuing_error_handler_set_failed_state_false(self):
        self._test_rescuing_error_handler(set_state=False)

    @mock.patch.object(conductor_utils.LOG, 'error', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_rescuing_error_handler_ironic_exc(self, node_power_mock,
                                               log_mock):
        self.node.provision_state = states.RESCUEWAIT
        expected_exc = exception.IronicException('moocow')
        clean_up_mock = self.task.driver.rescue.clean_up
        clean_up_mock.side_effect = expected_exc
        conductor_utils.rescuing_error_handler(self.task,
                                               'some exception for node')
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        log_mock.assert_called_once_with('Rescue operation was unsuccessful, '
                                         'clean up failed for node %(node)s: '
                                         '%(error)s',
                                         {'node': self.node.uuid,
                                          'error': expected_exc})
        self.node.save.assert_called_once_with()

    @mock.patch.object(conductor_utils.LOG, 'exception', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_rescuing_error_handler_other_exc(self, node_power_mock,
                                              log_mock):
        self.node.provision_state = states.RESCUEWAIT
        expected_exc = RuntimeError()
        clean_up_mock = self.task.driver.rescue.clean_up
        clean_up_mock.side_effect = expected_exc
        conductor_utils.rescuing_error_handler(self.task,
                                               'some exception for node')
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        log_mock.assert_called_once_with('Rescue failed for node '
                                         '%(node)s, an exception was '
                                         'encountered while aborting.',
                                         {'node': self.node.uuid})
        self.assertIsNotNone(self.node.last_error)
        self.node.save.assert_called_once_with()

    @mock.patch.object(conductor_utils.LOG, 'error', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action', autospec=True)
    def test_rescuing_error_handler_bad_state(self, node_power_mock,
                                              log_mock):
        self.node.provision_state = states.RESCUE
        self.task.process_event.side_effect = exception.InvalidState
        expected_exc = exception.IronicException('moocow')
        clean_up_mock = self.task.driver.rescue.clean_up
        clean_up_mock.side_effect = expected_exc
        conductor_utils.rescuing_error_handler(self.task,
                                               'some exception for node')
        node_power_mock.assert_called_once_with(mock.ANY, states.POWER_OFF)
        self.task.driver.rescue.clean_up.assert_called_once_with(self.task)
        self.task.process_event.assert_called_once_with('fail')
        log_calls = [mock.call('Rescue operation was unsuccessful, clean up '
                               'failed for node %(node)s: %(error)s',
                               {'node': self.node.uuid,
                                'error': expected_exc}),
                     mock.call('Internal error. Node %(node)s in provision '
                               'state "%(state)s" could not transition to a '
                               'failed state.',
                               {'node': self.node.uuid,
                                'state': self.node.provision_state})]
        log_mock.assert_has_calls(log_calls)
        self.node.save.assert_called_once_with()


class ValidatePortPhysnetTestCase(db_base.DbTestCase):

    def setUp(self):
        super(ValidatePortPhysnetTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')

    @mock.patch.object(objects.Port, 'obj_what_changed', autospec=True)
    def test_validate_port_physnet_no_portgroup_create(self, mock_owc):
        port = obj_utils.get_test_port(self.context, node_id=self.node.id)
        # NOTE(mgoddard): The port object passed to the conductor will not have
        # a portgroup_id attribute in this case.
        del port.portgroup_id
        with task_manager.acquire(self.context, self.node.uuid) as task:
            conductor_utils.validate_port_physnet(task, port)
        # Verify the early return in the non-portgroup case.
        self.assertFalse(mock_owc.called)

    @mock.patch.object(network, 'get_ports_by_portgroup_id', autospec=True)
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


class MiscTestCase(db_base.DbTestCase):
    def setUp(self):
        super(MiscTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake-hardware',
            instance_info={'rescue_password': 'pass'})

    def _test_remove_node_rescue_password(self, save=True):
        conductor_utils.remove_node_rescue_password(self.node, save=save)
        self.assertNotIn('rescue_password', self.node.instance_info)
        self.node.refresh()
        if save:
            self.assertNotIn('rescue_password', self.node.instance_info)
        else:
            self.assertIn('rescue_password', self.node.instance_info)

    def test_remove_node_rescue_password_save_true(self):
        self._test_remove_node_rescue_password(save=True)

    def test_remove_node_rescue_password_save_false(self):
        self._test_remove_node_rescue_password(save=False)

    @mock.patch.object(rpcapi.ConductorAPI, 'continue_node_deploy',
                       autospec=True)
    def test_notify_conductor_resume_operation(self, mock_rpc_call):
        self.config(host='fake-host')
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_utils.notify_conductor_resume_operation(task, 'deploy')
            mock_rpc_call.assert_called_once_with(
                mock.ANY, task.context, self.node.uuid,
                topic='ironic.conductor_manager.fake-host')

    @mock.patch.object(conductor_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    def test_notify_conductor_resume_clean(self, mock_resume):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_utils.notify_conductor_resume_clean(task)
            mock_resume.assert_called_once_with(task, 'clean')

    @mock.patch.object(conductor_utils, 'notify_conductor_resume_operation',
                       autospec=True)
    def test_notify_conductor_resume_deploy(self, mock_resume):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_utils.notify_conductor_resume_deploy(task)
            mock_resume.assert_called_once_with(task, 'deploy')

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    @mock.patch.object(drivers_base.NetworkInterface, 'need_power_on',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_power_on_node_if_needed_true(
            self, power_action_mock, boot_device_mock,
            need_power_on_mock, get_power_state_mock, time_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            need_power_on_mock.return_value = True
            get_power_state_mock.return_value = states.POWER_OFF
            power_state = conductor_utils.power_on_node_if_needed(task)
            self.assertEqual(power_state, states.POWER_OFF)
            boot_device_mock.assert_called_once_with(
                task, boot_devices.BIOS, persistent=False)
            power_action_mock.assert_called_once_with(task, states.POWER_ON)

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    @mock.patch.object(drivers_base.NetworkInterface, 'need_power_on',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_power_on_node_if_needed_false_power_on(
            self, power_action_mock, boot_device_mock,
            need_power_on_mock, get_power_state_mock, time_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            need_power_on_mock.return_value = True
            get_power_state_mock.return_value = states.POWER_ON
            power_state = conductor_utils.power_on_node_if_needed(task)
            self.assertIsNone(power_state)
            self.assertEqual(0, boot_device_mock.call_count)
            self.assertEqual(0, power_action_mock.call_count)

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    @mock.patch.object(drivers_base.NetworkInterface, 'need_power_on',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_power_on_node_if_needed_false_no_need(
            self, power_action_mock, boot_device_mock,
            need_power_on_mock, get_power_state_mock, time_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            need_power_on_mock.return_value = False
            get_power_state_mock.return_value = states.POWER_OFF
            power_state = conductor_utils.power_on_node_if_needed(task)
            self.assertIsNone(power_state)
            self.assertEqual(0, boot_device_mock.call_count)
            self.assertEqual(0, power_action_mock.call_count)

    @mock.patch.object(neutron, 'get_client', autospec=True)
    @mock.patch.object(neutron, 'wait_for_host_agent', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
    @mock.patch.object(drivers_base.NetworkInterface, 'need_power_on',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_set_boot_device',
                       autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_power_on_node_if_needed_with_smart_nic_port(
            self, power_action_mock, boot_device_mock,
            need_power_on_mock, get_power_state_mock, time_mock,
            wait_agent_mock, get_client_mock):
        llc = {'port_id': 'rep0-0', 'hostname': 'host1'}
        port = obj_utils.get_test_port(self.context, node_id=self.node.id,
                                       is_smartnic=True,
                                       local_link_connection=llc)
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            task.ports = [port]
            need_power_on_mock.return_value = True
            get_power_state_mock.return_value = states.POWER_OFF
            power_state = conductor_utils.power_on_node_if_needed(task)
            self.assertEqual(power_state, states.POWER_OFF)
            boot_device_mock.assert_called_once_with(
                task, boot_devices.BIOS, persistent=False)
            power_action_mock.assert_called_once_with(task, states.POWER_ON)
            get_client_mock.assert_called_once_with(context=self.context)
            wait_agent_mock.assert_called_once_with(mock.ANY, 'host1',
                                                    target_state='down')

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_restore_power_state_if_needed_true(
            self, power_action_mock, time_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            power_state = states.POWER_OFF
            conductor_utils.restore_power_state_if_needed(task, power_state)
            power_action_mock.assert_called_once_with(task, power_state)

    @mock.patch.object(time, 'sleep', autospec=True)
    @mock.patch.object(conductor_utils, 'node_power_action',
                       autospec=True)
    def test_restore_power_state_if_needed_false(
            self, power_action_mock, time_mock):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            power_state = None
            conductor_utils.restore_power_state_if_needed(task, power_state)
            self.assertEqual(0, power_action_mock.call_count)


class ValidateInstanceInfoTraitsTestCase(tests_base.TestCase):

    def setUp(self):
        super(ValidateInstanceInfoTraitsTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware',
                                            traits=['trait1', 'trait2'])

    def test_validate_instance_info_traits_no_instance_traits(self):
        conductor_utils.validate_instance_info_traits(self.node)

    def test_validate_instance_info_traits_empty_instance_traits(self):
        self.node.instance_info['traits'] = []
        conductor_utils.validate_instance_info_traits(self.node)

    def test_validate_instance_info_traits_invalid_type(self):
        self.node.instance_info['traits'] = 'not-a-list'
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Error parsing traits from Node',
                               conductor_utils.validate_instance_info_traits,
                               self.node)

    def test_validate_instance_info_traits_invalid_trait_type(self):
        self.node.instance_info['traits'] = ['trait1', {}]
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Error parsing traits from Node',
                               conductor_utils.validate_instance_info_traits,
                               self.node)

    def test_validate_instance_info_traits(self):
        self.node.instance_info['traits'] = ['trait1', 'trait2']
        conductor_utils.validate_instance_info_traits(self.node)

    def test_validate_instance_info_traits_missing(self):
        self.node.instance_info['traits'] = ['trait1', 'trait3']
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Cannot specify instance traits that are not',
                               conductor_utils.validate_instance_info_traits,
                               self.node)


@mock.patch.object(fake.FakePower, 'get_power_state', autospec=True)
class FastTrackTestCase(db_base.DbTestCase):

    def setUp(self):
        super(FastTrackTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            uuid=uuidutils.generate_uuid(),
            driver_internal_info={
                'agent_last_heartbeat': str(timeutils.utcnow().isoformat()),
                'agent_url': 'a_url'})
        self.config(fast_track=True, group='deploy')

    def test_is_fast_track(self, mock_get_power):
        mock_get_power.return_value = states.POWER_ON
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertTrue(conductor_utils.is_fast_track(task))

    def test_is_fast_track_config_false(self, mock_get_power):
        self.config(fast_track=False, group='deploy')
        mock_get_power.return_value = states.POWER_ON
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(conductor_utils.is_fast_track(task))

    def test_is_fast_track_power_off_false(self, mock_get_power):
        mock_get_power.return_value = states.POWER_OFF
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(conductor_utils.is_fast_track(task))

    def test_is_fast_track_no_heartbeat(self, mock_get_power):
        mock_get_power.return_value = states.POWER_ON
        i_info = self.node.driver_internal_info
        i_info.pop('agent_last_heartbeat')
        self.node.driver_internal_info = i_info
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(conductor_utils.is_fast_track(task))

    def test_is_fast_track_powered_after_heartbeat(self, mock_get_power):
        mock_get_power.return_value = states.POWER_ON
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            conductor_utils.node_power_action(task, states.POWER_OFF)
            conductor_utils.node_power_action(task, states.POWER_ON)
            self.assertFalse(conductor_utils.is_fast_track(task))

    def test_is_fast_track_error_blocks(self, mock_get_power):
        mock_get_power.return_value = states.POWER_ON
        self.node.last_error = "bad things happened"
        self.node.save()
        with task_manager.acquire(
                self.context, self.node.uuid, shared=False) as task:
            self.assertFalse(conductor_utils.is_fast_track(task))


class GetNodeNextStepsTestCase(db_base.DbTestCase):
    def setUp(self):
        super(GetNodeNextStepsTestCase, self).setUp()
        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy'}
        # Automated cleaning should be executed in this order
        self.clean_steps = [self.deploy_erase, self.power_update,
                            self.deploy_update]
        self.deploy_start = {
            'step': 'deploy_start', 'priority': 50, 'interface': 'deploy'}
        self.deploy_end = {
            'step': 'deploy_end', 'priority': 20, 'interface': 'deploy'}
        self.deploy_steps = [self.deploy_start, self.deploy_end]

    def _test_get_node_next_deploy_steps(self, skip=True):
        driver_internal_info = {'deploy_steps': self.deploy_steps,
                                'deploy_step_index': 0}
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYWAIT,
            target_provision_state=states.ACTIVE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            deploy_step=self.deploy_steps[0])

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = conductor_utils.get_node_next_deploy_steps(
                task, skip_current_step=skip)
            expected_index = 1 if skip else 0
            self.assertEqual(expected_index, step_index)

    def test_get_node_next_deploy_steps(self):
        self._test_get_node_next_deploy_steps()

    def test_get_node_next_deploy_steps_no_skip(self):
        self._test_get_node_next_deploy_steps(skip=False)

    def test_get_node_next_deploy_steps_unset_deploy_step(self):
        driver_internal_info = {'deploy_steps': self.deploy_steps,
                                'deploy_step_index': None}
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.DEPLOYWAIT,
            target_provision_state=states.ACTIVE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            deploy_step=None)

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = conductor_utils.get_node_next_deploy_steps(task)
            self.assertEqual(0, step_index)

    def test_get_node_next_steps_exception(self):
        node = obj_utils.create_test_node(self.context)

        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.Invalid,
                              conductor_utils._get_node_next_steps,
                              task, 'foo')

    def _test_get_node_next_clean_steps(self, skip=True):
        driver_internal_info = {'clean_steps': self.clean_steps,
                                'clean_step_index': 0}
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            clean_step=self.clean_steps[0])

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = conductor_utils.get_node_next_clean_steps(
                task, skip_current_step=skip)
            expected_index = 1 if skip else 0
            self.assertEqual(expected_index, step_index)

    def test_get_node_next_clean_steps(self):
        self._test_get_node_next_clean_steps()

    def test_get_node_next_clean_steps_no_skip(self):
        self._test_get_node_next_clean_steps(skip=False)

    def test_get_node_next_clean_steps_unset_clean_step(self):
        driver_internal_info = {'clean_steps': self.clean_steps,
                                'clean_step_index': None}
        node = obj_utils.create_test_node(
            self.context, driver='fake-hardware',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            clean_step=None)

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = conductor_utils.get_node_next_clean_steps(task)
            self.assertEqual(0, step_index)


class AgentTokenUtilsTestCase(tests_base.TestCase):

    def setUp(self):
        super(AgentTokenUtilsTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context,
                                            driver='fake-hardware')

    def test_add_secret_token(self):
        self.assertNotIn('agent_secret_token', self.node.driver_internal_info)
        conductor_utils.add_secret_token(self.node)
        self.assertIn('agent_secret_token', self.node.driver_internal_info)

    def test_wipe_deploy_internal_info(self):
        conductor_utils.add_secret_token(self.node)
        self.assertIn('agent_secret_token', self.node.driver_internal_info)
        conductor_utils.wipe_deploy_internal_info(mock.Mock(node=self.node))
        self.assertNotIn('agent_secret_token', self.node.driver_internal_info)

    def test_is_agent_token_present(self):
        # This should always be False as the token has not been added yet.
        self.assertFalse(conductor_utils.is_agent_token_present(self.node))
        conductor_utils.add_secret_token(self.node)
        self.assertTrue(conductor_utils.is_agent_token_present(self.node))


class GetAttachedVifTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetAttachedVifTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')
        self.port = obj_utils.get_test_port(self.context,
                                            node_id=self.node.id)

    def test_get_attached_vif_none(self):
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertIsNone(vif)
        self.assertIsNone(use)

    def test_get_attached_vif_tenant(self):
        self.port.internal_info = {'tenant_vif_port_id': '1'}
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertEqual('1', vif)
        self.assertEqual('tenant', use)

    def test_get_attached_vif_provisioning(self):
        self.port.internal_info = {'provisioning_vif_port_id': '1'}
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertEqual('1', vif)
        self.assertEqual('provisioning', use)

    def test_get_attached_vif_cleaning(self):
        self.port.internal_info = {'cleaning_vif_port_id': '1'}
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertEqual('1', vif)
        self.assertEqual('cleaning', use)

    def test_get_attached_vif_rescuing(self):
        self.port.internal_info = {'rescuing_vif_port_id': '1'}
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertEqual('1', vif)
        self.assertEqual('rescuing', use)

    def test_get_attached_vif_inspecting(self):
        self.port.internal_info = {'inspection_vif_port_id': '1'}
        vif, use = conductor_utils.get_attached_vif(self.port)
        self.assertEqual('1', vif)
        self.assertEqual('inspecting', use)


class StoreAgentCertificateTestCase(db_base.DbTestCase):

    def setUp(self):
        super(StoreAgentCertificateTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware')
        self.tempdir = tempfile.mkdtemp()
        CONF.set_override('certificates_path', self.tempdir, group='agent')
        self.fname = os.path.join(self.tempdir, '%s.crt' % self.node.uuid)

    def test_store_new(self):
        result = conductor_utils.store_agent_certificate(self.node,
                                                         'cert text')
        self.assertEqual(self.fname, result)
        with open(self.fname, 'rt') as fp:
            self.assertEqual('cert text', fp.read())

    def test_store_existing(self):
        old_fname = os.path.join(self.tempdir, 'old.crt')
        with open(old_fname, 'wt') as fp:
            fp.write('cert text')

        self.node.driver_internal_info['agent_verify_ca'] = old_fname
        result = conductor_utils.store_agent_certificate(self.node,
                                                         'cert text')
        self.assertEqual(old_fname, result)
        self.assertFalse(os.path.exists(self.fname))

    def test_no_change(self):
        old_fname = os.path.join(self.tempdir, 'old.crt')
        with open(old_fname, 'wt') as fp:
            fp.write('cert text')

        self.node.driver_internal_info['agent_verify_ca'] = old_fname
        self.assertRaises(exception.InvalidParameterValue,
                          conductor_utils.store_agent_certificate,
                          self.node, 'new cert text')
        self.assertFalse(os.path.exists(self.fname))

    def test_take_over(self):
        old_fname = os.path.join(self.tempdir, 'old.crt')
        self.node.driver_internal_info['agent_verify_ca'] = old_fname
        result = conductor_utils.store_agent_certificate(self.node,
                                                         'cert text')
        self.assertEqual(self.fname, result)
        with open(self.fname, 'rt') as fp:
            self.assertEqual('cert text', fp.read())


@mock.patch.object(fake.FakeManagement, 'detect_vendor', autospec=True,
                   return_value="Fake Inc.")
class CacheVendorTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CacheVendorTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               properties={})

    def test_ok(self, mock_detect):
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_vendor(task)
            self.assertFalse(task.shared)
            mock_detect.assert_called_once_with(task.driver.management, task)

        self.node.refresh()
        self.assertEqual("Fake Inc.", self.node.properties['vendor'])

    def test_already_present(self, mock_detect):
        self.node.properties = {'vendor': "Fake GmbH"}
        self.node.save()

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_vendor(task)
            self.assertTrue(task.shared)

        self.node.refresh()
        self.assertEqual("Fake GmbH", self.node.properties['vendor'])
        self.assertFalse(mock_detect.called)

    def test_empty(self, mock_detect):
        mock_detect.return_value = None
        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_vendor(task)
            self.assertTrue(task.shared)
            mock_detect.assert_called_once_with(task.driver.management, task)

        self.node.refresh()
        self.assertNotIn('vendor', self.node.properties)

    @mock.patch.object(conductor_utils.LOG, 'warning', autospec=True)
    def test_unsupported(self, mock_log, mock_detect):
        mock_detect.side_effect = exception.UnsupportedDriverExtension

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_vendor(task)
            self.assertTrue(task.shared)
            mock_detect.assert_called_once_with(task.driver.management, task)

        self.node.refresh()
        self.assertNotIn('vendor', self.node.properties)
        self.assertFalse(mock_log.called)

    @mock.patch.object(conductor_utils.LOG, 'warning', autospec=True)
    def test_failed(self, mock_log, mock_detect):
        mock_detect.side_effect = RuntimeError

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_vendor(task)
            self.assertTrue(task.shared)
            mock_detect.assert_called_once_with(task.driver.management, task)

        self.node.refresh()
        self.assertNotIn('vendor', self.node.properties)
        self.assertTrue(mock_log.called)


@mock.patch.object(fake.FakeManagement, 'get_secure_boot_state',
                   autospec=True)
@mock.patch.object(fake.FakeManagement, 'get_boot_mode',
                   autospec=True)
class CacheBootModeTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CacheBootModeTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               properties={})

    def test_noneness(self, mock_get_boot, mock_get_secure):
        mock_get_boot.return_value = None
        mock_get_secure.return_value = None

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # If nothing to save, lock needn't be upgraded
            self.assertTrue(task.shared)

        self.node.refresh()
        self.assertIsNone(self.node.boot_mode)
        self.assertIsNone(self.node.secure_boot)

    def test_unsupported(self, mock_get_boot, mock_get_secure):
        mock_get_boot.side_effect = exception.UnsupportedDriverExtension
        mock_get_secure.side_effect = exception.UnsupportedDriverExtension

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # If nothing to save, lock needn't be upgraded
            self.assertTrue(task.shared)

        self.node.refresh()
        self.assertIsNone(self.node.boot_mode)
        self.assertIsNone(self.node.secure_boot)

    def test_retreive_and_set(self, mock_get_boot, mock_get_secure):
        mock_get_boot.return_value = "fake-efi"
        mock_get_secure.return_value = True

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # Verify it upgraded lock
            self.assertFalse(task.shared)

        self.node.refresh()
        self.assertEqual("fake-efi", self.node.boot_mode)
        self.assertTrue(self.node.secure_boot)

    def test_already_present(self, mock_get_boot, mock_get_secure):
        self.node.boot_mode = "fake-efi"
        self.node.secure_boot = True
        self.node.save()

        mock_get_boot.return_value = "fake-efi"
        mock_get_secure.return_value = True

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # If no changes, lock needn't be upgraded
            self.assertTrue(task.shared)

        self.node.refresh()
        self.assertEqual("fake-efi", self.node.boot_mode)
        self.assertTrue(self.node.secure_boot)

    def test_change_secure_off(self, mock_get_boot, mock_get_secure):
        self.node.boot_mode = "fake-efi"
        self.node.secure_boot = True
        self.node.save()

        mock_get_boot.return_value = "fake-efi"
        mock_get_secure.return_value = False

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # Verify it upgraded lock
            self.assertFalse(task.shared)

        self.node.refresh()
        self.assertEqual("fake-efi", self.node.boot_mode)
        self.assertFalse(self.node.secure_boot)

    def test_change_secure_off_to_none(self, mock_get_boot, mock_get_secure):
        # Check that False and None are treated as distinct
        # Say during a transition from uefi to bios
        self.node.boot_mode = "fake-hybrid"
        self.node.secure_boot = False
        self.node.save()

        mock_get_boot.return_value = "fake-hybrid"
        mock_get_secure.return_value = None

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # Verify it upgraded lock
            self.assertFalse(task.shared)

        self.node.refresh()
        self.assertEqual("fake-hybrid", self.node.boot_mode)
        self.assertIsNone(self.node.secure_boot)

    @mock.patch.object(conductor_utils.LOG, 'warning', autospec=True)
    def test_failed_boot_mode(self, mock_log, mock_get_boot, mock_get_secure):
        self.node.boot_mode = "fake-efi"
        self.node.secure_boot = True
        self.node.save()

        mock_get_boot.side_effect = RuntimeError
        mock_get_secure.return_value = None

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            # Test that function aborts and doesn't do anything else.
            # NOTE(cenne): Do we want to update states to None instead?
            self.assertFalse(mock_get_secure.called)
            self.assertTrue(task.shared)

        self.assertTrue(mock_log.called)
        # Verify no changes
        self.node.refresh()
        self.assertEqual("fake-efi", self.node.boot_mode)
        self.assertTrue(self.node.secure_boot)

    @mock.patch.object(conductor_utils.LOG, 'warning', autospec=True)
    def test_failed_secure(self, mock_log, mock_get_boot, mock_get_secure):
        self.node.boot_mode = "fake-efi"
        self.node.secure_boot = True
        self.node.save()

        mock_get_boot.return_value = "fake-efi"
        mock_get_secure.side_effect = RuntimeError

        with task_manager.acquire(self.context, self.node.id,
                                  shared=True) as task:
            conductor_utils.node_cache_boot_mode(task)
            mock_get_boot.assert_called_once_with(
                task.driver.management, task)
            mock_get_secure.assert_called_once_with(
                task.driver.management, task)
            # Test that function aborts and doesn't do anything else.
            # NOTE(cenne): Do we want to update states to None instead?
            self.assertTrue(task.shared)

        self.assertTrue(mock_log.called)
        # Verify no changes
        self.node.refresh()
        self.assertEqual("fake-efi", self.node.boot_mode)
        self.assertTrue(self.node.secure_boot)


class GetConfigDriveImageTestCase(db_base.DbTestCase):

    def setUp(self):
        super(GetConfigDriveImageTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            instance_info={})

    def test_no_configdrive(self):
        self.assertIsNone(conductor_utils.get_configdrive_image(self.node))

    def test_string(self):
        self.node.instance_info['configdrive'] = 'data'
        self.assertEqual('data',
                         conductor_utils.get_configdrive_image(self.node))

    @mock.patch('openstack.baremetal.configdrive.build', autospec=True)
    def test_build_empty(self, mock_cd):
        self.node.instance_info['configdrive'] = {}
        self.assertEqual(mock_cd.return_value,
                         conductor_utils.get_configdrive_image(self.node))
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=None,
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build', autospec=True)
    def test_build_populated(self, mock_cd):
        configdrive = {
            'meta_data': {'uuid': uuidutils.generate_uuid(),
                          'name': 'new-name',
                          'hostname': 'example.com'},
            'network_data': {'links': []},
            'vendor_data': {'foo': 'bar'},
        }
        self.node.instance_info['configdrive'] = configdrive
        self.assertEqual(mock_cd.return_value,
                         conductor_utils.get_configdrive_image(self.node))
        mock_cd.assert_called_once_with(
            configdrive['meta_data'],
            network_data=configdrive['network_data'],
            user_data=None,
            vendor_data=configdrive['vendor_data'])

    @mock.patch('openstack.baremetal.configdrive.build', autospec=True)
    def test_build_user_data_as_string(self, mock_cd):
        self.node.instance_info['configdrive'] = {'user_data': 'abcd'}
        self.assertEqual(mock_cd.return_value,
                         conductor_utils.get_configdrive_image(self.node))
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=b'abcd',
                                        vendor_data=None)

    @mock.patch('openstack.baremetal.configdrive.build', autospec=True)
    def test_build_user_data_as_dict(self, mock_cd):
        self.node.instance_info['configdrive'] = {
            'user_data': {'user': 'data'}
        }
        self.assertEqual(mock_cd.return_value,
                         conductor_utils.get_configdrive_image(self.node))
        mock_cd.assert_called_once_with({'uuid': self.node.uuid},
                                        network_data=None,
                                        user_data=b'{"user": "data"}',
                                        vendor_data=None)


class NodeHistoryRecordTestCase(db_base.DbTestCase):

    def setUp(self):
        super(NodeHistoryRecordTestCase, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid())

    def test_record_node_history(self):
        conductor_utils.node_history_record(self.node, event='meow')
        entries = objects.NodeHistory.list_by_node_id(self.context,
                                                      self.node.id)
        entry = entries[0]
        self.assertEqual('meow', entry['event'])
        self.assertEqual(CONF.host, entry['conductor'])
        self.assertEqual('INFO', entry['severity'])
        self.assertIsNone(entry['user'])

    def test_record_node_history_with_user(self):
        conductor_utils.node_history_record(self.node, event='meow',
                                            user='peachesthecat')
        entries = objects.NodeHistory.list_by_node_id(self.context,
                                                      self.node.id)
        entry = entries[0]
        self.assertEqual('meow', entry['event'])
        self.assertEqual(CONF.host, entry['conductor'])
        self.assertEqual('peachesthecat', entry['user'])

    def test_record_node_history_with_error_severity(self):
        conductor_utils.node_history_record(self.node, event='meowmeow',
                                            error=True,
                                            event_type='catwantfood')
        entries = objects.NodeHistory.list_by_node_id(self.context,
                                                      self.node.id)
        entry = entries[0]
        self.assertEqual('meowmeow', entry['event'])
        self.assertEqual(CONF.host, entry['conductor'])
        self.assertEqual('ERROR', entry['severity'])
        self.assertEqual('catwantfood', entry['event_type'])

    @mock.patch.object(objects, 'NodeHistory', autospec=True)
    def test_record_node_history_noop(self, mock_history):
        CONF.set_override('node_history', False, group='conductor')
        self.assertIsNone(conductor_utils.node_history_record(self.node))
        mock_history.assert_not_called()

    @mock.patch.object(objects, 'NodeHistory', autospec=True)
    def test_record_node_history_disaled(self, mock_history):
        mock_create = mock.Mock()
        conductor_utils.node_history_record(self.node, event='meow',
                                            error=True)
        self.assertEqual('meow', self.node.last_error)
        mock_history.create = mock_create
        mock_history.assert_not_called()
        mock_create.assert_not_called()
