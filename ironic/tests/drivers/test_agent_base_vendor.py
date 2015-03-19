# -*- coding: utf-8 -*-
#
# Copyright 2015 Red Hat, Inc.
# All Rights Reserved.
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

import mock

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import agent_base_vendor
from ironic.drivers.modules import agent_client
from ironic.drivers.modules import deploy_utils
from ironic import objects
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as object_utils

INSTANCE_INFO = db_utils.get_test_agent_instance_info()
DRIVER_INFO = db_utils.get_test_agent_driver_info()
DRIVER_INTERNAL_INFO = db_utils.get_test_agent_driver_internal_info()


class TestBaseAgentVendor(db_base.DbTestCase):

    def setUp(self):
        super(TestBaseAgentVendor, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_agent")
        self.passthru = agent_base_vendor.BaseAgentVendor()
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

    def test_lookup_version_not_found(self):
        kwargs = {
            'version': '999',
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.passthru.lookup,
                              task.context,
                              **kwargs)

    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
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
    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
                '._get_node_id')
    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
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

    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
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
    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
                '._get_node_id')
    @mock.patch('ironic.drivers.modules.agent_base_vendor.BaseAgentVendor'
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
    @mock.patch.object(agent_base_vendor.BaseAgentVendor, 'deploy_is_done')
    @mock.patch.object(agent_base_vendor.LOG, 'exception')
    def test_heartbeat_deploy_done_fails(self, log_mock, done_mock,
                                         failed_mock):
        kwargs = {
            'agent_url': 'http://127.0.0.1:9999/bar'
        }
        done_mock.side_effect = Exception('LlamaException')
        with task_manager.acquire(
                self.context, self.node['uuid'], shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.target_provision_state = states.ACTIVE
            self.passthru.heartbeat(task, **kwargs)
            failed_mock.assert_called_once_with(task, mock.ANY)
        log_mock.assert_called_once_with(
            'Asynchronous exception for node '
            '1be26c0b-03f2-4d2e-ae87-c02d7f33c123: Failed checking if deploy '
            'is done. exception: LlamaException')

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

    @mock.patch.object(manager_utils, 'node_power_action')
    def test_reboot_and_finish_deploy_success(self, node_power_action_mock):
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.reboot_and_finish_deploy(task)
            node_power_action_mock.assert_called_once_with(task, states.REBOOT)
            self.assertEqual(states.ACTIVE, task.node.provision_state)
            self.assertEqual(states.NOSTATE, task.node.target_provision_state)

    @mock.patch.object(manager_utils, 'node_power_action')
    def test_reboot_and_finish_deploy_reboot_failure(self,
                                                     node_power_action_mock):
        exc = exception.PowerStateFailure(pstate=states.REBOOT)
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        node_power_action_mock.side_effect = exc
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              self.passthru.reboot_and_finish_deploy, task)
            node_power_action_mock.assert_any_call(task, states.REBOOT)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader')
    @mock.patch.object(deploy_utils, 'try_set_boot_device')
    def test_configure_local_boot(self, try_set_boot_device_mock,
                                   install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.configure_local_boot(task, 'some-root-uuid')
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK)
            install_bootloader_mock.assert_called_once_with(
                task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None)

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader')
    @mock.patch.object(deploy_utils, 'try_set_boot_device')
    def test_configure_local_boot_uefi(self, try_set_boot_device_mock,
                                       install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.configure_local_boot(
                task, root_uuid='some-root-uuid',
                efi_system_part_uuid='efi-system-part-uuid')
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK)
            install_bootloader_mock.assert_called_once_with(
                task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid='efi-system-part-uuid')

    @mock.patch.object(agent_client.AgentClient, 'install_bootloader')
    def test_configure_local_boot_boot_loader_install_fail(
            self, install_bootloader_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'FAILED', 'command_error': 'boom'}
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              self.passthru.configure_local_boot,
                              task, 'some-root-uuid')
            install_bootloader_mock.assert_called_once_with(
                task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(deploy_utils, 'try_set_boot_device')
    @mock.patch.object(agent_client.AgentClient, 'install_bootloader')
    def test_configure_local_boot_set_boot_device_fail(
            self, install_bootloader_mock, try_set_boot_device_mock):
        install_bootloader_mock.return_value = {
            'command_status': 'SUCCESS', 'command_error': None}
        try_set_boot_device_mock.side_effect = RuntimeError('error')
        self.node.provision_state = states.DEPLOYING
        self.node.target_provision_state = states.ACTIVE
        self.node.save()
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.assertRaises(exception.InstanceDeployFailure,
                              self.passthru.configure_local_boot,
                              task, 'some-root-uuid')
            install_bootloader_mock.assert_called_once_with(
                task.node, root_uuid='some-root-uuid',
                efi_system_part_uuid=None)
            try_set_boot_device_mock.assert_called_once_with(
                task, boot_devices.DISK)
            self.assertEqual(states.DEPLOYFAIL, task.node.provision_state)
            self.assertEqual(states.ACTIVE, task.node.target_provision_state)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       '_notify_conductor_resume_clean')
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_continue_cleaning(self, status_mock, notify_mock):
        status_mock.return_value = [{
            'command_status': 'SUCCEEDED',
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.continue_cleaning(task)
            notify_mock.assert_called_once_with(task)

    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       '_notify_conductor_resume_clean')
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_continue_cleaning_running(self, status_mock, notify_mock):
        status_mock.return_value = [{
            'command_status': 'RUNNING',
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.continue_cleaning(task)
            notify_mock.assert_not_called()

    @mock.patch('ironic.conductor.manager.cleaning_error_handler')
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_continue_cleaning_fail(self, status_mock, error_mock):
        status_mock.return_value = [{
            'command_status': 'FAILED',
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.continue_cleaning(task)
            error_mock.assert_called_once_with(task, mock.ANY)

    @mock.patch('ironic.conductor.manager.set_node_cleaning_steps')
    @mock.patch.object(agent_base_vendor.BaseAgentVendor,
                       '_notify_conductor_resume_clean')
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_continue_cleaning_clean_version_mismatch(
            self, status_mock, notify_mock, steps_mock):
        status_mock.return_value = [{
            'command_status': 'CLEAN_VERSION_MISMATCH',
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.continue_cleaning(task)
            steps_mock.assert_called_once_with(task)
            notify_mock.assert_called_once_with(task)

    @mock.patch('ironic.conductor.manager.cleaning_error_handler')
    @mock.patch.object(agent_client.AgentClient, 'get_commands_status')
    def test_continue_cleaning_unknown(self, status_mock, error_mock):
        status_mock.return_value = [{
            'command_status': 'UNKNOWN',
        }]
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.passthru.continue_cleaning(task)
            error_mock.assert_called_once_with(task, mock.ANY)
