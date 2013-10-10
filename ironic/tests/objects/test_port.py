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


class TestPortObject(base.DbTestCase):

    def setUp(self):
        super(TestPortObject, self).setUp()
        self.fake_port = utils.get_test_port()
        self.dbapi = db_api.get_instance()

    def test_load(self):
        uuid = self.fake_port['uuid']
        with mock.patch.object(self.dbapi, 'get_port',
                               autospec=True) as mock_get_port:
            mock_get_port.return_value = self.fake_port

            objects.Port.get_by_uuid(self.context, uuid)

            mock_get_port.assert_called_once_with(uuid)

    def test_save(self):
        uuid = self.fake_port['uuid']
        with mock.patch.object(self.dbapi, 'get_port',
                               autospec=True) as mock_get_port:
            mock_get_port.return_value = self.fake_port
            with mock.patch.object(self.dbapi, 'update_port',
                                   autospec=True) as mock_update_port:
                p = objects.Port.get_by_uuid(self.context, uuid)
                p.address = "b2:54:00:cf:2d:40"
                p.save()

                mock_get_port.assert_called_once_with(uuid)
                mock_update_port.assert_called_once_with(
                        uuid, {'address': "b2:54:00:cf:2d:40"})

    def test_refresh(self):
        uuid = self.fake_port['uuid']
        returns = [self.fake_port,
                   utils.get_test_port(address="c3:54:00:cf:2d:40")]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_port', side_effect=returns,
                               autospec=True) as mock_get_port:
            p = objects.Port.get_by_uuid(self.context, uuid)
            self.assertEqual(p.address, "52:54:00:cf:2d:31")
            p.refresh()
            self.assertEqual(p.address, "c3:54:00:cf:2d:40")

            self.assertEqual(mock_get_port.call_args_list, expected)

    def test_objectify(self):
        def _get_db_port():
            p = models.Port()
            p.update(self.fake_port)
            return p

        @objects.objectify(objects.Port)
        def _convert_db_port():
            return _get_db_port()

        self.assertIsInstance(_get_db_port(), models.Port)
        self.assertIsInstance(_convert_db_port(), objects.Port)

    def test_objectify_many(self):
        def _get_db_ports():
            nodes = []
            for i in xrange(5):
                n = models.Port()
                n.update(self.fake_port)
                nodes.append(n)
            return nodes

        @objects.objectify(objects.Port)
        def _convert_db_nodes():
            return _get_db_ports()

        for p in _get_db_ports():
            self.assertIsInstance(p, models.Port)
        for p in _convert_db_nodes():
            self.assertIsInstance(p, objects.Port)
