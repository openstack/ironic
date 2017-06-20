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


class TestPortgroupObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestPortgroupObject, self).setUp()
        self.fake_portgroup = db_utils.get_test_portgroup()

    def test_get_by_id(self):
        portgroup_id = self.fake_portgroup['id']
        with mock.patch.object(self.dbapi, 'get_portgroup_by_id',
                               autospec=True) as mock_get_portgroup:
            mock_get_portgroup.return_value = self.fake_portgroup

            portgroup = objects.Portgroup.get(self.context, portgroup_id)

            mock_get_portgroup.assert_called_once_with(portgroup_id)
            self.assertEqual(self.context, portgroup._context)

    def test_get_by_uuid(self):
        uuid = self.fake_portgroup['uuid']
        with mock.patch.object(self.dbapi, 'get_portgroup_by_uuid',
                               autospec=True) as mock_get_portgroup:
            mock_get_portgroup.return_value = self.fake_portgroup

            portgroup = objects.Portgroup.get(self.context, uuid)

            mock_get_portgroup.assert_called_once_with(uuid)
            self.assertEqual(self.context, portgroup._context)

    def test_get_by_address(self):
        address = self.fake_portgroup['address']
        with mock.patch.object(self.dbapi, 'get_portgroup_by_address',
                               autospec=True) as mock_get_portgroup:
            mock_get_portgroup.return_value = self.fake_portgroup

            portgroup = objects.Portgroup.get(self.context, address)

            mock_get_portgroup.assert_called_once_with(address)
            self.assertEqual(self.context, portgroup._context)

    def test_get_by_name(self):
        name = self.fake_portgroup['name']
        with mock.patch.object(self.dbapi, 'get_portgroup_by_name',
                               autospec=True) as mock_get_portgroup:
            mock_get_portgroup.return_value = self.fake_portgroup
            portgroup = objects.Portgroup.get(self.context, name)

            mock_get_portgroup.assert_called_once_with(name)
            self.assertEqual(self.context, portgroup._context)

    def test_get_bad_id_and_uuid_and_address_and_name(self):
        self.assertRaises(exception.InvalidIdentity,
                          objects.Portgroup.get,
                          self.context,
                          'not:a_name_or_uuid')

    def test_create(self):
        portgroup = objects.Portgroup(self.context, **self.fake_portgroup)
        with mock.patch.object(self.dbapi, 'create_portgroup',
                               autospec=True) as mock_create_portgroup:
            mock_create_portgroup.return_value = db_utils.get_test_portgroup()

            portgroup.create()

            args, _kwargs = mock_create_portgroup.call_args
            self.assertEqual(objects.Portgroup.VERSION, args[0]['version'])

    def test_save(self):
        uuid = self.fake_portgroup['uuid']
        address = "b2:54:00:cf:2d:40"
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_portgroup_by_uuid',
                               autospec=True) as mock_get_portgroup:
            mock_get_portgroup.return_value = self.fake_portgroup
            with mock.patch.object(self.dbapi, 'update_portgroup',
                                   autospec=True) as mock_update_portgroup:
                mock_update_portgroup.return_value = (
                    db_utils.get_test_portgroup(address=address,
                                                updated_at=test_time))
                p = objects.Portgroup.get_by_uuid(self.context, uuid)
                p.address = address
                p.save()

                mock_get_portgroup.assert_called_once_with(uuid)
                mock_update_portgroup.assert_called_once_with(
                    uuid, {'version': objects.Portgroup.VERSION,
                           'address': "b2:54:00:cf:2d:40"})
                self.assertEqual(self.context, p._context)
                res_updated_at = (p.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.fake_portgroup['uuid']
        returns = [self.fake_portgroup,
                   db_utils.get_test_portgroup(address="c3:54:00:cf:2d:40")]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_portgroup_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_portgroup:
            p = objects.Portgroup.get_by_uuid(self.context, uuid)
            self.assertEqual("52:54:00:cf:2d:31", p.address)
            p.refresh()
            self.assertEqual("c3:54:00:cf:2d:40", p.address)

            self.assertEqual(expected, mock_get_portgroup.call_args_list)
            self.assertEqual(self.context, p._context)

    def test_save_after_refresh(self):
        # Ensure that it's possible to do object.save() after object.refresh()
        address = "b2:54:00:cf:2d:40"
        db_node = db_utils.create_test_node()
        db_portgroup = db_utils.create_test_portgroup(node_id=db_node.id)
        p = objects.Portgroup.get_by_uuid(self.context, db_portgroup.uuid)
        p_copy = objects.Portgroup.get_by_uuid(self.context, db_portgroup.uuid)
        p.address = address
        p.save()
        p_copy.refresh()
        p_copy.address = 'aa:bb:cc:dd:ee:ff'
        # Ensure this passes and an exception is not generated
        p_copy.save()

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_portgroup_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_portgroup]
            portgroups = objects.Portgroup.list(self.context)
            self.assertThat(portgroups, matchers.HasLength(1))
            self.assertIsInstance(portgroups[0], objects.Portgroup)
            self.assertEqual(self.context, portgroups[0]._context)

    def test_list_by_node_id(self):
        with mock.patch.object(self.dbapi, 'get_portgroups_by_node_id',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_portgroup]
            node_id = self.fake_portgroup['node_id']
            portgroups = objects.Portgroup.list_by_node_id(self.context,
                                                           node_id)
            self.assertThat(portgroups, matchers.HasLength(1))
            self.assertIsInstance(portgroups[0], objects.Portgroup)
            self.assertEqual(self.context, portgroups[0]._context)

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.portgroup,
                                    objects.Portgroup.fields)
