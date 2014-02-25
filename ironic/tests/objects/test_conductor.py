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

from ironic.db import api as db_api
from ironic.db.sqlalchemy import models
from ironic import objects
from ironic.objects import utils as obj_utils
from ironic.openstack.common import timeutils
from ironic.tests.db import base
from ironic.tests.db import utils


class TestConductorObject(base.DbTestCase):

    def setUp(self):
        super(TestConductorObject, self).setUp()
        self.fake_conductor = utils.get_test_conductor(
                                        updated_at=timeutils.utcnow())
        self.dbapi = db_api.get_instance()

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
            self.assertEqual(obj_utils.datetime_or_none(t0), c.updated_at)
            c.refresh()
            self.assertEqual(obj_utils.datetime_or_none(t1), c.updated_at)
            self.assertEqual(expected, mock_get_cdr.call_args_list)

    def test_objectify(self):
        def _get_db_conductor():
            c = models.Conductor()
            c.update(self.fake_conductor)
            return c

        @objects.objectify(objects.Conductor)
        def _convert_db_conductor():
            return _get_db_conductor()

        self.assertIsInstance(_get_db_conductor(), models.Conductor)
        self.assertIsInstance(_convert_db_conductor(), objects.Conductor)

    def test_objectify_many(self):
        def _get_db_conductors():
            conductors = []
            for i in range(5):
                c = models.Conductor()
                c.update(self.fake_conductor)
                conductors.append(c)
            return conductors

        @objects.objectify(objects.Conductor)
        def _convert_db_conductors():
            return _get_db_conductors()

        for c in _get_db_conductors():
            self.assertIsInstance(c, models.Conductor)
        for c in _convert_db_conductors():
            self.assertIsInstance(c, objects.Conductor)
