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
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
from nova.tests import utils
from nova.virt import fake


CONF = cfg.CONF

IRONIC_FLAGS = dict(
    instance_type_extra_specs=['test_spec:test_value'],
    api_version=1,
    group='ironic',
)


class FakePortClient(object):

    def get(self, port_uuid):
        pass

    def update(self, port_uuid, patch):
        pass


class FakeNodeClient(object):

    def list(self):
        return []

    def get(self, node_uuid):
        pass

    def get_by_instance_uuid(self, instance_uuid):
        pass

    def list_ports(self, node_uuid):
        pass

    def set_power_state(self, node_uuid, target):
        pass

    def set_provision_state(self, node_uuid, target):
        pass

    def update(self, node_uuid, patch):
        pass

    def validate(self, node_uuid):
        pass


class FakeClient(object):

    node = FakeNodeClient()
    port = FakePortClient()


FAKE_CLIENT = FakeClient()


class IronicDriverTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicDriverTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)
        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()
        # mock _get_client
        self.mock_cli_patcher = mock.patch.object(self.driver, '_get_client')
        self.mock_cli = self.mock_cli_patcher.start()
        self.mock_cli.return_value = FAKE_CLIENT

        def stop_patchers():
            if self.mock_cli:
                self.mock_cli_patcher.stop()

        self.addCleanup(stop_patchers)

    def test_validate_driver_loading(self):
        self.assertIsInstance(self.driver, ironic_driver.IronicDriver)

    def test_get_hypervisor_type(self):
        self.assertEqual(self.driver.get_hypervisor_type(), 'ironic')

    def test_get_hypervisor_version(self):
        self.assertEqual(self.driver.get_hypervisor_version(), 1)

    def test__get_client_no_auth_token(self):
        self.flags(admin_auth_token=None, group='ironic')

        # stop _get_client mock
        self.mock_cli_patcher.stop()
        self.mock_cli = None

        with mock.patch.object(nova_context, 'get_admin_context') as mock_ctx:
            mock_ctx.return_value = self.ctx
            with mock.patch.object(ironic_client, 'get_client') as mock_ir_cli:
                self.driver._get_client()
                expected = {'os_username': CONF.ironic.admin_username,
                            'os_password': CONF.ironic.admin_password,
                            'os_auth_url': CONF.ironic.admin_url,
                            'os_tenant_name': CONF.ironic.admin_tenant_name,
                            'os_service_type': 'baremetal',
                            'os_endpoint_type': 'public'}
                mock_ir_cli.assert_called_once_with(CONF.ironic.api_version,
                                                    **expected)

    def test__get_client_with_auth_token(self):
        self.flags(admin_auth_token='fake-token', group='ironic')

        # stop _get_client mock
        self.mock_cli_patcher.stop()
        self.mock_cli = None

        with mock.patch.object(nova_context, 'get_admin_context') as mock_ctx:
            mock_ctx.return_value = self.ctx
            with mock.patch.object(ironic_client, 'get_client') as mock_ir_cli:
                self.driver._get_client()
                expected = {'os_auth_token': 'fake-token',
                            'ironic_url': CONF.ironic.api_endpoint}
                mock_ir_cli.assert_called_once_with(CONF.ironic.api_version,
                                                    **expected)

    def test_validate_instance_and_node(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        instance_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)

        with mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid') \
            as mock_gbiui:
            mock_gbiui.return_value = node
            result = ironic_driver.validate_instance_and_node(FAKE_CLIENT,
                                                              instance)
            self.assertEqual(result.uuid, node_uuid)

    def test_validate_instance_and_node_failed(self):
        with mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid') \
            as mock_gbiui:
            mock_gbiui.side_effect = ironic_exception.HTTPNotFound()
            instance_uuid = uuidutils.generate_uuid(),
            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       uuid=instance_uuid)
            self.assertRaises(exception.InstanceNotFound,
                              ironic_driver.validate_instance_and_node,
                              FAKE_CLIENT, instance)

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

    def test__retry_if_service_is_unavailable(self):
        test_list = []

        def test_func(test_list):
            test_list.append(1)

        self.driver._retry_if_service_is_unavailable(test_func, test_list)
        self.assertIn(1, test_list)

    def test__retry_if_service_is_unavailable_fail(self):
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

        def test_func():
            raise ironic_exception.HTTPServiceUnavailable()

        self.assertRaises(ironic_driver.MaximumRetriesReached,
                          self.driver._retry_if_service_is_unavailable,
                          test_func)

    def test__start_firewall(self):
        func_list = ['setup_basic_filtering',
                     'prepare_instance_filter',
                     'apply_instance_filter']
        patch_list = [mock.patch.object(self.driver.firewall_driver, func)
                      for func in func_list]
        mock_list = [patcher.start() for patcher in patch_list]
        for p in patch_list:
            self.addCleanup(p.stop)

        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        self.driver._start_firewall(fake_inst, fake_net_info)

        # assert all methods were invoked with the right args
        for m in mock_list:
            m.assert_called_once_with(fake_inst, fake_net_info)

    def test__stop_firewall(self):
        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        with mock.patch.object(self.driver.firewall_driver,
                               'unfilter_instance') as mock_ui:
            self.driver._stop_firewall(fake_inst, fake_net_info)
            mock_ui.assert_called_once_with(fake_inst, fake_net_info)

    def test_list_instances(self):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                      instance_uuid=uuidutils.generate_uuid()))
        # append a node w/o instance_uuid which shouldn't be listed
        nodes.append(ironic_utils.get_test_node(instance_uuid=None))

        with mock.patch.object(cw.IronicClientWrapper, 'call') as mock_list:
            mock_list.return_value = nodes

            expected = [n for n in nodes if n.instance_uuid]
            instances = self.driver.list_instances()
            mock_list.assert_called_with("node.list")
            self.assertEqual(sorted(expected), sorted(instances))
            self.assertEqual(num_nodes, len(instances))

    def test_list_instance_uuids(self):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                      instance_uuid=uuidutils.generate_uuid()))

        with mock.patch.object(self.driver, 'list_instances') as mock_list:
            mock_list.return_value = nodes
            uuids = self.driver.list_instance_uuids()
            self.assertTrue(mock_list.called)
            expected = [n.instance_uuid for n in nodes]
            self.assertEquals(sorted(expected), sorted(uuids))

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available(self, mock_get):
        no_guid = None
        any_guid = uuidutils.generate_uuid()
        in_maintenance = True
        is_available = True
        not_in_maintenance = False
        not_available = False
        power_off = ironic_states.POWER_OFF
        not_power_off = ironic_states.POWER_ON

        testing_set = {(no_guid, not_in_maintenance, power_off):is_available,
                       (no_guid, not_in_maintenance, not_power_off):not_available,
                       (no_guid, in_maintenance, power_off):not_available,
                       (no_guid, in_maintenance, not_power_off):not_available,
                       (any_guid, not_in_maintenance, power_off):not_available,
                       (any_guid, not_in_maintenance, not_power_off):not_available,
                       (any_guid, in_maintenance, power_off):not_available,
                       (any_guid, in_maintenance, not_power_off):not_available}

        for key in testing_set.keys():
            node = ironic_utils.get_test_node(instance_uuid=key[0],
                                              maintenance=key[1],
                                              power_state=key[2])
            mock_get.return_value = node
            expected = testing_set[key]
            observed = self.driver.node_is_available("dummy_nodename")
            self.assertEqual(expected, observed)

    def test_get_available_nodes(self):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                          uuid=uuidutils.generate_uuid(),
                                          power_state=ironic_states.POWER_OFF))
        # append a node w/o power_state which shouldn't be listed
        nodes.append(ironic_utils.get_test_node(power_state=None))

        with mock.patch.object(cw.IronicClientWrapper, 'call') as mock_list:
            mock_list.return_value = nodes

            expected = [n.uuid for n in nodes if n.power_state]
            available_nodes = self.driver.get_available_nodes()
            mock_list.assert_called_with("node.list")
            self.assertEqual(sorted(expected), sorted(available_nodes))
            self.assertEqual(num_nodes, len(available_nodes))

    def test_get_available_resource(self):
        node = ironic_utils.get_test_node()
        fake_resource = 'fake-resource'
        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)

        with mock.patch.object(self.driver, '_node_resource') as mock_nr:
            mock_nr.return_value = fake_resource

            result = self.driver.get_available_resource(node.uuid)
            self.assertEqual(fake_resource, result)
            mock_nr.assert_called_once_with(node)

    def test_get_info(self):
        instance_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = ironic_utils.get_test_node(instance_uuid=instance_uuid,
                                          properties=properties,
                                          power_state=power_state)

        with mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid') \
                as mock_gbiu:
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
            result = self.driver.get_info(instance)
            self.assertEqual(expected, result)

    def test_get_info_http_not_found(self):
        with mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid') \
                as mock_gbiu:
            mock_gbiu.side_effect = ironic_exception.HTTPNotFound()

            expected = {'state': nova_states.NOSTATE,
                        'max_mem': 0,
                        'mem': 0,
                        'num_cpu': 0,
                        'cpu_time': 0}
            instance = fake_instance.fake_instance_obj(
                                      self.ctx, uuid=uuidutils.generate_uuid())
            result = self.driver.get_info(instance)
            self.assertEqual(expected, result)

    def test_macs_for_instance(self):
        node = ironic_utils.get_test_node()
        port = ironic_utils.get_test_port()
        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]
            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node.uuid)
            result = self.driver.macs_for_instance(instance)
            self.assertEqual([port.address], result)
            mock_lp.assert_called_once_with(node.uuid)

    def test_macs_for_instance_http_not_found(self):
        with mock.patch.object(FAKE_CLIENT.node, 'get') as mock_get:
            mock_get.side_effect = ironic_exception.HTTPNotFound()

            instance = fake_instance.fake_instance_obj(
                                      self.ctx, node=uuidutils.generate_uuid())
            result = self.driver.macs_for_instance(instance)
            self.assertEqual([], result)

    def test_spawn(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_fg_bid = mock.patch.object(flavor_obj, 'get_by_id').start()
        mock_fg_bid.return_value = fake_flavor
        self.addCleanup(mock_fg_bid.stop)

        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = ironic_utils.get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_adf = mock.patch.object(self.driver, '_add_driver_fields').start()
        self.addCleanup(mock_adf.stop)
        mock_pvifs = mock.patch.object(self.driver, '_plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_sf = mock.patch.object(self.driver, '_start_firewall').start()
        self.addCleanup(mock_pvifs.stop)

        mock_get_node_by_iuuid = mock.patch.object(
            FAKE_CLIENT.node, 'get_by_instance_uuid').start()
        self.addCleanup(mock_get_node_by_iuuid.stop)
        mock_get_node_by_iuuid.return_value = node

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            node.provision_state = ironic_states.ACTIVE
            self.driver.spawn(self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg_bid.assert_called_once_with(self.ctx,
                                                instance['instance_type_id'])
            mock_adf.assert_called_once_with(node, instance, None, fake_flavor)
            mock_pvifs.assert_called_once_with(node, instance, None)
            mock_sf.assert_called_once_with(instance, None)
            mock_sps.assert_called_once_with(node_uuid, 'active')

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_good(self, mock_update):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._add_driver_fields(node, instance, None, None)
        expected_patch = [{'path': '/instance_uuid', 'op': 'add',
                           'value': instance['uuid']}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_fail(self, mock_update):
        mock_update.side_effect = ironic_exception.HTTPBadRequest()
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver._add_driver_fields,
                          node, instance, None, None)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_good(self, mock_update):
        node = ironic_utils.get_test_node(driver='fake', instance_uuid='fake-id')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._cleanup_deploy(node, instance, None)
        expected_patch = [{'path': '/instance_uuid', 'op': 'remove'}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_fail(self, mock_update):
        mock_update.side_effect = ironic_exception.HTTPBadRequest()
        node = ironic_utils.get_test_node(driver='fake', instance_uuid='fake-id')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.driver._cleanup_deploy,
                          node, instance, None)

    @mock.patch.object(flavor_obj, 'get_by_id')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(FAKE_CLIENT.node, 'validate')
    def test_spawn_node_driver_validation_fail(self, mock_validate, mock_get,
                                               mock_flavor):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_validate.return_value = ironic_utils.get_test_validation(
                                                                 power=False,
                                                                 deploy=False)
        mock_get.return_value = node
        mock_flavor.return_value = fake_flavor

        self.assertRaises(exception.ValidationError, self.driver.spawn,
                          self.ctx, instance, None, [], None)
        mock_get.assert_called_once_with(node_uuid)
        mock_validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])

    def test_spawn_node_prepare_for_deploy_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = ironic_utils.get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_fg_bid = mock.patch.object(flavor_obj, 'get_by_id').start()
        self.addCleanup(mock_fg_bid.stop)
        mock_pvifs = mock.patch.object(self.driver, '_plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_cleanup_deploy = mock.patch.object(
            self.driver, '_cleanup_deploy').start()
        self.addCleanup(mock_cleanup_deploy.stop)

        class TestException(Exception):
            pass

        with mock.patch.object(self.driver, '_start_firewall') as mock_sf:
            mock_sf.side_effect = TestException()
            self.assertRaises(TestException, self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg_bid.assert_called_once_with(self.ctx,
                                                instance['instance_type_id'])
            mock_cleanup_deploy.assert_called_with(node, instance, None)

    def test_spawn_node_trigger_deploy_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = ironic_utils.get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_fg_bid = mock.patch.object(flavor_obj, 'get_by_id').start()
        self.addCleanup(mock_fg_bid.stop)
        mock_pvifs = mock.patch.object(self.driver, '_plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_sf = mock.patch.object(self.driver, '_start_firewall').start()
        self.addCleanup(mock_sf.stop)
        mock_cleanup_deploy = mock.patch.object(
            self.driver, '_cleanup_deploy').start()
        self.addCleanup(mock_cleanup_deploy.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            mock_sps.side_effect = ironic_driver.MaximumRetriesReached
            self.assertRaises(exception.NovaException, self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg_bid.assert_called_once_with(self.ctx,
                                                instance['instance_type_id'])
            mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    def test_spawn_node_trigger_deploy_fail2(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = ironic_utils.get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_fg_bid = mock.patch.object(flavor_obj, 'get_by_id').start()
        self.addCleanup(mock_fg_bid.stop)
        mock_pvifs = mock.patch.object(self.driver, '_plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_sf = mock.patch.object(self.driver, '_start_firewall').start()
        self.addCleanup(mock_sf.stop)
        mock_cleanup_deploy = mock.patch.object(
            self.driver, '_cleanup_deploy').start()
        self.addCleanup(mock_cleanup_deploy.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            mock_sps.side_effect = ironic_exception.HTTPBadRequest
            self.assertRaises(exception.InstanceDeployFailure,
                              self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg_bid.assert_called_once_with(self.ctx,
                                                instance['instance_type_id'])
            mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_destroy(self, mock_get_by_iuuid, mock_sps, mock_update):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = None

        mock_get_by_iuuid.return_value = node
        mock_sps.side_effect = fake_set_provision_state
        with mock.patch.object(self.driver, '_cleanup_deploy') \
                as mock_cleanupd:
            self.driver.destroy(self.ctx, instance, network_info, None)
            mock_sps.assert_called_once_with(node_uuid, 'deleted')
            mock_get_by_iuuid.assert_called_with(instance.uuid)
            mock_cleanupd.assert_called_with(node, instance, network_info)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_destroy_ignore_unexpected_state(self, mock_get_by_iuuid,
                                             mock_sps, mock_update):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                        provision_state=ironic_states.DELETING)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get_by_iuuid.return_value = node
        with mock.patch.object(self.driver, '_cleanup_deploy') \
                as mock_cleanupd:
            self.driver.destroy(self.ctx, instance, network_info, None)
            self.assertFalse(mock_sps.called)
            mock_get_by_iuuid.assert_called_with(instance.uuid)
            mock_cleanupd.assert_called_with(node, instance, network_info)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver, 'validate_instance_and_node')
    def test_destroy_trigger_undeploy_fail(self, fake_validate, mock_sps):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        mock_sps.side_effect = ironic_driver.MaximumRetriesReached
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_destroy_unprovision_fail(self, mock_get_by_iuuid, mock_sps):
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = ironic_states.ERROR

        mock_get_by_iuuid.return_value = node
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_sps.assert_called_once_with(node_uuid, 'deleted')

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_destroy_unassociate_fail(self, mock_get_by_iuuid, mock_sps):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get_by_iuuid.return_value = node
        with mock.patch.object(FAKE_CLIENT.node, 'update') as mock_update:
            mock_update.side_effect = ironic_driver.MaximumRetriesReached()
            self.assertRaises(exception.NovaException, self.driver.destroy,
                              self.ctx, instance, None, None)
            mock_sps.assert_called_once_with(node_uuid, 'deleted')
            mock_get_by_iuuid.assert_called_with(instance.uuid)

    def test_reboot(self):
        #TODO(lucasagomes): Not implemented in the driver.py
        pass

    def test_power_off(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        with mock.patch.object(ironic_driver, 'validate_instance_and_node') \
            as fake_validate:
            fake_validate.return_value = node
            self.addCleanup(fake_validate.stop)
            instance_uuid = uuidutils.generate_uuid()
            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=instance_uuid)

            with mock.patch.object(FAKE_CLIENT.node, 'set_power_state') \
                as mock_sp:
                self.driver.power_off(instance)
                mock_sp.assert_called_once_with(node_uuid, 'off')

    def test_power_on(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        with mock.patch.object(ironic_driver, 'validate_instance_and_node') \
            as fake_validate:
            fake_validate.return_value = node
            self.addCleanup(fake_validate.stop)

            instance_uuid = uuidutils.generate_uuid()
            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=instance_uuid)

            with mock.patch.object(FAKE_CLIENT.node, 'set_power_state') \
                as mock_sp:
                self.driver.power_on(self.ctx, instance,
                                     utils.get_test_network_info())
                mock_sp.assert_called_once_with(node_uuid, 'on')

    def test__plug_vifs(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_uvifs = mock.patch.object(self.driver, '_unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)

        mock_retry = mock.patch.object(
            self.driver, '_retry_if_service_is_unavailable').start()
        self.addCleanup(mock_retry.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            network_info = utils.get_test_network_info()

            port_id = unicode(network_info[0]['id'])
            expected_patch = [{'op': 'add',
                               'path': '/extra/vif_port_id',
                               'value': port_id}]
            self.driver._plug_vifs(node, instance, network_info)

            # asserts
            mock_uvifs.assert_called_once_with(node, instance, network_info)
            mock_lp.assert_called_once_with(node_uuid)
            mock_retry.assert_called_with(FAKE_CLIENT.port.update,
                                          port.uuid, expected_patch)

    def test_plug_vifs(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)

        mock__plug_vifs = mock.patch.object(self.driver, '_plug_vifs').start()
        self.addCleanup(mock__plug_vifs.stop)

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()
        self.driver.plug_vifs(instance, network_info)

        mock_get.assert_called_once_with(node_uuid)
        mock__plug_vifs.assert_called_once_with(node, instance, network_info)

    def test__plug_vifs_count_missmatch(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_uvifs = mock.patch.object(self.driver, '_unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)
        mock_retry = mock.patch.object(
            self.driver, '_retry_if_service_is_unavailable').start()
        self.addCleanup(mock_retry.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            # len(network_info) > len(ports)
            network_info = (utils.get_test_network_info() +
                            utils.get_test_network_info())
            self.assertRaises(exception.NovaException,
                              self.driver._plug_vifs, node, instance,
                              network_info)

            # asserts
            mock_uvifs.assert_called_once_with(node, instance, network_info)
            mock_lp.assert_called_once_with(node_uuid)
            # assert port.update() was not called via _retry...()
            assert not mock_retry.called

    def test__plug_vifs_no_network_info(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_uvifs = mock.patch.object(self.driver, '_unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)

        mock_retry = mock.patch.object(
            self.driver, '_retry_if_service_is_unavailable').start()
        self.addCleanup(mock_retry.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            network_info = []
            self.driver._plug_vifs(node, instance, network_info)

            # asserts
            mock_uvifs.assert_called_once_with(node, instance, network_info)
            mock_lp.assert_called_once_with(node_uuid)
            # assert port.update() was not called via _retry...()
            assert not mock_retry.called

    def test_unplug_vifs(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_update = mock.patch.object(FAKE_CLIENT.port, 'update').start()
        self.addCleanup(mock_update.stop)
        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            expected_patch = [{'op': 'remove', 'path':
                               '/extra/vif_port_id'}]
            self.driver.unplug_vifs(instance,
                                    utils.get_test_network_info())

            # asserts
            mock_get.assert_called_once_with(node_uuid)
            mock_lp.assert_called_once_with(node_uuid)
            mock_update.assert_called_once_with(port.uuid, expected_patch)

    def test_unplug_vifs_no_network_info(self):
        mock_update = mock.patch.object(FAKE_CLIENT.port, 'update').start()
        self.addCleanup(mock_update.stop)

        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = []
        self.driver.unplug_vifs(instance, network_info)

        # assert port.update() was not called
        assert not mock_update.called
