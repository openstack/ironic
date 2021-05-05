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

    use_groups = False

    def setUp(self):
        super(HashRingManagerTestCase, self).setUp()
        self.ring_manager = hash_ring.HashRingManager(
            use_groups=self.use_groups)

    def register_conductors(self):
        c1 = self.dbapi.register_conductor({
            'hostname': 'host1',
            'drivers': ['driver1', 'driver2'],
        })
        c2 = self.dbapi.register_conductor({
            'hostname': 'host2',
            'drivers': ['driver1'],
        })
        c3 = self.dbapi.register_conductor({
            'hostname': 'host3',
            'drivers': ['driver1, driver2'],
            'conductor_group': 'foogroup',
        })
        c4 = self.dbapi.register_conductor({
            'hostname': 'host4',
            'drivers': ['driver1'],
            'conductor_group': 'foogroup',
        })
        c5 = self.dbapi.register_conductor({
            'hostname': 'host5',
            'drivers': ['driver1'],
            'conductor_group': 'bargroup',
        })
        for c in (c1, c2, c3, c4, c5):
            self.dbapi.register_conductor_hardware_interfaces(
                c.id,
                [{'hardware_type': 'hardware-type', 'interface_type': 'deploy',
                  'interface_name': 'ansible', 'default': True},
                 {'hardware_type': 'hardware-type', 'interface_type': 'deploy',
                  'interface_name': 'direct', 'default': False}]
            )

    def test_hash_ring_manager_hardware_type_success(self):
        self.register_conductors()
        ring = self.ring_manager.get_ring('hardware-type', '')
        self.assertEqual(sorted(['host1', 'host2', 'host3', 'host4', 'host5']),
                         sorted(ring.nodes))

    def test_hash_ring_manager_hardware_type_success_groups(self):
        # groupings should be ignored here
        self.register_conductors()
        ring = self.ring_manager.get_ring('hardware-type', 'foogroup')
        self.assertEqual(sorted(['host1', 'host2', 'host3', 'host4', 'host5']),
                         sorted(ring.nodes))

    def test_hash_ring_manager_driver_not_found(self):
        self.register_conductors()
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.get_ring,
                          'driver3', '')

    def test_hash_ring_manager_automatic_retry(self):
        self.assertRaises(exception.TemporaryFailure,
                          self.ring_manager.get_ring,
                          'hardware-type', '')
        self.register_conductors()
        self.ring_manager.get_ring('hardware-type', '')

    def test_hash_ring_manager_reset_interval(self):
        CONF.set_override('hash_ring_reset_interval', 30)
        # Just to simplify calculations
        CONF.set_override('hash_partition_exponent', 0)
        c1 = self.dbapi.register_conductor({
            'hostname': 'host1',
            'drivers': ['driver1', 'driver2'],
        })
        c2 = self.dbapi.register_conductor({
            'hostname': 'host2',
            'drivers': ['driver1'],
        })
        self.dbapi.register_conductor_hardware_interfaces(
            c1.id,
            [{'hardware_type': 'hardware-type', 'interface_type': 'deploy',
              'interface_name': 'ansible', 'default': True},
             {'hardware_type': 'hardware-type', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )

        ring = self.ring_manager.get_ring('hardware-type', '')
        self.assertEqual(1, len(ring))

        self.dbapi.register_conductor_hardware_interfaces(
            c2.id,
            [{'hardware_type': 'hardware-type', 'interface_type': 'deploy',
              'interface_name': 'ansible', 'default': True},
             {'hardware_type': 'hardware-type', 'interface_type': 'deploy',
              'interface_name': 'direct', 'default': False}]
        )
        ring = self.ring_manager.get_ring('hardware-type', '')
        # The new conductor is not known yet. Automatic retry does not kick in,
        # since there is an active conductor for the requested hardware type.
        self.assertEqual(1, len(ring))

        self.ring_manager.__class__._hash_rings = (
            self.ring_manager.__class__._hash_rings[0],
            time.time() - 31
        )
        ring = self.ring_manager.get_ring('hardware-type', '')
        self.assertEqual(2, len(ring))

    def test_hash_ring_manager_uncached(self):
        ring_mgr = hash_ring.HashRingManager(cache=False,
                                             use_groups=self.use_groups)
        ring = ring_mgr.ring
        self.assertIsNotNone(ring)
        self.assertEqual((None, 0), hash_ring.HashRingManager._hash_rings)


class HashRingManagerWithGroupsTestCase(HashRingManagerTestCase):

    use_groups = True

    def test_hash_ring_manager_hardware_type_success(self):
        self.register_conductors()
        ring = self.ring_manager.get_ring('hardware-type', '')
        self.assertEqual(sorted(['host1', 'host2']), sorted(ring.nodes))

    def test_hash_ring_manager_hardware_type_success_groups(self):
        self.register_conductors()
        ring = self.ring_manager.get_ring('hardware-type', 'foogroup')
        self.assertEqual(sorted(['host3', 'host4']), sorted(ring.nodes))
