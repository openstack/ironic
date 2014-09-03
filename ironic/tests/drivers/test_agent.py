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
from oslo.config import cfg

from ironic.common import dhcp_factory
from ironic.common import exception
from ironic.common import pxe_utils
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import agent
from ironic import objects
from ironic.openstack.common import context
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils


INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()

CONF = cfg.CONF


class TestAgentDeploy(db_base.DbTestCase):
    def setUp(self):
        super(TestAgentDeploy, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_agent')
        self.driver = agent.AgentDeploy()
        self.context = context.get_admin_context()
        n = {
            'driver': 'fake_agent',
            'instance_info': INSTANCE_INFO,
            'driver_info': DRIVER_INFO
        }
        self.node = object_utils.create_test_node(self.context, **n)

    def test_validate(self):
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=False) as task:
            self.driver.validate(task)

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
        mgr_utils.mock_the_extension_manager(driver="fake_pxe")
        self.passthru = agent.AgentVendorInterface()
        self.context = context.get_admin_context()
        n = {
              'driver': 'fake_pxe',
              'instance_info': INSTANCE_INFO,
              'driver_info': DRIVER_INFO
        }
        self.node = object_utils.create_test_node(self.context, **n)

    def test_validate(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.passthru.validate(task)

    @mock.patch('ironic.common.image_service.Service')
    def test_continue_deploy(self, image_service_mock):
        test_temp_url = 'http://image'
        expected_image_info = {
            'urls': [test_temp_url],
            'id': 'fake-image',
            'checksum': 'checksum'
        }

        client_mock = mock.Mock()
        glance_mock = mock.Mock()
        glance_mock.show.return_value = {}
        glance_mock.swift_temp_url.return_value = test_temp_url
        image_service_mock.return_value = glance_mock

        self.passthru._client = client_mock
        with task_manager.acquire(self.context, self.node.uuid,
                                      shared=False) as task:
            self.passthru._continue_deploy(task)

            client_mock.prepare_image.assert_called_with(task.node,
                expected_image_info)
            self.assertEqual(task.node.provision_state, states.DEPLOYING)

    def test_lookup_version_not_found(self):
        kwargs = {
            'version': '999',
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru._lookup,
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
            node = self.passthru._lookup(task.context, **kwargs)
        self.assertEqual(self.node, node['node'])

    def test_lookup_v2_missing_inventory(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru._lookup,
                              task.context)

    def test_lookup_v2_empty_inventory(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru._lookup,
                              task.context,
                              inventory={})

    def test_lookup_v2_empty_interfaces(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.NodeNotFound,
                              self.passthru._lookup,
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

    def test_heartbeat(self):
        kwargs = {
            'agent_url': 'http://127.0.0.1:9999/bar'
        }
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            self.passthru._heartbeat(task, **kwargs)
