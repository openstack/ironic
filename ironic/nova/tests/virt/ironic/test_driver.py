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

from nova.compute import power_state as nova_states
from nova import context as nova_context
from nova import exception
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
from nova.tests import utils
from nova.virt import fake
from nova.virt.ironic import driver as ironic_driver
from nova.virt.ironic import ironic_states


CONF = cfg.CONF

IRONIC_FLAGS = dict(
    instance_type_extra_specs=['test_spec:test_value'],
    api_version=1,
    group='ironic',
)


def get_test_validation(**kw):
    return type('interfaces', (object,),
               {'power': kw.get('power', True),
                'deploy': kw.get('deploy', True),
                'console': kw.get('console', True),
                'rescue': kw.get('rescue', True)})()


def get_test_node(**kw):
    return type('node', (object,),
               {'uuid': kw.get('uuid', 'eeeeeeee-dddd-cccc-bbbb-aaaaaaaaaaaa'),
                'chassis_uuid': kw.get('chassis_uuid'),
                'power_state': kw.get('power_state',
                                      ironic_states.NOSTATE),
                'target_power_state': kw.get('target_power_state',
                                             ironic_states.NOSTATE),
                'provision_state': kw.get('provision_state',
                                          ironic_states.NOSTATE),
                'target_provision_state': kw.get('target_provision_state',
                                                 ironic_states.NOSTATE),
                'last_error': kw.get('last_error'),
                'instance_uuid': kw.get('instance_uuid'),
                'driver': kw.get('driver', 'fake'),
                'driver_info': kw.get('driver_info', {}),
                'properties': kw.get('properties', {}),
                'reservation': kw.get('reservation'),
                'maintenance': kw.get('maintenance', False),
                'extra': kw.get('extra', {}),
                'updated_at': kw.get('created_at'),
                'created_at': kw.get('updated_at')})()


def get_test_port(**kw):
    return type('port', (object,),
               {'uuid': kw.get('uuid', 'gggggggg-uuuu-qqqq-ffff-llllllllllll'),
                'node_uuid': kw.get('node_uuid', get_test_node().uuid),
                'address': kw.get('address', 'FF:FF:FF:FF:FF:FF'),
                'extra': kw.get('extra', {}),
                'created_at': kw.get('created_at'),
                'updated_at': kw.get('updated_at')})()


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
                expected = {'os_auth_token': self.ctx.auth_token,
                            'ironic_url': CONF.ironic.api_endpoint}
                mock_ir_cli.assert_called_once_with(CONF.ironic.api_version,
                                                    **expected)

    def test__require_node(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        test_instance = fake_instance.fake_instance_obj(self.ctx,
                                                        node=node_uuid)
        self.assertEqual(node_uuid, self.driver._require_node(test_instance))

    def test__require_node_fail(self):
        test_instance = fake_instance.fake_instance_obj(self.ctx, node=None)
        self.assertRaises(exception.NovaException,
                          self.driver._require_node, test_instance)

    def test__node_resource(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        cpus = 2
        mem = 512
        disk = 10
        arch = 'x86_64'
        properties = {'cpus': cpus, 'memory_mb': mem,
                      'local_gb': disk, 'cpu_arch': arch}
        node = get_test_node(uuid=node_uuid,
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
                         'nova.virt.ironic.driver.IronicDriver", '
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
        node = get_test_node(uuid=node_uuid,
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
                         'nova.virt.ironic.driver.IronicDriver", '
                         '"test_spec": "test_value"}',
                         result['stats'])

    def test__retry_on_conflict(self):
        test_list = []

        def test_func(test_list):
            test_list.append(1)

        self.driver._retry_on_conflict(test_func, test_list)
        self.assertIn(1, test_list)

    def test__retry_on_conflict_fail(self):
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

        def test_func():
            raise ironic_exception.HTTPConflict()

        self.assertRaises(ironic_driver.MaximumRetriesReached,
                          self.driver._retry_on_conflict, test_func)

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
            nodes.append(get_test_node(
                            instance_uuid=uuidutils.generate_uuid()))
        # append a node w/o instance_uuid which shouldn't be listed
        nodes.append(get_test_node(instance_uuid=None))

        with mock.patch.object(FAKE_CLIENT.node, 'list') as mock_list:
            mock_list.return_value = nodes

            expected = [n for n in nodes if n.instance_uuid]
            instances = self.driver.list_instances()
            self.assertEqual(sorted(expected), sorted(instances))
            self.assertEqual(num_nodes, len(instances))

    def test_get_available_nodes(self):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(get_test_node(uuid=uuidutils.generate_uuid(),
                                       power_state=ironic_states.POWER_OFF))
        # append a node w/o power_state which shouldn't be listed
        nodes.append(get_test_node(power_state=None))

        with mock.patch.object(FAKE_CLIENT.node, 'list') as mock_list:
            mock_list.return_value = nodes

            expected = [n.uuid for n in nodes if n.power_state]
            available_nodes = self.driver.get_available_nodes()
            self.assertEqual(sorted(expected), sorted(available_nodes))
            self.assertEqual(num_nodes, len(available_nodes))

    def test_get_available_resource(self):
        node = get_test_node()
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
        node = get_test_node(instance_uuid=instance_uuid,
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
        node = get_test_node()
        port = get_test_port()
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
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_fg = mock.patch.object(self.driver.virtapi, 'flavor_get').start()
        mock_fg.return_value = fake_flavor
        self.addCleanup(mock_fg.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_adf = mock.patch.object(self.driver, '_add_driver_fields').start()
        self.addCleanup(mock_adf.stop)
        mock_pvifs = mock.patch.object(self.driver, 'plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_sf = mock.patch.object(self.driver, '_start_firewall').start()
        self.addCleanup(mock_pvifs.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            self.driver.spawn(self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
            mock_adf.assert_called_once_with(node, instance, None, fake_flavor)
            mock_pvifs.assert_called_once_with(instance, None)
            mock_sf.assert_called_once_with(instance, None)
            mock_sps.assert_called_once_with(node_uuid, 'active')

    def test_spawn_setting_instance_uuid_fail(self):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                node=uuidutils.generate_uuid())
        with mock.patch.object(FAKE_CLIENT.node, 'update') as mock_update:
            mock_update.side_effect = ironic_exception.HTTPBadRequest()
            self.assertRaises(exception.NovaException, self.driver.spawn,
                              self.ctx, instance, None, [], None)

    def test_spawn_node_driver_validation_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = 'fake-flavor'

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_fg = mock.patch.object(self.driver.virtapi, 'flavor_get').start()
        mock_fg.return_value = fake_flavor
        self.addCleanup(mock_fg.stop)

        mock_adf = mock.patch.object(self.driver, '_add_driver_fields').start()
        self.addCleanup(mock_adf.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'validate') as mock_validate:
            mock_validate.return_value = get_test_validation(power=False,
                                                             deploy=False)
            self.assertRaises(exception.ValidationError, self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
            mock_adf.assert_called_once_with(node, instance, None, fake_flavor)

    def test_spawn_node_prepare_for_deploy_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_fg = mock.patch.object(self.driver.virtapi, 'flavor_get').start()
        self.addCleanup(mock_fg.stop)
        mock_pvifs = mock.patch.object(self.driver, 'plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_upvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_upvifs.stop)
        mock_stof = mock.patch.object(self.driver, '_stop_firewall').start()
        self.addCleanup(mock_stof.stop)

        class TestException(Exception):
            pass

        with mock.patch.object(self.driver, '_start_firewall') as mock_sf:
            mock_sf.side_effect = TestException()
            self.assertRaises(TestException, self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
            mock_upvifs.assert_called_once_with(instance, None)
            mock_stof.assert_called_once_with(instance, None)

    def test_spawn_node_trigger_deploy_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_validate = mock.patch.object(FAKE_CLIENT.node, 'validate').start()
        mock_validate.return_value = get_test_validation()
        self.addCleanup(mock_validate.stop)

        mock_fg = mock.patch.object(self.driver.virtapi, 'flavor_get').start()
        self.addCleanup(mock_fg.stop)
        mock_pvifs = mock.patch.object(self.driver, 'plug_vifs').start()
        self.addCleanup(mock_pvifs.stop)
        mock_sf = mock.patch.object(self.driver, '_start_firewall').start()
        self.addCleanup(mock_sf.stop)
        mock_upvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_upvifs.stop)
        mock_stof = mock.patch.object(self.driver, '_stop_firewall').start()
        self.addCleanup(mock_stof.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            mock_sps.side_effect = ironic_driver.MaximumRetriesReached
            self.assertRaises(exception.NovaException, self.driver.spawn,
                              self.ctx, instance, None, [], None)

            mock_get.assert_called_once_with(node_uuid)
            mock_validate.assert_called_once_with(node_uuid)
            mock_fg.assert_called_once_with(self.ctx,
                                            instance['instance_type_id'])
            mock_upvifs.assert_called_once_with(instance, None)
            mock_stof.assert_called_once_with(instance, None)

    def test_destroy(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_sps = mock.patch.object(FAKE_CLIENT.node,
                                     'set_provision_state').start()
        self.addCleanup(mock_sps.stop)
        mock_update = mock.patch.object(FAKE_CLIENT.node, 'update').start()
        self.addCleanup(mock_update.stop)
        mock_upvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_upvifs.stop)
        mock_stof = mock.patch.object(self.driver, '_stop_firewall').start()
        self.addCleanup(mock_stof.stop)

        self.driver.destroy(self.ctx, instance, None, None)
        mock_sps.assert_called_once_with(node_uuid, 'deleted')
        mock_get.assert_called_with(node_uuid)
        mock_upvifs.assert_called_once_with(instance, None)
        mock_stof.assert_called_once_with(instance, None)

    def test_destroy_trigger_undeploy_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        with mock.patch.object(FAKE_CLIENT.node, 'set_provision_state') \
                as mock_sps:
            mock_sps.side_effect = ironic_driver.MaximumRetriesReached
            self.assertRaises(exception.NovaException, self.driver.destroy,
                              self.ctx, instance, None, None)

    def test_destroy_unprovision_fail(self):
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid,
                             provision_state='fake-state')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_sps = mock.patch.object(FAKE_CLIENT.node,
                                     'set_provision_state').start()
        self.addCleanup(mock_sps.stop)

        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_sps.assert_called_once_with(node_uuid, 'deleted')

    def test_destroy_unassociate_fail(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_sps = mock.patch.object(FAKE_CLIENT.node,
                                     'set_provision_state').start()
        self.addCleanup(mock_sps.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'update') as mock_update:
            mock_update.side_effect = ironic_driver.MaximumRetriesReached()
            self.assertRaises(exception.NovaException, self.driver.destroy,
                              self.ctx, instance, None, None)
            mock_sps.assert_called_once_with(node_uuid, 'deleted')
            mock_get.assert_called_with(node_uuid)

    def test_reboot(self):
        #TODO(lucasagomes): Not implemented in the driver.py
        pass

    def test_power_off(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        with mock.patch.object(FAKE_CLIENT.node, 'set_power_state') as mock_sp:
            self.driver.power_off(instance)
            mock_sp.assert_called_once_with(node_uuid, 'off')

    def test_power_on(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        with mock.patch.object(FAKE_CLIENT.node, 'set_power_state') as mock_sp:
            self.driver.power_on(self.ctx, instance,
                                 utils.get_test_network_info())
            mock_sp.assert_called_once_with(node_uuid, 'on')

    def test_get_host_stats(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        cpu_arch = 'x86_64'
        node = get_test_node(uuid=node_uuid,
                             properties={'cpu_arch': cpu_arch})
        supported_instances = 'fake-supported-instances'
        resource = {'supported_instances': supported_instances,
                    'hypervisor_hostname': uuidutils.generate_uuid(),
                    'cpu_info': 'baremetal cpu',
                    'hypervisor_version': 1,
                    'local_gb': 10,
                    'memory_mb_used': 512,
                    'stats': {'cpu_arch': 'x86_64',
                              'ironic_driver':
                                        'nova.virt.ironic.driver.IronicDriver',
                              'test_spec': 'test_value'},
                    'vcpus_used': 2,
                    'hypervisor_type': 'ironic',
                    'local_gb_used': 10,
                    'memory_mb': 512,
                    'vcpus': 2}

        # Reset driver specs
        test_extra_spec = 'test-spec'
        self.driver.extra_specs = {test_extra_spec: test_extra_spec}

        with mock.patch.object(FAKE_CLIENT.node, 'list') as mock_list:
            mock_list.return_value = [node]
            with mock.patch.object(self.driver, '_node_resource') as mock_nr:
                mock_nr.return_value = resource
                with mock.patch.object(ironic_driver,
                                '_get_nodes_supported_instances') as mock_gnsi:
                    mock_gnsi.return_value = supported_instances

                    expected = {'vcpus': resource['vcpus'],
                          'vcpus_used': resource['vcpus_used'],
                          'cpu_info': resource['cpu_info'],
                          'disk_total': resource['local_gb'],
                          'disk_used': resource['local_gb'],
                          'disk_available': 0,
                          'host_memory_total': resource['memory_mb'],
                          'host_memory_free': 0,
                          'hypervisor_type': resource['hypervisor_type'],
                          'hypervisor_version': resource['hypervisor_version'],
                          'supported_instances': supported_instances,
                          'host': CONF.host,
                          'hypervisor_hostname': node_uuid,
                          'node': node_uuid,
                          'cpu_arch': cpu_arch,
                          test_extra_spec: test_extra_spec}

                    result = self.driver.get_host_stats()
                    self.assertEqual([expected], result)

    def test_plug_vifs(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(uuid=node_uuid)
        port = get_test_port()

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_uvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)
        mock_update = mock.patch.object(FAKE_CLIENT.port, 'update').start()
        self.addCleanup(mock_update.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            network_info = utils.get_test_network_info()

            port_id = unicode(network_info[0]['id'])
            expected_patch = [{'op': 'add',
                               'path': '/extra/vif_port_id',
                               'value': port_id}]
            self.driver.plug_vifs(instance, network_info)

            # asserts
            mock_uvifs.assert_called_once_with(instance, network_info)
            mock_get.assert_called_once_with(node_uuid)
            mock_lp.assert_called_once_with(node_uuid)
            mock_update.assert_called_once_with(port.uuid, expected_patch)

    def test_plug_vifs_count_missmatch(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(uuid=node_uuid)
        port = get_test_port()

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_uvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)
        mock_update = mock.patch.object(FAKE_CLIENT.port, 'update').start()
        self.addCleanup(mock_update.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            # len(network_info) > len(ports)
            network_info = (utils.get_test_network_info() +
                            utils.get_test_network_info())
            self.assertRaises(exception.NovaException,
                              self.driver.plug_vifs, instance,
                              network_info)

            # asserts
            mock_uvifs.assert_called_once_with(instance, network_info)
            mock_get.assert_called_once_with(node_uuid)
            mock_lp.assert_called_once_with(node_uuid)
            # assert port.update() was not called
            assert not mock_update.called

    def test_plug_vifs_no_network_info(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(uuid=node_uuid)
        port = get_test_port()

        mock_get = mock.patch.object(FAKE_CLIENT.node, 'get').start()
        mock_get.return_value = node
        self.addCleanup(mock_get.stop)
        mock_uvifs = mock.patch.object(self.driver, 'unplug_vifs').start()
        self.addCleanup(mock_uvifs.stop)
        mock_update = mock.patch.object(FAKE_CLIENT.port, 'update').start()
        self.addCleanup(mock_update.stop)

        with mock.patch.object(FAKE_CLIENT.node, 'list_ports') as mock_lp:
            mock_lp.return_value = [port]

            instance = fake_instance.fake_instance_obj(self.ctx,
                                                       node=node_uuid)
            network_info = []
            self.driver.plug_vifs(instance, network_info)

            # asserts
            mock_uvifs.assert_called_once_with(instance, network_info)
            mock_get.assert_called_once_with(node_uuid)
            mock_lp.assert_called_once_with(node_uuid)
            # assert port.update() was not called
            assert not mock_update.called

    def test_unplug_vifs(self):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = get_test_node(uuid=node_uuid)
        port = get_test_port()

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
