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


class TestVolumeTarget(base.BaseBaremetalTest):
    """Basic test cases for volume target."""

    min_microversion = '1.32'
    extra = {'key1': 'value1', 'key2': 'value2'}

    def setUp(self):
        super(TestVolumeTarget, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                self.min_microversion))
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])
        _, self.volume_target = self.create_volume_target(
            self.node['uuid'], volume_type=data_utils.rand_name('volume_type'),
            volume_id=data_utils.rand_name('volume_id'),
            boot_index=10,
            extra=self.extra)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('da5c27d4-68cc-499f-b8ab-3048b87d3bca')
    def test_create_volume_target_error(self):
        """Create a volume target.

        Fail when creating a volume target with same boot index as the
        existing volume target.
        """
        regex_str = (r'.*A volume target .*already exists')

        self.assertRaisesRegex(
            lib_exc.Conflict, regex_str,
            self.create_volume_target,
            self.node['uuid'],
            volume_type=data_utils.rand_name('volume_type'),
            volume_id=data_utils.rand_name('volume_id'),
            boot_index=self.volume_target['boot_index'])

    @decorators.idempotent_id('ea3a9b2e-8971-4830-9274-abaf0239f1ce')
    def test_delete_volume_target(self):
        """Delete a volume target."""
        # Powering off the Node before deleting a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.delete_volume_target(self.volume_target['uuid'])
        self.assertRaises(lib_exc.NotFound, self.client.show_volume_target,
                          self.volume_target['uuid'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('532a06bc-a9b2-44b0-828a-c53279c87cb2')
    def test_delete_volume_target_error(self):
        """Fail when deleting a volume target on node with power on state."""
        # Powering on the Node before deleting a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power on')

        regex_str = (r'.*The requested action \\\\"volume target '
                     r'deletion\\\\" can not be performed on node*')

        self.assertRaisesRegex(lib_exc.BadRequest,
                               regex_str,
                               self.delete_volume_target,
                               self.volume_target['uuid'])

    @decorators.idempotent_id('a2598388-8f61-4b7e-944f-f37e4f60e1e2')
    def test_show_volume_target(self):
        """Show a specified volume target."""
        _, volume_target = self.client.show_volume_target(
            self.volume_target['uuid'])
        self._assertExpected(self.volume_target, volume_target)

    @decorators.idempotent_id('ae99a986-d93c-4324-9cdc-41d89e3a659f')
    def test_list_volume_targets(self):
        """List volume targets."""
        _, body = self.client.list_volume_targets()
        self.assertIn(self.volume_target['uuid'],
                      [i['uuid'] for i in body['targets']])
        self.assertIn(self.volume_target['volume_type'],
                      [i['volume_type'] for i in body['targets']])
        self.assertIn(self.volume_target['volume_id'],
                      [i['volume_id'] for i in body['targets']])

    @decorators.idempotent_id('9da25447-0370-4b33-9c1f-d4503f5950ae')
    def test_list_with_limit(self):
        """List volume targets with limit."""
        _, body = self.client.list_volume_targets(limit=3)

        next_marker = body['targets'][-1]['uuid']
        self.assertIn(next_marker, body['next'])

    @decorators.idempotent_id('8559cd08-feae-4f1a-a0ad-5bad8ea12b76')
    def test_update_volume_target_replace(self):
        """Update a volume target by replacing volume id."""
        new_volume_id = data_utils.rand_name('volume_id')

        patch = [{'path': '/volume_id',
                  'op': 'replace',
                  'value': new_volume_id}]

        # Powering off the Node before updating a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.client.update_volume_target(self.volume_target['uuid'], patch)

        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        self.assertEqual(new_volume_id, body['volume_id'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('fd5266d3-4f3c-4dce-9c87-bfdea2b756c7')
    def test_update_volume_target_replace_error(self):
        """Fail when updating a volume target on node with power on state."""
        new_volume_id = data_utils.rand_name('volume_id')

        patch = [{'path': '/volume_id',
                  'op': 'replace',
                  'value': new_volume_id}]

        # Powering on the Node before updating a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power on')

        regex_str = (r'.*The requested action \\\\"volume target '
                     r'update\\\\" can not be performed on node*')

        self.assertRaisesRegex(lib_exc.BadRequest,
                               regex_str,
                               self.client.update_volume_target,
                               self.volume_target['uuid'],
                               patch)

    @decorators.idempotent_id('1c13a4ee-1a49-4739-8c19-77960fbd1af8')
    def test_update_volume_target_remove_item(self):
        """Update a volume target by removing one item from the collection."""
        new_extra = {'key1': 'value1'}
        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        volume_id = body['volume_id']
        volume_type = body['volume_type']

        # Powering off the Node before updating a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        # Removing one item from the collection
        self.client.update_volume_target(self.volume_target['uuid'],
                                         [{'path': '/extra/key2',
                                           'op': 'remove'}])

        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        self.assertEqual(new_extra, body['extra'])

        # Assert nothing else was changed
        self.assertEqual(volume_id, body['volume_id'])
        self.assertEqual(volume_type, body['volume_type'])

    @decorators.idempotent_id('6784ddb0-9144-41ea-b8a0-f888ad5c5b62')
    def test_update_volume_target_remove_collection(self):
        """Update a volume target by removing the collection."""
        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        volume_id = body['volume_id']
        volume_type = body['volume_type']

        # Powering off the Node before updating a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        # Removing the collection
        self.client.update_volume_target(self.volume_target['uuid'],
                                         [{'path': '/extra',
                                           'op': 'remove'}])
        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        self.assertEqual({}, body['extra'])

        # Assert nothing else was changed
        self.assertEqual(volume_id, body['volume_id'])
        self.assertEqual(volume_type, body['volume_type'])

    @decorators.idempotent_id('9629715d-57ba-423b-b985-232674cc3a25')
    def test_update_volume_target_add(self):
        """Update a volume target by adding to the collection."""
        new_extra = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}

        patch = [{'path': '/extra/key3',
                  'op': 'add',
                  'value': new_extra['key3']}]

        # Powering off the Node before updating a volume target.
        self.client.set_node_power_state(self.node['uuid'], 'power off')

        self.client.update_volume_target(self.volume_target['uuid'], patch)

        _, body = self.client.show_volume_target(self.volume_target['uuid'])
        self.assertEqual(new_extra, body['extra'])
