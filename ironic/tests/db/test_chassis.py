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

import six

from ironic.common import exception
from ironic.common import utils as ironic_utils
from ironic.tests.db import base
from ironic.tests.db import utils


class DbChassisTestCase(base.DbTestCase):

    def _create_test_chassis(self, **kwargs):
        ch = utils.get_test_chassis(**kwargs)
        self.dbapi.create_chassis(ch)
        return ch

    def test_get_chassis_list(self):
        uuids = []
        for i in range(1, 6):
            n = utils.get_test_chassis(id=i, uuid=ironic_utils.generate_uuid())
            self.dbapi.create_chassis(n)
            uuids.append(six.text_type(n['uuid']))
        res = self.dbapi.get_chassis_list()
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids.sort(), res_uuids.sort())

    def test_get_chassis_by_id(self):
        ch = self._create_test_chassis()
        chassis = self.dbapi.get_chassis_by_id(ch['id'])

        self.assertEqual(ch['uuid'], chassis.uuid)

    def test_get_chassis_by_uuid(self):
        ch = self._create_test_chassis()
        chassis = self.dbapi.get_chassis_by_uuid(ch['uuid'])

        self.assertEqual(ch['id'], chassis.id)

    def test_get_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_chassis_by_id, 666)

    def test_update_chassis(self):
        ch = self._create_test_chassis()
        res = self.dbapi.update_chassis(ch['id'], {'description': 'hello'})

        self.assertEqual('hello', res.description)

    def test_update_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.update_chassis, 666, {'description': ''})

    def test_update_chassis_uuid(self):
        ch = self._create_test_chassis()
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_chassis, ch['id'],
                          {'uuid': 'hello'})

    def test_destroy_chassis(self):
        ch = self._create_test_chassis()
        self.dbapi.destroy_chassis(ch['id'])

        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.get_chassis_by_id, ch['id'])

    def test_destroy_chassis_that_does_not_exist(self):
        self.assertRaises(exception.ChassisNotFound,
                          self.dbapi.destroy_chassis, 666)

    def test_destroy_chassis_with_nodes(self):
        ch = self._create_test_chassis()
        utils.create_test_node(chassis_id=ch['id'])

        self.assertRaises(exception.ChassisNotEmpty,
                          self.dbapi.destroy_chassis, ch['id'])

    def test_create_chassis_already_exists(self):
        uuid = ironic_utils.generate_uuid()
        self._create_test_chassis(id=1, uuid=uuid)
        self.assertRaises(exception.ChassisAlreadyExists,
                          self._create_test_chassis,
                          id=2, uuid=uuid)
