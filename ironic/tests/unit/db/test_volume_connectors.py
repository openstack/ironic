# Copyright 2015 Hitachi Data Systems
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

"""Tests for manipulating VolumeConnectors via the DB API"""

from oslo_utils import uuidutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils as db_utils


class DbVolumeConnectorTestCase(base.DbTestCase):

    def setUp(self):
        # This method creates a volume_connector for every test and
        # replaces a test for creating a volume_connector.
        super(DbVolumeConnectorTestCase, self).setUp()
        self.node = db_utils.create_test_node()
        self.connector = db_utils.create_test_volume_connector(
            node_id=self.node.id, type='test',
            connector_id='test-connector_id')

    def test_create_volume_connector_duplicated_type_connector_id(self):
        self.assertRaises(exception.VolumeConnectorTypeAndIdAlreadyExists,
                          db_utils.create_test_volume_connector,
                          uuid=uuidutils.generate_uuid(),
                          node_id=self.node.id,
                          type=self.connector.type,
                          connector_id=self.connector.connector_id)

    def test_create_volume_connector_duplicated_uuid(self):
        self.assertRaises(exception.VolumeConnectorAlreadyExists,
                          db_utils.create_test_volume_connector,
                          uuid=self.connector.uuid,
                          node_id=self.node.id,
                          type='test',
                          connector_id='test-connector_id-2')

    def test_get_volume_connector_by_id(self):
        res = self.dbapi.get_volume_connector_by_id(self.connector.id)
        self.assertEqual(self.connector.type, res.type)
        self.assertEqual(self.connector.connector_id, res.connector_id)
        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.get_volume_connector_by_id,
                          -1)

    def test_get_volume_connector_by_uuid(self):
        res = self.dbapi.get_volume_connector_by_uuid(self.connector.uuid)
        self.assertEqual(self.connector.id, res.id)
        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.get_volume_connector_by_uuid,
                          -1)

    def _connector_list_preparation(self):
        uuids = [str(self.connector.uuid)]
        for i in range(1, 6):
            volume_connector = db_utils.create_test_volume_connector(
                uuid=uuidutils.generate_uuid(),
                node_id=self.node.id,
                type='iqn',
                connector_id='iqn.test-%s' % i)
            uuids.append(str(volume_connector.uuid))
        return uuids

    def test_get_volume_connector_list(self):
        uuids = self._connector_list_preparation()
        res = self.dbapi.get_volume_connector_list()
        res_uuids = [r.uuid for r in res]
        self.assertCountEqual(uuids, res_uuids)

    def test_get_volume_connector_list_sorted(self):
        uuids = self._connector_list_preparation()
        res = self.dbapi.get_volume_connector_list(sort_key='uuid')
        res_uuids = [r.uuid for r in res]
        self.assertEqual(sorted(uuids), res_uuids)

        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.get_volume_connector_list, sort_key='foo')

    def test_get_volume_connectors_by_node_id(self):
        res = self.dbapi.get_volume_connectors_by_node_id(self.node.id)
        self.assertEqual(self.connector.type, res[0].type)
        self.assertEqual(self.connector.connector_id, res[0].connector_id)

    def test_get_volume_connectors_by_node_id_that_does_not_exist(self):
        self.assertEqual([], self.dbapi.get_volume_connectors_by_node_id(99))

    def test_update_volume_connector(self):
        old_connector_id = self.connector.connector_id
        new_connector_id = 'test-connector_id-2'

        self.assertNotEqual(old_connector_id, new_connector_id)

        res = self.dbapi.update_volume_connector(
            self.connector.id,
            {'connector_id': new_connector_id})
        self.assertEqual(new_connector_id, res.connector_id)
        res = self.dbapi.update_volume_connector(
            self.connector.uuid,
            {'connector_id': old_connector_id})
        self.assertEqual(old_connector_id, res.connector_id)

    def test_update_volume_connector_uuid(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.dbapi.update_volume_connector,
                          self.connector.id,
                          {'uuid': ''})

    def test_update_volume_connector_fails_invalid_id(self):
        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.update_volume_connector,
                          -1,
                          {'node_id': ''})

    def test_update_volume_connector_duplicated_type_connector_id(self):
        type = self.connector.type
        connector_id1 = self.connector.connector_id
        connector_id2 = 'test-connector_id-2'
        volume_connector2 = db_utils.create_test_volume_connector(
            uuid=uuidutils.generate_uuid(),
            node_id=self.node.id,
            type=type,
            connector_id=connector_id2)
        self.assertRaises(exception.VolumeConnectorTypeAndIdAlreadyExists,
                          self.dbapi.update_volume_connector,
                          volume_connector2.id,
                          {'connector_id': connector_id1})

    def test_destroy_volume_connector(self):
        self.dbapi.destroy_volume_connector(self.connector.id)
        # Attempt to retrieve the volume to verify it is gone.
        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.get_volume_connector_by_id,
                          self.connector.id)
        # Ensure that the destroy_volume_connector returns the
        # expected exception.
        self.assertRaises(exception.VolumeConnectorNotFound,
                          self.dbapi.destroy_volume_connector,
                          self.connector.id)
