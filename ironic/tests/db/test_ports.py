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
from ironic.tests.db import base
from ironic.tests.db import utils


class DbPortTestCase(base.DbTestCase):

    def setUp(self):
        super(DbPortTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        self.n = None
        self.p = None

    def _init(self):
        self.n = utils.get_test_node()
        self.p = utils.get_test_port()
        self.dbapi.create_node(self.n)
        self.dbapi.create_port(self.p)

    def test_create_port(self):
        self._init()

    def test_get_port(self):
        self._init()

        # test get-by-id
        res = self.dbapi.get_port(self.p['id'])
        self.assertEqual(self.p['address'], res['address'])

        # test get-by-uuid
        res = self.dbapi.get_port(self.p['uuid'])
        self.assertEqual(self.p['id'], res['id'])

        # test get-by-address
        res = self.dbapi.get_port(self.p['address'])
        self.assertEqual(self.p['id'], res['id'])

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 99)
        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port, 'aa:bb:cc:dd:ee:ff')
        self.assertRaises(exception.InvalidMAC,
                          self.dbapi.get_port, 'not-a-mac')

    def test_get_ports_by_node(self):
        self._init()

        # test get-by-node-id
        res = self.dbapi.get_ports_by_node(self.n['id'])
        self.assertEqual(self.p['address'], res[0]['address'])

        # test get-by-node-uuid
        res = self.dbapi.get_ports_by_node(self.n['uuid'])
        self.assertEqual(self.p['address'], res[0]['address'])

        # same tests, but fail
        res = self.dbapi.get_ports_by_node(99)
        self.assertEqual(0, len(res))

        res = self.dbapi.get_ports_by_node(
                '12345678-9999-0000-aaaa-123456789012')
        self.assertEqual(0, len(res))
