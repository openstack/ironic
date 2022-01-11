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

import datetime
import types
from unittest import mock

from testtools.matchers import HasLength

from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestVolumeConnectorObject(db_base.DbTestCase,
                                obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestVolumeConnectorObject, self).setUp()
        self.volume_connector_dict = db_utils.get_test_volume_connector()

    @mock.patch('ironic.objects.VolumeConnector.get_by_uuid',
                spec_set=types.FunctionType)
    @mock.patch('ironic.objects.VolumeConnector.get_by_id',
                spec_set=types.FunctionType)
    def test_get(self, mock_get_by_id, mock_get_by_uuid):
        id = self.volume_connector_dict['id']
        uuid = self.volume_connector_dict['uuid']

        objects.VolumeConnector.get(self.context, id)
        mock_get_by_id.assert_called_once_with(self.context, id)
        self.assertFalse(mock_get_by_uuid.called)

        objects.VolumeConnector.get(self.context, uuid)
        mock_get_by_uuid.assert_called_once_with(self.context, uuid)

        # Invalid identifier (not ID or UUID)
        self.assertRaises(exception.InvalidIdentity,
                          objects.VolumeConnector.get,
                          self.context, 'not-valid-identifier')

    def test_get_by_id(self):
        id = self.volume_connector_dict['id']
        with mock.patch.object(self.dbapi, 'get_volume_connector_by_id',
                               autospec=True) as mock_get_volume_connector:
            mock_get_volume_connector.return_value = self.volume_connector_dict

            connector = objects.VolumeConnector.get_by_id(self.context, id)

            mock_get_volume_connector.assert_called_once_with(id)
            self.assertIsInstance(connector, objects.VolumeConnector)
            self.assertEqual(self.context, connector._context)

    def test_get_by_uuid(self):
        uuid = self.volume_connector_dict['uuid']
        with mock.patch.object(self.dbapi, 'get_volume_connector_by_uuid',
                               autospec=True) as mock_get_volume_connector:
            mock_get_volume_connector.return_value = self.volume_connector_dict

            connector = objects.VolumeConnector.get_by_uuid(self.context, uuid)

            mock_get_volume_connector.assert_called_once_with(uuid)
            self.assertIsInstance(connector, objects.VolumeConnector)
            self.assertEqual(self.context, connector._context)

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_volume_connector_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.volume_connector_dict]
            volume_connectors = objects.VolumeConnector.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc',
                project=None)
            self.assertThat(volume_connectors, HasLength(1))
            self.assertIsInstance(volume_connectors[0],
                                  objects.VolumeConnector)
            self.assertEqual(self.context, volume_connectors[0]._context)

    def test_list_none(self):
        with mock.patch.object(self.dbapi, 'get_volume_connector_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = []
            volume_connectors = objects.VolumeConnector.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc',
                project=None)
            self.assertEqual([], volume_connectors)

    def test_list_by_node_id(self):
        with mock.patch.object(self.dbapi, 'get_volume_connectors_by_node_id',
                               autospec=True) as mock_get_list_by_node_id:
            mock_get_list_by_node_id.return_value = [
                self.volume_connector_dict]
            node_id = self.volume_connector_dict['node_id']
            volume_connectors = objects.VolumeConnector.list_by_node_id(
                self.context, node_id, limit=10, sort_dir='desc')

            mock_get_list_by_node_id.assert_called_once_with(
                node_id, limit=10, marker=None, sort_key=None, sort_dir='desc',
                project=None)
            self.assertThat(volume_connectors, HasLength(1))
            self.assertIsInstance(volume_connectors[0],
                                  objects.VolumeConnector)
            self.assertEqual(self.context, volume_connectors[0]._context)

    def test_create(self):
        with mock.patch.object(self.dbapi, 'create_volume_connector',
                               autospec=True) as mock_db_create:
            mock_db_create.return_value = self.volume_connector_dict
            new_connector = objects.VolumeConnector(
                self.context, **self.volume_connector_dict)
            new_connector.create()

            mock_db_create.assert_called_once_with(self.volume_connector_dict)

    def test_destroy(self):
        uuid = self.volume_connector_dict['uuid']
        with mock.patch.object(self.dbapi, 'get_volume_connector_by_uuid',
                               autospec=True) as mock_get_volume_connector:
            mock_get_volume_connector.return_value = self.volume_connector_dict
            with mock.patch.object(self.dbapi, 'destroy_volume_connector',
                                   autospec=True) as mock_db_destroy:
                connector = objects.VolumeConnector.get_by_uuid(self.context,
                                                                uuid)
                connector.destroy()

                mock_db_destroy.assert_called_once_with(uuid)

    def test_save(self):
        uuid = self.volume_connector_dict['uuid']
        connector_id = "new_connector_id"
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_volume_connector_by_uuid',
                               autospec=True) as mock_get_volume_connector:
            mock_get_volume_connector.return_value = self.volume_connector_dict
            with mock.patch.object(self.dbapi, 'update_volume_connector',
                                   autospec=True) as mock_update_connector:
                mock_update_connector.return_value = (
                    db_utils.get_test_volume_connector(
                        connector_id=connector_id, updated_at=test_time))
                c = objects.VolumeConnector.get_by_uuid(self.context, uuid)
                c.connector_id = connector_id
                c.save()

                mock_get_volume_connector.assert_called_once_with(uuid)
                mock_update_connector.assert_called_once_with(
                    uuid,
                    {'version': objects.VolumeConnector.VERSION,
                     'connector_id': connector_id})
                self.assertEqual(self.context, c._context)
                res_updated_at = (c.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.volume_connector_dict['uuid']
        old_connector_id = self.volume_connector_dict['connector_id']
        returns = [self.volume_connector_dict,
                   db_utils.get_test_volume_connector(
                       connector_id="new_connector_id")]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_volume_connector_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_volume_connector:
            c = objects.VolumeConnector.get_by_uuid(self.context, uuid)
            self.assertEqual(old_connector_id, c.connector_id)
            c.refresh()
            self.assertEqual('new_connector_id', c.connector_id)

            self.assertEqual(expected,
                             mock_get_volume_connector.call_args_list)
            self.assertEqual(self.context, c._context)

    def test_save_after_refresh(self):
        node = db_utils.create_test_node()
        # Ensure that it's possible to do object.save() after object.refresh()
        db_volume_connector = db_utils.create_test_volume_connector(
            node_id=node['id'])

        vc = objects.VolumeConnector.get_by_uuid(self.context,
                                                 db_volume_connector.uuid)
        vc_copy = objects.VolumeConnector.get_by_uuid(self.context,
                                                      db_volume_connector.uuid)
        vc.name = 'b240'
        vc.save()
        vc_copy.refresh()
        vc_copy.name = 'aaff'
        # Ensure this passes and an exception is not generated
        vc_copy.save()

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.volume_connector,
                                    objects.VolumeConnector.fields)
