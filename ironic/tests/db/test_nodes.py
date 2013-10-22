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

    def _create_test_node(self, **kwargs):
        n = utils.get_test_node(**kwargs)
        self.dbapi.create_node(n)
        return n

    def _create_many_test_nodes(self):
        uuids = []
        for i in xrange(1, 6):
            n = self._create_test_node(id=i, uuid=uuidutils.generate_uuid())
            uuids.append(n['uuid'])
        uuids.sort()
        return uuids

    def _create_associated_nodes(self):
        uuids = []
        uuids_with_instance = []

        for i in xrange(1, 5):
            uuid = uuidutils.generate_uuid()
            uuids.append(unicode(uuid))
            if i < 3:
                instance_uuid = uuidutils.generate_uuid()
                uuids_with_instance.append(unicode(uuid))
            else:
                instance_uuid = None

            n = utils.get_test_node(id=i,
                                    uuid=uuid,
                                    instance_uuid=instance_uuid)
            self.dbapi.create_node(n)

        uuids.sort()
        uuids_with_instance.sort()
        return (uuids, uuids_with_instance)

    def test_create_node(self):
        self._create_test_node()

    def test_get_nodes_by_chassis_id(self):
        ch = utils.get_test_chassis()
        ch = self.dbapi.create_chassis(ch)
        n = self._create_test_node(chassis_id=ch['id'])
        nodes = self.dbapi.get_nodes_by_chassis(ch['id'])
        self.assertEqual(n['uuid'], nodes[0]['uuid'])

    def test_get_nodes_by_chassis_uuid(self):
        ch = utils.get_test_chassis()
        ch = self.dbapi.create_chassis(ch)
        n = self._create_test_node(chassis_id=ch['id'])
        nodes = self.dbapi.get_nodes_by_chassis(ch['uuid'])
        self.assertEqual(n['id'], nodes[0]['id'])

    def test_get_nodes_by_chassis_that_does_not_exist(self):
        nodes = self.dbapi.get_nodes_by_chassis(33)
        self.assertEqual(0, len(nodes))

        nodes = self.dbapi.get_nodes_by_chassis("1231231-123123-123123")
        self.assertEqual(0, len(nodes))

    def test_get_node_by_id(self):
        n = self._create_test_node()
        res = self.dbapi.get_node(n['id'])
        self.assertEqual(n['uuid'], res['uuid'])

    def test_get_node_by_uuid(self):
        n = self._create_test_node()
        res = self.dbapi.get_node(n['uuid'])
        self.assertEqual(n['id'], res['id'])

    def test_get_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node, 99)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node,
                          '12345678-9999-0000-aaaa-123456789012')
        self.assertRaises(exception.InvalidIdentity,
                          self.dbapi.get_node, 'not-a-uuid')

    def test_get_node_list(self):
        uuids = []
        for i in xrange(1, 6):
            n = utils.get_test_node(id=i, uuid=uuidutils.generate_uuid())
            self.dbapi.create_node(n)
            uuids.append(unicode(n['uuid']))
        res = self.dbapi.get_node_list()
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids.sort(), res_uuids.sort())

    def test_get_node_by_instance(self):
        n = self._create_test_node(instance_uuid='fake-uuid-1234')

        res = self.dbapi.get_node_by_instance(n['instance_uuid'])
        self.assertEqual(n['uuid'], res['uuid'])

        self.assertRaises(exception.InstanceNotFound,
                          self.dbapi.get_node_by_instance,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_destroy_node(self):
        n = self._create_test_node()

        self.dbapi.destroy_node(n['id'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node, n['id'])

    def test_destroy_node_by_uuid(self):
        n = self._create_test_node()

        self.dbapi.destroy_node(n['uuid'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node, n['uuid'])

    def test_destroy_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.destroy_node,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_destroy_reserved_node(self):
        n = self._create_test_node()
        uuid = n['uuid']
        self.dbapi.reserve_nodes('fake-reservation', [uuid])
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.destroy_node, n['id'])

    def test_destroy_associated_node(self):
        n = self._create_test_node(instance_uuid='fake-uuid-1234')
        self.assertRaises(exception.NodeAssociated,
                          self.dbapi.destroy_node, n['uuid'])

    def test_ports_get_destroyed_after_destroying_a_node(self):
        n = self._create_test_node()
        node_id = n['id']

        p = utils.get_test_port(node_id=node_id)
        p = self.dbapi.create_port(p)

        self.dbapi.destroy_node(node_id)

        self.assertRaises(exception.PortNotFound, self.dbapi.get_port, p['id'])

    def test_ports_get_destroyed_after_destroying_a_node_by_uuid(self):
        n = self._create_test_node()
        node_id = n['id']

        p = utils.get_test_port(node_id=node_id)
        p = self.dbapi.create_port(p)

        self.dbapi.destroy_node(n['uuid'])

        self.assertRaises(exception.PortNotFound, self.dbapi.get_port, p['id'])

    def test_update_node(self):
        n = self._create_test_node()

        old_extra = n['extra']
        new_extra = {'foo': 'bar'}
        self.assertNotEqual(old_extra, new_extra)

        res = self.dbapi.update_node(n['id'], {'extra': new_extra})
        self.assertEqual(new_extra, res['extra'])

    def test_reserve_one_node(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'

        # reserve the node
        self.dbapi.reserve_nodes(r1, [uuid])

        # check reservation
        res = self.dbapi.get_node(uuid)
        self.assertEqual(r1, res['reservation'])

    def test_release_reservation(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        self.dbapi.reserve_nodes(r1, [uuid])

        # release reservation
        self.dbapi.release_nodes(r1, [uuid])
        res = self.dbapi.get_node(uuid)
        self.assertEqual(None, res['reservation'])

    def test_reservation_of_reserved_node_fails(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        # reserve the node
        self.dbapi.reserve_nodes(r1, [uuid])

        # another host fails to reserve or release
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, [uuid])
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_nodes,
                          r2, [uuid])

    def test_reservation_after_release(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        self.dbapi.reserve_nodes(r1, [uuid])
        self.dbapi.release_nodes(r1, [uuid])

        # another host succeeds
        self.dbapi.reserve_nodes(r2, [uuid])
        res = self.dbapi.get_node(uuid)
        self.assertEqual(r2, res['reservation'])

    def test_reserve_many_nodes(self):
        uuids = self._create_many_test_nodes()
        r1 = 'first-reservation'

        self.dbapi.reserve_nodes(r1, uuids)

        for uuid in uuids:
            res = self.dbapi.get_node(uuid)
            self.assertEqual(r1, res['reservation'])

    def test_reserve_overlaping_ranges_fails(self):
        uuids = self._create_many_test_nodes()

        r1 = 'first-reservation'
        r2 = 'second-reservation'

        self.dbapi.reserve_nodes(r1, uuids[:3])

        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, uuids)
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_nodes,
                          r2, uuids[2:])

    def test_reserve_non_overlaping_ranges(self):
        uuids = self._create_many_test_nodes()

        r1 = 'first-reservation'
        r2 = 'second-reservation'

        self.dbapi.reserve_nodes(r1, uuids[:3])
        self.dbapi.reserve_nodes(r2, uuids[3:])

        for i in range(0, len(uuids)):
            res = self.dbapi.get_node(uuids[i])

            reservation = r1 if i < 3 else r2
            self.assertEqual(reservation, res['reservation'])

    def test_reserve_empty(self):
        self.assertRaises(exception.InvalidIdentity,
                          self.dbapi.reserve_nodes, 'reserv1', [])

    def test_release_overlaping_ranges_fails(self):
        uuids = self._create_many_test_nodes()

        r1 = 'first-reservation'
        r2 = 'second-reservation'

        self.dbapi.reserve_nodes(r1, uuids[:3])
        self.dbapi.reserve_nodes(r2, uuids[3:])

        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_nodes,
                          r1, uuids)

    def test_release_non_ranges(self):
        uuids = self._create_many_test_nodes()

        r1 = 'first-reservation'
        r2 = 'second-reservation'

        self.dbapi.reserve_nodes(r1, uuids[:3])
        self.dbapi.reserve_nodes(r2, uuids[3:])

        self.dbapi.release_nodes(r1, uuids[:3])
        self.dbapi.release_nodes(r2, uuids[3:])

        for uuid in uuids:
            res = self.dbapi.get_node(uuid)
            self.assertEqual(None, res['reservation'])

    def test_get_associated_nodes(self):
        (uuids, uuids_with_instance) = self._create_associated_nodes()

        res = self.dbapi.get_associated_nodes()
        res_uuids = [r.uuid for r in res]
        res_uuids.sort()
        self.assertEqual(uuids_with_instance, res_uuids)

    def test_get_unassociated_nodes(self):
        (uuids, uuids_with_instance) = self._create_associated_nodes()
        uuids_without_instance = list(set(uuids) - set(uuids_with_instance))
        uuids_without_instance.sort()

        res = self.dbapi.get_unassociated_nodes()
        res_uuids = [r.uuid for r in res]
        res_uuids.sort()
        self.assertEqual(uuids_without_instance, res_uuids)
