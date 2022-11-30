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
"""
Tests for the API /shards/ methods.
"""

from http import client as http_client
import uuid

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.tests.unit.api import base as test_api_base
from ironic.tests.unit.objects import utils as obj_utils


class TestListShards(test_api_base.BaseApiTest):
    headers = {api_base.Version.string: str(api_v1.max_version())}

    def _create_test_shard(self, name, count):
        for i in range(count):
            obj_utils.create_test_node(
                self.context, uuid=uuid.uuid4(), shard=name)

    def test_empty(self):
        data = self.get_json('/shards', headers=self.headers)
        self.assertEqual([], data['shards'])

    def test_one_shard(self):
        shard = 'shard1'
        count = 1
        self._create_test_shard(shard, count)
        data = self.get_json('/shards', headers=self.headers)
        self.assertEqual(shard, data['shards'][0]['name'])
        self.assertEqual(count, data['shards'][0]['count'])

    def test_multiple_shards(self):
        for i in range(0, 6):
            self._create_test_shard('shard{}'.format(i), i)
        data = self.get_json('/shards', headers=self.headers)
        self.assertEqual(5, len(data['shards']))

    def test_nodes_but_no_shards(self):
        self._create_test_shard(None, 5)
        data = self.get_json('/shards', headers=self.headers)
        self.assertEqual("None", data['shards'][0]['name'])
        self.assertEqual(5, data['shards'][0]['count'])

    def test_fail_wrong_version(self):
        headers = {api_base.Version.string: '1.80'}
        self._create_test_shard('shard1', 1)
        result = self.get_json(
            '/shards', expect_errors=True, headers=headers)
        self.assertEqual(http_client.NOT_FOUND, result.status_int)

    def test_fail_get_one(self):
        # We do not implement a get /v1/shards/<shard> endpoint
        # validate it errors properly
        self._create_test_shard('shard1', 1)
        result = self.get_json(
            '/shards/shard1', expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.NOT_FOUND, result.status_int)

    def test_fail_post(self):
        result = self.post_json(
            '/shards', {}, expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, result.status_int)

    def test_fail_put(self):
        result = self.put_json(
            '/shards', {}, expect_errors=True, headers=self.headers)
        self.assertEqual(http_client.METHOD_NOT_ALLOWED, result.status_int)
