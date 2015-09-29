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

import mock
from oslo_utils import timeutils

from ironic import objects
from ironic.objects import fields
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class TestConductorObject(base.DbTestCase):

    def setUp(self):
        super(TestConductorObject, self).setUp()
        self.fake_conductor = (
            utils.get_test_conductor(updated_at=timeutils.utcnow()))

    def test_load(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            mock_get_cdr.return_value = self.fake_conductor
            objects.Conductor.get_by_hostname(self.context, host)
            mock_get_cdr.assert_called_once_with(host)

    def test_save(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            mock_get_cdr.return_value = self.fake_conductor
            c = objects.Conductor.get_by_hostname(self.context, host)
            c.hostname = 'another-hostname'
            self.assertRaises(NotImplementedError,
                              c.save, self.context)
            mock_get_cdr.assert_called_once_with(host)

    def test_touch(self):
        host = self.fake_conductor['hostname']
        with mock.patch.object(self.dbapi, 'get_conductor',
                               autospec=True) as mock_get_cdr:
            with mock.patch.object(self.dbapi, 'touch_conductor',
                                   autospec=True) as mock_touch_cdr:
                mock_get_cdr.return_value = self.fake_conductor
                c = objects.Conductor.get_by_hostname(self.context, host)
                c.touch(self.context)
                mock_get_cdr.assert_called_once_with(host)
                mock_touch_cdr.assert_called_once_with(host)

    def test_refresh(self):
        host = self.fake_conductor['hostname']
        t0 = self.fake_conductor['updated_at']
        t1 = t0 + datetime.timedelta(seconds=10)
        returns = [dict(self.fake_conductor, updated_at=t0),
                   dict(self.fake_conductor, updated_at=t1)]
        expected = [mock.call(host), mock.call(host)]
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
