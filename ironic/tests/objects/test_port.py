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

from ironic.common import context
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
        ctxt = context.get_admin_context()
        uuid = self.fake_port['uuid']
        self.mox.StubOutWithMock(self.dbapi, 'get_port')

        self.dbapi.get_port(uuid).AndReturn(self.fake_port)
        self.mox.ReplayAll()

        objects.Port.get_by_uuid(ctxt, uuid)
        self.mox.VerifyAll()

    def test_save(self):
        ctxt = context.get_admin_context()
        uuid = self.fake_port['uuid']
        self.mox.StubOutWithMock(self.dbapi, 'get_port')
        self.mox.StubOutWithMock(self.dbapi, 'update_port')

        self.dbapi.get_port(uuid).AndReturn(self.fake_port)
        self.dbapi.update_port(uuid, {'address': "b2:54:00:cf:2d:40"})
        self.mox.ReplayAll()

        p = objects.Port.get_by_uuid(ctxt, uuid)
        p.address = "b2:54:00:cf:2d:40"
        p.save()
        self.mox.VerifyAll()

    def test_refresh(self):
        ctxt = context.get_admin_context()
        uuid = self.fake_port['uuid']
        self.mox.StubOutWithMock(self.dbapi, 'get_port')

        self.dbapi.get_port(uuid).AndReturn(self.fake_port)
        self.dbapi.get_port(uuid).AndReturn(
            utils.get_test_port(address="c3:54:00:cf:2d:40"))

        self.mox.ReplayAll()

        p = objects.Port.get_by_uuid(ctxt, uuid)
        self.assertEqual(p.address, "52:54:00:cf:2d:31")

        p.refresh()

        self.assertEqual(p.address, "c3:54:00:cf:2d:40")
        self.mox.VerifyAll()

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
