# coding=utf-8
#
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

import datetime

import mock
from oslo.utils import timeutils
from testtools.matchers import HasLength

from ironic.common import exception
from ironic.db import api as db_api
from ironic.db.sqlalchemy import models
from ironic import objects
from ironic.tests.db import base
from ironic.tests.db import utils


class TestNodeObject(base.DbTestCase):

    def setUp(self):
        super(TestNodeObject, self).setUp()
        self.fake_node = utils.get_test_node()
        self.dbapi = db_api.get_instance()

    def test_get_by_id(self):
        node_id = self.fake_node['id']
        with mock.patch.object(self.dbapi, 'get_node_by_id',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            objects.Node.get(self.context, node_id)

            mock_get_node.assert_called_once_with(node_id)

    def test_get_by_uuid(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            objects.Node.get(self.context, uuid)

            mock_get_node.assert_called_once_with(uuid)

    def test_get_bad_id_and_uuid(self):
        self.assertRaises(exception.InvalidIdentity,
                          objects.Node.get, self.context, 'not-a-uuid')

    def test_save(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            with mock.patch.object(self.dbapi, 'update_node',
                                   autospec=True) as mock_update_node:

                n = objects.Node.get(self.context, uuid)
                n.properties = {"fake": "property"}
                n.save()

                mock_get_node.assert_called_once_with(uuid)
                mock_update_node.assert_called_once_with(
                        uuid, {'properties': {"fake": "property"}})

    def test_refresh(self):
        uuid = self.fake_node['uuid']
        returns = [dict(self.fake_node, properties={"fake": "first"}),
                   dict(self.fake_node, properties={"fake": "second"})]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_node_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_node:
            n = objects.Node.get(self.context, uuid)
            self.assertEqual({"fake": "first"}, n.properties)
            n.refresh()
            self.assertEqual({"fake": "second"}, n.properties)
            self.assertEqual(expected, mock_get_node.call_args_list)

    def test_objectify(self):
        def _get_db_node():
            n = models.Node()
            n.update(self.fake_node)
            return n

        @objects.objectify(objects.Node)
        def _convert_db_node():
            return _get_db_node()

        self.assertIsInstance(_get_db_node(), models.Node)
        self.assertIsInstance(_convert_db_node(), objects.Node)

    def test_objectify_deserialize_provision_updated_at(self):
        dt = timeutils.isotime(datetime.datetime(2000, 1, 1, 0, 0))
        self.fake_node['provision_updated_at'] = dt

        def _get_db_node():
            n = models.Node()
            n.update(self.fake_node)
            return n

        @objects.objectify(objects.Node)
        def _convert_db_node():
            return _get_db_node()

        self.assertIsInstance(_get_db_node(), models.Node)
        self.assertIsInstance(_convert_db_node(), objects.Node)

    def test_objectify_many(self):
        def _get_db_nodes():
            nodes = []
            for i in range(5):
                n = models.Node()
                n.update(self.fake_node)
                nodes.append(n)
            return nodes

        @objects.objectify(objects.Node)
        def _convert_db_nodes():
            return _get_db_nodes()

        for n in _get_db_nodes():
            self.assertIsInstance(n, models.Node)
        for n in _convert_db_nodes():
            self.assertIsInstance(n, objects.Node)

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_node_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_node]
            nodes = objects.Node.list(self.context)
            self.assertThat(nodes, HasLength(1))
            self.assertIsInstance(nodes[0], objects.Node)
