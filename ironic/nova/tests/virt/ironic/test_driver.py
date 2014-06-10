# coding=utf-8
#
# Copyright 2014 Red Hat, Inc.
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for the ironic driver."""

from ironicclient import client as ironic_client
from ironicclient import exc as ironic_exception
import mock
from oslo.config import cfg

from ironic.nova.virt.ironic import client_wrapper as cw
from ironic.nova.tests.virt.ironic import utils as ironic_utils
from ironic.nova.virt.ironic import driver as ironic_driver
from ironic.nova.virt.ironic import ironic_states

from nova.compute import power_state as nova_states
from nova import context as nova_context
from nova import exception
from nova.objects.flavor import Flavor as flavor_obj
from nova.objects import instance as instance_obj
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
from nova.tests import utils
from nova.virt import fake
from nova.virt import firewall


CONF = cfg.CONF

IRONIC_FLAGS = dict(
    instance_type_extra_specs=['test_spec:test_value'],
    api_version=1,
    group='ironic',
)

FAKE_CLIENT = ironic_utils.FakeClient()


class IronicDriverTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicDriverTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)
        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()

        # mock retries configs to avoid sleeps and make tests run quicker
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

    def test_validate_driver_loading(self):
        self.assertIsInstance(self.driver, ironic_driver.IronicDriver)

    def test_get_hypervisor_type(self):
        self.assertEqual(self.driver.get_hypervisor_type(), 'ironic')

    def test_get_hypervisor_version(self):
        self.assertEqual(self.driver.get_hypervisor_version(), 1)

    @mock.patch.object(ironic_client, 'get_client')
    @mock.patch.object(nova_context, 'get_admin_context')
    def test__get_client_no_auth_token(self, mock_ctx, mock_ir_cli):
        self.flags(admin_auth_token=None, group='ironic')
        mock_ctx.return_value = self.ctx
        icli = cw.IronicClientWrapper()
        # dummy call to have _get_client() called
        icli.call("node.list")
        expected = {'os_username': CONF.ironic.admin_username,
                    'os_password': CONF.ironic.admin_password,
                    'os_auth_url': CONF.ironic.admin_url,
                    'os_tenant_name': CONF.ironic.admin_tenant_name,
                    'os_service_type': 'baremetal',
                    'os_endpoint_type': 'public'}
        mock_ir_cli.assert_called_once_with(CONF.ironic.api_version,
                                            **expected)

    @mock.patch.object(ironic_client, 'get_client')
    @mock.patch.object(nova_context, 'get_admin_context')
    def test__get_client_with_auth_token(self, mock_ctx, mock_ir_cli):
        self.flags(admin_auth_token='fake-token', group='ironic')
        mock_ctx.return_value = self.ctx
        icli = cw.IronicClientWrapper()
        # dummy call to have _get_client() called
        icli.call("node.list")
        expected = {'os_auth_token': 'fake-token',
                    'ironic_url': CONF.ironic.api_endpoint}
        mock_ir_cli.assert_called_once_with(CONF.ironic.api_version,
                                            **expected)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_validate_instance_and_node(self, mock_gbiui, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        instance_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        icli = cw.IronicClientWrapper()

        mock_gbiui.return_value = node
        mock_cli.return_value = FAKE_CLIENT
        result = ironic_driver.validate_instance_and_node(icli, instance)
        self.assertEqual(result.uuid, node_uuid)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_validate_instance_and_node_failed(self, mock_gbiui, mock_cli):
        icli = cw.IronicClientWrapper()
        mock_gbiui.side_effect = ironic_exception.NotFound()
        instance_uuid = uuidutils.generate_uuid(),
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.InstanceNotFound,
                          ironic_driver.validate_instance_and_node,
                          icli, instance)

    def test__node_resource(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        cpus = 2
        mem = 512
        disk = 10
        arch = 'x86_64'
        properties = {'cpus': cpus, 'memory_mb': mem,
                      'local_gb': disk, 'cpu_arch': arch}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                       instance_uuid=uuidutils.generate_uuid(),
                                       properties=properties)

        result = self.driver._node_resource(node)
        self.assertEqual(cpus, result['vcpus'])
        self.assertEqual(cpus, result['vcpus_used'])
        self.assertEqual(mem, result['memory_mb'])
        self.assertEqual(mem, result['memory_mb_used'])
        self.assertEqual(disk, result['local_gb'])
        self.assertEqual(disk, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual('{"cpu_arch": "x86_64", "ironic_driver": "'
                         'ironic.nova.virt.ironic.driver.IronicDriver", '
                         '"test_spec": "test_value"}',
                         result['stats'])

    def test__node_resource_no_instance_uuid(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        cpus = 2
        mem = 512
        disk = 10
        arch = 'x86_64'
        properties = {'cpus': cpus, 'memory_mb': mem,
                      'local_gb': disk, 'cpu_arch': arch}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=None,
                                          power_state=ironic_states.POWER_OFF,
                                          properties=properties)

        result = self.driver._node_resource(node)
        self.assertEqual(cpus, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(mem, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(disk, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual('{"cpu_arch": "x86_64", "ironic_driver": "'
                         'ironic.nova.virt.ironic.driver.IronicDriver", '
                         '"test_spec": "test_value"}',
                         result['stats'])

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable')
    def test__node_resource_unavailable_node_res(self, mock_res_unavail):
        mock_res_unavail.return_value = True
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        cpus = 2
        mem = 512
        disk = 10
        arch = 'x86_64'
        properties = {'cpus': cpus, 'memory_mb': mem,
                      'local_gb': disk, 'cpu_arch': arch}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=None,
                                          properties=properties)

        result = self.driver._node_resource(node)
        self.assertEqual(0, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(0, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(0, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual('{"cpu_arch": "x86_64", "ironic_driver": "'
                         'ironic.nova.virt.ironic.driver.IronicDriver", '
                         '"test_spec": "test_value"}',
                         result['stats'])

    @mock.patch.object(firewall.NoopFirewallDriver, 'prepare_instance_filter',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'setup_basic_filtering',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'apply_instance_filter',
                       create=True)
    def test__start_firewall(self, mock_aif, mock_sbf, mock_pif):
        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        self.driver._start_firewall(fake_inst, fake_net_info)

        mock_aif.assert_called_once_with(fake_inst, fake_net_info)
        mock_sbf.assert_called_once_with(fake_inst, fake_net_info)
        mock_pif.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'unfilter_instance',
                       create=True)
    def test__stop_firewall(self, mock_ui):
        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        self.driver._stop_firewall(fake_inst, fake_net_info)
        mock_ui.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists(self, mock_call):
        instance_uuid = 'fake-uuid'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        self.assertTrue(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          instance_uuid)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists_fail(self, mock_call):
        mock_call.side_effect = ironic_exception.NotFound
        instance_uuid = 'fake-uuid'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        self.assertFalse(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          instance_uuid)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    @mock.patch.object(instance_obj.Instance, 'get_by_uuid')
    def test_list_instances(self, mock_inst_by_uuid, mock_call):
        nodes = []
        instances = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            instances.append(fake_instance.fake_instance_obj(self.ctx,
                                                             id=i,
                                                             uuid=uuid))
            nodes.append(ironic_utils.get_test_node(instance_uuid=uuid))

        mock_inst_by_uuid.side_effect = instances
        mock_call.return_value = nodes

        response = self.driver.list_instances()
        mock_call.assert_called_with("node.list", associated=True)
        expected_calls = [mock.call(mock.ANY, instances[0].uuid),
                          mock.call(mock.ANY, instances[1].uuid)]
        mock_inst_by_uuid.assert_has_calls(expected_calls)
        self.assertEqual(['instance-00000000', 'instance-00000001'],
                          sorted(response))

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_list_instance_uuids(self, mock_call):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                      instance_uuid=uuidutils.generate_uuid()))

        mock_call.return_value = nodes
        uuids = self.driver.list_instance_uuids()
        mock_call.assert_called_with('node.list', associated=True)
        expected = [n.instance_uuid for n in nodes]
        self.assertEquals(sorted(expected), sorted(uuids))

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available(self, mock_get, mock_cli):
        node = ironic_utils.get_test_node()
        mock_get.return_value = node
        mock_cli.return_value = FAKE_CLIENT
        self.assertTrue(self.driver.node_is_available(node.uuid))
        mock_get.assert_called_with(node.uuid)

        mock_get.side_effect = ironic_exception.NotFound
        self.assertFalse(self.driver.node_is_available(node.uuid))

    def test__node_resources_unavailable(self):
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF},
            # a node in maintenance /w no instance and ERROR power state
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.ERROR},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.NOSTATE},
        ]
        for n in node_dicts:
            node = ironic_utils.get_test_node(**n)
            self.assertTrue(self.driver._node_resources_unavailable(node))

        avail_node = ironic_utils.get_test_node(
                        power_state=ironic_states.POWER_OFF)
        self.assertFalse(self.driver._node_resources_unavailable(avail_node))

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'list')
    def test_get_available_nodes(self, mock_list, mock_cli):
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF},
            # a node /w instance and power ON
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.ERROR},
        ]
        nodes = [ironic_utils.get_test_node(**n) for n in node_dicts]
        mock_list.return_value = nodes
        mock_cli.return_value = FAKE_CLIENT
        available_nodes = self.driver.get_available_nodes()
        expected_uuids = [n['uuid'] for n in node_dicts]
        self.assertEqual(sorted(expected_uuids), sorted(available_nodes))

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource(self, mock_nr, mock_get, mock_cli):
        node = ironic_utils.get_test_node()
        fake_resource = 'fake-resource'
        mock_get.return_value = node
        mock_nr.return_value = fake_resource
        mock_cli.return_value = FAKE_CLIENT
        result = self.driver.get_available_resource(node.uuid)
        self.assertEqual(fake_resource, result)
        mock_nr.assert_called_once_with(node)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info(self, mock_gbiu, mock_cli):
        instance_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = ironic_utils.get_test_node(instance_uuid=instance_uuid,
                                          properties=properties,
                                          power_state=power_state)

        mock_gbiu.return_value = node

        # ironic_states.POWER_ON should me be mapped to
        # nova_states.RUNNING
        expected = {'state': nova_states.RUNNING,
                    'max_mem': properties['memory_mb'],
                    'mem': properties['memory_mb'],
                    'num_cpu': properties['cpus'],
                    'cpu_time': 0}
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=instance_uuid)
        mock_cli.return_value = FAKE_CLIENT
        result = self.driver.get_info(instance)
        self.assertEqual(expected, result)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info_http_not_found(self, mock_gbiu, mock_cli):
        mock_gbiu.side_effect = ironic_exception.NotFound()

        expected = {'state': nova_states.NOSTATE,
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 0,
                    'cpu_time': 0}
        instance = fake_instance.fake_instance_obj(
                                  self.ctx, uuid=uuidutils.generate_uuid())
        mock_cli.return_value = FAKE_CLIENT
        result = self.driver.get_info(instance)
        self.assertEqual(expected, result)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_macs_for_instance(self, mock_node, mock_cli):
        node = ironic_utils.get_test_node()
        port = ironic_utils.get_test_port()
        mock_node.get.return_value = node
        mock_node.list_ports.return_value = [port]
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        result = self.driver.macs_for_instance(instance)
        self.assertEqual([port.address], result)
        mock_node.list_ports.assert_called_once_with(node.uuid)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_macs_for_instance_http_not_found(self, mock_get, mock_cli):
        mock_get.side_effect = ironic_exception.NotFound()

        instance = fake_instance.fake_instance_obj(
                                  self.ctx, node=uuidutils.generate_uuid())
        mock_cli.return_value = FAKE_CLIENT
        result = self.driver.macs_for_instance(instance)
        self.assertEqual([], result)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(flavor_obj, 'get_by_id')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn(self, mock_sf, mock_pvifs, mock_adf, mock_cli,
                   mock_fg_bid, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        mock_fg_bid.return_value = fake_flavor

        node.provision_state = ironic_states.ACTIVE
        mock_cli.return_value = FAKE_CLIENT
        self.driver.spawn(self.ctx, instance, None, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_fg_bid.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
        mock_adf.assert_called_once_with(node, instance, None, fake_flavor)
        mock_pvifs.assert_called_once_with(node, instance, None)
        mock_sf.assert_called_once_with(instance, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid, 'active')

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_good(self, mock_update, mock_cli):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.driver._add_driver_fields(node, instance, None, None)
        expected_patch = [{'path': '/instance_uuid', 'op': 'add',
                           'value': instance['uuid']}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_fail(self, mock_update, mock_cli):
        mock_update.side_effect = ironic_exception.BadRequest()
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver._add_driver_fields,
                          node, instance, None, None)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_good(self, mock_update, mock_cli):
        node = ironic_utils.get_test_node(driver='fake', instance_uuid='fake-id')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.driver._cleanup_deploy(node, instance, None)
        expected_patch = [{'path': '/instance_uuid', 'op': 'remove'}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_fail(self, mock_update, mock_cli):
        mock_update.side_effect = ironic_exception.BadRequest()
        node = ironic_utils.get_test_node(driver='fake', instance_uuid='fake-id')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.driver._cleanup_deploy,
                          node, instance, None)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(flavor_obj, 'get_by_id')
    def test_spawn_node_driver_validation_fail(self, mock_flavor, mock_cli,
                                               mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_node.validate.return_value = ironic_utils.get_test_validation(
            power=False, deploy=False)
        mock_node.get.return_value = node
        mock_flavor.return_value = fake_flavor
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.ValidationError, self.driver.spawn,
                          self.ctx, instance, None, [], None)
        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(flavor_obj, 'get_by_id')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_prepare_for_deploy_fail(self, mock_cleanup_deploy,
                                                mock_pvifs, mock_sf, mock_cli,
                                                mock_fg_bid, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        class TestException(Exception):
            pass

        mock_sf.side_effect = TestException()
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(TestException, self.driver.spawn,
                          self.ctx, instance, None, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_fg_bid.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
        mock_cleanup_deploy.assert_called_with(node, instance, None)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(flavor_obj, 'get_by_id')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail(self, mock_cleanup_deploy,
                                            mock_pvifs, mock_sf, mock_cli,
                                            mock_fg_bid, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        mock_node.set_provision_state.side_effect = exception.NovaException()
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.NovaException, self.driver.spawn,
                          self.ctx, instance, None, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_fg_bid.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(flavor_obj, 'get_by_id')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail2(self, mock_cleanup_deploy,
                                            mock_pvifs, mock_sf, mock_cli,
                                            mock_fg_bid, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.set_provision_state.side_effect = ironic_exception.BadRequest
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver.spawn,
                          self.ctx, instance, None, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_fg_bid.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_destroy(self, mock_cleanup_deploy, mock_node, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = None

        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.side_effect = fake_set_provision_state
        mock_cli.return_value = FAKE_CLIENT
        self.driver.destroy(self.ctx, instance, network_info, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)
        mock_cleanup_deploy.assert_called_with(node, instance, network_info)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_destroy_ignore_unexpected_state(self, mock_cleanup_deploy,
                                             mock_node, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                        provision_state=ironic_states.DELETING)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get_by_instance_uuid.return_value = node
        mock_cli.return_value = FAKE_CLIENT
        self.driver.destroy(self.ctx, instance, network_info, None)
        self.assertFalse(mock_node.set_provision_state.called)
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)
        mock_cleanup_deploy.assert_called_with(node, instance, network_info)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver, 'validate_instance_and_node')
    def test_destroy_trigger_undeploy_fail(self, fake_validate, mock_sps,
                                           mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        mock_sps.side_effect = exception.NovaException()
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_destroy_unprovision_fail(self, mock_node, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = ironic_states.ERROR

        mock_node.get_by_instance_uuid.return_value = node
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_destroy_unassociate_fail(self, mock_node, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get_by_instance_uuid.return_value = node
        mock_node.update.side_effect = exception.NovaException()
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    @mock.patch.object(ironic_driver, 'validate_instance_and_node')
    def test_reboot(self, mock_val_inst, mock_set_power, mock_cli):
        node = ironic_utils.get_test_node()
        mock_val_inst.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        mock_cli.return_value = FAKE_CLIENT
        self.driver.reboot(self.ctx, instance, None, None)
        mock_set_power.assert_called_once_with(node.uuid, 'reboot')

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver, 'validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off(self, mock_sp, fake_validate, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        fake_validate.return_value = node
        instance_uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=instance_uuid)

        mock_cli.return_value = FAKE_CLIENT
        self.driver.power_off(instance)
        mock_sp.assert_called_once_with(node_uuid, 'off')

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver, 'validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_on(self, mock_sp, fake_validate, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        fake_validate.return_value = node

        instance_uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=instance_uuid)

        mock_cli.return_value = FAKE_CLIENT
        self.driver.power_on(self.ctx, instance,
                             utils.get_test_network_info())
        mock_sp.assert_called_once_with(node_uuid, 'on')

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_with_port(self, mock_uvifs, mock_port_udt, mock_lp,
                                 mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()

        port_id = unicode(network_info[0]['id'])
        expected_patch = [{'op': 'add',
                           'path': '/extra/vif_port_id',
                           'value': port_id}]
        mock_cli.return_value = FAKE_CLIENT
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        mock_port_udt.assert_called_with(port.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    def test_plug_vifs(self, mock__plug_vifs, mock_cli, mock_get):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)

        mock_get.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()
        mock_cli.return_value = FAKE_CLIENT
        self.driver.plug_vifs(instance, network_info)

        mock_get.assert_called_once_with(node_uuid)
        mock__plug_vifs.assert_called_once_with(node, instance, network_info)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_count_mismatch(self, mock_uvifs, mock_lp,
                                      mock_port_udt, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        # len(network_info) > len(ports)
        network_info = (utils.get_test_network_info() +
                        utils.get_test_network_info())
        mock_cli.return_value = FAKE_CLIENT
        self.assertRaises(exception.NovaException,
                          self.driver._plug_vifs, node, instance,
                          network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        # assert port.update() was not called
        self.assertFalse(mock_port_udt.called)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_no_network_info(self, mock_uvifs, mock_lp,
                                       mock_port_udt, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = []
        mock_cli.return_value = FAKE_CLIENT
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        # assert port.update() was not called
        self.assertFalse(mock_port_udt.called)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_unplug_vifs(self, mock_node, mock_update, mock_cli):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_node.get.return_value = node
        mock_node.list_ports.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        expected_patch = [{'op': 'remove', 'path':
                           '/extra/vif_port_id'}]
        mock_cli.return_value = FAKE_CLIENT
        self.driver.unplug_vifs(instance,
                                utils.get_test_network_info())

        # asserts
        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.list_ports.assert_called_once_with(node_uuid)
        mock_update.assert_called_once_with(port.uuid, expected_patch)

    @mock.patch.object(cw.IronicClientWrapper, '_get_client')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    def test_unplug_vifs_no_network_info(self, mock_update, mock_cli):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = []
        mock_cli.return_value = FAKE_CLIENT
        self.driver.unplug_vifs(instance, network_info)

        # assert port.update() was not called
        self.assertFalse(mock_update.called)
