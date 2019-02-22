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

"""Tests for manipulating allocations via the DB API"""

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.db import api as db_api
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class AllocationsTestCase(base.DbTestCase):

    def setUp(self):
        super(AllocationsTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.allocation = db_utils.create_test_allocation(name='host1')

    def test_create(self):
        dbapi = db_api.get_instance()
        allocation = dbapi.create_allocation({'resource_class': 'bm'})
        self.assertIsNotNone(allocation.uuid)
        self.assertEqual('allocating', allocation.state)

    def _create_test_allocation_range(self, count, start_idx=0, **kw):
        """Create the specified number of test allocation entries in DB

        It uses create_test_allocation method. And returns List of Allocation
        DB objects.

        :param count: Specifies the number of allocations to be created
        :returns: List of Allocation DB objects

        """
        return [db_utils.create_test_allocation(uuid=uuidutils.generate_uuid(),
                                                name='allocation' + str(i),
                                                **kw).uuid
                for i in range(start_idx, count + start_idx)]

    def test_get_allocation_by_id(self):
        res = self.dbapi.get_allocation_by_id(self.allocation.id)
        self.assertEqual(self.allocation.uuid, res.uuid)

    def test_get_allocation_by_id_that_does_not_exist(self):
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_id, 99)

    def test_get_allocation_by_uuid(self):
        res = self.dbapi.get_allocation_by_uuid(self.allocation.uuid)
        self.assertEqual(self.allocation.id, res.id)

    def test_get_allocation_by_uuid_that_does_not_exist(self):
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_uuid,
                          'EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE')

    def test_get_allocation_by_name(self):
        res = self.dbapi.get_allocation_by_name(self.allocation.name)
        self.assertEqual(self.allocation.id, res.id)

    def test_get_allocation_by_name_that_does_not_exist(self):
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_name, 'testfail')

    def test_get_allocation_list(self):
        uuids = self._create_test_allocation_range(6)
        # Also add the uuid for the allocation created in setUp()
        uuids.append(self.allocation.uuid)

        res = self.dbapi.get_allocation_list()
        self.assertEqual(set(uuids), {r.uuid for r in res})

    def test_get_allocation_list_sorted(self):
        uuids = self._create_test_allocation_range(6)
        # Also add the uuid for the allocation created in setUp()
        uuids.append(self.allocation.uuid)

        res = self.dbapi.get_allocation_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

    def test_get_allocation_list_filter_by_state(self):
        self._create_test_allocation_range(6, state='error')

        res = self.dbapi.get_allocation_list(filters={'state': 'allocating'})
        self.assertEqual([self.allocation.uuid], [r.uuid for r in res])

        res = self.dbapi.get_allocation_list(filters={'state': 'error'})
        self.assertEqual(6, len(res))

    def test_get_allocation_list_filter_by_node(self):
        self._create_test_allocation_range(6)
        self.dbapi.update_allocation(self.allocation.id,
                                     {'node_id': self.node.id})

        res = self.dbapi.get_allocation_list(
            filters={'node_uuid': self.node.uuid})
        self.assertEqual([self.allocation.uuid], [r.uuid for r in res])

    def test_get_allocation_list_filter_by_rsc(self):
        self._create_test_allocation_range(6)
        self.dbapi.update_allocation(self.allocation.id,
                                     {'resource_class': 'very-large'})

        res = self.dbapi.get_allocation_list(
            filters={'resource_class': 'very-large'})
        self.assertEqual([self.allocation.uuid], [r.uuid for r in res])

    def test_get_allocation_list_filter_by_conductor_affinity(self):
        db_utils.create_test_conductor(id=1, hostname='host1')
        db_utils.create_test_conductor(id=2, hostname='host2')
        in_host1 = self._create_test_allocation_range(2, conductor_affinity=1)
        in_host2 = self._create_test_allocation_range(2, conductor_affinity=2,
                                                      start_idx=2)

        res = self.dbapi.get_allocation_list(
            filters={'conductor_affinity': 1})
        self.assertEqual(set(in_host1), {r.uuid for r in res})

        res = self.dbapi.get_allocation_list(
            filters={'conductor_affinity': 'host2'})
        self.assertEqual(set(in_host2), {r.uuid for r in res})

    def test_get_allocation_list_invalid_fields(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_allocation_list, sort_key='foo')
        self.assertRaises(ValueError,
                          self.dbapi.get_allocation_list,
                          filters={'foo': 42})

    def test_destroy_allocation(self):
        self.dbapi.destroy_allocation(self.allocation.id)
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_id, self.allocation.id)

    def test_destroy_allocation_with_node(self):
        self.dbapi.update_node(self.node.id,
                               {'allocation_id': self.allocation.id,
                                'instance_uuid': uuidutils.generate_uuid(),
                                'instance_info': {'traits': ['foo']}})
        self.dbapi.destroy_allocation(self.allocation.id)
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.get_allocation_by_id, self.allocation.id)
        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertIsNone(node.allocation_id)
        self.assertIsNone(node.instance_uuid)
        # NOTE(dtantsur): currently we do not clean up instance_info contents
        # on deallocation. It may be changed in the future.
        self.assertEqual(node.instance_info, {'traits': ['foo']})

    def test_destroy_allocation_that_does_not_exist(self):
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.destroy_allocation, 99)

    def test_destroy_allocation_uuid(self):
        self.dbapi.destroy_allocation(self.allocation.uuid)

    def test_update_allocation(self):
        old_name = self.allocation.name
        new_name = 'newname'
        self.assertNotEqual(old_name, new_name)
        res = self.dbapi.update_allocation(self.allocation.id,
                                           {'name': new_name})
        self.assertEqual(new_name, res.name)

    def test_update_allocation_uuid(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_allocation, self.allocation.id,
                          {'uuid': ''})

    def test_update_allocation_not_found(self):
        id_2 = 99
        self.assertNotEqual(self.allocation.id, id_2)
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.update_allocation, id_2,
                          {'name': 'newname'})

    def test_update_allocation_duplicated_name(self):
        name1 = self.allocation.name
        allocation2 = db_utils.create_test_allocation(
            uuid=uuidutils.generate_uuid(), name='name2')
        self.assertRaises(exception.AllocationDuplicateName,
                          self.dbapi.update_allocation, allocation2.id,
                          {'name': name1})

    def test_update_allocation_with_node_id(self):
        res = self.dbapi.update_allocation(self.allocation.id,
                                           {'name': 'newname',
                                            'traits': ['foo'],
                                            'node_id': self.node.id})
        self.assertEqual('newname', res.name)
        self.assertEqual(['foo'], res.traits)
        self.assertEqual(self.node.id, res.node_id)

        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertEqual(res.id, node.allocation_id)
        self.assertEqual(res.uuid, node.instance_uuid)
        self.assertEqual(['foo'], node.instance_info['traits'])

    def test_update_allocation_node_already_associated(self):
        existing_uuid = uuidutils.generate_uuid()
        self.dbapi.update_node(self.node.id, {'instance_uuid': existing_uuid})
        self.assertRaises(exception.NodeAssociated,
                          self.dbapi.update_allocation, self.allocation.id,
                          {'node_id': self.node.id, 'traits': ['foo']})

        # Make sure we do not see partial updates
        allocation = self.dbapi.get_allocation_by_id(self.allocation.id)
        self.assertEqual([], allocation.traits)
        self.assertIsNone(allocation.node_id)

        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertIsNone(node.allocation_id)
        self.assertEqual(existing_uuid, node.instance_uuid)
        self.assertNotIn('traits', node.instance_info)

    def test_update_allocation_associated_with_another_node(self):
        db_utils.create_test_node(uuid=uuidutils.generate_uuid(),
                                  allocation_id=self.allocation.id,
                                  instance_uuid=self.allocation.uuid)

        self.assertRaises(exception.InstanceAssociated,
                          self.dbapi.update_allocation, self.allocation.id,
                          {'node_id': self.node.id, 'traits': ['foo']})

        # Make sure we do not see partial updates
        allocation = self.dbapi.get_allocation_by_id(self.allocation.id)
        self.assertEqual([], allocation.traits)
        self.assertIsNone(allocation.node_id)

        node = self.dbapi.get_node_by_id(self.node.id)
        self.assertIsNone(node.allocation_id)
        self.assertIsNone(node.instance_uuid)
        self.assertNotIn('traits', node.instance_info)

    def test_take_over_success(self):
        for i in range(2):
            db_utils.create_test_conductor(id=i, hostname='host-%d' % i)
        allocation = db_utils.create_test_allocation(conductor_affinity=0)

        self.assertTrue(self.dbapi.take_over_allocation(
            allocation.id, old_conductor_id=0, new_conductor_id=1))
        allocation = self.dbapi.get_allocation_by_id(allocation.id)
        self.assertEqual(1, allocation.conductor_affinity)

    def test_take_over_conflict(self):
        for i in range(3):
            db_utils.create_test_conductor(id=i, hostname='host-%d' % i)
        allocation = db_utils.create_test_allocation(conductor_affinity=2)

        self.assertFalse(self.dbapi.take_over_allocation(
            allocation.id, old_conductor_id=0, new_conductor_id=1))
        allocation = self.dbapi.get_allocation_by_id(allocation.id)
        # The affinity was not changed
        self.assertEqual(2, allocation.conductor_affinity)

    def test_take_over_allocation_not_found(self):
        self.assertRaises(exception.AllocationNotFound,
                          self.dbapi.take_over_allocation, 999, 0, 1)

    def test_create_allocation_duplicated_name(self):
        self.assertRaises(exception.AllocationDuplicateName,
                          db_utils.create_test_allocation,
                          uuid=uuidutils.generate_uuid(),
                          name=self.allocation.name)

    def test_create_allocation_duplicated_uuid(self):
        self.assertRaises(exception.AllocationAlreadyExists,
                          db_utils.create_test_allocation,
                          uuid=self.allocation.uuid)
