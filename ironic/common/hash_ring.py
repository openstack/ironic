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

import threading
import time

from oslo_log import log
from tooz import hashring

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF
from ironic.db import api as dbapi


LOG = log.getLogger(__name__)


class HashRingManager(object):
    _hash_rings = None
    _lock = threading.Lock()

    def __init__(self, use_groups=True, cache=True):
        self.dbapi = dbapi.get_instance()
        self.updated_at = time.time()
        self.use_groups = use_groups
        self.cache = cache

    @property
    def ring(self):
        interval = CONF.hash_ring_reset_interval
        limit = time.time() - interval

        if not self.cache:
            return self._load_hash_rings()

        # Hot path, no lock. Using a local variable to avoid races with code
        # changing the class variable.
        hash_rings = self.__class__._hash_rings
        if hash_rings is not None and self.updated_at >= limit:
            return hash_rings

        with self._lock:
            if self.__class__._hash_rings is None or self.updated_at < limit:
                LOG.debug('Rebuilding cached hash rings')
                rings = self._load_hash_rings()
                self.__class__._hash_rings = rings
                self.updated_at = time.time()
                LOG.debug('Finished rebuilding hash rings, available drivers '
                          'are %s', ', '.join(rings))
            return self.__class__._hash_rings

    def _load_hash_rings(self):
        rings = {}
        d2c = self.dbapi.get_active_hardware_type_dict(
            use_groups=self.use_groups)

        for driver_name, hosts in d2c.items():
            rings[driver_name] = hashring.HashRing(
                hosts, partitions=2 ** CONF.hash_partition_exponent,
                hash_function=CONF.hash_ring_algorithm)

        return rings

    @classmethod
    def reset(cls):
        with cls._lock:
            LOG.debug('Resetting cached hash rings')
            cls._hash_rings = None

    def get_ring(self, driver_name, conductor_group):
        try:
            return self._get_ring(driver_name, conductor_group)
        except (exception.DriverNotFound, exception.TemporaryFailure):
            # NOTE(dtantsur): we assume that this case is more often caused by
            # conductors coming and leaving, so we try to rebuild the rings.
            LOG.debug('No conductor from group %(group)s found for driver '
                      '%(driver)s, trying to rebuild the hash rings',
                      {'driver': driver_name,
                       'group': conductor_group or '<none>'})

        self.__class__.reset()
        return self._get_ring(driver_name, conductor_group)

    def _get_ring(self, driver_name, conductor_group):
        # There are no conductors, temporary failure - 503 Service Unavailable
        if not self.ring:
            raise exception.TemporaryFailure()

        try:
            if self.use_groups:
                return self.ring['%s:%s' % (conductor_group, driver_name)]
            return self.ring[driver_name]
        except KeyError:
            raise exception.DriverNotFound(
                _("The driver '%s' is unknown.") % driver_name)
