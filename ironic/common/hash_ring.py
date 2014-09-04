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

import bisect
import hashlib
import struct
import threading

from oslo.config import cfg

from ironic.common import exception
from ironic.common.i18n import _
from ironic.db import api as dbapi

hash_opts = [
    cfg.IntOpt('hash_partition_exponent',
               default=5,
               help='Exponent to determine number of hash partitions to use '
                    'when distributing load across conductors. Larger values '
                    'will result in more even distribution of load and less '
                    'load when rebalancing the ring, but more memory usage. '
                    'Number of partitions per conductor is '
                    '(2^hash_partition_exponent). This determines the '
                    'granularity of rebalancing: given 10 hosts, and an '
                    'exponent of the 2, there are 40 partitions in the ring.'
                    'A few thousand partitions should make rebalancing '
                    'smooth in most cases. The default is suitable for up to '
                    'a few hundred conductors. Too many partitions has a CPU '
                    'impact.'),
    cfg.IntOpt('hash_distribution_replicas',
               default=1,
               help='[Experimental Feature] '
                    'Number of hosts to map onto each hash partition. '
                    'Setting this to more than one will cause additional '
                    'conductor services to prepare deployment environments '
                    'and potentially allow the Ironic cluster to recover '
                    'more quickly if a conductor instance is terminated.'),
]

CONF = cfg.CONF
CONF.register_opts(hash_opts)


class HashRing(object):
    """A stable hash ring.

    We map item N to a host Y based on the closest lower hash
    - hash(item) -> partition
    - hash(host) -> divider
    - closest lower divider is the host to use
    - we hash each host many times to spread load more finely
      as otherwise adding a host gets (on average) 50% of the load of
      just one other host assigned to it.
    """

    def __init__(self, hosts, replicas=None):
        """Create a new hash ring across the specified hosts.

        :param hosts: an iterable of hosts which will be mapped.
        :param replicas: number of hosts to map to each hash partition,
                         or len(hosts), which ever is lesser.
                         Default: CONF.hash_distribution_replicas

        """
        if replicas is None:
            replicas = CONF.hash_distribution_replicas

        try:
            self.hosts = set(hosts)
            self.replicas = replicas if replicas <= len(hosts) else len(hosts)
        except TypeError:
            raise exception.Invalid(
                    _("Invalid hosts supplied when building HashRing."))

        self._host_hashes = {}
        for host in hosts:
            key = str(host).encode('utf8')
            key_hash = hashlib.md5(key)
            for p in range(2 ** CONF.hash_partition_exponent):
                key_hash.update(key)
                hashed_key = struct.unpack_from('>I', key_hash.digest())[0]
                self._host_hashes[hashed_key] = host
        # Gather the (possibly colliding) resulting hashes into a bisectable
        # list.
        self._partitions = sorted(self._host_hashes.keys())

    def _get_partition(self, data):
        try:
            hashed_key = struct.unpack_from(
                '>I', hashlib.md5(data).digest())[0]
            position = bisect.bisect(self._partitions, hashed_key)
            return position if position < len(self._partitions) else 0
        except TypeError:
            raise exception.Invalid(
                    _("Invalid data supplied to HashRing.get_hosts."))

    def get_hosts(self, data, ignore_hosts=None):
        """Get the list of hosts which the supplied data maps onto.

        :param data: A string identifier to be mapped across the ring.
        :param ignore_hosts: A list of hosts to skip when performing the hash.
                             Useful to temporarily skip down hosts without
                             performing a full rebalance.
                             Default: None.
        :returns: a list of hosts.
                  The length of this list depends on the number of replicas
                  this `HashRing` was created with. It may be less than this
                  if ignore_hosts is not None.
        """
        hosts = []
        if ignore_hosts is None:
            ignore_hosts = set()
        else:
            ignore_hosts = set(ignore_hosts)
            ignore_hosts.intersection_update(self.hosts)
        partition = self._get_partition(data)
        for replica in range(0, self.replicas):
            if len(hosts) + len(ignore_hosts) == len(self.hosts):
                # prevent infinite loop - cannot allocate more fallbacks.
                break
            # Linear probing: partition N, then N+1 etc.
            host = self._get_host(partition)
            while host in hosts or host in ignore_hosts:
                partition += 1
                if partition >= len(self._partitions):
                    partition = 0
                host = self._get_host(partition)
            hosts.append(host)
        return hosts

    def _get_host(self, partition):
        """Find what host is serving a partition.

        :param partition: The index of the partition in the partition map.
            e.g. 0 is the first partition, 1 is the second.
        :return: The host object the ring was constructed with.
        """
        return self._host_hashes[self._partitions[partition]]


class HashRingManager(object):
    _hash_rings = None
    _lock = threading.Lock()

    def __init__(self):
        self.dbapi = dbapi.get_instance()

    @property
    def ring(self):
        # Hot path, no lock
        if self._hash_rings is not None:
            return self._hash_rings

        with self._lock:
            if self._hash_rings is None:
                rings = self._load_hash_rings()
                self.__class__._hash_rings = rings
            return self._hash_rings

    def _load_hash_rings(self):
        rings = {}
        d2c = self.dbapi.get_active_driver_dict()

        for driver_name, hosts in d2c.iteritems():
            rings[driver_name] = HashRing(hosts)
        return rings

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._hash_rings = None

    def __getitem__(self, driver_name):
        try:
            return self.ring[driver_name]
        except KeyError:
            raise exception.DriverNotFound(
                    _("The driver '%s' is unknown.") % driver_name)
