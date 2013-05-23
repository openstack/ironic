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

from ironic.openstack.common import uuidutils

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

    def test_reserve_one_node(self):
        n = utils.get_test_node()
        uuid = n['uuid']
        self.dbapi.create_node(n)

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        # reserve the node
        self.dbapi.reserve_nodes(r1, [uuid])

        # check reservation
        res = self.dbapi.get_node(uuid)
        self.assertEqual(r1, res['reservation'])

        # another host fails to reserve or release
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, [uuid])
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_nodes,
                          r2, [uuid])

        # release reservation
        self.dbapi.release_nodes(r1, [uuid])
        res = self.dbapi.get_node(uuid)
        self.assertEqual(None, res['reservation'])

        # another host succeeds
        self.dbapi.reserve_nodes(r2, [uuid])
        res = self.dbapi.get_node(uuid)
        self.assertEqual(r2, res['reservation'])

    def test_reserve_many_nodes(self):
        uuids = []
        for i in xrange(1, 6):
            n = utils.get_test_node(id=i, uuid=uuidutils.generate_uuid())
            self.dbapi.create_node(n)
            uuids.append(n['uuid'])

        uuids.sort()
        r1 = 'first-reservation'
        r2 = 'second-reservation'

        # nodes 1,2,3: r1. nodes 4,5: unreseved
        self.dbapi.reserve_nodes(r1, uuids[:3])

        # overlapping ranges fail
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, uuids)
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, uuids[2:])

        # non-overlapping range succeeds
        self.dbapi.reserve_nodes(r2, uuids[3:])

        # overlapping release fails
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_nodes,
                          r1, uuids)

        # non-overlapping release succeeds
        self.dbapi.release_nodes(r1, uuids[:3])
        self.dbapi.release_nodes(r2, uuids[3:])
