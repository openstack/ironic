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

from tempest.lib.common.utils import data_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc

from ironic_tempest_plugin.tests.api.admin import api_microversion_fixture
from ironic_tempest_plugin.tests.api.admin import base


class TestPortGroups(base.BaseBaremetalTest):
    """Basic positive test cases for port groups."""

    min_microversion = '1.23'

    def setUp(self):
        super(TestPortGroups, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                self.min_microversion))
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])
        _, self.portgroup = self.create_portgroup(
            self.node['uuid'], address=data_utils.rand_mac_address(),
            name=data_utils.rand_name('portgroup'))

    @decorators.idempotent_id('110cd302-256b-4ddc-be10-fc6c9ad8e649')
    def test_create_portgroup_with_address(self):
        """Create a port group with specific MAC address."""
        _, body = self.client.show_portgroup(self.portgroup['uuid'])
        self.assertEqual(self.portgroup['address'], body['address'])

    @decorators.idempotent_id('4336fa0f-da86-4cec-b788-89f59a7635a5')
    def test_create_portgroup_no_address(self):
        """Create a port group without setting MAC address."""
        _, portgroup = self.create_portgroup(self.node['uuid'])
        _, body = self.client.show_portgroup(portgroup['uuid'])

        self._assertExpected(portgroup, body)
        self.assertIsNone(body['address'])

    @decorators.idempotent_id('8378c69f-f806-454b-8ddd-6b7fd93ab12b')
    def test_delete_portgroup(self):
        """Delete a port group."""
        self.delete_portgroup(self.portgroup['uuid'])
        self.assertRaises(lib_exc.NotFound, self.client.show_portgroup,
                          self.portgroup['uuid'])

    @decorators.idempotent_id('f6be5e70-3e3b-435c-b2fc-bbb2cc9b3185')
    def test_show_portgroup(self):
        """Show a specified port group."""
        _, portgroup = self.client.show_portgroup(self.portgroup['uuid'])
        self._assertExpected(self.portgroup, portgroup)

    @decorators.idempotent_id('cf2dfd95-5ea1-4109-8ad3-297cd76aa5d3')
    def test_list_portgroups(self):
        """List port groups."""
        _, body = self.client.list_portgroups()
        self.assertIn(self.portgroup['uuid'],
                      [i['uuid'] for i in body['portgroups']])
        self.assertIn(self.portgroup['address'],
                      [i['address'] for i in body['portgroups']])
        self.assertIn(self.portgroup['name'],
                      [i['name'] for i in body['portgroups']])
