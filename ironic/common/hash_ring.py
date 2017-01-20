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

from tooz import hashring

from ironic.common import exception
from ironic.common.i18n import _
from ironic.conf import CONF
from ironic.db import api as dbapi


class HashRingManager(object):
    _hash_rings = None
    _lock = threading.Lock()

    def __init__(self):
        self.dbapi = dbapi.get_instance()
        self.updated_at = time.time()

    @property
    def ring(self):
        interval = CONF.hash_ring_reset_interval
        limit = time.time() - interval
        # Hot path, no lock
        if self.__class__._hash_rings is not None and self.updated_at >= limit:
            return self.__class__._hash_rings

        with self._lock:
            if self.__class__._hash_rings is None or self.updated_at < limit:
                rings = self._load_hash_rings()
                self.__class__._hash_rings = rings
                self.updated_at = time.time()
            return self.__class__._hash_rings

    def _load_hash_rings(self):
        rings = {}
        d2c = self.dbapi.get_active_driver_dict()
        d2c.update(self.dbapi.get_active_hardware_type_dict())

        for driver_name, hosts in d2c.items():
            rings[driver_name] = hashring.HashRing(
                hosts, partitions=2 ** CONF.hash_partition_exponent)
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
