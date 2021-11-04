# Copyright 2017 Red Hat, Inc.
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

from unittest import mock

from oslo_utils import importutils
from oslo_utils import units

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import inspect
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


class MockedSushyError(Exception):
    pass


class RedfishInspectTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishInspectTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)

    def init_system_mock(self, system_mock, **properties):

        system_mock.reset()

        system_mock.boot.mode = sushy.BOOT_SOURCE_MODE_UEFI

        system_mock.memory_summary.size_gib = 2

        system_mock.processors.summary = '8', sushy.PROCESSOR_ARCH_MIPS

        system_mock.simple_storage.disks_sizes_bytes = (
            1 * units.Gi, units.Gi * 3, units.Gi * 5)
        system_mock.storage.volumes_sizes_bytes = (
            2 * units.Gi, units.Gi * 4, units.Gi * 6)

        system_mock.ethernet_interfaces.summary = {
            '00:11:22:33:44:55': sushy.STATE_ENABLED,
            '66:77:88:99:AA:BB': sushy.STATE_DISABLED,
        }

        return system_mock

    def test_get_properties(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            properties = task.driver.get_properties()
            for prop in redfish_utils.COMMON_PROPERTIES:
                self.assertIn(prop, properties)

    @mock.patch.object(redfish_utils, 'parse_driver_info', autospec=True)
    def test_validate(self, mock_parse_driver_info):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.management.validate(task)
            mock_parse_driver_info.assert_called_once_with(task.node)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_hardware_ok(self, mock_create_ports_if_not_exist,
                                 mock_get_system):
        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'mips', 'cpus': '8',
            'local_gb': '3', 'memory_mb': '2048'
        }

        self.init_system_mock(mock_get_system.return_value)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(1, mock_create_ports_if_not_exist.call_count)
            mock_get_system.assert_called_once_with(task.node)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_port_creation(self, mock_create_ports_if_not_exist,
                                   mock_get_system):
        self.init_system_mock(mock_get_system.return_value)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            result = task.driver.management.get_mac_addresses(task)
            inspect_utils.create_ports_if_not_exist.assert_called_once_with(
                task, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_fail_missing_cpu(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.processors.summary = None, None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties.pop('cpu_arch')
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpu(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.processors.summary = None, None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_properties = {
                'capabilities': 'boot_mode:uefi',
                'cpu_arch': 'x86_64', 'cpus': '8',
                'local_gb': '3', 'memory_mb': '2048'
            }
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_local_gb(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.simple_storage.disks_sizes_bytes = None
        system_mock.storage.volumes_sizes_bytes = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_properties = {
                'capabilities': 'boot_mode:uefi',
                'cpu_arch': 'mips', 'cpus': '8',
                'local_gb': '0', 'memory_mb': '2048'
            }
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_fail_missing_memory_mb(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.memory_summary.size_gib = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties.pop('memory_mb')
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_memory_mb(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.memory_summary.size_gib = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_properties = {
                'capabilities': 'boot_mode:uefi',
                'cpu_arch': 'mips', 'cpus': '8',
                'local_gb': '3', 'memory_mb': '4096'
            }
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_hardware_ignore_missing_nics(
            self, mock_create_ports_if_not_exist, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.ethernet_interfaces.summary = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertFalse(mock_create_ports_if_not_exist.called)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_preserve_boot_mode(self, mock_get_system):
        self.init_system_mock(mock_get_system.return_value)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties = {
                'capabilities': 'boot_mode:bios'
            }
            expected_properties = {
                'capabilities': 'boot_mode:bios',
                'cpu_arch': 'mips', 'cpus': '8',
                'local_gb': '3', 'memory_mb': '2048'
            }
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_boot_mode(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.boot.mode = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_properties = {
                'cpu_arch': 'mips', 'cpus': '8',
                'local_gb': '3', 'memory_mb': '2048'
            }
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(expected_properties, task.node.properties)

    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_set_port_pxe_enabled(
            self, mock_get_system, mock_list_by_node_id):
        self.init_system_mock(mock_get_system.return_value)

        pxe_disabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid, node_id=self.node.id,
            address='24:6E:96:70:49:00', pxe_enabled=False)
        mock_list_by_node_id.return_value = [pxe_disabled_port]
        port = mock_list_by_node_id.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = \
                ['24:6E:96:70:49:00']
            task.driver.inspect.inspect_hardware(task)
            self.assertTrue(port[0].pxe_enabled)

    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_set_port_pxe_disabled(
            self, mock_get_system, mock_list_by_node_id):
        self.init_system_mock(mock_get_system.return_value)

        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='24:6E:96:70:49:01',
            pxe_enabled=True)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = \
                ['24:6E:96:70:49:00']
            task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertFalse(port[0].pxe_enabled)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_no_mac(self, mock_get_system):
        self.init_system_mock(mock_get_system.return_value)
        system = mock_get_system.return_value
        system.ethernet_interfaces.summary = {
            '00:11:22:33:44:55': sushy.STATE_ENABLED,
            '': sushy.STATE_ENABLED,
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            ports = objects.Port.list_by_node_id(task.context, self.node.id)
            self.assertEqual(1, len(ports))

    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_empty_pxe_port_macs(
            self, mock_get_system, mock_list_by_node_id):
        self.init_system_mock(mock_get_system.return_value)

        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='24:6E:96:70:49:01',
            pxe_enabled=True)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = []
            return_value = task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertFalse(port[0].pxe_enabled)
            self.assertEqual(states.MANAGEABLE, return_value)

    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect.LOG, 'warning', autospec=True)
    def test_inspect_hardware_with_none_pxe_port_macs(
            self, mock_log, mock_get_system, mock_list_by_node_id):
        self.init_system_mock(mock_get_system.return_value)

        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='24:6E:96:70:49:01',
            pxe_enabled=True)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = None
            task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertTrue(port[0].pxe_enabled)
            mock_log.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_create_port_when_its_state_is_none(self, mock_get_system):
        self.init_system_mock(mock_get_system.return_value)
        expected_port_mac_list = ["00:11:22:33:44:55", "24:6e:96:70:49:00"]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            ports = objects.Port.list_by_node_id(task.context, self.node.id)
            for port in ports:
                self.assertIn(port.address, expected_port_mac_list)

    def test_get_pxe_port_macs(self):
        expected_properties = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs(task)
            self.assertEqual(expected_properties,
                             task.driver.inspect._get_pxe_port_macs(task))
