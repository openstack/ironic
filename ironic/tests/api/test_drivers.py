#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat, Inc.
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

from testtools.matchers import HasLength

from ironic.tests.api import base


class TestListDrivers(base.FunctionalTest):

    def test_drivers(self):
        d1 = 'fake-driver1'
        d2 = 'fake-driver2'
        h1 = 'fake-host1'
        h2 = 'fake-host2'
        self.dbapi.register_conductor({'hostname': h1, 'drivers': [d1, d2]})
        self.dbapi.register_conductor({'hostname': h2, 'drivers': [d2]})
        expected = [{'name': d1, 'hosts': [h1]},
                    {'name': d2, 'hosts': [h1, h2]}]
        data = self.get_json('/drivers')
        self.assertThat(data['drivers'], HasLength(2))
        self.assertEqual(sorted(expected), sorted(data['drivers']))

    def test_drivers_no_active_conductor(self):
        data = self.get_json('/drivers')
        self.assertThat(data['drivers'], HasLength(0))
        self.assertEqual([], data['drivers'])
