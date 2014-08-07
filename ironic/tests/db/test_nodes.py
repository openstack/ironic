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

import datetime

import mock
from oslo.utils import timeutils
import six

from ironic.common import exception
from ironic.common import states
from ironic.common import utils as ironic_utils
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

    def test_create_node(self):
        self._create_test_node()

    def test_create_node_nullable_chassis_id(self):
        n = utils.get_test_node()
        del n['chassis_id']
        self.dbapi.create_node(n)

    def test_create_node_already_exists(self):
        n = utils.get_test_node()
        del n['id']
        self.dbapi.create_node(n)
        self.assertRaises(exception.NodeAlreadyExists,
                          self.dbapi.create_node, n)

    def test_create_node_instance_already_associated(self):
        instance = ironic_utils.generate_uuid()
        n1 = utils.get_test_node(id=1, uuid=ironic_utils.generate_uuid(),
                                 instance_uuid=instance)
        self.dbapi.create_node(n1)
        n2 = utils.get_test_node(id=2, uuid=ironic_utils.generate_uuid(),
                                 instance_uuid=instance)
        self.assertRaises(exception.InstanceAssociated,
                          self.dbapi.create_node, n2)

    def test_get_node_by_id(self):
        n = self._create_test_node()
        res = self.dbapi.get_node_by_id(n['id'])
        self.assertEqual(n['id'], res.id)
        self.assertEqual(n['uuid'], res.uuid)

    def test_get_node_by_uuid(self):
        n = self._create_test_node()
        res = self.dbapi.get_node_by_uuid(n['uuid'])
        self.assertEqual(n['id'], res.id)
        self.assertEqual(n['uuid'], res.uuid)

    def test_get_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_id, 99)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_get_nodeinfo_list_defaults(self):
        for i in range(1, 6):
            n = utils.get_test_node(id=i, uuid=ironic_utils.generate_uuid())
            self.dbapi.create_node(n)
        res = [i[0] for i in self.dbapi.get_nodeinfo_list()]
        self.assertEqual(sorted(res), sorted(range(1, 6)))

    def test_get_nodeinfo_list_with_cols(self):
        uuids = {}
        extras = {}
        for i in range(1, 6):
            uuid = ironic_utils.generate_uuid()
            extra = {'foo': i}
            uuids[i] = uuid
            extras[i] = extra
            n = utils.get_test_node(id=i, extra=extra, uuid=uuid)
            self.dbapi.create_node(n)
        res = self.dbapi.get_nodeinfo_list(columns=['id', 'extra', 'uuid'])
        self.assertEqual(extras, dict((r[0], r[1]) for r in res))
        self.assertEqual(uuids, dict((r[0], r[2]) for r in res))

    def test_get_nodeinfo_list_with_filters(self):
        n1 = utils.get_test_node(id=1, driver='driver-one',
                                 instance_uuid=ironic_utils.generate_uuid(),
                                 reservation='fake-host',
                                 uuid=ironic_utils.generate_uuid())
        n2 = utils.get_test_node(id=2, driver='driver-two',
                                 uuid=ironic_utils.generate_uuid(),
                                 maintenance=True)
        self.dbapi.create_node(n1)
        self.dbapi.create_node(n2)

        res = self.dbapi.get_nodeinfo_list(filters={'driver': 'driver-one'})
        self.assertEqual([1], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'driver': 'bad-driver'})
        self.assertEqual([], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'associated': True})
        self.assertEqual([1], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'associated': False})
        self.assertEqual([2], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'reserved': True})
        self.assertEqual([1], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'reserved': False})
        self.assertEqual([2], [r[0] for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': True})
        self.assertEqual([2], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': False})
        self.assertEqual([1], [r.id for r in res])

    @mock.patch.object(timeutils, 'utcnow')
    def test_get_nodeinfo_list_provision(self, mock_utcnow):
        past = datetime.datetime(2000, 1, 1, 0, 0)
        next = past + datetime.timedelta(minutes=8)
        present = past + datetime.timedelta(minutes=10)
        mock_utcnow.return_value = past

        # node with provision_updated timeout
        n1 = utils.get_test_node(id=1, uuid=ironic_utils.generate_uuid(),
                                 provision_updated_at=past)
        # node with None in provision_updated_at
        n2 = utils.get_test_node(id=2, uuid=ironic_utils.generate_uuid(),
                                 provision_state=states.DEPLOYWAIT)
        # node without timeout
        n3 = utils.get_test_node(id=3, uuid=ironic_utils.generate_uuid(),
                                 provision_updated_at=next)
        self.dbapi.create_node(n1)
        self.dbapi.create_node(n2)
        self.dbapi.create_node(n3)

        mock_utcnow.return_value = present
        res = self.dbapi.get_nodeinfo_list(filters={'provisioned_before': 300})
        self.assertEqual([1], [r[0] for r in res])

        res = self.dbapi.get_nodeinfo_list(filters={'provision_state':
                                                    states.DEPLOYWAIT})
        self.assertEqual([2], [r[0] for r in res])

    def test_get_node_list(self):
        uuids = []
        for i in range(1, 6):
            n = utils.get_test_node(id=i, uuid=ironic_utils.generate_uuid())
            self.dbapi.create_node(n)
            uuids.append(six.text_type(n['uuid']))
        res = self.dbapi.get_node_list()
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids.sort(), res_uuids.sort())

    def test_get_node_list_with_filters(self):
        ch1 = utils.get_test_chassis(id=1, uuid=ironic_utils.generate_uuid())
        ch2 = utils.get_test_chassis(id=2, uuid=ironic_utils.generate_uuid())
        self.dbapi.create_chassis(ch1)
        self.dbapi.create_chassis(ch2)

        n1 = utils.get_test_node(id=1, driver='driver-one',
                                 instance_uuid=ironic_utils.generate_uuid(),
                                 reservation='fake-host',
                                 uuid=ironic_utils.generate_uuid(),
                                 chassis_id=ch1['id'])
        n2 = utils.get_test_node(id=2, driver='driver-two',
                                 uuid=ironic_utils.generate_uuid(),
                                 chassis_id=ch2['id'],
                                 maintenance=True)
        self.dbapi.create_node(n1)
        self.dbapi.create_node(n2)

        res = self.dbapi.get_node_list(filters={'chassis_uuid': ch1['uuid']})
        self.assertEqual([1], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'chassis_uuid': ch2['uuid']})
        self.assertEqual([2], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'driver': 'driver-one'})
        self.assertEqual([1], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'driver': 'bad-driver'})
        self.assertEqual([], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'associated': True})
        self.assertEqual([1], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'associated': False})
        self.assertEqual([2], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'reserved': True})
        self.assertEqual([1], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'reserved': False})
        self.assertEqual([2], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': True})
        self.assertEqual([2], [r.id for r in res])

        res = self.dbapi.get_node_list(filters={'maintenance': False})
        self.assertEqual([1], [r.id for r in res])

    def test_get_node_list_chassis_not_found(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_node_list,
                          {'chassis_uuid': ironic_utils.generate_uuid()})

    def test_get_node_by_instance(self):
        n = self._create_test_node(
                instance_uuid='12345678-9999-0000-aaaa-123456789012')

        res = self.dbapi.get_node_by_instance(n['instance_uuid'])
        self.assertEqual(n['uuid'], res.uuid)

    def test_get_node_by_instance_wrong_uuid(self):
        self._create_test_node(
                instance_uuid='12345678-9999-0000-aaaa-123456789012')

        self.assertRaises(exception.InstanceNotFound,
                          self.dbapi.get_node_by_instance,
                          '12345678-9999-0000-bbbb-123456789012')

    def test_get_node_by_instance_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID,
                          self.dbapi.get_node_by_instance,
                          'fake_uuid')

    def test_destroy_node(self):
        n = self._create_test_node()

        self.dbapi.destroy_node(n['id'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_id, n['id'])

    def test_destroy_node_by_uuid(self):
        n = self._create_test_node()

        self.dbapi.destroy_node(n['uuid'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid, n['uuid'])

    def test_destroy_node_that_does_not_exist(self):
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.destroy_node,
                          '12345678-9999-0000-aaaa-123456789012')

    def test_ports_get_destroyed_after_destroying_a_node(self):
        n = self._create_test_node()
        node_id = n['id']

        p = utils.get_test_port(node_id=node_id)
        p = self.dbapi.create_port(p)

        self.dbapi.destroy_node(node_id)

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port_by_id, p.id)

    def test_ports_get_destroyed_after_destroying_a_node_by_uuid(self):
        n = self._create_test_node()
        node_id = n['id']

        p = utils.get_test_port(node_id=node_id)
        p = self.dbapi.create_port(p)

        self.dbapi.destroy_node(n['uuid'])

        self.assertRaises(exception.PortNotFound,
                          self.dbapi.get_port_by_id, p.id)

    def test_update_node(self):
        n = self._create_test_node()

        old_extra = n['extra']
        new_extra = {'foo': 'bar'}
        self.assertNotEqual(old_extra, new_extra)

        res = self.dbapi.update_node(n['id'], {'extra': new_extra})
        self.assertEqual(new_extra, res.extra)

    def test_update_node_not_found(self):
        node_uuid = ironic_utils.generate_uuid()
        new_extra = {'foo': 'bar'}
        self.assertRaises(exception.NodeNotFound, self.dbapi.update_node,
                          node_uuid, {'extra': new_extra})

    def test_update_node_uuid(self):
        n = self._create_test_node()
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_node, n['id'],
                          {'uuid': ''})

    def test_update_node_associate_and_disassociate(self):
        n = self._create_test_node()
        new_i_uuid = ironic_utils.generate_uuid()
        res = self.dbapi.update_node(n['id'], {'instance_uuid': new_i_uuid})
        self.assertEqual(new_i_uuid, res.instance_uuid)
        res = self.dbapi.update_node(n['id'], {'instance_uuid': None})
        self.assertIsNone(res.instance_uuid)

    def test_update_node_already_associated(self):
        n = self._create_test_node()
        new_i_uuid_one = ironic_utils.generate_uuid()
        self.dbapi.update_node(n['id'], {'instance_uuid': new_i_uuid_one})
        new_i_uuid_two = ironic_utils.generate_uuid()
        self.assertRaises(exception.NodeAssociated,
                          self.dbapi.update_node,
                          n['id'],
                          {'instance_uuid': new_i_uuid_two})

    def test_update_node_instance_already_associated(self):
        n = self._create_test_node(id=1, uuid=ironic_utils.generate_uuid())
        new_i_uuid = ironic_utils.generate_uuid()
        self.dbapi.update_node(n['id'], {'instance_uuid': new_i_uuid})
        n = self._create_test_node(id=2, uuid=ironic_utils.generate_uuid())
        self.assertRaises(exception.InstanceAssociated,
                          self.dbapi.update_node,
                          n['id'],
                          {'instance_uuid': new_i_uuid})

    @mock.patch.object(timeutils, 'utcnow')
    def test_update_node_provision(self, mock_utcnow):
        mocked_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = mocked_time
        n = self._create_test_node()
        res = self.dbapi.update_node(n['id'], {'provision_state': 'fake'})
        self.assertEqual(mocked_time,
                         timeutils.normalize_time(res['provision_updated_at']))

    def test_update_node_no_provision(self):
        n = self._create_test_node()
        res = self.dbapi.update_node(n['id'], {'extra': {'foo': 'bar'}})
        self.assertIsNone(res['provision_updated_at'])

    def test_reserve_node(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'

        # reserve the node
        self.dbapi.reserve_node(r1, uuid)

        # check reservation
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertEqual(r1, res.reservation)

    def test_release_reservation(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        self.dbapi.reserve_node(r1, uuid)

        # release reservation
        self.dbapi.release_node(r1, uuid)
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertIsNone(res.reservation)

    def test_reservation_of_reserved_node_fails(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        # reserve the node
        self.dbapi.reserve_node(r1, uuid)

        # another host fails to reserve or release
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.reserve_node,
                          r2, uuid)
        self.assertRaises(exception.NodeLocked,
                          self.dbapi.release_node,
                          r2, uuid)

    def test_reservation_after_release(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r1 = 'fake-reservation'
        r2 = 'another-reservation'

        self.dbapi.reserve_node(r1, uuid)
        self.dbapi.release_node(r1, uuid)

        # another host succeeds
        self.dbapi.reserve_node(r2, uuid)
        res = self.dbapi.get_node_by_uuid(uuid)
        self.assertEqual(r2, res.reservation)

    def test_reservation_in_exception_message(self):
        n = self._create_test_node()
        uuid = n['uuid']

        r = 'fake-reservation'
        self.dbapi.reserve_node(r, uuid)
        try:
            self.dbapi.reserve_node('another', uuid)
        except exception.NodeLocked as e:
            self.assertIn(r, str(e))

    def test_reservation_non_existent_node(self):
        n = self._create_test_node()
        self.dbapi.destroy_node(n['id'])

        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.reserve_node, 'fake', n['id'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.reserve_node, 'fake', n['uuid'])

    def test_release_non_existent_node(self):
        n = self._create_test_node()
        self.dbapi.destroy_node(n['id'])

        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.release_node, 'fake', n['id'])
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.release_node, 'fake', n['uuid'])

    def test_release_non_locked_node(self):
        n = self._create_test_node()

        self.assertEqual(None, n['reservation'])
        self.assertRaises(exception.NodeNotLocked,
                          self.dbapi.release_node, 'fake', n['id'])
        self.assertRaises(exception.NodeNotLocked,
                          self.dbapi.release_node, 'fake', n['uuid'])
