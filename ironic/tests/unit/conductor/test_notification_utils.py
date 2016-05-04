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
from ironic.objects import fields
from ironic.objects import node as node_objects
from ironic.tests.unit.db import base
from ironic.tests.unit.objects import utils as obj_utils


class TestNotificationUtils(base.DbTestCase):
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

    def test__emit_conductor_node_notification(self):
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

    def test__emit_conductor_node_notification_known_notify_exc(self):
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
