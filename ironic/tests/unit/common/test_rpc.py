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

from ironic.common import context as ironic_context
from ironic.common import rpc
from ironic.tests import base


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
        self.context.user = 'fake-user'
        self.context.tenant = 'fake-tenant'
        serialize_values = self.context.to_dict()
        new_context = self.serializer.deserialize_context(serialize_values)
        # Ironic RequestContext from_dict will pop 'user' and 'tenant' and
        # initialize to None.
        self.assertIsNone(new_context.user)
        self.assertIsNone(new_context.tenant)
