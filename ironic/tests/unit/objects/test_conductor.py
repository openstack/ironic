# coding=utf-8
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

from oslo_utils import timeutils

from ironic.common import exception
from ironic import objects
from ironic.objects import base
from ironic.objects import fields
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils


class TestConductorObject(db_base.DbTestCase):

    def setUp(self):
        super(TestConductorObject, self).setUp()
        self.fake_conductor = (
            db_utils.get_test_conductor(updated_at=timeutils.utcnow()))

    def test_load(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            mock_get_cdr.return_value = self.fake_conductor
            objects.Conductor.get_by_hostname(self.context, host)
            mock_get_cdr.assert_called_once_with(host, online=True)

    def test_list(self):
        conductor1 = db_utils.get_test_conductor(hostname='cond1')
        conductor2 = db_utils.get_test_conductor(hostname='cond2')
        with mock.patch.object(self.dbapi, 'get_conductor_list',
                               autospec=True) as mock_cond_list:
            mock_cond_list.return_value = [conductor1, conductor2]
            conductors = objects.Conductor.list(self.context)
            self.assertEqual(2, len(conductors))
            self.assertIsInstance(conductors[0], objects.Conductor)
            self.assertIsInstance(conductors[1], objects.Conductor)
            self.assertEqual(conductors[0].hostname, 'cond1')
            self.assertEqual(conductors[1].hostname, 'cond2')

    def test_save(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            mock_get_cdr.return_value = self.fake_conductor
            c = objects.Conductor.get_by_hostname(self.context, host)
            c.hostname = 'another-hostname'
            self.assertRaises(NotImplementedError,
                              c.save, self.context)
            mock_get_cdr.assert_called_once_with(host, online=True)

    def test_touch(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            with mock.patch.object(self.dbapi, 'touch_conductor',
                                   autospec=True) as mock_touch_cdr:
                mock_get_cdr.return_value = self.fake_conductor
                c = objects.Conductor.get_by_hostname(self.context, host)
                c.touch(self.context)
                mock_get_cdr.assert_called_once_with(host, online=True)
                mock_touch_cdr.assert_called_once_with(host)

    def test_refresh(self):
        host = self.fake_conductor['hostname']
        t0 = self.fake_conductor['updated_at']
        t1 = t0 + datetime.timedelta(seconds=10)
        returns = [dict(self.fake_conductor, updated_at=t0),
                   dict(self.fake_conductor, updated_at=t1)]
        expected = [mock.call(host, online=True),
                    mock.call(host, online=True)]
        with mock.patch.object(self.dbapi, 'get_conductor',
                               side_effect=returns,
                               autospec=True) as mock_get_cdr:
            c = objects.Conductor.get_by_hostname(self.context, host)
            # ensure timestamps have tzinfo
            datetime_field = fields.DateTimeField()
            self.assertEqual(
                datetime_field.coerce(datetime_field, 'updated_at', t0),
                c.updated_at)
            c.refresh()
            self.assertEqual(
                datetime_field.coerce(datetime_field, 'updated_at', t1),
                c.updated_at)
            self.assertEqual(expected, mock_get_cdr.call_args_list)
            self.assertEqual(self.context, c._context)

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def _test_register(self, mock_target_version, update_existing=False,
                       conductor_group=''):
        mock_target_version.return_value = '1.5'
        host = self.fake_conductor['hostname']
        drivers = self.fake_conductor['drivers']
        with mock.patch.object(self.dbapi, 'register_conductor',
                               autospec=True) as mock_register_cdr:
            mock_register_cdr.return_value = self.fake_conductor
            c = objects.Conductor.register(self.context, host, drivers,
                                           conductor_group,
                                           update_existing=update_existing)

            self.assertIsInstance(c, objects.Conductor)
            mock_register_cdr.assert_called_once_with(
                {'drivers': drivers,
                 'hostname': host,
                 'conductor_group': conductor_group.lower(),
                 'version': '1.5'},
                update_existing=update_existing)

    def test_register(self):
        self._test_register()

    def test_register_update_existing_true(self):
        self._test_register(update_existing=True)

    def test_register_into_group(self):
        self._test_register(conductor_group='dc1')

    def test_register_into_group_uppercased(self):
        self._test_register(conductor_group='DC1')

    def test_register_into_group_with_update(self):
        self._test_register(conductor_group='dc1', update_existing=True)

    @mock.patch.object(base.IronicObject, 'get_target_version',
                       spec_set=types.FunctionType)
    def test_register_with_invalid_group(self, mock_target_version):
        mock_target_version.return_value = '1.5'
        host = self.fake_conductor['hostname']
        drivers = self.fake_conductor['drivers']
        self.assertRaises(exception.InvalidConductorGroup,
                          objects.Conductor.register,
                          self.context, host, drivers, 'invalid:group')

    @mock.patch.object(objects.Conductor, 'unregister_all_hardware_interfaces',
                       autospec=True)
    def test_unregister(self, mock_unreg_ifaces):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            with mock.patch.object(self.dbapi, 'unregister_conductor',
                                   autospec=True) as mock_unregister_cdr:
                mock_get_cdr.return_value = self.fake_conductor
                c = objects.Conductor.get_by_hostname(self.context, host)
                c.unregister()
                mock_unregister_cdr.assert_called_once_with(host)
                mock_unreg_ifaces.assert_called_once_with(mock.ANY)

    def test_register_hardware_interfaces(self):
        host = self.fake_conductor['hostname']
        self.config(default_deploy_interface='iscsi')
        arg = [{"hardware_type": "hardware-type", "interface_type": "deploy",
                "interface_name": "iscsi", "default": True},
               {"hardware_type": "hardware-type", "interface_type": "deploy",
                "interface_name": "direct", "default": False}]
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            with mock.patch.object(self.dbapi,
                                   'register_conductor_hardware_interfaces',
                                   autospec=True) as mock_register:
                mock_get_cdr.return_value = self.fake_conductor
                c = objects.Conductor.get_by_hostname(self.context, host)
                c.register_hardware_interfaces(arg)
                mock_register.assert_called_once_with(c.id, arg)

    def test_unregister_all_hardware_interfaces(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            with mock.patch.object(self.dbapi,
                                   'unregister_conductor_hardware_interfaces',
                                   autospec=True) as mock_unregister:
                mock_get_cdr.return_value = self.fake_conductor
                c = objects.Conductor.get_by_hostname(self.context, host)
                c.unregister_all_hardware_interfaces()
                mock_unregister.assert_called_once_with(c.id)
