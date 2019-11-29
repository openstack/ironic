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

"""Tests for manipulating Chassis via the DB API"""

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class DbChassisTestCase(base.DbTestCase):

    def setUp(self):
        super(DbChassisTestCase, self).setUp()
        self.chassis = utils.create_test_chassis()

    def test_get_chassis_list(self):
        uuids = [self.chassis.uuid]
        for i in range(1, 6):
            ch = utils.create_test_chassis(uuid=uuidutils.generate_uuid())
            uuids.append(str(ch.uuid))
        res = self.dbapi.get_chassis_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_chassis_by_id(self):
        chassis = self.dbapi.get_chassis_by_id(self.chassis.id)

        self.assertEqual(self.chassis.uuid, chassis.uuid)

    def test_get_chassis_by_uuid(self):
        chassis = self.dbapi.get_chassis_by_uuid(self.chassis.uuid)

        self.assertEqual(self.chassis.id, chassis.id)

    def test_get_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_chassis_by_id, 666)

    def test_update_chassis(self):
        res = self.dbapi.update_chassis(self.chassis.id,
                                        {'description': 'hello'})

        self.assertEqual('hello', res.description)

    def test_update_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.update_chassis, 666, {'description': ''})

    def test_update_chassis_uuid(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_chassis, self.chassis.id,
                          {'uuid': 'hello'})

    def test_destroy_chassis(self):
        self.dbapi.destroy_chassis(self.chassis.id)

        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_chassis_by_id, self.chassis.id)

    def test_destroy_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.destroy_chassis, 666)

    def test_destroy_chassis_with_nodes(self):
        utils.create_test_node(chassis_id=self.chassis.id)

        self.assertRaises(exception.ChassisNotEmpty,
                          self.dbapi.destroy_chassis, self.chassis.id)

    def test_create_chassis_already_exists(self):
        self.assertRaises(exception.ChassisAlreadyExists,
                          utils.create_test_chassis,
                          uuid=self.chassis.uuid)
