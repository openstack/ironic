# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import mock

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

    def test_load(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node

            objects.Node.get_by_uuid(self.context, uuid)

            mock_get_node.assert_called_once_with(uuid)

            # TODO(deva): add tests for load-on-demand info, eg. ports,
            #             once Port objects are created

    def test_save(self):
        uuid = self.fake_node['uuid']
        with mock.patch.object(self.dbapi, 'get_node',
                               autospec=True) as mock_get_node:
            mock_get_node.return_value = self.fake_node
            with mock.patch.object(self.dbapi, 'update_node',
                                   autospec=True) as mock_update_node:

                n = objects.Node.get_by_uuid(self.context, uuid)
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
        with mock.patch.object(self.dbapi, 'get_node', side_effect=returns,
                               autospec=True) as mock_get_node:
            n = objects.Node.get_by_uuid(self.context, uuid)
            self.assertEqual(n.properties, {"fake": "first"})
            n.refresh()
            self.assertEqual(n.properties, {"fake": "second"})
            self.assertEqual(mock_get_node.call_args_list, expected)

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

    def test_objectify_many(self):
        def _get_db_nodes():
            nodes = []
            for i in xrange(5):
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
