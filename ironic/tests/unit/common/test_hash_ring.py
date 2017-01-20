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

import time

from oslo_config import cfg

from ironic.common import exception
from ironic.common import hash_ring
from ironic.tests.unit.db import base as db_base

CONF = cfg.CONF


class HashRingManagerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(HashRingManagerTestCase, self).setUp()
        self.ring_manager = hash_ring.HashRingManager()

    def register_conductors(self):
        c1 = self.dbapi.register_conductor({
            'hostname': 'host1',
            'drivers': ['driver1', 'driver2'],
        })
        c2 = self.dbapi.register_conductor({
            'hostname': 'host2',
            'drivers': ['driver1'],
        })
        for c in (c1, c2):
            self.dbapi.register_conductor_hardware_interfaces(
                c.id, 'hardware-type', 'deploy', ['iscsi', 'direct'], 'iscsi')

    def test_hash_ring_manager_get_ring_success(self):
        self.register_conductors()
        ring = self.ring_manager['driver1']
        self.assertEqual(sorted(['host1', 'host2']), sorted(ring.nodes))

    def test_hash_ring_manager_hardware_type_success(self):
        self.register_conductors()
        ring = self.ring_manager['hardware-type']
        self.assertEqual(sorted(['host1', 'host2']), sorted(ring.nodes))

    def test_hash_ring_manager_driver_not_found(self):
        self.register_conductors()
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.__getitem__,
                          'driver3')

    def test_hash_ring_manager_no_refresh(self):
        # If a new conductor is registered after the ring manager is
        # initialized, it won't be seen. Long term this is probably
        # undesirable, but today is the intended behavior.
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.__getitem__,
                          'driver1')
        self.register_conductors()
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.__getitem__,
                          'driver1')

    def test_hash_ring_manager_refresh(self):
        CONF.set_override('hash_ring_reset_interval', 30)
        # Initialize the ring manager to make _hash_rings not None, then
        # hash ring will refresh only when time interval exceeded.
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.__getitem__,
                          'driver1')
        self.register_conductors()
        self.ring_manager.updated_at = time.time() - 31
        self.ring_manager.__getitem__('driver1')
