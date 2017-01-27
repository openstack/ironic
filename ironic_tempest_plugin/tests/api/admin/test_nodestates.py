# Copyright 2014 NEC Corporation.  All rights reserved.
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

from oslo_utils import timeutils
from tempest.lib import decorators
from tempest.lib import exceptions

from ironic_tempest_plugin.tests.api.admin import api_microversion_fixture
from ironic_tempest_plugin.tests.api.admin import base


class TestNodeStatesMixin(object):
    """Mixin for for baremetal node states tests."""

    @classmethod
    def resource_setup(cls):
        super(TestNodeStatesMixin, cls).resource_setup()
        _, cls.chassis = cls.create_chassis()

    def _validate_power_state(self, node_uuid, power_state):
        # Validate that power state is set within timeout
        if power_state == 'rebooting':
            power_state = 'power on'
        start = timeutils.utcnow()
        while timeutils.delta_seconds(
                start, timeutils.utcnow()) < self.power_timeout:
            _, node = self.client.show_node(node_uuid)
            if node['power_state'] == power_state:
                return
        message = ('Failed to set power state within '
                   'the required time: %s sec.' % self.power_timeout)
        raise exceptions.TimeoutException(message)

    def _validate_provision_state(self, node_uuid, target_state):
        # Validate that provision state is set within timeout
        start = timeutils.utcnow()
        while timeutils.delta_seconds(
                start, timeutils.utcnow()) < self.unprovision_timeout:
            _, node = self.client.show_node(node_uuid)
            if node['provision_state'] == target_state:
                return
        message = ('Failed to set provision state %(state)s within '
                   'the required time: %(timeout)s sec.',
                   {'state': target_state,
                    'timeout': self.unprovision_timeout})
        raise exceptions.TimeoutException(message)

    @decorators.idempotent_id('cd8afa5e-3f57-4e43-8185-beb83d3c9015')
    def test_list_nodestates(self):
        _, node = self.create_node(self.chassis['uuid'])
        _, nodestates = self.client.list_nodestates(node['uuid'])
        for key in nodestates:
            self.assertEqual(nodestates[key], node[key])

    @decorators.idempotent_id('fc5b9320-0c98-4e5a-8848-877fe5a0322c')
    def test_set_node_power_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        states = ["power on", "rebooting", "power off"]
        for state in states:
            # Set power state
            self.client.set_node_power_state(node['uuid'], state)
            # Check power state after state is set
            self._validate_power_state(node['uuid'], state)


class TestNodeStatesV1_1(TestNodeStatesMixin, base.BaseBaremetalTest):

    @decorators.idempotent_id('ccb8fca9-2ba0-480c-a037-34c3bd09dc74')
    def test_set_node_provision_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        # Nodes appear in NONE state by default until v1.1
        self.assertIsNone(node['provision_state'])
        provision_states_list = ['active', 'deleted']
        target_states_list = ['active', None]
        for (provision_state, target_state) in zip(provision_states_list,
                                                   target_states_list):
            self.client.set_node_provision_state(node['uuid'], provision_state)
            self._validate_provision_state(node['uuid'], target_state)


class TestNodeStatesV1_2(TestNodeStatesMixin, base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodeStatesV1_2, self).setUp()
        self.useFixture(api_microversion_fixture.APIMicroversionFixture('1.2'))

    @decorators.idempotent_id('9c414984-f3b6-4b3d-81da-93b60d4662fb')
    def test_set_node_provision_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        # Nodes appear in AVAILABLE state by default from v1.2 to v1.10
        self.assertEqual('available', node['provision_state'])
        provision_states_list = ['active', 'deleted']
        target_states_list = ['active', 'available']
        for (provision_state, target_state) in zip(provision_states_list,
                                                   target_states_list):
            self.client.set_node_provision_state(node['uuid'], provision_state)
            self._validate_provision_state(node['uuid'], target_state)


class TestNodeStatesV1_4(TestNodeStatesMixin, base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodeStatesV1_4, self).setUp()
        self.useFixture(api_microversion_fixture.APIMicroversionFixture('1.4'))

    @decorators.idempotent_id('3d606003-05ce-4b5a-964d-bdee382fafe9')
    def test_set_node_provision_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        # Nodes appear in AVAILABLE state by default from v1.2 to v1.10
        self.assertEqual('available', node['provision_state'])
        # MANAGEABLE state and PROVIDE transition have been added in v1.4
        provision_states_list = [
            'manage', 'provide', 'active', 'deleted']
        target_states_list = [
            'manageable', 'available', 'active', 'available']
        for (provision_state, target_state) in zip(provision_states_list,
                                                   target_states_list):
            self.client.set_node_provision_state(node['uuid'], provision_state)
            self._validate_provision_state(node['uuid'], target_state)


class TestNodeStatesV1_6(TestNodeStatesMixin, base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodeStatesV1_6, self).setUp()
        self.useFixture(api_microversion_fixture.APIMicroversionFixture('1.6'))

    @decorators.idempotent_id('6c9ce4a3-713b-4c76-91af-18c48d01f1bb')
    def test_set_node_provision_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        # Nodes appear in AVAILABLE state by default from v1.2 to v1.10
        self.assertEqual('available', node['provision_state'])
        # INSPECT* states have been added in v1.6
        provision_states_list = [
            'manage', 'inspect', 'provide', 'active', 'deleted']
        target_states_list = [
            'manageable', 'manageable', 'available', 'active', 'available']
        for (provision_state, target_state) in zip(provision_states_list,
                                                   target_states_list):
            self.client.set_node_provision_state(node['uuid'], provision_state)
            self._validate_provision_state(node['uuid'], target_state)


class TestNodeStatesV1_11(TestNodeStatesMixin, base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodeStatesV1_11, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture('1.11')
        )

    @decorators.idempotent_id('31f53828-b83d-40c7-98e5-843e28a1b6b9')
    def test_set_node_provision_state(self):
        _, node = self.create_node(self.chassis['uuid'])
        # Nodes appear in ENROLL state by default from v1.11
        self.assertEqual('enroll', node['provision_state'])
        provision_states_list = [
            'manage', 'inspect', 'provide', 'active', 'deleted']
        target_states_list = [
            'manageable', 'manageable', 'available', 'active', 'available']
        for (provision_state, target_state) in zip(provision_states_list,
                                                   target_states_list):
            self.client.set_node_provision_state(node['uuid'], provision_state)
            self._validate_provision_state(node['uuid'], target_state)


class TestNodeStatesV1_12(TestNodeStatesMixin, base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodeStatesV1_12, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture('1.12')
        )

    @decorators.idempotent_id('4427b1ca-8e79-4139-83d6-77dfac03e61e')
    def test_set_node_raid_config(self):
        _, node = self.create_node(self.chassis['uuid'])
        target_raid_config = {'logical_disks': [{'size_gb': 100,
                                                 'raid_level': '1'}]}
        self.client.set_node_raid_config(node['uuid'], target_raid_config)
        _, ret = self.client.show_node(node['uuid'])
        self.assertEqual(target_raid_config, ret['target_raid_config'])
