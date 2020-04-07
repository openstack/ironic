# coding=utf-8
#
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
from unittest import mock

from oslo_utils import uuidutils
from testtools import matchers

from ironic.common import exception
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


class TestChassisObject(db_base.DbTestCase, obj_utils.SchemasTestMixIn):

    def setUp(self):
        super(TestChassisObject, self).setUp()
        self.fake_chassis = db_utils.get_test_chassis()

    def test_get_by_id(self):
        chassis_id = self.fake_chassis['id']
        with mock.patch.object(self.dbapi, 'get_chassis_by_id',
                               autospec=True) as mock_get_chassis:
            mock_get_chassis.return_value = self.fake_chassis

            chassis = objects.Chassis.get(self.context, chassis_id)

            mock_get_chassis.assert_called_once_with(chassis_id)
            self.assertEqual(self.context, chassis._context)

    def test_get_by_uuid(self):
        uuid = self.fake_chassis['uuid']
        with mock.patch.object(self.dbapi, 'get_chassis_by_uuid',
                               autospec=True) as mock_get_chassis:
            mock_get_chassis.return_value = self.fake_chassis

            chassis = objects.Chassis.get(self.context, uuid)

            mock_get_chassis.assert_called_once_with(uuid)
            self.assertEqual(self.context, chassis._context)

    def test_get_bad_id_and_uuid(self):
        self.assertRaises(exception.InvalidIdentity,
                          objects.Chassis.get, self.context, 'not-a-uuid')

    def test_create(self):
        chassis = objects.Chassis(self.context, **self.fake_chassis)
        with mock.patch.object(self.dbapi, 'create_chassis',
                               autospec=True) as mock_create_chassis:
            mock_create_chassis.return_value = db_utils.get_test_chassis()

            chassis.create()

            args, _kwargs = mock_create_chassis.call_args
            self.assertEqual(objects.Chassis.VERSION, args[0]['version'])

    def test_save(self):
        uuid = self.fake_chassis['uuid']
        extra = {"test": 123}
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        with mock.patch.object(self.dbapi, 'get_chassis_by_uuid',
                               autospec=True) as mock_get_chassis:
            mock_get_chassis.return_value = self.fake_chassis
            with mock.patch.object(self.dbapi, 'update_chassis',
                                   autospec=True) as mock_update_chassis:
                mock_update_chassis.return_value = (
                    db_utils.get_test_chassis(extra=extra,
                                              updated_at=test_time))
                c = objects.Chassis.get_by_uuid(self.context, uuid)
                c.extra = extra
                c.save()

                mock_get_chassis.assert_called_once_with(uuid)
                mock_update_chassis.assert_called_once_with(
                    uuid, {'version': objects.Chassis.VERSION,
                           'extra': {"test": 123}})
                self.assertEqual(self.context, c._context)
                res_updated_at = (c.updated_at).replace(tzinfo=None)
                self.assertEqual(test_time, res_updated_at)

    def test_refresh(self):
        uuid = self.fake_chassis['uuid']
        new_uuid = uuidutils.generate_uuid()
        returns = [dict(self.fake_chassis, uuid=uuid),
                   dict(self.fake_chassis, uuid=new_uuid)]
        expected = [mock.call(uuid), mock.call(uuid)]
        with mock.patch.object(self.dbapi, 'get_chassis_by_uuid',
                               side_effect=returns,
                               autospec=True) as mock_get_chassis:
            c = objects.Chassis.get_by_uuid(self.context, uuid)
            self.assertEqual(uuid, c.uuid)
            c.refresh()
            self.assertEqual(new_uuid, c.uuid)
            self.assertEqual(expected, mock_get_chassis.call_args_list)
            self.assertEqual(self.context, c._context)

    # NOTE(vsaienko) current implementation of update_chassis() dbapi is
    # differ from other object like update_port() or node_update() which
    # allows to perform object.save() after object.refresh()
    # This test will avoid update_chassis() regressions in future.
    def test_save_after_refresh(self):
        # Ensure that it's possible to do object.save() after object.refresh()
        db_chassis = db_utils.create_test_chassis()
        c = objects.Chassis.get_by_uuid(self.context, db_chassis.uuid)
        c_copy = objects.Chassis.get_by_uuid(self.context, db_chassis.uuid)
        c.description = 'b240'
        c.save()
        c_copy.refresh()
        c_copy.description = 'aaff'
        # Ensure this passes and an exception is not generated
        c_copy.save()

    def test_list(self):
        with mock.patch.object(self.dbapi, 'get_chassis_list',
                               autospec=True) as mock_get_list:
            mock_get_list.return_value = [self.fake_chassis]
            chassis = objects.Chassis.list(self.context)
            self.assertThat(chassis, matchers.HasLength(1))
            self.assertIsInstance(chassis[0], objects.Chassis)
            self.assertEqual(self.context, chassis[0]._context)

    def test_payload_schemas(self):
        self._check_payload_schemas(objects.chassis, objects.Chassis.fields)
