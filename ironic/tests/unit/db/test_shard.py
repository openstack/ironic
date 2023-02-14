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

"""Tests for fetching shards via the DB API"""
import uuid

from oslo_db.sqlalchemy import enginefacade

from ironic.tests.unit.db import base
from ironic.tests.unit.db import utils


class ShardTestCase(base.DbTestCase):
    def setUp(self):
        super(ShardTestCase, self).setUp()
        self.engine = enginefacade.writer.get_engine()

    def test_get_shard_list(self):
        """Validate shard list is returned, and with correct sorting."""
        for i in range(1, 2):
            utils.create_test_node(uuid=str(uuid.uuid4()))
        for i in range(1, 3):
            utils.create_test_node(uuid=str(uuid.uuid4()), shard="shard1")
        for i in range(1, 4):
            utils.create_test_node(uuid=str(uuid.uuid4()), shard="shard2")

        res = self.dbapi.get_shard_list()
        self.assertEqual(res, [
            {"name": "shard2", "count": 3},
            {"name": "shard1", "count": 2},
            {"name": "None", "count": 1},
        ])

    def test_get_shard_empty_list(self):
        """Validate empty list is returned if no assigned shards."""
        res = self.dbapi.get_shard_list()
        self.assertEqual(res, [])
