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

import six

from tempest import config
from tempest.lib.common.utils import data_utils
from tempest.lib import decorators
from tempest.lib import exceptions as lib_exc

from ironic_tempest_plugin.common import waiters
from ironic_tempest_plugin.tests.api.admin import api_microversion_fixture
from ironic_tempest_plugin.tests.api.admin import base

CONF = config.CONF


class TestNodes(base.BaseBaremetalTest):
    """Tests for baremetal nodes."""

    def setUp(self):
        super(TestNodes, self).setUp()

        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    def _associate_node_with_instance(self):
        self.client.set_node_power_state(self.node['uuid'], 'power off')
        waiters.wait_for_bm_node_status(self.client, self.node['uuid'],
                                        'power_state', 'power off')
        instance_uuid = data_utils.rand_uuid()
        self.client.update_node(self.node['uuid'],
                                instance_uuid=instance_uuid)
        self.addCleanup(self.client.update_node,
                        uuid=self.node['uuid'], instance_uuid=None)
        return instance_uuid

    @decorators.idempotent_id('4e939eb2-8a69-4e84-8652-6fffcbc9db8f')
    def test_create_node(self):
        params = {'cpu_arch': 'x86_64',
                  'cpus': '12',
                  'local_gb': '10',
                  'memory_mb': '1024'}

        _, body = self.create_node(self.chassis['uuid'], **params)
        self._assertExpected(params, body['properties'])

    @decorators.idempotent_id('9ade60a4-505e-4259-9ec4-71352cbbaf47')
    def test_delete_node(self):
        _, node = self.create_node(self.chassis['uuid'])

        self.delete_node(node['uuid'])

        self.assertRaises(lib_exc.NotFound, self.client.show_node,
                          node['uuid'])

    @decorators.idempotent_id('55451300-057c-4ecf-8255-ba42a83d3a03')
    def test_show_node(self):
        _, loaded_node = self.client.show_node(self.node['uuid'])
        self._assertExpected(self.node, loaded_node)

    @decorators.idempotent_id('4ca123c4-160d-4d8d-a3f7-15feda812263')
    def test_list_nodes(self):
        _, body = self.client.list_nodes()
        self.assertIn(self.node['uuid'],
                      [i['uuid'] for i in body['nodes']])

    @decorators.idempotent_id('85b1f6e0-57fd-424c-aeff-c3422920556f')
    def test_list_nodes_association(self):
        _, body = self.client.list_nodes(associated=True)
        self.assertNotIn(self.node['uuid'],
                         [n['uuid'] for n in body['nodes']])

        self._associate_node_with_instance()

        _, body = self.client.list_nodes(associated=True)
        self.assertIn(self.node['uuid'], [n['uuid'] for n in body['nodes']])

        _, body = self.client.list_nodes(associated=False)
        self.assertNotIn(self.node['uuid'], [n['uuid'] for n in body['nodes']])

    @decorators.idempotent_id('18c4ebd8-f83a-4df7-9653-9fb33a329730')
    def test_node_port_list(self):
        _, port = self.create_port(self.node['uuid'],
                                   data_utils.rand_mac_address())
        _, body = self.client.list_node_ports(self.node['uuid'])
        self.assertIn(port['uuid'],
                      [p['uuid'] for p in body['ports']])

    @decorators.idempotent_id('72591acb-f215-49db-8395-710d14eb86ab')
    def test_node_port_list_no_ports(self):
        _, node = self.create_node(self.chassis['uuid'])
        _, body = self.client.list_node_ports(node['uuid'])
        self.assertEmpty(body['ports'])

    @decorators.idempotent_id('4fed270a-677a-4d19-be87-fd38ae490320')
    def test_update_node(self):
        props = {'cpu_arch': 'x86_64',
                 'cpus': '12',
                 'local_gb': '10',
                 'memory_mb': '128'}

        _, node = self.create_node(self.chassis['uuid'], **props)

        new_p = {'cpu_arch': 'x86',
                 'cpus': '1',
                 'local_gb': '10000',
                 'memory_mb': '12300'}

        _, body = self.client.update_node(node['uuid'], properties=new_p)
        _, node = self.client.show_node(node['uuid'])
        self._assertExpected(new_p, node['properties'])

    @decorators.idempotent_id('cbf1f515-5f4b-4e49-945c-86bcaccfeb1d')
    def test_validate_driver_interface(self):
        _, body = self.client.validate_driver_interface(self.node['uuid'])
        core_interfaces = ['power', 'deploy']
        for interface in core_interfaces:
            self.assertIn(interface, body)

    @decorators.idempotent_id('5519371c-26a2-46e9-aa1a-f74226e9d71f')
    def test_set_node_boot_device(self):
        self.client.set_node_boot_device(self.node['uuid'], 'pxe')

    @decorators.idempotent_id('9ea73775-f578-40b9-bc34-efc639c4f21f')
    def test_get_node_boot_device(self):
        body = self.client.get_node_boot_device(self.node['uuid'])
        self.assertIn('boot_device', body)
        self.assertIn('persistent', body)
        self.assertIsInstance(body['boot_device'], six.string_types)
        self.assertIsInstance(body['persistent'], bool)

    @decorators.idempotent_id('3622bc6f-3589-4bc2-89f3-50419c66b133')
    def test_get_node_supported_boot_devices(self):
        body = self.client.get_node_supported_boot_devices(self.node['uuid'])
        self.assertIn('supported_boot_devices', body)
        self.assertIsInstance(body['supported_boot_devices'], list)

    @decorators.idempotent_id('f63b6288-1137-4426-8cfe-0d5b7eb87c06')
    def test_get_console(self):
        _, body = self.client.get_console(self.node['uuid'])
        con_info = ['console_enabled', 'console_info']
        for key in con_info:
            self.assertIn(key, body)

    @decorators.idempotent_id('80504575-9b21-4670-92d1-143b948f9437')
    def test_set_console_mode(self):
        self.client.set_console_mode(self.node['uuid'], True)
        waiters.wait_for_bm_node_status(self.client, self.node['uuid'],
                                        'console_enabled', True)

    @decorators.idempotent_id('b02a4f38-5e8b-44b2-aed2-a69a36ecfd69')
    def test_get_node_by_instance_uuid(self):
        instance_uuid = self._associate_node_with_instance()
        _, body = self.client.show_node_by_instance_uuid(instance_uuid)
        self.assertEqual(1, len(body['nodes']))
        self.assertIn(self.node['uuid'], [n['uuid'] for n in body['nodes']])


class TestNodesResourceClass(base.BaseBaremetalTest):

    min_microversion = '1.21'

    def setUp(self):
        super(TestNodesResourceClass, self).setUp()
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture(
                TestNodesResourceClass.min_microversion)
        )
        _, self.chassis = self.create_chassis()
        self.resource_class = data_utils.rand_name(name='Resource_Class')
        _, self.node = self.create_node(
            self.chassis['uuid'], resource_class=self.resource_class)

    @decorators.idempotent_id('2a00340c-8152-4a61-9fc5-0b3cdefec258')
    def test_create_node_resource_class_long(self):
        """Create new node with specified longest name of resource class."""
        res_class_long_name = data_utils.arbitrary_string(80)
        _, body = self.create_node(
            self.chassis['uuid'],
            resource_class=res_class_long_name)
        self.assertEqual(res_class_long_name, body['resource_class'])

    @decorators.idempotent_id('142db00d-ac0f-415b-8da8-9095fbb561f7')
    def test_update_node_resource_class(self):
        """Update existing node with specified resource class."""
        new_res_class_name = data_utils.rand_name(name='Resource_Class')
        _, body = self.client.update_node(
            self.node['uuid'], resource_class=new_res_class_name)
        _, body = self.client.show_node(self.node['uuid'])
        self.assertEqual(new_res_class_name, body['resource_class'])

    @decorators.idempotent_id('73e6f7b5-3e51-49ea-af5b-146cd49f40ee')
    def test_show_node_resource_class(self):
        """Show resource class field of specified node."""
        _, body = self.client.show_node(self.node['uuid'])
        self.assertEqual(self.resource_class, body['resource_class'])

    @decorators.idempotent_id('f2bf4465-280c-4fdc-bbf7-fcf5188befa4')
    def test_list_nodes_resource_class(self):
        """List nodes of specified resource class only."""
        res_class = 'ResClass-{0}'.format(data_utils.rand_uuid())
        for node in range(3):
            _, body = self.create_node(
                self.chassis['uuid'], resource_class=res_class)

        _, body = self.client.list_nodes(resource_class=res_class)
        self.assertEqual(3, len([i['uuid'] for i in body['nodes']]))

    @decorators.idempotent_id('40733bad-bb79-445e-a094-530a44042995')
    def test_list_nodes_detail_resource_class(self):
        """Get detailed nodes list of specified resource class only."""
        res_class = 'ResClass-{0}'.format(data_utils.rand_uuid())
        for node in range(3):
            _, body = self.create_node(
                self.chassis['uuid'], resource_class=res_class)

        _, body = self.client.list_nodes_detail(resource_class=res_class)
        self.assertEqual(3, len([i['uuid'] for i in body['nodes']]))

        for node in body['nodes']:
            self.assertEqual(res_class, node['resource_class'])

    @decorators.attr(type='negative')
    @decorators.idempotent_id('e75136d4-0690-48a5-aef3-75040aee73ad')
    def test_create_node_resource_class_too_long(self):
        """Try to create a node with too long resource class name."""
        resource_class = data_utils.arbitrary_string(81)
        self.assertRaises(lib_exc.BadRequest, self.create_node,
                          self.chassis['uuid'], resource_class=resource_class)

    @decorators.attr(type='negative')
    @decorators.idempotent_id('f0aeece4-8671-44ea-a482-b4047fc4cf74')
    def test_update_node_resource_class_too_long(self):
        """Try to update a node with too long resource class name."""
        resource_class = data_utils.arbitrary_string(81)
        self.assertRaises(lib_exc.BadRequest, self.client.update_node,
                          self.node['uuid'], resource_class=resource_class)


class TestNodesResourceClassOldApi(base.BaseBaremetalTest):

    def setUp(self):
        super(TestNodesResourceClassOldApi, self).setUp()
        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.attr(type='negative')
    @decorators.idempotent_id('2c364408-4746-4b3c-9821-20d47b57bdec')
    def test_create_node_resource_class_old_api(self):
        """Try to create a node with resource class using older api version."""
        resource_class = data_utils.arbitrary_string()
        self.assertRaises(lib_exc.UnexpectedResponseCode, self.create_node,
                          self.chassis['uuid'], resource_class=resource_class)

    @decorators.attr(type='negative')
    @decorators.idempotent_id('666f3c1a-4922-4a3d-b6d9-dea7c74d30bc')
    def test_update_node_resource_class_old_api(self):
        """Try to update a node with resource class using older api version."""
        resource_class = data_utils.arbitrary_string()
        self.assertRaises(lib_exc.UnexpectedResponseCode,
                          self.client.update_node,
                          self.node['uuid'], resource_class=resource_class)

    @decorators.attr(type='negative')
    @decorators.idempotent_id('95903480-f16d-4774-8775-6c7f87b27c59')
    def test_list_nodes_by_resource_class_old_api(self):
        """Try to list nodes with resource class using older api version."""
        resource_class = data_utils.arbitrary_string()
        self.assertRaises(
            lib_exc.UnexpectedResponseCode,
            self.client.list_nodes, resource_class=resource_class)
        self.assertRaises(
            lib_exc.UnexpectedResponseCode,
            self.client.list_nodes_detail, resource_class=resource_class)


class TestNodesVif(base.BaseBaremetalTest):

    min_microversion = '1.28'

    @classmethod
    def skip_checks(cls):
        super(TestNodesVif, cls).skip_checks()
        if not CONF.service_available.neutron:
            raise cls.skipException('Neutron is not enabled.')

    def setUp(self):
        super(TestNodesVif, self).setUp()

        _, self.chassis = self.create_chassis()
        _, self.node = self.create_node(self.chassis['uuid'])

    @decorators.idempotent_id('a3d319d0-cacb-4e55-a3dc-3fa8b74880f1')
    def test_vif_on_port(self):
        """Test attachment and detachment of VIFs on the node with port.

        Test steps:
        1) Create chassis and node in setUp.
        2) Create port for the node.
        3) Attach VIF to the node.
        4) Check VIF info in VIFs list and port internal_info.
        5) Detach VIF from the node.
        6) Check that no more VIF info in VIFs list and port internal_info.
        """
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture('1.28'))
        _, self.port = self.create_port(self.node['uuid'],
                                        data_utils.rand_mac_address())
        self.client.vif_attach(self.node['uuid'], 'test-vif')
        _, body = self.client.vif_list(self.node['uuid'])
        self.assertEqual({'vifs': [{'id': 'test-vif'}]}, body)
        _, port = self.client.show_port(self.port['uuid'])
        self.assertEqual('test-vif',
                         port['internal_info']['tenant_vif_port_id'])
        self.client.vif_detach(self.node['uuid'], 'test-vif')
        _, body = self.client.vif_list(self.node['uuid'])
        self.assertEqual({'vifs': []}, body)
        _, port = self.client.show_port(self.port['uuid'])
        self.assertNotIn('tenant_vif_port_id', port['internal_info'])

    @decorators.idempotent_id('95279515-7d0a-4f5f-987f-93e36aae5585')
    def test_vif_on_portgroup(self):
        """Test attachment and detachment of VIFs on the node with port group.

        Test steps:
        1) Create chassis and node in setUp.
        2) Create port for the node.
        3) Create port group for the node.
        4) Plug port into port group.
        5) Attach VIF to the node.
        6) Check VIF info in VIFs list and port group internal_info, but
           not in port internal_info.
        7) Detach VIF from the node.
        8) Check that no VIF info in VIFs list and port group internal_info.
        """
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture('1.28'))
        _, self.port = self.create_port(self.node['uuid'],
                                        data_utils.rand_mac_address())
        _, self.portgroup = self.create_portgroup(
            self.node['uuid'], address=data_utils.rand_mac_address())

        patch = [{'path': '/portgroup_uuid',
                  'op': 'add',
                  'value': self.portgroup['uuid']}]
        self.client.update_port(self.port['uuid'], patch)

        self.client.vif_attach(self.node['uuid'], 'test-vif')
        _, body = self.client.vif_list(self.node['uuid'])
        self.assertEqual({'vifs': [{'id': 'test-vif'}]}, body)

        _, port = self.client.show_port(self.port['uuid'])
        self.assertNotIn('tenant_vif_port_id', port['internal_info'])
        _, portgroup = self.client.show_portgroup(self.portgroup['uuid'])
        self.assertEqual('test-vif',
                         portgroup['internal_info']['tenant_vif_port_id'])

        self.client.vif_detach(self.node['uuid'], 'test-vif')
        _, body = self.client.vif_list(self.node['uuid'])
        self.assertEqual({'vifs': []}, body)
        _, portgroup = self.client.show_portgroup(self.portgroup['uuid'])
        self.assertNotIn('tenant_vif_port_id', portgroup['internal_info'])

    @decorators.idempotent_id('a3d319d0-cacb-4e55-a3dc-3fa8b74880f2')
    def test_vif_already_set_on_extra(self):
        self.useFixture(
            api_microversion_fixture.APIMicroversionFixture('1.28'))
        _, self.port = self.create_port(self.node['uuid'],
                                        data_utils.rand_mac_address())
        patch = [{'path': '/extra/vif_port_id',
                  'op': 'add',
                  'value': 'test-vif'}]
        self.client.update_port(self.port['uuid'], patch)

        _, body = self.client.vif_list(self.node['uuid'])
        self.assertEqual({'vifs': [{'id': 'test-vif'}]}, body)

        self.assertRaises(lib_exc.Conflict, self.client.vif_attach,
                          self.node['uuid'], 'test-vif')

        self.client.vif_detach(self.node['uuid'], 'test-vif')
