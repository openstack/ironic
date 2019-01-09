# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock
from oslo_config import cfg
import oslo_messaging as messaging

from ironic.common import context as ironic_context
from ironic.common import rpc
from ironic.tests import base

CONF = cfg.CONF


class TestUtils(base.TestCase):

    @mock.patch.object(messaging, 'Notifier', autospec=True)
    @mock.patch.object(messaging, 'JsonPayloadSerializer', autospec=True)
    @mock.patch.object(messaging, 'get_notification_transport', autospec=True)
    @mock.patch.object(messaging, 'get_rpc_transport', autospec=True)
    def test_init_globals_notifications_disabled(self, mock_get_rpc_transport,
                                                 mock_get_notification,
                                                 mock_json_serializer,
                                                 mock_notifier):
        self._test_init_globals(False, mock_get_rpc_transport,
                                mock_get_notification, mock_json_serializer,
                                mock_notifier)

    @mock.patch.object(messaging, 'Notifier', autospec=True)
    @mock.patch.object(messaging, 'JsonPayloadSerializer', autospec=True)
    @mock.patch.object(messaging, 'get_notification_transport', autospec=True)
    @mock.patch.object(messaging, 'get_rpc_transport', autospec=True)
    def test_init_globals_notifications_enabled(self, mock_get_rpc_transport,
                                                mock_get_notification,
                                                mock_json_serializer,
                                                mock_notifier):
        self.config(notification_level='debug')
        self._test_init_globals(True, mock_get_rpc_transport,
                                mock_get_notification, mock_json_serializer,
                                mock_notifier)

    @mock.patch.object(messaging, 'Notifier', autospec=True)
    @mock.patch.object(messaging, 'JsonPayloadSerializer', autospec=True)
    @mock.patch.object(messaging, 'get_notification_transport', autospec=True)
    @mock.patch.object(messaging, 'get_rpc_transport', autospec=True)
    def test_init_globals_with_custom_topics(self, mock_get_rpc_transport,
                                             mock_get_notification,
                                             mock_json_serializer,
                                             mock_notifier):
        self._test_init_globals(
            False, mock_get_rpc_transport, mock_get_notification,
            mock_json_serializer, mock_notifier,
            versioned_notifications_topics=['custom_topic1', 'custom_topic2'])

    def _test_init_globals(
            self, notifications_enabled, mock_get_rpc_transport,
            mock_get_notification, mock_json_serializer, mock_notifier,
            versioned_notifications_topics=['ironic_versioned_notifications']):

        rpc.TRANSPORT = None
        rpc.NOTIFICATION_TRANSPORT = None
        rpc.SENSORS_NOTIFIER = None
        rpc.VERSIONED_NOTIFIER = None
        mock_request_serializer = mock.Mock()
        mock_request_serializer.return_value = mock.Mock()
        rpc.RequestContextSerializer = mock_request_serializer

        # Make sure that two separate Notifiers are instantiated: one for the
        # regular RPC transport, one for the notification transport
        mock_notifiers = [mock.Mock()] * 2
        mock_notifier.side_effect = mock_notifiers

        rpc.init(CONF)

        self.assertEqual(mock_get_rpc_transport.return_value, rpc.TRANSPORT)
        self.assertEqual(mock_get_notification.return_value,
                         rpc.NOTIFICATION_TRANSPORT)
        self.assertTrue(mock_json_serializer.called)

        if not notifications_enabled:
            notifier_calls = [
                mock.call(
                    rpc.NOTIFICATION_TRANSPORT,
                    serializer=mock_request_serializer.return_value),
                mock.call(
                    rpc.NOTIFICATION_TRANSPORT,
                    serializer=mock_request_serializer.return_value,
                    driver='noop')
            ]
        else:
            notifier_calls = [
                mock.call(
                    rpc.NOTIFICATION_TRANSPORT,
                    serializer=mock_request_serializer.return_value),
                mock.call(
                    rpc.NOTIFICATION_TRANSPORT,
                    serializer=mock_request_serializer.return_value,
                    topics=versioned_notifications_topics)
            ]

        mock_notifier.assert_has_calls(notifier_calls)

        self.assertEqual(mock_notifiers[0], rpc.SENSORS_NOTIFIER)
        self.assertEqual(mock_notifiers[1], rpc.VERSIONED_NOTIFIER)

    def test_get_sensors_notifier(self):
        rpc.SENSORS_NOTIFIER = mock.Mock(autospec=True)
        rpc.get_sensors_notifier(service='conductor', host='my_conductor',
                                 publisher_id='a_great_publisher')
        rpc.SENSORS_NOTIFIER.prepare.assert_called_once_with(
            publisher_id='a_great_publisher')

    def test_get_sensors_notifier_no_publisher_id(self):
        rpc.SENSORS_NOTIFIER = mock.Mock(autospec=True)
        rpc.get_sensors_notifier(service='conductor', host='my_conductor')
        rpc.SENSORS_NOTIFIER.prepare.assert_called_once_with(
            publisher_id='conductor.my_conductor')

    def test_get_sensors_notifier_no_notifier(self):
        rpc.SENSORS_NOTIFIER = None
        self.assertRaises(AssertionError, rpc.get_sensors_notifier)

    def test_get_versioned_notifier(self):
        rpc.VERSIONED_NOTIFIER = mock.Mock(autospec=True)
        rpc.get_versioned_notifier(publisher_id='a_great_publisher')
        rpc.VERSIONED_NOTIFIER.prepare.assert_called_once_with(
            publisher_id='a_great_publisher')

    def test_get_versioned_notifier_no_publisher_id(self):
        rpc.VERSIONED_NOTIFIER = mock.Mock()
        self.assertRaises(AssertionError,
                          rpc.get_versioned_notifier, publisher_id=None)

    def test_get_versioned_notifier_no_notifier(self):
        rpc.VERSIONED_NOTIFIER = None
        self.assertRaises(
            AssertionError,
            rpc.get_versioned_notifier, publisher_id='a_great_publisher')


class TestRequestContextSerializer(base.TestCase):

    def setUp(self):
        super(TestRequestContextSerializer, self).setUp()

        self.mock_serializer = mock.MagicMock()
        self.serializer = rpc.RequestContextSerializer(self.mock_serializer)
        self.context = ironic_context.RequestContext()
        self.entity = {'foo': 'bar'}

    def test_serialize_entity(self):
        self.serializer.serialize_entity(self.context, self.entity)
        self.mock_serializer.serialize_entity.assert_called_with(
            self.context, self.entity)

    def test_serialize_entity_empty_base(self):
        # NOTE(viktors): Return False for check `if self.serializer._base:`
        bool_args = {'__bool__': lambda *args: False,
                     '__nonzero__': lambda *args: False}
        self.mock_serializer.configure_mock(**bool_args)

        entity = self.serializer.serialize_entity(self.context, self.entity)
        self.assertFalse(self.mock_serializer.serialize_entity.called)
        # If self.serializer._base is empty, return entity directly
        self.assertEqual(self.entity, entity)

    def test_deserialize_entity(self):
        self.serializer.deserialize_entity(self.context, self.entity)
        self.mock_serializer.deserialize_entity.assert_called_with(
            self.context, self.entity)

    def test_deserialize_entity_empty_base(self):
        # NOTE(viktors): Return False for check `if self.serializer._base:`
        bool_args = {'__bool__': lambda *args: False,
                     '__nonzero__': lambda *args: False}
        self.mock_serializer.configure_mock(**bool_args)

        entity = self.serializer.deserialize_entity(self.context, self.entity)
        self.assertFalse(self.mock_serializer.serialize_entity.called)
        self.assertEqual(self.entity, entity)

    def test_serialize_context(self):
        serialize_values = self.serializer.serialize_context(self.context)

        self.assertEqual(self.context.to_dict(), serialize_values)

    def test_deserialize_context(self):
        serialize_values = self.context.to_dict()
        new_context = self.serializer.deserialize_context(serialize_values)
        self.assertEqual(serialize_values, new_context.to_dict())
        self.assertIsInstance(new_context, ironic_context.RequestContext)
