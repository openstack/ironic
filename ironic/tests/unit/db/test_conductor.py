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
from unittest import mock

from oslo_utils import timeutils

from ironic.common import exception
from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class DbConductorTestCase(base.DbTestCase):

    def test_register_conductor_existing_fails(self):
        c = utils.get_test_conductor()
        self.dbapi.register_conductor(c)
        self.assertRaises(
            exception.ConductorAlreadyRegistered,
            self.dbapi.register_conductor,
            c)

    def test_register_conductor_override(self):
        c = utils.get_test_conductor()
        self.dbapi.register_conductor(c)
        self.dbapi.register_conductor(c, update_existing=True)

    def _create_test_cdr(self, hardware_types=None, **kwargs):
        hardware_types = hardware_types or []
        c = utils.get_test_conductor(**kwargs)
        cdr = self.dbapi.register_conductor(c)
        for ht in hardware_types:
            self.dbapi.register_conductor_hardware_interfaces(
                cdr.id,
                [{'hardware_type': ht, 'interface_type': 'power',
                  'interface_name': 'ipmi', 'default': True},
                 {'hardware_type': ht, 'interface_type': 'power',
                  'interface_name': 'fake', 'default': False}]
            )
        return cdr

    def test_register_conductor_hardware_interfaces(self):
        c = self._create_test_cdr()
        interfaces = ['direct', 'ansible']
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'generic', 'interface_type': 'deploy',
              'interface_name': interfaces[0], 'default': False},
             {'hardware_type': 'generic', 'interface_type': 'deploy',
              'interface_name': interfaces[1], 'default': True}]
        )
        ifaces = self.dbapi.list_conductor_hardware_interfaces(c.id)
        ci1, ci2 = ifaces
        self.assertEqual(2, len(ifaces))
        self.assertEqual('generic', ci1.hardware_type)
        self.assertEqual('generic', ci2.hardware_type)
        self.assertEqual('deploy', ci1.interface_type)
        self.assertEqual('deploy', ci2.interface_type)
        self.assertEqual('ansible', ci1.interface_name)
        self.assertEqual('direct', ci2.interface_name)
        self.assertTrue(ci1.default)
        self.assertFalse(ci2.default)

    def test_register_conductor_hardware_interfaces_duplicate(self):
        c = self._create_test_cdr()
        interfaces = [
            {'hardware_type': 'generic', 'interface_type': 'deploy',
             'interface_name': 'direct', 'default': False},
            {'hardware_type': 'generic', 'interface_type': 'deploy',
             'interface_name': 'ansible', 'default': True}
        ]
        self.dbapi.register_conductor_hardware_interfaces(c.id, interfaces)
        ifaces = self.dbapi.list_conductor_hardware_interfaces(c.id)
        ci1, ci2 = ifaces
        self.assertEqual(2, len(ifaces))

        # do it again for the duplicates
        self.assertRaises(
            exception.ConductorHardwareInterfacesAlreadyRegistered,
            self.dbapi.register_conductor_hardware_interfaces,
            c.id, interfaces)

    def test_unregister_conductor_hardware_interfaces(self):
        c = self._create_test_cdr()
        interfaces = ['direct', 'ansible']
        self.dbapi.register_conductor_hardware_interfaces(
            c.id,
            [{'hardware_type': 'generic', 'interface_type': 'deploy',
              'interface_name': interfaces[0], 'default': False},
             {'hardware_type': 'generic', 'interface_type': 'deploy',
              'interface_name': interfaces[1], 'default': True}]
        )
        self.dbapi.unregister_conductor_hardware_interfaces(c.id)

        ifaces = self.dbapi.list_conductor_hardware_interfaces(c.id)
        self.assertEqual([], ifaces)

    def test_get_conductor(self):
        c1 = self._create_test_cdr()
        c2 = self.dbapi.get_conductor(c1.hostname)
        self.assertEqual(c1.id, c2.id)

    def test_get_inactive_conductor_ignore_online(self):
        c1 = self._create_test_cdr()
        self.dbapi.unregister_conductor(c1.hostname)
        c2 = self.dbapi.get_conductor(c1.hostname, online=None)
        self.assertEqual(c1.id, c2.id)

    def test_get_inactive_conductor_with_online_true(self):
        c1 = self._create_test_cdr()
        self.dbapi.unregister_conductor(c1.hostname)
        self.assertRaises(exception.ConductorNotFound,
                          self.dbapi.get_conductor, c1.hostname)

    def test_get_conductor_not_found(self):
        self._create_test_cdr()
        self.assertRaises(
            exception.ConductorNotFound,
            self.dbapi.get_conductor,
            'bad-hostname')

    def test_unregister_conductor(self):
        c = self._create_test_cdr()
        self.dbapi.unregister_conductor(c.hostname)
        self.assertRaises(
            exception.ConductorNotFound,
            self.dbapi.unregister_conductor,
            c.hostname)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_touch_conductor(self, mock_utcnow):
        test_time = datetime.datetime(2000, 1, 1, 0, 0)
        mock_utcnow.return_value = test_time
        c = self._create_test_cdr()
        self.assertEqual(test_time, timeutils.normalize_time(c.updated_at))

        test_time = datetime.datetime(2000, 1, 1, 0, 1)
        mock_utcnow.return_value = test_time
        self.dbapi.touch_conductor(c.hostname)
        c = self.dbapi.get_conductor(c.hostname)
        self.assertEqual(test_time, timeutils.normalize_time(c.updated_at))

    def test_touch_conductor_not_found(self):
        # A conductor's heartbeat will not create a new record,
        # it will only update existing ones
        self._create_test_cdr()
        self.assertRaises(
            exception.ConductorNotFound,
            self.dbapi.touch_conductor,
            'bad-hostname')

    def test_touch_offline_conductor(self):
        # Ensure that a conductor's periodic heartbeat task can make the
        # conductor visible again, even if it was spuriously marked offline
        c = self._create_test_cdr()
        self.dbapi.unregister_conductor(c.hostname)
        self.assertRaises(
            exception.ConductorNotFound,
            self.dbapi.get_conductor,
            c.hostname)
        self.dbapi.touch_conductor(c.hostname)
        self.dbapi.get_conductor(c.hostname)

    def test_clear_node_reservations_for_conductor(self):
        node1 = self.dbapi.create_node({'reservation': 'hostname1'})
        node2 = self.dbapi.create_node({'reservation': 'hostname2'})
        node3 = self.dbapi.create_node({'reservation': None})
        node4 = self.dbapi.create_node({'reservation': 'hostName1'})
        self.dbapi.clear_node_reservations_for_conductor('hostname1')
        node1 = self.dbapi.get_node_by_id(node1.id)
        node2 = self.dbapi.get_node_by_id(node2.id)
        node3 = self.dbapi.get_node_by_id(node3.id)
        node4 = self.dbapi.get_node_by_id(node4.id)
        self.assertIsNone(node1.reservation)
        self.assertEqual('hostname2', node2.reservation)
        self.assertIsNone(node3.reservation)
        self.assertIsNone(node4.reservation)

    def test_clear_node_target_power_state(self):
        node1 = self.dbapi.create_node({'reservation': 'hostname1',
                                        'target_power_state': 'power on'})
        node2 = self.dbapi.create_node({'reservation': 'hostname2',
                                        'target_power_state': 'power on'})
        node3 = self.dbapi.create_node({'reservation': None,
                                        'target_power_state': 'power on'})
        node4 = self.dbapi.create_node({'reservation': 'hostName1',
                                        'target_power_state': 'power on'})
        self.dbapi.clear_node_target_power_state('hostname1')
        node1 = self.dbapi.get_node_by_id(node1.id)
        node2 = self.dbapi.get_node_by_id(node2.id)
        node3 = self.dbapi.get_node_by_id(node3.id)
        node4 = self.dbapi.get_node_by_id(node4.id)
        self.assertIsNone(node1.target_power_state)
        self.assertIn('power operation was aborted', node1.last_error)
        self.assertEqual('power on', node2.target_power_state)
        self.assertIsNone(node2.last_error)
        self.assertEqual('power on', node3.target_power_state)
        self.assertIsNone(node3.last_error)
        self.assertIsNone(node4.target_power_state)
        self.assertIn('power operation was aborted', node4.last_error)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_one_host_no_ht(self, mock_utcnow):
        h = 'fake-host'
        expected = {}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(hostname=h, drivers=[], hardware_types=[])
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_one_host_one_ht(self, mock_utcnow):
        h = 'fake-host'
        ht = 'hardware-type'
        expected = {ht: {h}}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(hostname=h, drivers=[], hardware_types=[ht])
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_one_host_one_ht_groups(
            self, mock_utcnow):
        h = 'fake-host'
        ht = 'hardware-type'
        group = 'foogroup'
        key = '%s:%s' % (group, ht)
        expected = {key: {h}}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(hostname=h, drivers=[], hardware_types=[ht],
                              conductor_group=group)
        result = self.dbapi.get_active_hardware_type_dict(use_groups=True)
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_one_host_many_ht(self, mock_utcnow):
        h = 'fake-host'
        ht1 = 'hardware-type'
        ht2 = 'another-hardware-type'
        expected = {ht1: {h}, ht2: {h}}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(hostname=h, drivers=[],
                              hardware_types=[ht1, ht2])
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_many_host_one_ht(self, mock_utcnow):
        h1 = 'host-one'
        h2 = 'host-two'
        ht = 'hardware-type'
        expected = {ht: {h1, h2}}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(id=1, hostname=h1, drivers=[],
                              hardware_types=[ht])
        self._create_test_cdr(id=2, hostname=h2, drivers=[],
                              hardware_types=[ht])
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_many_host_many_ht(self,
                                                             mock_utcnow):
        h1 = 'host-one'
        h2 = 'host-two'
        ht1 = 'hardware-type'
        ht2 = 'another-hardware-type'
        expected = {ht1: {h1, h2}, ht2: {h1, h2}}

        mock_utcnow.return_value = datetime.datetime.utcnow()
        self._create_test_cdr(id=1, hostname=h1, drivers=[],
                              hardware_types=[ht1, ht2])
        self._create_test_cdr(id=2, hostname=h2, drivers=[],
                              hardware_types=[ht1, ht2])
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_active_hardware_type_dict_with_old_conductor(self,
                                                              mock_utcnow):
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=2)

        ht = 'hardware-type'

        h1 = 'old-host'
        ht1 = 'old-hardware-type'
        mock_utcnow.return_value = past
        self._create_test_cdr(id=1, hostname=h1, drivers=[],
                              hardware_types=[ht, ht1])

        h2 = 'new-host'
        ht2 = 'new-hardware-type'
        mock_utcnow.return_value = present
        self._create_test_cdr(id=2, hostname=h2, drivers=[],
                              hardware_types=[ht, ht2])

        # verify that old-host does not show up in current list
        self.config(heartbeat_timeout=60, group='conductor')
        expected = {ht: {h2}, ht2: {h2}}
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

        # change the heartbeat timeout, and verify that old-host appears
        self.config(heartbeat_timeout=120, group='conductor')
        expected = {ht: {h1, h2}, ht1: {h1}, ht2: {h2}}
        result = self.dbapi.get_active_hardware_type_dict()
        self.assertEqual(expected, result)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_offline_conductors(self, mock_utcnow):
        self.config(heartbeat_timeout=60, group='conductor')
        time_ = datetime.datetime(2000, 1, 1, 0, 0)

        mock_utcnow.return_value = time_
        c = self._create_test_cdr()

        # Only 30 seconds passed since last heartbeat, it's still
        # considered alive
        mock_utcnow.return_value = time_ + datetime.timedelta(seconds=30)
        self.assertEqual([], self.dbapi.get_offline_conductors())

        # 61 seconds passed since last heartbeat, it's dead
        mock_utcnow.return_value = time_ + datetime.timedelta(seconds=61)
        self.assertEqual([c.hostname], self.dbapi.get_offline_conductors())
        self.assertEqual([c.id], self.dbapi.get_offline_conductors(field='id'))

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_get_online_conductors(self, mock_utcnow):
        self.config(heartbeat_timeout=60, group='conductor')
        time_ = datetime.datetime(2000, 1, 1, 0, 0)

        mock_utcnow.return_value = time_
        c = self._create_test_cdr()

        # Only 30 seconds passed since last heartbeat, it's still
        # considered alive
        mock_utcnow.return_value = time_ + datetime.timedelta(seconds=30)
        self.assertEqual([c.hostname], self.dbapi.get_online_conductors())

        # 61 seconds passed since last heartbeat, it's dead
        mock_utcnow.return_value = time_ + datetime.timedelta(seconds=61)
        self.assertEqual([], self.dbapi.get_online_conductors())

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_list_hardware_type_interfaces(self, mock_utcnow):
        self.config(heartbeat_timeout=60, group='conductor')
        time_ = datetime.datetime(2000, 1, 1, 0, 0)
        h = 'fake-host'
        ht1 = 'hw-type-1'
        ht2 = 'hw-type-2'

        mock_utcnow.return_value = time_
        self._create_test_cdr(hostname=h, hardware_types=[ht1, ht2])

        expected = [
            {
                'hardware_type': ht1,
                'interface_type': 'power',
                'interface_name': 'ipmi',
                'default': True,
            },
            {
                'hardware_type': ht1,
                'interface_type': 'power',
                'interface_name': 'fake',
                'default': False,
            },
            {
                'hardware_type': ht2,
                'interface_type': 'power',
                'interface_name': 'ipmi',
                'default': True,
            },
            {
                'hardware_type': ht2,
                'interface_type': 'power',
                'interface_name': 'fake',
                'default': False,
            },
        ]

        def _verify(expected, result):
            for expected_row, row in zip(expected, result):
                for k, v in expected_row.items():
                    self.assertEqual(v, getattr(row, k))

        # with both hw types
        result = self.dbapi.list_hardware_type_interfaces([ht1, ht2])
        _verify(expected, result)

        # with one hw type
        result = self.dbapi.list_hardware_type_interfaces([ht1])
        _verify(expected[:2], result)

        # 61 seconds passed since last heartbeat, it's dead
        mock_utcnow.return_value = time_ + datetime.timedelta(seconds=61)
        result = self.dbapi.list_hardware_type_interfaces([ht1, ht2])
        self.assertEqual([], result)
