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

import types
from unittest import mock

from testtools.matchers import HasLength

from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestNodeHistoryObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestNodeHistoryObject, self).setUp()
        self.fake_history = db_utils.get_test_history()

    def test_get_by_id(self):
        with mock.patch.object(self.dbapi, 'get_node_history_by_id',
                               autospec=True) as mock_get:
            id_ = self.fake_history['id']
            mock_get.return_value = self.fake_history

            history = objects.NodeHistory.get_by_id(self.context, id_)

            mock_get.assert_called_once_with(id_)
            self.assertIsInstance(history, objects.NodeHistory)
            self.assertEqual(self.context, history._context)

    def test_get_by_uuid(self):
        uuid = self.fake_history['uuid']
        with mock.patch.object(self.dbapi, 'get_node_history_by_uuid',
                               autospec=True) as mock_get:
            mock_get.return_value = self.fake_history

            history = objects.NodeHistory.get_by_uuid(self.context, uuid)

            mock_get.assert_called_once_with(uuid)
            self.assertIsInstance(history, objects.NodeHistory)
            self.assertEqual(self.context, history._context)

    @mock.patch('ironic.objects.NodeHistory.get_by_uuid',
                spec_set=types.FunctionType)
    @mock.patch('ironic.objects.NodeHistory.get_by_id',
                spec_set=types.FunctionType)
    def test_get(self, mock_get_by_id, mock_get_by_uuid):
        id_ = self.fake_history['id']
        uuid = self.fake_history['uuid']

        objects.NodeHistory.get(self.context, id_)
        mock_get_by_id.assert_called_once_with(self.context, id_)
        self.assertFalse(mock_get_by_uuid.called)

        objects.NodeHistory.get(self.context, uuid)
        mock_get_by_uuid.assert_called_once_with(self.context, uuid)

        # Invalid identifier (not ID or UUID)
        self.assertRaises(exception.InvalidIdentity,
                          objects.NodeHistory.get,
                          self.context, 'not-valid-identifier')

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_node_history_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_history]
            history = objects.NodeHistory.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc')
            self.assertThat(history, HasLength(1))
            self.assertIsInstance(history[0], objects.NodeHistory)
            self.assertEqual(self.context, history[0]._context)

    def test_list_none(self):
        with mock.patch.object(self.dbapi, 'get_node_history_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = []
            history = objects.NodeHistory.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc')
            self.assertEqual([], history)

    def test_list_by_node_id(self):
        with mock.patch.object(self.dbapi, 'get_node_history_by_node_id',
                               autospec=True) as mock_get_list_by_node_id:
            mock_get_list_by_node_id.return_value = [self.fake_history]
            node_id = self.fake_history['node_id']
            history = objects.NodeHistory.list_by_node_id(
                self.context, node_id, limit=10, sort_dir='desc')

            mock_get_list_by_node_id.assert_called_once_with(
                node_id, limit=10, marker=None, sort_key=None, sort_dir='desc')
            self.assertThat(history, HasLength(1))
            self.assertIsInstance(history[0], objects.NodeHistory)
            self.assertEqual(self.context, history[0]._context)

    def test_create(self):
        with mock.patch.object(self.dbapi, 'create_node_history',
                               autospec=True) as mock_db_create:
            mock_db_create.return_value = self.fake_history
            new_history = objects.NodeHistory(
                self.context, **self.fake_history)
            new_history.create()

            mock_db_create.assert_called_once_with(self.fake_history)

    def test_destroy(self):
        uuid = self.fake_history['uuid']
        with mock.patch.object(self.dbapi, 'get_node_history_by_uuid',
                               autospec=True) as mock_get:
            mock_get.return_value = self.fake_history
            with mock.patch.object(self.dbapi, 'destroy_node_history_by_uuid',
                                   autospec=True) as mock_db_destroy:
                history = objects.NodeHistory.get_by_uuid(self.context, uuid)
                history.destroy()

                mock_db_destroy.assert_called_once_with(uuid)
