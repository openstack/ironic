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

"""Tests for manipulating portgroups via the DB API"""

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbportgroupTestCase(base.DbTestCase):

    def setUp(self):
        # This method creates a portgroup for every test and
        # replaces a test for creating a portgroup.
        super(DbportgroupTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.portgroup = db_utils.create_test_portgroup(node_id=self.node.id)

    def _create_test_portgroup_range(self, count):
        """Create the specified number of test portgroup entries in DB

        It uses create_test_portgroup method. And returns List of Portgroup
        DB objects.

        :param count: Specifies the number of portgroups to be created
        :returns: List of Portgroup DB objects

        """
        uuids = []
        for i in range(1, count):
            portgroup = db_utils.create_test_portgroup(
                uuid=uuidutils.generate_uuid(),
                name='portgroup' + str(i),
                address='52:54:00:cf:2d:4%s' % i)
            uuids.append(str(portgroup.uuid))

        return uuids

    def test_get_portgroup_by_id(self):
        res = self.dbapi.get_portgroup_by_id(self.portgroup.id)
        self.assertEqual(self.portgroup.address, res.address)

    def test_get_portgroup_by_id_that_does_not_exist(self):
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.get_portgroup_by_id, 99)

    def test_get_portgroup_by_uuid(self):
        res = self.dbapi.get_portgroup_by_uuid(self.portgroup.uuid)
        self.assertEqual(self.portgroup.id, res.id)

    def test_get_portgroup_by_uuid_that_does_not_exist(self):
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.get_portgroup_by_uuid,
                          'EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE')

    def test_get_portgroup_by_address(self):
        res = self.dbapi.get_portgroup_by_address(self.portgroup.address)
        self.assertEqual(self.portgroup.id, res.id)

    def test_get_portgroup_by_address_that_does_not_exist(self):
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.get_portgroup_by_address,
                          '31:31:31:31:31:31')

    def test_get_portgroup_by_name(self):
        res = self.dbapi.get_portgroup_by_name(self.portgroup.name)
        self.assertEqual(self.portgroup.id, res.id)

    def test_get_portgroup_by_name_that_does_not_exist(self):
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.get_portgroup_by_name, 'testfail')

    def test_get_portgroup_list(self):
        uuids = self._create_test_portgroup_range(6)

        # Also add the uuid for the portgroup created in setUp()
        uuids.append(str(self.portgroup.uuid))
        res = self.dbapi.get_portgroup_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_portgroup_list_sorted(self):
        uuids = self._create_test_portgroup_range(6)

        # Also add the uuid for the portgroup created in setUp()
        uuids.append(str(self.portgroup.uuid))
        res = self.dbapi.get_portgroup_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_portgroup_list, sort_key='foo')

    def test_get_portgroups_by_node_id(self):
        res = self.dbapi.get_portgroups_by_node_id(self.node.id)
        self.assertEqual(self.portgroup.address, res[0].address)

    def test_get_portgroups_by_node_id_that_does_not_exist(self):
        self.assertEqual([], self.dbapi.get_portgroups_by_node_id(99))

    def test_destroy_portgroup(self):
        self.dbapi.destroy_portgroup(self.portgroup.id)
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.get_portgroup_by_id, self.portgroup.id)

    def test_destroy_portgroup_that_does_not_exist(self):
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.destroy_portgroup, 99)

    def test_destroy_portgroup_uuid(self):
        self.dbapi.destroy_portgroup(self.portgroup.uuid)

    def test_destroy_portgroup_not_empty(self):
        self.port = db_utils.create_test_port(node_id=self.node.id,
                                              portgroup_id=self.portgroup.id)
        self.assertRaises(exception.PortgroupNotEmpty,
                          self.dbapi.destroy_portgroup, self.portgroup.id)

    def test_update_portgroup(self):
        old_address = self.portgroup.address
        new_address = 'ff:ee:dd:cc:bb:aa'
        self.assertNotEqual(old_address, new_address)
        old_name = self.portgroup.name
        new_name = 'newname'
        self.assertNotEqual(old_name, new_name)
        res = self.dbapi.update_portgroup(self.portgroup.id,
                                          {'address': new_address,
                                           'name': new_name})
        self.assertEqual(new_address, res.address)
        self.assertEqual(new_name, res.name)

    def test_update_portgroup_uuid(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_portgroup, self.portgroup.id,
                          {'uuid': ''})

    def test_update_portgroup_not_found(self):
        id_2 = 99
        self.assertNotEqual(self.portgroup.id, id_2)
        address2 = 'aa:bb:cc:11:22:33'
        self.assertRaises(exception.PortgroupNotFound,
                          self.dbapi.update_portgroup, id_2,
                          {'address': address2})

    def test_update_portgroup_duplicated_address(self):
        address1 = self.portgroup.address
        address2 = 'aa:bb:cc:11:22:33'
        portgroup2 = db_utils.create_test_portgroup(
            uuid=uuidutils.generate_uuid(),
            node_id=self.node.id,
            name=str(uuidutils.generate_uuid()),
            address=address2)
        self.assertRaises(exception.PortgroupMACAlreadyExists,
                          self.dbapi.update_portgroup, portgroup2.id,
                          {'address': address1})

    def test_update_portgroup_duplicated_name(self):
        name1 = self.portgroup.name
        portgroup2 = db_utils.create_test_portgroup(
            uuid=uuidutils.generate_uuid(),
            node_id=self.node.id,
            name='name2', address='aa:bb:cc:11:22:55')
        self.assertRaises(exception.PortgroupDuplicateName,
                          self.dbapi.update_portgroup, portgroup2.id,
                          {'name': name1})

    def test_create_portgroup_duplicated_name(self):
        self.assertRaises(exception.PortgroupDuplicateName,
                          db_utils.create_test_portgroup,
                          uuid=uuidutils.generate_uuid(),
                          node_id=self.node.id,
                          name=self.portgroup.name,
                          address='aa:bb:cc:11:22:55')

    def test_create_portgroup_duplicated_address(self):
        self.assertRaises(exception.PortgroupMACAlreadyExists,
                          db_utils.create_test_portgroup,
                          uuid=uuidutils.generate_uuid(),
                          node_id=self.node.id,
                          name=str(uuidutils.generate_uuid()),
                          address=self.portgroup.address)

    def test_create_portgroup_duplicated_uuid(self):
        self.assertRaises(exception.PortgroupAlreadyExists,
                          db_utils.create_test_portgroup,
                          uuid=self.portgroup.uuid,
                          node_id=self.node.id,
                          name=str(uuidutils.generate_uuid()),
                          address='aa:bb:cc:33:11:22')

    def test_create_portgroup_no_mode(self):
        self.config(default_portgroup_mode='802.3ad')
        name = uuidutils.generate_uuid()
        db_utils.create_test_portgroup(uuid=uuidutils.generate_uuid(),
                                       node_id=self.node.id, name=name,
                                       address='aa:bb:cc:dd:ee:ff')
        res = self.dbapi.get_portgroup_by_id(self.portgroup.id)
        self.assertEqual('active-backup', res.mode)
        res = self.dbapi.get_portgroup_by_name(name)
        self.assertEqual('802.3ad', res.mode)
