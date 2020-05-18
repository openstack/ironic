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
Tests for the API /volume/ methods.
"""

from http import client as http_client

from ironic.api.controllers import base as api_base
from ironic.api.controllers import v1 as api_v1
from ironic.tests.unit.api import base as test_api_base


class TestGetVolume(test_api_base.BaseApiTest):

    def _test_links(self, data, key, headers):
        self.assertIn(key, data)
        self.assertEqual(2, len(data[key]))
        for link in data[key]:
            bookmark = (link['rel'] == 'bookmark')
            self.assertTrue(self.validate_link(link['href'],
                                               bookmark=bookmark,
                                               headers=headers))

    def test_get_volume(self):
        headers = {api_base.Version.string: str(api_v1.max_version())}
        data = self.get_json('/volume/', headers=headers)
        for key in ['links', 'connectors', 'targets']:
            self._test_links(data, key, headers)
        self.assertIn('/volume/connectors',
                      data['connectors'][0]['href'])
        self.assertIn('/volume/connectors',
                      data['connectors'][1]['href'])
        self.assertIn('/volume/targets',
                      data['targets'][0]['href'])
        self.assertIn('/volume/targets',
                      data['targets'][1]['href'])

    def test_get_volume_invalid_api_version(self):
        headers = {api_base.Version.string: str(api_v1.min_version())}
        response = self.get_json('/volume/', headers=headers,
                                 expect_errors=True)
        self.assertEqual(http_client.NOT_FOUND, response.status_int)
