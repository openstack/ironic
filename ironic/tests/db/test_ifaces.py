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

"""Tests for manipulating Interfacesvia the DB API"""

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.tests.db import base
from ironic.tests.db import utils


class DbIfaceTestCase(base.DbTestCase):

    def setUp(self):
        super(DbIfaceTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()

    def test_create_iface(self):
        i = utils.get_test_iface()
        self.dbapi.create_iface(i)

    def test_get_iface_by_vif(self):
        pass

    def test_get_iface(self):
        i = utils.get_test_iface()
        self.dbapi.create_iface(i)

        # test get-by-id
        res = self.dbapi.get_iface(i['id'])
        self.assertEqual(i['address'], res['address'])

        # test get-by-address
        res = self.dbapi.get_iface(i['address'])
        self.assertEqual(i['id'], res['id'])

        self.assertRaises(exception.InterfaceNotFound,
                          self.dbapi.get_iface, 99)
        self.assertRaises(exception.InterfaceNotFound,
                          self.dbapi.get_iface, 'aa:bb:cc:dd:ee:ff')
        self.assertRaises(exception.InvalidMAC,
                          self.dbapi.get_iface, 'not-a-mac')

    def test_get_iface_by_node(self):
        i = utils.get_test_iface()
        self.dbapi.create_iface(i)

        n = utils.get_test_node()
        self.dbapi.create_node(n)

        # test get-by-node-id
        res = self.dbapi.get_iface_by_node(n['id'])
        self.assertEqual(i['address'], res[0]['address'])

        # test get-by-node-uuid
        res = self.dbapi.get_iface_by_node(n['uuid'])
        self.assertEqual(i['address'], res[0]['address'])

        # same tests, but fail
        res = self.dbapi.get_iface_by_node(99)
        self.assertEqual(0, len(res))

        res = self.dbapi.get_iface_by_node(
                '12345678-9999-0000-aaaa-123456789012')
        self.assertEqual(0, len(res))
