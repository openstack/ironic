# Copyright 2016 Rackspace, Inc.
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

"""Test class for ironic-conductor notification utilities."""

import mock
from oslo_versionedobjects.exception import VersionedObjectsException

from ironic.common import exception
from ironic.common import states
from ironic.conductor import notification_utils as notif_utils
from ironic.conductor import task_manager
from ironic.objects import fields
from ironic.objects import node as node_objects
from ironic.objects import notification
from ironic.tests import base as tests_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


class TestNotificationUtils(db_base.DbTestCase):
    def setUp(self):
        super(TestNotificationUtils, self).setUp()
        self.config(notification_level='debug')
        self.node = obj_utils.create_test_node(self.context)
        self.task = mock.Mock(spec_set=['context', 'driver', 'node',
                                        'upgrade_lock', 'shared'])
        self.task.node = self.node

    @mock.patch.object(notif_utils, '_emit_conductor_node_notification')
    def test_emit_power_state_corrected_notification(self, mock_cond_emit):
        notif_utils.emit_power_state_corrected_notification(
            self.task, states.POWER_ON)
        mock_cond_emit.assert_called_once_with(
            self.task,
            node_objects.NodeCorrectedPowerStateNotification,
            node_objects.NodeCorrectedPowerStatePayload,
            'power_state_corrected',
            fields.NotificationLevel.INFO,
            fields.NotificationStatus.SUCCESS,
            from_power=states.POWER_ON
        )

    @mock.patch.object(notif_utils, '_emit_conductor_node_notification')
    def test_emit_power_set_notification(self, mock_cond_emit):
        notif_utils.emit_power_set_notification(
            self.task,
            fields.NotificationLevel.DEBUG,
            fields.NotificationStatus.END,
            states.POWER_ON)
        mock_cond_emit.assert_called_once_with(
            self.task,
            node_objects.NodeSetPowerStateNotification,
            node_objects.NodeSetPowerStatePayload,
            'power_set',
            fields.NotificationLevel.DEBUG,
            fields.NotificationStatus.END,
            to_power=states.POWER_ON
        )

    @mock.patch.object(notif_utils, '_emit_conductor_node_notification')
    def test_emit_console_notification(self, mock_cond_emit):
        notif_utils.emit_console_notification(
            self.task, 'console_set', fields.NotificationStatus.END)
        mock_cond_emit.assert_called_once_with(
            self.task,
            node_objects.NodeConsoleNotification,
            node_objects.NodePayload,
            'console_set',
            fields.NotificationLevel.INFO,
            fields.NotificationStatus.END,
        )

    @mock.patch.object(notif_utils, '_emit_conductor_node_notification')
    def test_emit_console_notification_error_status(self, mock_cond_emit):
        notif_utils.emit_console_notification(
            self.task, 'console_set', fields.NotificationStatus.ERROR)
        mock_cond_emit.assert_called_once_with(
            self.task,
            node_objects.NodeConsoleNotification,
            node_objects.NodePayload,
            'console_set',
            fields.NotificationLevel.ERROR,
            fields.NotificationStatus.ERROR,
        )

    @mock.patch.object(notification, 'mask_secrets')
    def test__emit_conductor_node_notification(self, mock_secrets):
        mock_notify_method = mock.Mock()
        # Required for exception handling
        mock_notify_method.__name__ = 'MockNotificationConstructor'
        mock_payload_method = mock.Mock()
        mock_payload_method.__name__ = 'MockPayloadConstructor'
        mock_kwargs = {'mock0': mock.Mock(),
                       'mock1': mock.Mock()}

        notif_utils._emit_conductor_node_notification(
            self.task,
            mock_notify_method,
            mock_payload_method,
            'fake_action',
            fields.NotificationLevel.INFO,
            fields.NotificationStatus.SUCCESS,
            **mock_kwargs
        )

        mock_payload_method.assert_called_once_with(
            self.task.node, **mock_kwargs)
        mock_secrets.assert_called_once_with(mock_payload_method.return_value)
        mock_notify_method.assert_called_once_with(
            publisher=mock.ANY,
            event_type=mock.ANY,
            level=fields.NotificationLevel.INFO,
            payload=mock_payload_method.return_value
        )
        mock_notify_method.return_value.emit.assert_called_once_with(
            self.task.context)

    def test__emit_conductor_node_notification_known_payload_exc(self):
        """Test exception caught for a known payload exception."""
        mock_notify_method = mock.Mock()
        # Required for exception handling
        mock_notify_method.__name__ = 'MockNotificationConstructor'
        mock_payload_method = mock.Mock()
        mock_payload_method.__name__ = 'MockPayloadConstructor'
        mock_kwargs = {'mock0': mock.Mock(),
                       'mock1': mock.Mock()}
        mock_payload_method.side_effect = exception.NotificationSchemaKeyError

        notif_utils._emit_conductor_node_notification(
            self.task,
            mock_notify_method,
            mock_payload_method,
            'fake_action',
            fields.NotificationLevel.INFO,
            fields.NotificationStatus.SUCCESS,
            **mock_kwargs
        )

        self.assertFalse(mock_notify_method.called)

    @mock.patch.object(notification, 'mask_secrets')
    def test__emit_conductor_node_notification_known_notify_exc(self,
                                                                mock_secrets):
        """Test exception caught for a known notification exception."""
        mock_notify_method = mock.Mock()
        # Required for exception handling
        mock_notify_method.__name__ = 'MockNotificationConstructor'
        mock_payload_method = mock.Mock()
        mock_payload_method.__name__ = 'MockPayloadConstructor'
        mock_kwargs = {'mock0': mock.Mock(),
                       'mock1': mock.Mock()}
        mock_notify_method.side_effect = VersionedObjectsException

        notif_utils._emit_conductor_node_notification(
            self.task,
            mock_notify_method,
            mock_payload_method,
            'fake_action',
            fields.NotificationLevel.INFO,
            fields.NotificationStatus.SUCCESS,
            **mock_kwargs
        )

        self.assertFalse(mock_notify_method.return_value.emit.called)


class ProvisionNotifyTestCase(tests_base.TestCase):
    @mock.patch('ironic.objects.node.NodeSetProvisionStateNotification')
    def test_emit_notification(self, provision_mock):
        provision_mock.__name__ = 'NodeSetProvisionStateNotification'
        self.config(host='fake-host')
        node = obj_utils.get_test_node(self.context,
                                       provision_state='fake state',
                                       target_provision_state='fake target',
                                       instance_info={'foo': 'baz'})
        task = mock.Mock(spec=task_manager.TaskManager)
        task.node = node
        test_level = fields.NotificationLevel.INFO
        test_status = fields.NotificationStatus.SUCCESS
        notif_utils.emit_provision_set_notification(
            task, test_level, test_status, 'fake_old',
            'fake_old_target', 'event')
        init_kwargs = provision_mock.call_args[1]
        publisher = init_kwargs['publisher']
        event_type = init_kwargs['event_type']
        level = init_kwargs['level']
        payload = init_kwargs['payload']
        self.assertEqual('fake-host', publisher.host)
        self.assertEqual('ironic-conductor', publisher.service)
        self.assertEqual('node', event_type.object)
        self.assertEqual('provision_set', event_type.action)
        self.assertEqual(test_status, event_type.status)
        self.assertEqual(test_level, level)
        self.assertEqual(node.uuid, payload.uuid)
        self.assertEqual('fake state', payload.provision_state)
        self.assertEqual('fake target', payload.target_provision_state)
        self.assertEqual('fake_old', payload.previous_provision_state)
        self.assertEqual('fake_old_target',
                         payload.previous_target_provision_state)
        self.assertEqual({'foo': 'baz'}, payload.instance_info)

    def test_mask_secrets(self):
        test_info = {'configdrive': 'fake_drive', 'image_url': 'fake-url',
                     'some_value': 'fake-value'}
        node = obj_utils.get_test_node(self.context,
                                       instance_info=test_info)
        notification.mask_secrets(node)
        self.assertEqual('******', node.instance_info['configdrive'])
        self.assertEqual('******', node.instance_info['image_url'])
        self.assertEqual('fake-value', node.instance_info['some_value'])
