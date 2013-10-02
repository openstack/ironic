# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for manipulating Ports via the DB API"""

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.openstack.common import uuidutils
from ironic.tests.db import base
from ironic.tests.db import utils


class DbPortTestCase(base.DbTestCase):

    def setUp(self):
        # This method creates a port for every test and
        # replaces a test for creating a port.
        super(DbPortTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        ndict = utils.get_test_node()
        self.n = self.dbapi.create_node(ndict)
        self.p = utils.get_test_port()

    def test_get_port_by_id(self):
        self.dbapi.create_port(self.p)
        res = self.dbapi.get_port(self.p['id'])
        self.assertEqual(self.p['address'], res['address'])

    def test_get_port_by_uuid(self):
        self.dbapi.create_port(self.p)
        res = self.dbapi.get_port(self.p['uuid'])
        self.assertEqual(self.p['id'], res['id'])

    def test_get_port_list(self):
        uuids = []
        for i in xrange(1, 6):
            n = utils.get_test_port(id=i, uuid=uuidutils.generate_uuid())
            self.dbapi.create_port(n)
            uuids.append(unicode(n['uuid']))
        res = self.dbapi.get_port_list()
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids.sort(), res_uuids.sort())

    def test_get_port_by_address(self):
        self.dbapi.create_port(self.p)

        res = self.dbapi.get_port(self.p['address'])
        self.assertEqual(self.p['id'], res['id'])

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 99)
        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 'aa:bb:cc:dd:ee:ff')
        self.assertRaises(exception.InvalidIdentity,
                          self.dbapi.get_port, 'not-a-mac')

    def test_get_ports_by_node_id(self):
        p = utils.get_test_port(node_id=self.n['id'])
        self.dbapi.create_port(p)
        res = self.dbapi.get_ports_by_node(self.n['id'])
        self.assertEqual(self.p['address'], res[0]['address'])

    def test_get_ports_by_node_uuid(self):
        p = utils.get_test_port(node_id=self.n['id'])
        self.dbapi.create_port(p)
        res = self.dbapi.get_ports_by_node(self.n['uuid'])
        self.assertEqual(self.p['address'], res[0]['address'])

    def test_get_ports_by_node_that_does_not_exist(self):
        self.dbapi.create_port(self.p)
        res = self.dbapi.get_ports_by_node(99)
        self.assertEqual(0, len(res))

        res = self.dbapi.get_ports_by_node(
                '12345678-9999-0000-aaaa-123456789012')
        self.assertEqual(0, len(res))

    def test_destroy_port(self):
        self.dbapi.create_port(self.p)
        self.dbapi.destroy_port(self.p['id'])
        self.assertRaises(exception.PortNotFound,
                          self.dbapi.destroy_port, self.p['id'])

    def test_update_port(self):
        self.dbapi.create_port(self.p)
        old_address = self.p['address']
        new_address = 'ff.ee.dd.cc.bb.aa'

        self.assertNotEqual(old_address, new_address)

        res = self.dbapi.update_port(self.p['id'], {'address': new_address})
        self.assertEqual(new_address, res['address'])

    def test_destroy_port_on_reserved_node(self):
        p = self.dbapi.create_port(utils.get_test_port(node_id=self.n['id']))
        uuid = self.n['uuid']
        self.dbapi.reserve_nodes('fake-reservation', [uuid])
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.destroy_port, p['id'])

    def test_update_port_on_reserved_node(self):
        p = self.dbapi.create_port(utils.get_test_port(node_id=self.n['id']))
        uuid = self.n['uuid']
        self.dbapi.reserve_nodes('fake-reservation', [uuid])
        new_address = 'ff.ee.dd.cc.bb.aa'
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.update_port, p['id'],
                          {'address': new_address})
