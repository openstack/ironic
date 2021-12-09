# Copyright 2016 Hitachi, Ltc
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

"""Tests for manipulating VolumeTargets via the DB API"""

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbVolumeTargetTestCase(base.DbTestCase):

    def setUp(self):
        # This method creates a volume_target for every test.
        super(DbVolumeTargetTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.target = db_utils.create_test_volume_target(node_id=self.node.id)

    def test_create_volume_target(self):
        info = {'uuid': uuidutils.generate_uuid(),
                'node_id': self.node.id,
                'boot_index': 1,
                'volume_type': 'iscsi',
                'volume_id': '12345678'}

        target = self.dbapi.create_volume_target(info)
        self.assertEqual(info['uuid'], target.uuid)
        self.assertEqual(info['node_id'], target.node_id)
        self.assertEqual(info['boot_index'], target.boot_index)
        self.assertEqual(info['volume_type'], target.volume_type)
        self.assertEqual(info['volume_id'], target.volume_id)
        self.assertIsNone(target.properties)
        self.assertIsNone(target.extra)

    def test_create_volume_target_duplicated_nodeid_and_bootindex(self):
        self.assertRaises(exception.VolumeTargetBootIndexAlreadyExists,
                          db_utils.create_test_volume_target,
                          uuid=uuidutils.generate_uuid(),
                          node_id=self.target.node_id,
                          boot_index=self.target.boot_index)

    def test_create_volume_target_duplicated_uuid(self):
        self.assertRaises(exception.VolumeTargetAlreadyExists,
                          db_utils.create_test_volume_target,
                          uuid=self.target.uuid,
                          node_id=self.node.id,
                          boot_index=100)

    def test_get_volume_target_by_id(self):
        res = self.dbapi.get_volume_target_by_id(self.target.id)
        self.assertEqual(self.target.volume_type, res.volume_type)
        self.assertEqual(self.target.properties, res.properties)
        self.assertEqual(self.target.boot_index, res.boot_index)

        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.get_volume_target_by_id,
                          100)

    def test_get_volume_target_by_uuid(self):
        res = self.dbapi.get_volume_target_by_uuid(self.target.uuid)
        self.assertEqual(self.target.id, res.id)

        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.get_volume_target_by_uuid,
                          '11111111-2222-3333-4444-555555555555')

    def _create_list_of_volume_targets(self, num):
        uuids = [str(self.target.uuid)]
        for i in range(1, num):
            volume_target = db_utils.create_test_volume_target(
                uuid=uuidutils.generate_uuid(),
                node_id=self.node.id,
                properties={"target_iqn": "iqn.test-%s" % i},
                boot_index=i)
            uuids.append(str(volume_target.uuid))
        return uuids

    def test_get_volume_target_list(self):
        uuids = self._create_list_of_volume_targets(6)
        res = self.dbapi.get_volume_target_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_volume_target_list_sorted(self):
        uuids = self._create_list_of_volume_targets(5)
        res = self.dbapi.get_volume_target_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_volume_target_list, sort_key='foo')

    def test_get_volume_targets_by_node_id(self):
        node2 = db_utils.create_test_node(uuid=uuidutils.generate_uuid())
        target2 = db_utils.create_test_volume_target(
            uuid=uuidutils.generate_uuid(), node_id=node2.id)
        self._create_list_of_volume_targets(2)
        res = self.dbapi.get_volume_targets_by_node_id(node2.id)
        self.assertEqual(1, len(res))
        self.assertEqual(target2.uuid, res[0].uuid)

    def test_get_volume_targets_by_node_id_that_does_not_exist(self):
        self.assertEqual([], self.dbapi.get_volume_targets_by_node_id(99))

    def test_get_volume_targets_by_volume_id(self):
        # Create two volume_targets. They'll have the same volume_id.
        uuids = self._create_list_of_volume_targets(2)
        res = self.dbapi.get_volume_targets_by_volume_id('12345678')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(uuids, res_uuids)

    def test_get_volume_targets_by_volume_id_that_does_not_exist(self):
        self.assertEqual([], self.dbapi.get_volume_targets_by_volume_id('dne'))

    def test_update_volume_target(self):
        old_boot_index = self.target.boot_index
        new_boot_index = old_boot_index + 1

        res = self.dbapi.update_volume_target(self.target.id,
                                              {'boot_index': new_boot_index})
        self.assertEqual(new_boot_index, res.boot_index)

        res = self.dbapi.update_volume_target(self.target.id,
                                              {'boot_index': old_boot_index})
        self.assertEqual(old_boot_index, res.boot_index)

    def test_update_volume_target_uuid(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_volume_target,
                          self.target.id,
                          {'uuid': uuidutils.generate_uuid()})

    def test_update_volume_target_fails_invalid_id(self):
        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.update_volume_target,
                          99,
                          {'boot_index': 6})

    def test_update_volume_target_duplicated_nodeid_and_bootindex(self):
        t = db_utils.create_test_volume_target(uuid=uuidutils.generate_uuid(),
                                               boot_index=1,
                                               node_id=self.node.id)
        self.assertRaises(exception.VolumeTargetBootIndexAlreadyExists,
                          self.dbapi.update_volume_target,
                          t.uuid,
                          {'boot_index': self.target.boot_index,
                           'node_id': self.target.node_id})

    def test_destroy_volume_target(self):
        self.dbapi.destroy_volume_target(self.target.id)
        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.get_volume_target_by_id,
                          self.target.id)

        # Ensure that destroy_volume_target returns the expected exception.
        self.assertRaises(exception.VolumeTargetNotFound,
                          self.dbapi.destroy_volume_target,
                          self.target.id)
