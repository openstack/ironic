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
from ironic.openstack.common import uuidutils
from ironic.tests.db import base
from ironic.tests.db import utils


class TestChassisObject(base.DbTestCase):

    def setUp(self):
        super(TestChassisObject, self).setUp()
        self.fake_chassis = utils.get_test_chassis()
        self.dbapi = db_api.get_instance()
        self.ctxt = context.get_admin_context()

    def test_load(self):
        uuid = self.fake_chassis['uuid']

        self.mox.StubOutWithMock(self.dbapi, 'get_chassis')
        self.dbapi.get_chassis(uuid).AndReturn(self.fake_chassis)
        self.mox.ReplayAll()

        objects.Chassis.get_by_uuid(self.ctxt, uuid)
        self.mox.VerifyAll()

    def test_save(self):
        uuid = self.fake_chassis['uuid']

        self.mox.StubOutWithMock(self.dbapi, 'get_chassis')
        self.mox.StubOutWithMock(self.dbapi, 'update_chassis')
        self.dbapi.get_chassis(uuid).AndReturn(self.fake_chassis)

        self.dbapi.update_chassis(uuid, {'extra': '{"test": 123}'})
        self.mox.ReplayAll()

        c = objects.Chassis.get_by_uuid(self.ctxt, uuid)
        c.extra = '{"test": 123}'
        c.save()
        self.mox.VerifyAll()

    def test_refresh(self):
        uuid = self.fake_chassis['uuid']
        new_uuid = uuidutils.generate_uuid()

        self.mox.StubOutWithMock(self.dbapi, 'get_chassis')

        self.dbapi.get_chassis(uuid).AndReturn(
                dict(self.fake_chassis, uuid=uuid))
        self.dbapi.get_chassis(uuid).AndReturn(
                dict(self.fake_chassis, uuid=new_uuid))
        self.mox.ReplayAll()

        c = objects.Chassis.get_by_uuid(self.ctxt, uuid)
        self.assertEqual(c.uuid, uuid)
        c.refresh()
        self.assertEqual(c.uuid, new_uuid)
        self.mox.VerifyAll()

    def test_objectify(self):
        def _get_db_chassis():
            c = models.Chassis()
            c.update(self.fake_chassis)
            return c

        @objects.objectify(objects.Chassis)
        def _convert_db_chassis():
            return _get_db_chassis()

        self.assertIsInstance(_get_db_chassis(), models.Chassis)
        self.assertIsInstance(_convert_db_chassis(), objects.Chassis)

    def test_objectify_many(self):
        def _get_many_db_chassis():
            chassis = []
            for i in xrange(5):
                c = models.Chassis()
                c.update(self.fake_chassis)
                chassis.append(c)
            return chassis

        @objects.objectify(objects.Chassis)
        def _convert_many_db_chassis():
            return _get_many_db_chassis()

        for c in _get_many_db_chassis():
            self.assertIsInstance(c, models.Chassis)
        for c in _convert_many_db_chassis():
            self.assertIsInstance(c, objects.Chassis)
