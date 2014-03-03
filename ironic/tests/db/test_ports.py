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

import six

from ironic.common import exception
from ironic.common import utils as ironic_utils
from ironic.db import api as dbapi

from ironic.tests.db import base
from ironic.tests.db import utils as db_utils


class DbPortTestCase(base.DbTestCase):

    def setUp(self):
        # This method creates a port for every test and
        # replaces a test for creating a port.
        super(DbPortTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        ndict = db_utils.get_test_node()
        self.n = self.dbapi.create_node(ndict)
        self.p = db_utils.get_test_port()

    def test_get_port_by_id(self):
        self.dbapi.create_port(self.p)
        res = self.dbapi.get_port(self.p['id'])
        self.assertEqual(self.p['address'], res.address)

    def test_get_port_by_uuid(self):
        self.dbapi.create_port(self.p)
        res = self.dbapi.get_port(self.p['uuid'])
        self.assertEqual(self.p['id'], res.id)

    def test_get_port_list(self):
        uuids = []
        for i in range(1, 6):
            n = db_utils.get_test_port(id=i, uuid=ironic_utils.generate_uuid(),
                                    address='52:54:00:cf:2d:3%s' % i)
            self.dbapi.create_port(n)
            uuids.append(six.text_type(n['uuid']))
        res = self.dbapi.get_port_list()
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids.sort(), res_uuids.sort())

    def test_get_port_by_address(self):
        self.dbapi.create_port(self.p)

        res = self.dbapi.get_port(self.p['address'])
        self.assertEqual(self.p['id'], res.id)

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 99)
        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 'aa:bb:cc:dd:ee:ff')
        self.assertRaises(exception.InvalidIdentity,
                          self.dbapi.get_port, 'not-a-mac')

    def test_get_ports_by_node_id(self):
        p = db_utils.get_test_port(node_id=self.n.id)
        self.dbapi.create_port(p)
        res = self.dbapi.get_ports_by_node(self.n.id)
        self.assertEqual(self.p['address'], res[0].address)

    def test_get_ports_by_node_uuid(self):
        p = db_utils.get_test_port(node_id=self.n.id)
        self.dbapi.create_port(p)
        res = self.dbapi.get_ports_by_node(self.n.uuid)
        self.assertEqual(self.p['address'], res[0].address)

    def test_get_ports_by_node_that_does_not_exist(self):
        self.dbapi.create_port(self.p)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_ports_by_node,
                          99)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_ports_by_node,
                          '12345678-9999-0000-aaaa-123456789012')

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
        self.assertEqual(new_address, res.address)

    def test_destroy_port_on_reserved_node(self):
        p = self.dbapi.create_port(db_utils.get_test_port(node_id=self.n.id))
        uuid = self.n.uuid
        self.dbapi.reserve_nodes('fake-reservation', [uuid])
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.destroy_port, p.id)

    def test_update_port_duplicated_address(self):
        self.dbapi.create_port(self.p)
        address1 = self.p['address']
        address2 = 'aa-bb-cc-11-22-33'
        p2 = db_utils.get_test_port(id=123, uuid=ironic_utils.generate_uuid(),
                                 node_id=self.n.id, address=address2)
        self.dbapi.create_port(p2)
        self.assertRaises(exception.MACAlreadyExists,
                          self.dbapi.update_port, p2['id'],
                          {'address': address1})

    def test_create_port_duplicated_address(self):
        self.dbapi.create_port(self.p)
        dup_address = self.p['address']
        p2 = db_utils.get_test_port(id=123, uuid=ironic_utils.generate_uuid(),
                                 node_id=self.n.id, address=dup_address)
        self.assertRaises(exception.MACAlreadyExists,
                          self.dbapi.create_port, p2)
