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

    def test_list_active_conductor_drivers(self):
        # create some conductors with different timestamps
        now = datetime.datetime(2000, 1, 1, 0, 0)
        then = now + datetime.timedelta(hours=1)

        d1 = [u'not-this-one']
        timeutils.set_time_override(override_time=now)
        self._create_test_cdr(id=1, hostname='d1', drivers=d1)

        d2 = [u'foo', u'bar']
        d3 = [u'another']
        timeutils.set_time_override(override_time=then)
        self._create_test_cdr(id=2, hostname='d2', drivers=d2)
        self._create_test_cdr(id=3, hostname='d3', drivers=d3)

        # verify that res contains d2 and d3, but not the old d1
        res = self.dbapi.list_active_conductor_drivers(interval=60)
        drivers = d2 + d3
        self.assertEqual(sorted(res), sorted(drivers))

        # change the interval, and verify that d1 appears
        res = self.dbapi.list_active_conductor_drivers(interval=7200)
        drivers = d1 + d2 + d3
        self.assertEqual(sorted(res), sorted(drivers))
