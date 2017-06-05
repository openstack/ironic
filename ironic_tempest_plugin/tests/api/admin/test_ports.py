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


class TestPorts(base.BaseBaremetalTest):
    """Tests for ports."""

    def setUp(self):
        super(TestPorts, self).setUp()

        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])
        _, self.port = self.create_port(self.node['uuid'],
                                        data_utils.rand_mac_address())

    @decorators.idempotent_id('83975898-2e50-42ed-b5f0-e510e36a0b56')
    def test_create_port(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)

        _, body = self.client.show_port(port['uuid'])

        self._assertExpected(port, body)

    @decorators.idempotent_id('d1f6b249-4cf6-4fe6-9ed6-a6e84b1bf67b')
    def test_create_port_specifying_uuid(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        uuid = data_utils.rand_uuid()

        _, port = self.create_port(node_id=node_id,
                                   address=address, uuid=uuid)

        _, body = self.client.show_port(uuid)
        self._assertExpected(port, body)

    @decorators.idempotent_id('4a02c4b0-6573-42a4-a513-2e36ad485b62')
    def test_create_port_with_extra(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'str': 'value', 'int': 123, 'float': 0.123,
                 'bool': True, 'list': [1, 2, 3], 'dict': {'foo': 'bar'}}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)

        _, body = self.client.show_port(port['uuid'])
        self._assertExpected(port, body)

    @decorators.idempotent_id('1bf257a9-aea3-494e-89c0-63f657ab4fdd')
    def test_delete_port(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        _, port = self.create_port(node_id=node_id, address=address)

        self.delete_port(port['uuid'])

        self.assertRaises(lib_exc.NotFound, self.client.show_port,
                          port['uuid'])

    @decorators.idempotent_id('9fa77ab5-ce59-4f05-baac-148904ba1597')
    def test_show_port(self):
        _, port = self.client.show_port(self.port['uuid'])
        self._assertExpected(self.port, port)

    @decorators.idempotent_id('7c1114ff-fc3f-47bb-bc2f-68f61620ba8b')
    def test_show_port_by_address(self):
        _, port = self.client.show_port_by_address(self.port['address'])
        self._assertExpected(self.port, port['ports'][0])

    @decorators.idempotent_id('bd773405-aea5-465d-b576-0ab1780069e5')
    def test_show_port_with_links(self):
        _, port = self.client.show_port(self.port['uuid'])
        self.assertIn('links', port.keys())
        self.assertEqual(2, len(port['links']))
        self.assertIn(port['uuid'], port['links'][0]['href'])

    @decorators.idempotent_id('b5e91854-5cd7-4a8e-bb35-3e0a1314606d')
    def test_list_ports(self):
        _, body = self.client.list_ports()
        self.assertIn(self.port['uuid'],
                      [i['uuid'] for i in body['ports']])
        # Verify self links.
        for port in body['ports']:
            self.validate_self_link('ports', port['uuid'],
                                    port['links'][0]['href'])

    @decorators.idempotent_id('324a910e-2f80-4258-9087-062b5ae06240')
    def test_list_with_limit(self):
        _, body = self.client.list_ports(limit=3)

        next_marker = body['ports'][-1]['uuid']
        self.assertIn(next_marker, body['next'])

    @decorators.idempotent_id('8a94b50f-9895-4a63-a574-7ecff86e5875')
    def test_list_ports_details(self):
        node_id = self.node['uuid']

        uuids = [
            self.create_port(node_id=node_id,
                             address=data_utils.rand_mac_address())
            [1]['uuid'] for i in range(0, 5)]

        _, body = self.client.list_ports_detail()

        ports_dict = dict((port['uuid'], port) for port in body['ports']
                          if port['uuid'] in uuids)

        for uuid in uuids:
            self.assertIn(uuid, ports_dict)
            port = ports_dict[uuid]
            self.assertIn('extra', port)
            self.assertIn('node_uuid', port)
            # never expose the node_id
            self.assertNotIn('node_id', port)
            # Verify self link.
            self.validate_self_link('ports', port['uuid'],
                                    port['links'][0]['href'])

    @decorators.idempotent_id('8a03f688-7d75-4ecd-8cbc-e06b8f346738')
    def test_list_ports_details_with_address(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        self.create_port(node_id=node_id, address=address)
        for i in range(0, 5):
            self.create_port(node_id=node_id,
                             address=data_utils.rand_mac_address())

        _, body = self.client.list_ports_detail(address=address)
        self.assertEqual(1, len(body['ports']))
        self.assertEqual(address, body['ports'][0]['address'])

    @decorators.idempotent_id('9c26298b-1bcb-47b7-9b9e-8bdd6e3c4aba')
    def test_update_port_replace(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)

        new_address = data_utils.rand_mac_address()
        new_extra = {'key1': 'new-value1', 'key2': 'new-value2',
                     'key3': 'new-value3'}

        patch = [{'path': '/address',
                  'op': 'replace',
                  'value': new_address},
                 {'path': '/extra/key1',
                  'op': 'replace',
                  'value': new_extra['key1']},
                 {'path': '/extra/key2',
                  'op': 'replace',
                  'value': new_extra['key2']},
                 {'path': '/extra/key3',
                  'op': 'replace',
                  'value': new_extra['key3']}]

        self.client.update_port(port['uuid'], patch)

        _, body = self.client.show_port(port['uuid'])
        self.assertEqual(new_address, body['address'])
        self.assertEqual(new_extra, body['extra'])

    @decorators.idempotent_id('d7e7fece-6ed9-460a-9ebe-9267217e8580')
    def test_update_port_remove(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key1': 'value1', 'key2': 'value2', 'key3': 'value3'}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)

        # Removing one item from the collection
        self.client.update_port(port['uuid'],
                                [{'path': '/extra/key2',
                                 'op': 'remove'}])
        extra.pop('key2')
        _, body = self.client.show_port(port['uuid'])
        self.assertEqual(extra, body['extra'])

        # Removing the collection
        self.client.update_port(port['uuid'], [{'path': '/extra',
                                               'op': 'remove'}])
        _, body = self.client.show_port(port['uuid'])
        self.assertEqual({}, body['extra'])

        # Assert nothing else was changed
        self.assertEqual(node_id, body['node_uuid'])
        self.assertEqual(address, body['address'])

    @decorators.idempotent_id('241288b3-e98a-400f-a4d7-d1f716146361')
    def test_update_port_add(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)

        extra = {'key1': 'value1', 'key2': 'value2'}

        patch = [{'path': '/extra/key1',
                  'op': 'add',
                  'value': extra['key1']},
                 {'path': '/extra/key2',
                  'op': 'add',
                  'value': extra['key2']}]

        self.client.update_port(port['uuid'], patch)

        _, body = self.client.show_port(port['uuid'])
        self.assertEqual(extra, body['extra'])

    @decorators.idempotent_id('5309e897-0799-4649-a982-0179b04c3876')
    def test_update_port_mixed_ops(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key1': 'value1', 'key2': 'value2'}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)

        new_address = data_utils.rand_mac_address()
        new_extra = {'key1': 0.123, 'key3': {'cat': 'meow'}}

        patch = [{'path': '/address',
                  'op': 'replace',
                  'value': new_address},
                 {'path': '/extra/key1',
                  'op': 'replace',
                  'value': new_extra['key1']},
                 {'path': '/extra/key2',
                  'op': 'remove'},
                 {'path': '/extra/key3',
                  'op': 'add',
                  'value': new_extra['key3']}]

        self.client.update_port(port['uuid'], patch)

        _, body = self.client.show_port(port['uuid'])
        self.assertEqual(new_address, body['address'])
        self.assertEqual(new_extra, body['extra'])


class TestPortsWithPhysicalNetwork(base.BaseBaremetalTest):
    """Tests for ports with physical network information."""

    min_microversion = '1.34'

    def setUp(self):
        super(TestPortsWithPhysicalNetwork, self).setUp()

        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                TestPortsWithPhysicalNetwork.min_microversion)
        )
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.idempotent_id('f1a5d279-c456-4311-ad31-fea09f61c22b')
    def test_create_port_with_physical_network(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address,
                                   physical_network='physnet1')

        _, body = self.client.show_port(port['uuid'])

        self._assertExpected(port, body)
        self.assertEqual('physnet1', port['physical_network'])

    @decorators.idempotent_id('9c26298b-1bcb-47b7-9b9e-8bdd6e3c4aba')
    def test_update_port_replace_physical_network(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address,
                                   physical_network='physnet1')

        new_physnet = 'physnet2'

        patch = [{'path': '/physical_network',
                  'op': 'replace',
                  'value': new_physnet}]

        self.client.update_port(port['uuid'], patch)

        _, body = self.client.show_port(port['uuid'])
        self.assertEqual(new_physnet, body['physical_network'])

    @decorators.idempotent_id('6503309c-b2c7-4f59-b15a-0d92b5de9210')
    def test_update_port_remove_physical_network(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address,
                                   physical_network='physnet1')

        patch = [{'path': '/physical_network',
                  'op': 'remove'}]

        self.client.update_port(port['uuid'], patch)

        _, body = self.client.show_port(port['uuid'])
        self.assertIsNone(body['physical_network'])

    @decorators.idempotent_id('4155c24d-8474-4b53-a320-aee475f85a68')
    def test_create_ports_in_portgroup_with_physical_network(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, portgroup = self.create_portgroup(node_id, address=address)

        _, port1 = self.create_port(node_id=node_id, address=address,
                                    portgroup_uuid=portgroup['uuid'],
                                    physical_network='physnet1')

        address = data_utils.rand_mac_address()
        _, port2 = self.create_port(node_id=node_id, address=address,
                                    portgroup_uuid=portgroup['uuid'],
                                    physical_network='physnet1')

        _, body = self.client.show_port(port1['uuid'])
        self.assertEqual('physnet1', body['physical_network'])
        self.assertEqual(portgroup['uuid'], body['portgroup_uuid'])

        _, body = self.client.show_port(port2['uuid'])
        self.assertEqual('physnet1', body['physical_network'])
        self.assertEqual(portgroup['uuid'], body['portgroup_uuid'])

    @decorators.idempotent_id('cf05a3ef-3bc4-4db7-bb4c-4eb871eb9f81')
    def test_update_ports_in_portgroup_with_physical_network(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, portgroup = self.create_portgroup(node_id, address=address)

        _, port1 = self.create_port(node_id=node_id, address=address,
                                    portgroup_uuid=portgroup['uuid'],
                                    physical_network='physnet1')

        address = data_utils.rand_mac_address()
        _, port2 = self.create_port(node_id=node_id, address=address,
                                    physical_network='physnet1')

        patch = [{'path': '/portgroup_uuid',
                  'op': 'replace',
                  'value': portgroup['uuid']}]

        self.client.update_port(port2['uuid'], patch)

        _, body = self.client.show_port(port1['uuid'])
        self.assertEqual('physnet1', body['physical_network'])
        self.assertEqual(portgroup['uuid'], body['portgroup_uuid'])

        _, body = self.client.show_port(port2['uuid'])
        self.assertEqual('physnet1', body['physical_network'])
        self.assertEqual(portgroup['uuid'], body['portgroup_uuid'])
