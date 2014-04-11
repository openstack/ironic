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

from oslo.config import cfg

from ironic.common import exception
from ironic.common import hash_ring as hash
from ironic.db import api as dbapi
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.db import base as db_base

CONF = cfg.CONF


class HashRingTestCase(base.TestCase):

    # NOTE(deva): the mapping used in these tests is as follows:
    #             if hosts = [foo, bar]:
    #                fake -> foo, bar
    #             if hosts = [foo, bar, baz]:
    #                fake -> foo, bar, baz
    #                fake-again -> bar, baz, foo

    def test_create_ring(self):
        hosts = ['foo', 'bar']
        replicas = 2
        ring = hash.HashRing(hosts, replicas=replicas)
        self.assertEqual(hosts, ring.hosts)
        self.assertEqual(replicas, ring.replicas)

    def test_create_with_different_partition_counts(self):
        hosts = ['foo', 'bar']
        CONF.set_override('hash_partition_exponent', 2)
        ring = hash.HashRing(hosts)
        self.assertEqual(2 ** 2, len(ring.part2host))

        CONF.set_override('hash_partition_exponent', 8)
        ring = hash.HashRing(hosts)
        self.assertEqual(2 ** 8, len(ring.part2host))

        CONF.set_override('hash_partition_exponent', 16)
        ring = hash.HashRing(hosts)
        self.assertEqual(2 ** 16, len(ring.part2host))

    def test_distribution_one_replica(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash.HashRing(hosts, replicas=1)
        self.assertEqual(['foo'], ring.get_hosts('fake'))
        self.assertEqual(['bar'], ring.get_hosts('fake-again'))

    def test_distribution_two_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash.HashRing(hosts, replicas=2)
        self.assertEqual(['foo', 'bar'], ring.get_hosts('fake'))
        self.assertEqual(['bar', 'baz'], ring.get_hosts('fake-again'))

    def test_distribution_three_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash.HashRing(hosts, replicas=3)
        self.assertEqual(['foo', 'bar', 'baz'], ring.get_hosts('fake'))
        self.assertEqual(['bar', 'baz', 'foo'], ring.get_hosts('fake-again'))

    def test_ignore_hosts(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash.HashRing(hosts, replicas=1)
        self.assertEqual(['bar'], ring.get_hosts('fake',
                                                 ignore_hosts=['foo']))
        self.assertEqual(['baz'], ring.get_hosts('fake',
                                                 ignore_hosts=['foo', 'bar']))
        self.assertEqual([], ring.get_hosts('fake',
                                            ignore_hosts=hosts))

    def test_ignore_hosts_with_replicas(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash.HashRing(hosts, replicas=2)
        self.assertEqual(['bar', 'baz'], ring.get_hosts('fake',
                                                        ignore_hosts=['foo']))
        self.assertEqual(['baz'], ring.get_hosts('fake',
                                                 ignore_hosts=['foo', 'bar']))
        self.assertEqual(['baz', 'foo'], ring.get_hosts('fake-again',
                                                        ignore_hosts=['bar']))
        self.assertEqual(['foo'], ring.get_hosts('fake-again',
                                                 ignore_hosts=['bar', 'baz']))
        self.assertEqual([], ring.get_hosts('fake',
                                            ignore_hosts=hosts))

    def test_more_replicas_than_hosts(self):
        hosts = ['foo', 'bar']
        ring = hash.HashRing(hosts, replicas=10)
        self.assertEqual(hosts, ring.get_hosts('fake'))

    def test_ignore_non_existent_host(self):
        hosts = ['foo', 'bar']
        ring = hash.HashRing(hosts, replicas=1)
        self.assertEqual(['foo'], ring.get_hosts('fake',
                                                 ignore_hosts=['baz']))

    def test_create_ring_invalid_data(self):
        hosts = None
        self.assertRaises(exception.Invalid,
                          hash.HashRing,
                          hosts)

    def test_get_hosts_invalid_data(self):
        hosts = ['foo', 'bar']
        ring = hash.HashRing(hosts)
        self.assertRaises(exception.Invalid,
                          ring.get_hosts,
                          None)


class HashRingManagerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(HashRingManagerTestCase, self).setUp()
        self.ring_manager = hash.HashRingManager()
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()

    def register_conductors(self):
        self.dbapi.register_conductor({
            'hostname': 'host1',
            'drivers': ['driver1', 'driver2'],
        })
        self.dbapi.register_conductor({
            'hostname': 'host2',
            'drivers': ['driver1'],
        })

    def test_hash_ring_manager_get_ring_success(self):
        self.register_conductors()
        ring = self.ring_manager.get_hash_ring('driver1')
        self.assertEqual(sorted(['host1', 'host2']), sorted(ring.hosts))

    def test_hash_ring_manager_driver_not_found(self):
        self.register_conductors()
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.get_hash_ring,
                          'driver3')

    def test_hash_ring_manager_no_refresh(self):
        # If a new conductor is registered after the ring manager is
        # initialized, it won't be seen. Long term this is probably
        # undesirable, but today is the intended behavior.
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.get_hash_ring,
                          'driver1')
        self.register_conductors()
        self.assertRaises(exception.DriverNotFound,
                          self.ring_manager.get_hash_ring,
                          'driver1')
