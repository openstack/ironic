# Copyright 2016 Hitachi, Ltd.
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


class TestVolumeTargetObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestVolumeTargetObject, self).setUp()
        self.volume_target_dict = db_utils.get_test_volume_target()

    @mock.patch('ironic.objects.VolumeTarget.get_by_uuid',
                spec_set=types.FunctionType)
    @mock.patch('ironic.objects.VolumeTarget.get_by_id',
                spec_set=types.FunctionType)
    def test_get(self, mock_get_by_id, mock_get_by_uuid):
        id = self.volume_target_dict['id']
        uuid = self.volume_target_dict['uuid']

        objects.VolumeTarget.get(self.context, id)
        mock_get_by_id.assert_called_once_with(self.context, id)
        self.assertFalse(mock_get_by_uuid.called)

        objects.VolumeTarget.get(self.context, uuid)
        mock_get_by_uuid.assert_called_once_with(self.context, uuid)

        # Invalid identifier (not ID or UUID)
        self.assertRaises(exception.InvalidIdentity,
                          objects.VolumeTarget.get,
                          self.context, 'not-valid-identifier')

    def test_get_by_id(self):
        id = self.volume_target_dict['id']
        with mock.patch.object(self.dbapi, 'get_volume_target_by_id',
                               autospec=True) as mock_get_volume_target:
            mock_get_volume_target.return_value = self.volume_target_dict

            target = objects.VolumeTarget.get(self.context, id)

            mock_get_volume_target.assert_called_once_with(id)
            self.assertIsInstance(target, objects.VolumeTarget)
            self.assertEqual(self.context, target._context)

    def test_get_by_uuid(self):
        uuid = self.volume_target_dict['uuid']
        with mock.patch.object(self.dbapi, 'get_volume_target_by_uuid',
                               autospec=True) as mock_get_volume_target:
            mock_get_volume_target.return_value = self.volume_target_dict

            target = objects.VolumeTarget.get(self.context, uuid)

            mock_get_volume_target.assert_called_once_with(uuid)
            self.assertIsInstance(target, objects.VolumeTarget)
            self.assertEqual(self.context, target._context)

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_volume_target_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.volume_target_dict]
            volume_targets = objects.VolumeTarget.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc',
                project=None)
            self.assertThat(volume_targets, HasLength(1))
            self.assertIsInstance(volume_targets[0],
                                  objects.VolumeTarget)
            self.assertEqual(self.context, volume_targets[0]._context)

    def test_list_none(self):
        with mock.patch.object(self.dbapi, 'get_volume_target_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = []
            volume_targets = objects.VolumeTarget.list(
                self.context, limit=4, sort_key='uuid', sort_dir='asc')

            mock_get_list.assert_called_once_with(
                limit=4, marker=None, sort_key='uuid', sort_dir='asc',
                project=None)
            self.assertEqual([], volume_targets)

    def test_list_by_node_id(self):
        with mock.patch.object(self.dbapi, 'get_volume_targets_by_node_id',
                               autospec=True) as mock_get_list_by_node_id:
            mock_get_list_by_node_id.return_value = [self.volume_target_dict]
            node_id = self.volume_target_dict['node_id']
            volume_targets = objects.VolumeTarget.list_by_node_id(
                self.context, node_id, limit=10, sort_dir='desc')

            mock_get_list_by_node_id.assert_called_once_with(
                node_id, limit=10, marker=None, sort_key=None, sort_dir='desc',
                project=None)
            self.assertThat(volume_targets, HasLength(1))
            self.assertIsInstance(volume_targets[0], objects.VolumeTarget)
            self.assertEqual(self.context, volume_targets[0]._context)

    def test_list_by_volume_id(self):
        with mock.patch.object(self.dbapi, 'get_volume_targets_by_volume_id',
                               autospec=True) as mock_get_list_by_volume_id:
            mock_get_list_by_volume_id.return_value = [self.volume_target_dict]
            volume_id = self.volume_target_dict['volume_id']
            volume_targets = objects.VolumeTarget.list_by_volume_id(
                self.context, volume_id, limit=10, sort_dir='desc')

            mock_get_list_by_volume_id.assert_called_once_with(
                volume_id, limit=10, marker=None,
                sort_key=None, sort_dir='desc', project=None)
            self.assertThat(volume_targets, HasLength(1))
            self.assertIsInstance(volume_targets[0], objects.VolumeTarget)
            self.assertEqual(self.context, volume_targets[0]._context)

    def test_create(self):
        with mock.patch.object(self.dbapi, 'create_volume_target',
                               autospec=True) as mock_db_create:
            mock_db_create.return_value = self.volume_target_dict
            new_target = objects.VolumeTarget(
                self.context, **self.volume_target_dict)
            new_target.create()

            mock_db_create.assert_called_once_with(self.volume_target_dict)

    def test_destroy(self):
        uuid = self.volume_target_dict['uuid']
        with mock.patch.object(self.dbapi, 'get_volume_target_by_uuid',
                               autospec=True) as mock_get_volume_target:
            mock_get_volume_target.return_value = self.volume_target_dict
            with mock.patch.object(self.dbapi, 'destroy_volume_target',
                                   autospec=True) as mock_db_destroy:
                target = objects.VolumeTarget.get_by_uuid(self.context, uuid)
                target.destroy()

                mock_db_destroy.assert_called_once_with(uuid)

    def test_save(self):
        uuid = self.volume_target_dict['uuid']
        boot_index = 100
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_volume_target_by_uuid',
                               autospec=True) as mock_get_volume_target:
            mock_get_volume_target.return_value = self.volume_target_dict
            with mock.patch.object(self.dbapi, 'update_volume_target',
                                   autospec=True) as mock_update_target:
                mock_update_target.return_value = (
                    db_utils.get_test_volume_target(boot_index=boot_index,
                                                    updated_at=test_time))
                target = objects.VolumeTarget.get_by_uuid(self.context, uuid)
                target.boot_index = boot_index
                target.save()

                mock_get_volume_target.assert_called_once_with(uuid)
                mock_update_target.assert_called_once_with(
                    uuid,
                    {'version': objects.VolumeTarget.VERSION,
                     'boot_index': boot_index})
                self.assertEqual(self.context, target._context)
                res_updated_at = (target.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.volume_target_dict['uuid']
        old_boot_index = self.volume_target_dict['boot_index']
        returns = [self.volume_target_dict,
                   db_utils.get_test_volume_target(boot_index=100)]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_volume_target_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_volume_target:
            target = objects.VolumeTarget.get_by_uuid(self.context, uuid)
            self.assertEqual(old_boot_index, target.boot_index)
            target.refresh()
            self.assertEqual(100, target.boot_index)

            self.assertEqual(expected,
                             mock_get_volume_target.call_args_list)
            self.assertEqual(self.context, target._context)

    def test_save_after_refresh(self):
        node = db_utils.create_test_node()
        # Ensure that it's possible to do object.save() after object.refresh()
        db_volume_target = db_utils.create_test_volume_target(
            node_id=node.id)

        vt = objects.VolumeTarget.get_by_uuid(self.context,
                                              db_volume_target.uuid)
        vt_copy = objects.VolumeTarget.get_by_uuid(self.context,
                                                   db_volume_target.uuid)
        vt.name = 'b240'
        vt.save()
        vt_copy.refresh()
        vt_copy.name = 'aaff'
        # Ensure this passes and an exception is not generated
        vt_copy.save()

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.volume_target,
                                    objects.VolumeTarget.fields)
