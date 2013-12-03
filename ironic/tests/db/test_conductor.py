# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Tests for manipulating Conductors via the DB API"""

import datetime

from ironic.openstack.common import timeutils

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.tests.db import base
from ironic.tests.db import utils


class DbConductorTestCase(base.DbTestCase):

    def setUp(self):
        super(DbConductorTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        timeutils.set_time_override()
        self.addCleanup(timeutils.clear_time_override)

    def _create_test_cdr(self, **kwargs):
        c = utils.get_test_conductor(**kwargs)
        return self.dbapi.register_conductor(c)

    def test_register_conductor(self):
        self._create_test_cdr(id=1)
        self.assertRaises(
                exception.ConductorAlreadyRegistered,
                self._create_test_cdr,
                id=2)

    def test_get_conductor(self):
        c1 = self._create_test_cdr()
        c2 = self.dbapi.get_conductor(c1['hostname'])
        self.assertEqual(c1['id'], c2['id'])

    def test_get_conductor_not_found(self):
        self._create_test_cdr()
        self.assertRaises(
                exception.ConductorNotFound,
                self.dbapi.get_conductor,
                'bad-hostname')

    def test_unregister_conductor(self):
        c = self._create_test_cdr()
        self.dbapi.unregister_conductor(c['hostname'])
        self.assertRaises(
                exception.ConductorNotFound,
                self.dbapi.unregister_conductor,
                c['hostname'])

    def test_touch_conductor(self):
        t = datetime.datetime(2000, 1, 1, 0, 0)
        timeutils.set_time_override(override_time=t)
        c = self._create_test_cdr(updated_at=t)
        self.assertEqual(t, timeutils.normalize_time(c['updated_at']))

        t = datetime.datetime(2000, 1, 1, 0, 1)
        timeutils.set_time_override(override_time=t)
        self.dbapi.touch_conductor(c['hostname'])
        c = self.dbapi.get_conductor(c['hostname'])
        self.assertEqual(t, timeutils.normalize_time(c['updated_at']))

    def test_touch_conductor_not_found(self):
        self._create_test_cdr()
        self.assertRaises(
                exception.ConductorNotFound,
                self.dbapi.touch_conductor,
                'bad-hostname')

    def test_get_active_driver_dict_one_host_no_driver(self):
        h = 'fake-host'
        expected = {}

        timeutils.set_time_override()
        self._create_test_cdr(hostname=h, drivers=[])
        result = self.dbapi.get_active_driver_dict(interval=1)
        self.assertEqual(expected, result)

    def test_get_active_driver_dict_one_host_one_driver(self):
        h = 'fake-host'
        d = 'fake-driver'
        expected = {d: set([h])}

        timeutils.set_time_override()
        self._create_test_cdr(hostname=h, drivers=[d])
        result = self.dbapi.get_active_driver_dict(interval=1)
        self.assertEqual(expected, result)

    def test_get_active_driver_dict_one_host_many_drivers(self):
        h = 'fake-host'
        d1 = 'driver-one'
        d2 = 'driver-two'
        expected = {d1: set([h]), d2: set([h])}

        timeutils.set_time_override()
        self._create_test_cdr(hostname=h, drivers=[d1, d2])
        result = self.dbapi.get_active_driver_dict(interval=1)
        self.assertEqual(expected, result)

    def test_get_active_driver_dict_many_hosts_one_driver(self):
        h1 = 'host-one'
        h2 = 'host-two'
        d = 'fake-driver'
        expected = {d: set([h1, h2])}

        timeutils.set_time_override()
        self._create_test_cdr(id=1, hostname=h1, drivers=[d])
        self._create_test_cdr(id=2, hostname=h2, drivers=[d])
        result = self.dbapi.get_active_driver_dict(interval=1)
        self.assertEqual(expected, result)

    def test_get_active_driver_dict_many_hosts_and_drivers(self):
        h1 = 'host-one'
        h2 = 'host-two'
        h3 = 'host-three'
        d1 = 'driver-one'
        d2 = 'driver-two'
        expected = {d1: set([h1, h2]), d2: set([h2, h3])}

        timeutils.set_time_override()
        self._create_test_cdr(id=1, hostname=h1, drivers=[d1])
        self._create_test_cdr(id=2, hostname=h2, drivers=[d1, d2])
        self._create_test_cdr(id=3, hostname=h3, drivers=[d2])
        result = self.dbapi.get_active_driver_dict(interval=1)
        self.assertEqual(expected, result)

    def test_get_active_driver_dict_with_old_conductor(self):
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=2)

        d = 'common-driver'

        h1 = 'old-host'
        d1 = 'old-driver'
        timeutils.set_time_override(override_time=past)
        self._create_test_cdr(id=1, hostname=h1, drivers=[d, d1])

        h2 = 'new-host'
        d2 = 'new-driver'
        timeutils.set_time_override(override_time=present)
        self._create_test_cdr(id=2, hostname=h2, drivers=[d, d2])

        # verify that old-host does not show up in current list
        one_minute = 60
        expected = {d: set([h2]), d2: set([h2])}
        result = self.dbapi.get_active_driver_dict(interval=one_minute)
        self.assertEqual(expected, result)

        # change the interval, and verify that old-host appears
        two_minute = one_minute * 2
        expected = {d: set([h1, h2]), d1: set([h1]), d2: set([h2])}
        result = self.dbapi.get_active_driver_dict(interval=two_minute)
        self.assertEqual(expected, result)
