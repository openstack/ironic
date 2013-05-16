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

"""Tests for manipulating Nodes via the DB API"""

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.tests.db import base
from ironic.tests.db import utils


class DbNodeTestCase(base.DbTestCase):

    def setUp(self):
        super(DbNodeTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()

    def test_create_node(self):
        n = utils.get_test_node()
        self.dbapi.create_node(n)

    def test_get_node(self):
        n = utils.get_test_node()
        self.dbapi.create_node(n)

        # test get-by-id
        res = self.dbapi.get_node(n['id'])
        self.assertEqual(n['uuid'], res['uuid'])

        # test get-by-uuid
        res = self.dbapi.get_node(n['uuid'])
        self.assertEqual(n['id'], res['id'])

        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node, 99)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node,
                          '12345678-9999-0000-aaaa-123456789012')
        self.assertRaises(exception.InvalidUUID,
                          self.dbapi.get_node, 'not-a-uuid')

    def test_get_node_by_instance(self):
        n = utils.get_test_node()
        self.dbapi.create_node(n)

        res = self.dbapi.get_node_by_instance(n['instance_uuid'])
        self.assertEqual(n['uuid'], res['uuid'])

        self.assertRaises(exception.InstanceNotFound,
                          self.dbapi.get_node_by_instance,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_destroy_node(self):
        n = utils.get_test_node()
        self.dbapi.create_node(n)

        self.dbapi.destroy_node(n['id'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.destroy_node, n['id'])

    def test_update_node(self):
        n = utils.get_test_node()
        self.dbapi.create_node(n)

        old_state = n['task_state']
        new_state = 'TESTSTATE'
        self.assertNotEqual(old_state, new_state)

        res = self.dbapi.update_node(n['id'], {'task_state': new_state})
        self.assertEqual(new_state, res['task_state'])
