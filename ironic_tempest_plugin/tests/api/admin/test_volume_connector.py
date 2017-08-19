# Copyright 2017 FUJITSU LIMITED
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from tempest.lib.common.utils import data_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc

from ironic_tempest_plugin.tests.api.admin import api_microversion_fixture
from ironic_tempest_plugin.tests.api.admin import base


class TestVolumeConnector(base.BaseBaremetalTest):
    """Basic test cases for volume connector."""

    min_microversion = '1.32'
    extra = {'key1': 'value1', 'key2': 'value2'}

    def setUp(self):
        super(TestVolumeConnector, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                self.min_microversion))
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])
        _, self.volume_connector = self.create_volume_connector(
            self.node['uuid'], type='iqn',
            connector_id=data_utils.rand_name('connector_id'),
            extra=self.extra)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('3c3cbf45-488a-4386-a811-bf0aa2589c58')
    def test_create_volume_connector_error(self):
        """Create a volume connector.

        Fail when creating a volume connector with same connector_id
        & type as an existing volume connector.
        """
        regex_str = (r'.*A volume connector .*already exists')

        self.assertRaisesRegex(
            lib_exc.Conflict, regex_str,
            self.create_volume_connector,
            self.node['uuid'],
            type=self.volume_connector['type'],
            connector_id=self.volume_connector['connector_id'])

    @decorators.idempotent_id('5795f816-0789-42e6-bb9c-91b4876ad13f')
    def test_delete_volume_connector(self):
        """Delete a volume connector."""
        # Powering off the Node before deleting a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.delete_volume_connector(self.volume_connector['uuid'])
        self.assertRaises(lib_exc.NotFound, self.client.show_volume_connector,
                          self.volume_connector['uuid'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('ccbda5e6-52b7-400c-94d7-25eec1d590f0')
    def test_delete_volume_connector_error(self):
        """Delete a volume connector

        Fail when deleting a volume connector on node
        with powered on state.
        """

        # Powering on the Node before deleting a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power on')

        regex_str = (r'.*The requested action \\\\"volume connector '
                     r'deletion\\\\" can not be performed on node*')

        self.assertRaisesRegex(lib_exc.BadRequest,
                               regex_str,
                               self.delete_volume_connector,
                               self.volume_connector['uuid'])

    @decorators.idempotent_id('6e4f50b7-0f4f-41c2-971e-d751abcac4e0')
    def test_show_volume_connector(self):
        """Show a specified volume connector."""
        _, volume_connector = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        self._assertExpected(self.volume_connector, volume_connector)

    @decorators.idempotent_id('a4725778-e164-4ee5-96a0-66119a35f783')
    def test_list_volume_connectors(self):
        """List volume connectors."""
        _, body = self.client.list_volume_connectors()
        self.assertIn(self.volume_connector['uuid'],
                      [i['uuid'] for i in body['connectors']])
        self.assertIn(self.volume_connector['type'],
                      [i['type'] for i in body['connectors']])
        self.assertIn(self.volume_connector['connector_id'],
                      [i['connector_id'] for i in body['connectors']])

    @decorators.idempotent_id('1d0459ad-01c0-46db-b930-7301bc2a3c98')
    def test_list_with_limit(self):
        """List volume connectors with limit."""
        _, body = self.client.list_volume_connectors(limit=3)

        next_marker = body['connectors'][-1]['uuid']
        self.assertIn(next_marker, body['next'])

    @decorators.idempotent_id('3c6f8354-e9bd-4f21-aae2-6deb96b04be7')
    def test_update_volume_connector_replace(self):
        """Update a volume connector with new connector id."""
        new_connector_id = data_utils.rand_name('connector_id')

        patch = [{'path': '/connector_id',
                  'op': 'replace',
                  'value': new_connector_id}]

        # Powering off the Node before updating a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.client.update_volume_connector(
            self.volume_connector['uuid'], patch)

        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        self.assertEqual(new_connector_id, body['connector_id'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('5af8dc7a-9965-4787-8184-e60aeaf30957')
    def test_update_volume_connector_replace_error(self):
        """Updating a volume connector.

        Fail when updating a volume connector on node
        with power on state.
        """

        new_connector_id = data_utils.rand_name('connector_id')

        patch = [{'path': '/connector_id',
                  'op': 'replace',
                  'value': new_connector_id}]

        # Powering on the Node before updating a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power on')

        regex_str = (r'.*The requested action \\\\"volume connector '
                     r'update\\\\" can not be performed on node*')
        self.assertRaisesRegex(lib_exc.BadRequest,
                               regex_str,
                               self.client.update_volume_connector,
                               self.volume_connector['uuid'],
                               patch)

    @decorators.idempotent_id('b95c75eb-4048-482e-99ff-fe1d32538383')
    def test_update_volume_connector_remove_item(self):
        """Update a volume connector by removing one item from collection."""
        new_extra = {'key1': 'value1'}
        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        connector_id = body['connector_id']
        connector_type = body['type']

        # Powering off the Node before updating a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        # Removing one item from the collection
        self.client.update_volume_connector(self.volume_connector['uuid'],
                                            [{'path': '/extra/key2',
                                              'op': 'remove'}])
        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        self.assertEqual(new_extra, body['extra'])

        # Assert nothing else was changed
        self.assertEqual(connector_id, body['connector_id'])
        self.assertEqual(connector_type, body['type'])

    @decorators.idempotent_id('8de03acd-532a-476f-8bc9-0e8b23bfe609')
    def test_update_volume_connector_remove_collection(self):
        """Update a volume connector by removing collection."""
        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        connector_id = body['connector_id']
        connector_type = body['type']

        # Powering off the Node before updating a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        # Removing the collection
        self.client.update_volume_connector(self.volume_connector['uuid'],
                                            [{'path': '/extra',
                                              'op': 'remove'}])
        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        self.assertEqual({}, body['extra'])

        # Assert nothing else was changed
        self.assertEqual(connector_id, body['connector_id'])
        self.assertEqual(connector_type, body['type'])

    @decorators.idempotent_id('bfb0ca6b-086d-4663-9b25-e0eaf42da55b')
    def test_update_volume_connector_add(self):
        """Update a volume connector by adding one item to collection."""
        new_extra = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}

        patch = [{'path': '/extra/key3',
                  'op': 'add',
                  'value': new_extra['key3']},
                 {'path': '/extra/key3',
                  'op': 'add',
                  'value': new_extra['key3']}]

        # Powering off the Node before updating a volume connector.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.client.update_volume_connector(
            self.volume_connector['uuid'], patch)

        _, body = self.client.show_volume_connector(
            self.volume_connector['uuid'])
        self.assertEqual(new_extra, body['extra'])
