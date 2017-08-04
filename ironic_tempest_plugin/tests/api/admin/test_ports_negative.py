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


class TestPortsNegative(base.BaseBaremetalTest):
    """Negative tests for ports."""

    def setUp(self):
        super(TestPortsNegative, self).setUp()

        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('0a6ee1f7-d0d9-4069-8778-37f3aa07303a')
    def test_create_port_malformed_mac(self):
        node_id = self.node['uuid']
        address = 'malformed:mac'

        self.assertRaises(lib_exc.BadRequest,
                          self.create_port, node_id=node_id, address=address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('30277ee8-0c60-4f1d-b125-0e51c2f43369')
    def test_create_port_nonexsistent_node_id(self):
        node_id = str(data_utils.rand_uuid())
        address = data_utils.rand_mac_address()
        self.assertRaises(lib_exc.BadRequest, self.create_port,
                          node_id=node_id, address=address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('029190f6-43e1-40a3-b64a-65173ba653a3')
    def test_show_port_malformed_uuid(self):
        self.assertRaises(lib_exc.BadRequest, self.client.show_port,
                          'malformed:uuid')

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('0d00e13d-e2e0-45b1-bcbc-55a6d90ca793')
    def test_show_port_nonexistent_uuid(self):
        self.assertRaises(lib_exc.NotFound, self.client.show_port,
                          data_utils.rand_uuid())

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('4ad85266-31e9-4942-99ac-751897dc9e23')
    def test_show_port_by_mac_not_allowed(self):
        self.assertRaises(lib_exc.BadRequest, self.client.show_port,
                          data_utils.rand_mac_address())

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('89a34380-3c61-4c32-955c-2cd9ce94da21')
    def test_create_port_duplicated_port_uuid(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        uuid = data_utils.rand_uuid()

        self.create_port(node_id=node_id, address=address, uuid=uuid)
        self.assertRaises(lib_exc.Conflict, self.create_port, node_id=node_id,
                          address=address, uuid=uuid)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('65e84917-733c-40ae-ae4b-96a4adff931c')
    def test_create_port_no_mandatory_field_node_id(self):
        address = data_utils.rand_mac_address()

        self.assertRaises(lib_exc.BadRequest, self.create_port, node_id=None,
                          address=address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('bcea3476-7033-4183-acfe-e56a30809b46')
    def test_create_port_no_mandatory_field_mac(self):
        node_id = self.node['uuid']

        self.assertRaises(lib_exc.BadRequest, self.create_port,
                          node_id=node_id, address=None)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('2b51cd18-fb95-458b-9780-e6257787b649')
    def test_create_port_malformed_port_uuid(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        uuid = 'malformed:uuid'

        self.assertRaises(lib_exc.BadRequest, self.create_port,
                          node_id=node_id, address=address, uuid=uuid)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('583a6856-6a30-4ac4-889f-14e2adff8105')
    def test_create_port_malformed_node_id(self):
        address = data_utils.rand_mac_address()
        self.assertRaises(lib_exc.BadRequest, self.create_port,
                          node_id='malformed:nodeid', address=address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('e27f8b2e-42c6-4a43-a3cd-accff716bc5c')
    def test_create_port_duplicated_mac(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        self.create_port(node_id=node_id, address=address)
        self.assertRaises(lib_exc.Conflict,
                          self.create_port, node_id=node_id,
                          address=address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('8907082d-ac5e-4be3-b05f-d072ede82020')
    def test_update_port_by_mac_not_allowed(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key': 'value'}

        self.create_port(node_id=node_id, address=address, extra=extra)

        patch = [{'path': '/extra/key',
                  'op': 'replace',
                  'value': 'new-value'}]

        self.assertRaises(lib_exc.BadRequest,
                          self.client.update_port, address,
                          patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('df1ac70c-db9f-41d9-90f1-78cd6b905718')
    def test_update_port_nonexistent(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key': 'value'}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)
        port_id = port['uuid']

        _, body = self.client.delete_port(port_id)

        patch = [{'path': '/extra/key',
                  'op': 'replace',
                  'value': 'new-value'}]
        self.assertRaises(lib_exc.NotFound,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('c701e315-aa52-41ea-817c-65c5ca8ca2a8')
    def test_update_port_malformed_port_uuid(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        self.create_port(node_id=node_id, address=address)

        new_address = data_utils.rand_mac_address()
        self.assertRaises(lib_exc.BadRequest, self.client.update_port,
                          uuid='malformed:uuid',
                          patch=[{'path': '/address', 'op': 'replace',
                                  'value': new_address}])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('f8f15803-34d6-45dc-b06f-e5e04bf1b38b')
    def test_update_port_add_nonexistent_property(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        self.assertRaises(lib_exc.BadRequest, self.client.update_port, port_id,
                          [{'path': '/nonexistent', ' op': 'add',
                            'value': 'value'}])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('898ec904-38b1-4fcb-9584-1187d4263a2a')
    def test_update_port_replace_node_id_with_malformed(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        patch = [{'path': '/node_uuid',
                  'op': 'replace',
                  'value': 'malformed:node_uuid'}]
        self.assertRaises(lib_exc.BadRequest,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('2949f30f-5f59-43fa-a6d9-4eac578afab4')
    def test_update_port_replace_mac_with_duplicated(self):
        node_id = self.node['uuid']
        address1 = data_utils.rand_mac_address()
        address2 = data_utils.rand_mac_address()

        _, port1 = self.create_port(node_id=node_id, address=address1)

        _, port2 = self.create_port(node_id=node_id, address=address2)
        port_id = port2['uuid']

        patch = [{'path': '/address',
                  'op': 'replace',
                  'value': address1}]
        self.assertRaises(lib_exc.Conflict,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('97f6e048-6e4f-4eba-a09d-fbbc78b77a77')
    def test_update_port_replace_node_id_with_nonexistent(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        patch = [{'path': '/node_uuid',
                  'op': 'replace',
                  'value': data_utils.rand_uuid()}]
        self.assertRaises(lib_exc.BadRequest,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('375022c5-9e9e-4b11-9ca4-656729c0c9b2')
    def test_update_port_replace_mac_with_malformed(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        patch = [{'path': '/address',
                  'op': 'replace',
                  'value': 'malformed:mac'}]

        self.assertRaises(lib_exc.BadRequest,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('5722b853-03fc-4854-8308-2036a1b67d85')
    def test_update_port_replace_nonexistent_property(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        patch = [{'path': '/nonexistent', ' op': 'replace', 'value': 'value'}]

        self.assertRaises(lib_exc.BadRequest,
                          self.client.update_port, port_id, patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('ae2696ca-930a-4a7f-918f-30ae97c60f56')
    def test_update_port_remove_mandatory_field_mac(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        self.assertRaises(lib_exc.BadRequest, self.client.update_port, port_id,
                          [{'path': '/address', 'op': 'remove'}])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('5392c1f0-2071-4697-9064-ec2d63019018')
    def test_update_port_remove_mandatory_field_port_uuid(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        self.assertRaises(lib_exc.BadRequest, self.client.update_port, port_id,
                          [{'path': '/uuid', 'op': 'remove'}])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('06b50d82-802a-47ef-b079-0a3311cf85a2')
    def test_update_port_remove_nonexistent_property(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, port = self.create_port(node_id=node_id, address=address)
        port_id = port['uuid']

        self.assertRaises(lib_exc.BadRequest, self.client.update_port, port_id,
                          [{'path': '/nonexistent', 'op': 'remove'}])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('03d42391-2145-4a6c-95bf-63fe55eb64fd')
    def test_delete_port_by_mac_not_allowed(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        self.create_port(node_id=node_id, address=address)
        self.assertRaises(lib_exc.BadRequest, self.client.delete_port, address)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('0629e002-818e-4763-b25b-ae5e07b1cb23')
    def test_update_port_mixed_ops_integrity(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()
        extra = {'key1': 'value1', 'key2': 'value2'}

        _, port = self.create_port(node_id=node_id, address=address,
                                   extra=extra)
        port_id = port['uuid']

        new_address = data_utils.rand_mac_address()
        new_extra = {'key1': 'new-value1', 'key3': 'new-value3'}

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
                  'value': new_extra['key3']},
                 {'path': '/nonexistent',
                  'op': 'replace',
                  'value': 'value'}]

        self.assertRaises(lib_exc.BadRequest, self.client.update_port, port_id,
                          patch)

        # patch should not be applied
        _, body = self.client.show_port(port_id)
        self.assertEqual(address, body['address'])
        self.assertEqual(extra, body['extra'])


class TestPortsWithPhysicalNetworkOldAPI(base.BaseBaremetalTest):
    """Negative tests for ports with physical network information."""

    def setUp(self):
        super(TestPortsWithPhysicalNetworkOldAPI, self).setUp()
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('307e57e9-082f-4830-9480-91affcbfda08')
    def test_create_port_with_physical_network_old_api(self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        self.assertRaises((lib_exc.BadRequest, lib_exc.UnexpectedResponseCode),
                          self.create_port,
                          node_id=node_id, address=address,
                          physical_network='physnet1')

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('0b278c0a-d334-424e-a5c5-b6d001c2a715')
    def test_update_port_replace_physical_network_old_api(self):
        _, port = self.create_port(self.node['uuid'],
                                   data_utils.rand_mac_address())

        new_physnet = 'physnet1'

        patch = [{'path': '/physical_network',
                  'op': 'replace',
                  'value': new_physnet}]

        self.assertRaises((lib_exc.BadRequest, lib_exc.UnexpectedResponseCode),
                          self.client.update_port,
                          port['uuid'], patch)


class TestPortsNegativeWithPhysicalNetwork(base.BaseBaremetalTest):
    """Negative tests for ports with physical network information."""

    min_microversion = '1.34'

    def setUp(self):
        super(TestPortsNegativeWithPhysicalNetwork, self).setUp()

        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                TestPortsNegativeWithPhysicalNetwork.min_microversion)
        )
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('e20156fb-956b-4d5b-89a4-f379044a1d3c')
    def test_create_ports_in_portgroup_with_inconsistent_physical_network(
            self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, portgroup = self.create_portgroup(node_id, address=address)

        _, _ = self.create_port(node_id=node_id, address=address,
                                portgroup_uuid=portgroup['uuid'],
                                physical_network='physnet1')

        address = data_utils.rand_mac_address()
        self.assertRaises(lib_exc.Conflict,
                          self.create_port,
                          node_id=node_id, address=address,
                          portgroup_uuid=portgroup['uuid'],
                          physical_network='physnet2')

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('050e792c-22c9-4e4a-ae89-dfbfc52ad00d')
    def test_update_ports_in_portgroup_with_inconsistent_physical_network(
            self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, portgroup = self.create_portgroup(node_id, address=address)

        _, _ = self.create_port(node_id=node_id, address=address,
                                portgroup_uuid=portgroup['uuid'],
                                physical_network='physnet1')

        address = data_utils.rand_mac_address()
        _, port2 = self.create_port(node_id=node_id, address=address,
                                    physical_network='physnet2')

        patch = [{'path': '/portgroup_uuid',
                  'op': 'replace',
                  'value': portgroup['uuid']}]

        self.assertRaises(lib_exc.Conflict,
                          self.client.update_port,
                          port2['uuid'], patch)

    @decorators.attr(type=['negative'])
    @decorators.idempotent_id('3cd1c8ec-57d1-40cb-922b-dd02431beea3')
    def test_update_ports_in_portgroup_with_inconsistent_physical_network_2(
            self):
        node_id = self.node['uuid']
        address = data_utils.rand_mac_address()

        _, portgroup = self.create_portgroup(node_id, address=address)

        _, _ = self.create_port(node_id=node_id, address=address,
                                portgroup_uuid=portgroup['uuid'],
                                physical_network='physnet1')

        address = data_utils.rand_mac_address()
        _, port2 = self.create_port(node_id=node_id, address=address,
                                    portgroup_uuid=portgroup['uuid'],
                                    physical_network='physnet1')

        patch = [{'path': '/physical_network',
                  'op': 'replace',
                  'value': 'physnet2'}]

        self.assertRaises(lib_exc.Conflict,
                          self.client.update_port,
                          port2['uuid'], patch)
