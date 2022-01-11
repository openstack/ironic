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

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DBNodeHistoryTestCase(base.DbTestCase):

    def setUp(self):
        super(DBNodeHistoryTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.history = db_utils.create_test_history(
            id=0, node_id=self.node.id, conductor='test-conductor',
            user='fake-user', event='Something bad happened but fear not')

    def test_destroy_node_history_by_uuid(self):
        self.dbapi.destroy_node_history_by_uuid(self.history.uuid)
        self.assertRaises(exception.NodeHistoryNotFound,
                          self.dbapi.get_node_history_by_id,
                          self.history.id)
        self.assertRaises(exception.NodeHistoryNotFound,
                          self.dbapi.get_node_history_by_uuid,
                          self.history.uuid)

    def test_get_history_by_id(self):
        res = self.dbapi.get_node_history_by_id(self.history.id)
        self.assertEqual(self.history.conductor, res.conductor)
        self.assertEqual(self.history.user, res.user)
        self.assertEqual(self.history.event, res.event)

    def test_get_history_by_id_not_found(self):
        self.assertRaises(exception.NodeHistoryNotFound,
                          self.dbapi.get_node_history_by_id, -1)

    def test_get_history_by_uuid(self):
        res = self.dbapi.get_node_history_by_uuid(self.history.uuid)
        self.assertEqual(self.history.id, res.id)

    def test_get_history_by_uuid_not_found(self):
        self.assertRaises(exception.NodeHistoryNotFound,
                          self.dbapi.get_node_history_by_uuid,
                          'wrong-uuid')

    def _prepare_history_entries(self):
        uuids = [str(self.history.uuid)]
        for i in range(1, 6):
            history = db_utils.create_test_history(
                id=i, uuid=uuidutils.generate_uuid(),
                node_id=self.node.id,
                conductor='test-conductor', user='fake-user',
                event='Something bad happened but fear not %s' % i,
                severity='ERROR', event_type='test')
            uuids.append(str(history.uuid))
        return uuids

    def test_get_node_history_list(self):
        uuids = self._prepare_history_entries()
        res = self.dbapi.get_node_history_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_node_history_list_sorted(self):
        self._prepare_history_entries()

        res = self.dbapi.get_node_history_list(sort_key='created_at',
                                               sort_dir='desc')
        expected = sorted(res, key=lambda r: r.created_at, reverse=True)
        self.assertEqual(res, expected)
        self.assertIn('fear not 5', res[0].event)

    def test_get_history_by_node_id_empty(self):
        self.assertEqual([], self.dbapi.get_node_history_by_node_id(10))

    def test_get_history_by_node_id(self):
        res = self.dbapi.get_node_history_by_node_id(self.node.id)
        self.assertEqual(self.history.uuid, res[0].uuid)
        self.assertEqual(self.history.user, res[0].user)
        self.assertEqual(self.history.conductor, res[0].conductor)
        self.assertEqual(self.history.event, res[0].event)
        self.assertEqual(self.history.event_type, res[0].event_type)
        self.assertEqual(self.history.severity, res[0].severity)
