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

import datetime

import mock
from testtools import matchers

from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestAllocationObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestAllocationObject, self).setUp()
        self.fake_allocation = db_utils.get_test_allocation(name='host1')

    def test_get_by_id(self):
        allocation_id = self.fake_allocation['id']
        with mock.patch.object(self.dbapi, 'get_allocation_by_id',
                               autospec=True) as mock_get_allocation:
            mock_get_allocation.return_value = self.fake_allocation

            allocation = objects.Allocation.get(self.context, allocation_id)

            mock_get_allocation.assert_called_once_with(allocation_id)
            self.assertEqual(self.context, allocation._context)

    def test_get_by_uuid(self):
        uuid = self.fake_allocation['uuid']
        with mock.patch.object(self.dbapi, 'get_allocation_by_uuid',
                               autospec=True) as mock_get_allocation:
            mock_get_allocation.return_value = self.fake_allocation

            allocation = objects.Allocation.get(self.context, uuid)

            mock_get_allocation.assert_called_once_with(uuid)
            self.assertEqual(self.context, allocation._context)

    def test_get_by_name(self):
        name = self.fake_allocation['name']
        with mock.patch.object(self.dbapi, 'get_allocation_by_name',
                               autospec=True) as mock_get_allocation:
            mock_get_allocation.return_value = self.fake_allocation
            allocation = objects.Allocation.get(self.context, name)

            mock_get_allocation.assert_called_once_with(name)
            self.assertEqual(self.context, allocation._context)

    def test_get_bad_id_and_uuid_and_name(self):
        self.assertRaises(exception.InvalidIdentity,
                          objects.Allocation.get,
                          self.context,
                          'not:a_name_or_uuid')

    def test_create(self):
        allocation = objects.Allocation(self.context, **self.fake_allocation)
        with mock.patch.object(self.dbapi, 'create_allocation',
                               autospec=True) as mock_create_allocation:
            mock_create_allocation.return_value = (
                db_utils.get_test_allocation())

            allocation.create()

            args, _kwargs = mock_create_allocation.call_args
            self.assertEqual(objects.Allocation.VERSION, args[0]['version'])

    def test_save(self):
        uuid = self.fake_allocation['uuid']
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_allocation_by_uuid',
                               autospec=True) as mock_get_allocation:
            mock_get_allocation.return_value = self.fake_allocation
            with mock.patch.object(self.dbapi, 'update_allocation',
                                   autospec=True) as mock_update_allocation:
                mock_update_allocation.return_value = (
                    db_utils.get_test_allocation(name='newname',
                                                 updated_at=test_time))
                p = objects.Allocation.get_by_uuid(self.context, uuid)
                p.name = 'newname'
                p.save()

                mock_get_allocation.assert_called_once_with(uuid)
                mock_update_allocation.assert_called_once_with(
                    uuid, {'version': objects.Allocation.VERSION,
                           'name': 'newname'})
                self.assertEqual(self.context, p._context)
                res_updated_at = (p.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.fake_allocation['uuid']
        returns = [self.fake_allocation,
                   db_utils.get_test_allocation(name='newname')]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_allocation_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_allocation:
            p = objects.Allocation.get_by_uuid(self.context, uuid)
            self.assertEqual(self.fake_allocation['name'], p.name)
            p.refresh()
            self.assertEqual('newname', p.name)

            self.assertEqual(expected, mock_get_allocation.call_args_list)
            self.assertEqual(self.context, p._context)

    def test_save_after_refresh(self):
        # Ensure that it's possible to do object.save() after object.refresh()
        db_allocation = db_utils.create_test_allocation()
        p = objects.Allocation.get_by_uuid(self.context, db_allocation.uuid)
        p_copy = objects.Allocation.get_by_uuid(self.context,
                                                db_allocation.uuid)
        p.name = 'newname'
        p.save()
        p_copy.refresh()
        p.copy = 'newname2'
        # Ensure this passes and an exception is not generated
        p_copy.save()

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_allocation_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_allocation]
            allocations = objects.Allocation.list(self.context)
            self.assertThat(allocations, matchers.HasLength(1))
            self.assertIsInstance(allocations[0], objects.Allocation)
            self.assertEqual(self.context, allocations[0]._context)

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.allocation,
                                    objects.Allocation.fields)
