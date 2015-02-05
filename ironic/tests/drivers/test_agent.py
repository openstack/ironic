# Copyright 2014 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock
from oslo_config import cfg

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import keystone
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic.drivers.modules import deploy_utils
from ironic import objects
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils


INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()
DRIVER_INTERNAL_INFO = db_utils.get_test_agent_driver_internal_info()

CONF = cfg.CONF


class TestAgentMethods(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentMethods, self).setUp()
        self.node = object_utils.create_test_node(self.context,
                                                  driver='fake_agent')

    def test_build_agent_options_conf(self):
        self.config(api_url='api-url', group='conductor')
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])

    @mock.patch.object(keystone, 'get_service_url')
    def test_build_agent_options_keystone(self, get_url_mock):

        self.config(api_url=None, group='conductor')
        get_url_mock.return_value = 'api-url'
        options = agent.build_agent_options(self.node)
        self.assertEqual('api-url', options['ipa-api-url'])
        self.assertEqual('fake_agent', options['ipa-driver-name'])


class TestAgentDeploy(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentDeploy, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        self.driver = agent.AgentDeploy()
        n = {
            'driver': 'fake_agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO,
            'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    def test_validate(self):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)

    def test_validate_driver_info_missing_params(self):
        self.node.driver_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            e = self.assertRaises(exception.MissingParameterValue,
                                  self.driver.validate, task)
        self.assertIn('driver_info.deploy_ramdisk', str(e))
        self.assertIn('driver_info.deploy_kernel', str(e))

    def test_validate_instance_info_missing_params(self):
        self.node.instance_info = {}
        self.node.save()
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            e = self.assertRaises(exception.MissingParameterValue,
                                  self.driver.validate, task)
        self.assertIn('instance_info.image_source', str(e))

    @mock.patch.object(dhcp_factory.DHCPFactory, 'update_dhcp')
    @mock.patch('ironic.conductor.utils.node_set_boot_device')
    @mock.patch('ironic.conductor.utils.node_power_action')
    def test_deploy(self, power_mock, bootdev_mock, dhcp_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            dhcp_opts = pxe_utils.dhcp_options_for_instance(task)
            driver_return = self.driver.deploy(task)
            self.assertEqual(driver_return, states.DEPLOYWAIT)
            dhcp_mock.assert_called_once_with(task, dhcp_opts)
            bootdev_mock.assert_called_once_with(task, 'pxe', persistent=True)
            power_mock.assert_called_once_with(task,
                                               states.REBOOT)

    @mock.patch('ironic.conductor.utils.node_power_action')
    def test_tear_down(self, power_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            driver_return = self.driver.tear_down(task)
            power_mock.assert_called_once_with(task, states.POWER_OFF)
            self.assertEqual(driver_return, states.DELETED)

    def test_prepare(self):
        pass

    def test_clean_up(self):
        pass

    @mock.patch.object(dhcp_factory.DHCPFactory, 'update_dhcp')
    def test_take_over(self, update_dhcp_mock):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            task.driver.deploy.take_over(task)
            update_dhcp_mock.assert_called_once_with(
                task, CONF.agent.agent_pxe_bootfile_name)


class TestAgentVendor(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentVendor, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_agent")
        self.passthru = agent.AgentVendorInterface()
        n = {
              'driver': 'fake_agent',
              'instance_info': INSTANCE_INFO,
              'driver_info': DRIVER_INFO,
              'driver_internal_info': DRIVER_INTERNAL_INFO,
        }
        self.node = object_utils.create_test_node(self.context, **n)

    def test_validate(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            method = 'heartbeat'
            self.passthru.validate(task, method)

    def test_driver_validate(self):
        kwargs = {'version': '2'}
        method = 'lookup'
        self.passthru.driver_validate(method, **kwargs)

    def test_driver_validate_invalid_paremeter(self):
        method = 'lookup'
        kwargs = {'version': '1'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.passthru.driver_validate,
                          method, **kwargs)

    def test_driver_validate_missing_parameter(self):
        method = 'lookup'
        kwargs = {}
        self.assertRaises(exception.MissingParameterValue,
                          self.passthru.driver_validate,
                          method, **kwargs)

    def test_continue_deploy(self):
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
        }

        client_mock = mock.Mock()
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru._continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                expected_image_info)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    def test_continue_deploy_image_source_is_url(self):
        self.node.instance_info['image_source'] = 'glance://fake-image'
        self.node.provision_state = states.DEPLOYWAIT
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'checksum': 'checksum',
            'disk_format': 'qcow2',
            'container_format': 'bare',
        }

        client_mock = mock.Mock()
        self.passthru._client = client_mock

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru._continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                expected_image_info)
            self.assertEqual(states.DEPLOYING, task.node.provision_state)
            self.assertEqual(states.ACTIVE,
                             task.node.target_provision_state)

    @mock.patch('ironic.conductor.utils.node_power_action')
    @mock.patch('ironic.conductor.utils.node_set_boot_device')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._check_deploy_success')
    def test__reboot_to_instance(self, check_deploy_mock, bootdev_mock,
                                 power_mock):
        check_deploy_mock.return_value = None

        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru._reboot_to_instance(task)

            check_deploy_mock.assert_called_once_with(task.node)
            bootdev_mock.assert_called_once_with(task, 'disk', persistent=True)
            power_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    def test_lookup_version_not_found(self):
        kwargs = {
            'version': '999',
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru.lookup,
                              task.context,
                              **kwargs)

    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._find_node_by_macs')
    def test_lookup_v2(self, find_mock):
        kwargs = {
            'version': '2',
            'inventory': {
                'interfaces': [
                    {
                        'mac_address': 'aa:bb:cc:dd:ee:ff',
                        'name': 'eth0'
                    },
                    {
                        'mac_address': 'ff:ee:dd:cc:bb:aa',
                        'name': 'eth1'
                    }

                ]
            }
        }
        find_mock.return_value = self.node
        with task_manager.acquire(self.context, self.node.uuid) as task:
            node = self.passthru.lookup(task.context, **kwargs)
        self.assertEqual(self.node, node['node'])

    def test_lookup_v2_missing_inventory(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru.lookup,
                              task.context)

    def test_lookup_v2_empty_inventory(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru.lookup,
                              task.context,
                              inventory={})

    def test_lookup_v2_empty_interfaces(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.NodeNotFound,
                              self.passthru.lookup,
                              task.context,
                              version='2',
                              inventory={'interfaces': []})

    @mock.patch.object(objects.Port, 'get_by_address')
    def test_find_ports_by_macs(self, mock_get_port):
        fake_port = object_utils.get_test_port(self.context)
        mock_get_port.return_value = fake_port

        macs = ['aa:bb:cc:dd:ee:ff']

        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            ports = self.passthru._find_ports_by_macs(task, macs)
        self.assertEqual(1, len(ports))
        self.assertEqual(fake_port.uuid, ports[0].uuid)
        self.assertEqual(fake_port.node_id, ports[0].node_id)

    @mock.patch.object(objects.Port, 'get_by_address')
    def test_find_ports_by_macs_bad_params(self, mock_get_port):
        mock_get_port.side_effect = exception.PortNotFound(port="123")

        macs = ['aa:bb:cc:dd:ee:ff']
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            empty_ids = self.passthru._find_ports_by_macs(task, macs)
        self.assertEqual([], empty_ids)

    @mock.patch('ironic.objects.node.Node.get_by_id')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._get_node_id')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._find_ports_by_macs')
    def test_find_node_by_macs(self, ports_mock, node_id_mock, node_mock):
        ports_mock.return_value = object_utils.get_test_port(self.context)
        node_id_mock.return_value = '1'
        node_mock.return_value = self.node

        macs = ['aa:bb:cc:dd:ee:ff']
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            node = self.passthru._find_node_by_macs(task, macs)
        self.assertEqual(node, node)

    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._find_ports_by_macs')
    def test_find_node_by_macs_no_ports(self, ports_mock):
        ports_mock.return_value = []

        macs = ['aa:bb:cc:dd:ee:ff']
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            self.assertRaises(exception.NodeNotFound,
                              self.passthru._find_node_by_macs,
                              task,
                              macs)

    @mock.patch('ironic.objects.node.Node.get_by_uuid')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._get_node_id')
    @mock.patch('ironic.drivers.modules.agent.AgentVendorInterface'
                '._find_ports_by_macs')
    def test_find_node_by_macs_nodenotfound(self, ports_mock, node_id_mock,
                                            node_mock):
        port = object_utils.get_test_port(self.context)
        ports_mock.return_value = [port]
        node_id_mock.return_value = self.node['uuid']
        node_mock.side_effect = [self.node,
                                 exception.NodeNotFound(node=self.node)]

        macs = ['aa:bb:cc:dd:ee:ff']
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            self.assertRaises(exception.NodeNotFound,
                              self.passthru._find_node_by_macs,
                              task,
                              macs)

    def test_get_node_id(self):
        fake_port1 = object_utils.get_test_port(self.context,
                                                node_id=123,
                                                address="aa:bb:cc:dd:ee:fe")
        fake_port2 = object_utils.get_test_port(self.context,
                                                node_id=123,
                                                id=42,
                                                address="aa:bb:cc:dd:ee:fb",
                                                uuid='1be26c0b-03f2-4d2e-ae87-'
                                                     'c02d7f33c782')

        node_id = self.passthru._get_node_id([fake_port1, fake_port2])
        self.assertEqual(fake_port2.node_id, node_id)

    def test_get_node_id_exception(self):
        fake_port1 = object_utils.get_test_port(self.context,
                                                node_id=123,
                                                address="aa:bb:cc:dd:ee:fc")
        fake_port2 = object_utils.get_test_port(self.context,
                                                node_id=321,
                                                id=42,
                                                address="aa:bb:cc:dd:ee:fd",
                                                uuid='1be26c0b-03f2-4d2e-ae87-'
                                                     'c02d7f33c782')

        self.assertRaises(exception.NodeNotFound,
                          self.passthru._get_node_id,
                          [fake_port1, fake_port2])

    def test_get_interfaces(self):
        fake_inventory = {
            'interfaces': [
                {
                    'mac_address': 'aa:bb:cc:dd:ee:ff',
                    'name': 'eth0'
                }
            ]
        }
        interfaces = self.passthru._get_interfaces(fake_inventory)
        self.assertEqual(fake_inventory['interfaces'], interfaces)

    def test_get_interfaces_bad(self):
        self.assertRaises(exception.InvalidParameterValue,
                          self.passthru._get_interfaces,
                          inventory={})

    def test_heartbeat(self):
        kwargs = {
            'agent_url': 'http://127.0.0.1:9999/bar'
        }
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            self.passthru.heartbeat(task, **kwargs)

    def test_heartbeat_bad(self):
        kwargs = {}
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.passthru.heartbeat, task, **kwargs)

    @mock.patch.object(deploy_utils, 'set_failed_state')
    @mock.patch.object(agent.AgentVendorInterface, '_deploy_is_done')
    def test_heartbeat_deploy_done_fails(self, done_mock, failed_mock):
        kwargs = {
            'agent_url': 'http://127.0.0.1:9999/bar'
        }
        done_mock.side_effect = Exception
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.target_provision_state = states.ACTIVE
            self.passthru.heartbeat(task, **kwargs)
            failed_mock.assert_called_once_with(task, mock.ANY)

    def test_vendor_passthru_vendor_routes(self):
        expected = ['heartbeat']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(expected, list(vendor_routes))

    def test_vendor_passthru_driver_routes(self):
        expected = ['lookup']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_routes = task.driver.vendor.driver_routes
            self.assertIsInstance(driver_routes, dict)
            self.assertEqual(expected, list(driver_routes))
