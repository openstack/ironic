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

from oslo_utils import units
import sushy

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conf import CONF
from ironic.drivers.modules import inspect_utils
from ironic.drivers.modules.redfish import inspect
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic import objects
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

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
            self.context, driver='redfish', driver_info=INFO_DICT,
            provision_state=states.MANAGEABLE)

    def init_system_mock(self, system_mock, **properties):

        system_mock.reset()

        system_mock.boot.mode = sushy.BOOT_SOURCE_MODE_UEFI

        system_mock.memory_summary.size_gib = 2

        mock_processor = mock.Mock(
            spec=sushy.resources.system.processor.Processor)
        mock_processor.model = 'test'
        mock_processor.processor_architecture = sushy.PROCESSOR_ARCH_x86
        mock_processor.instruction_set = sushy.InstructionSet.X86_64
        mock_processor.max_speed_mhz = 1234
        mock_processor.total_threads = 8
        system_mock.processors.get_members.return_value = [mock_processor]

        # make the summary follow the data above by making it
        # a property like sushy and returning the same data
        type(system_mock.processors).summary = mock.PropertyMock(
            side_effect=lambda:
                sushy.resources.system.processor.ProcessorSummary(
                    count=mock_processor.total_threads,
                    architecture=mock_processor.processor_architecture
                )
        )

        mock_storage_drive = mock.Mock(
            spec=sushy.resources.system.storage.drive.Drive)
        mock_storage_drive.name = 'storage-drive'
        mock_storage_drive.capacity_bytes = '128'

        mock_storage = mock.Mock(
            spec=sushy.resources.system.storage.storage.Storage)
        mock_storage.drives = [mock_storage_drive]
        system_mock.storage.get_members.return_value = [
            mock_storage]

        mock_simple_storage_device = mock.Mock(
            spec=sushy.resources.system.simple_storage.DeviceListField)
        mock_simple_storage_device.name = 'test-name'
        mock_simple_storage_device.capacity_bytes = '123'

        mock_simple_storage = mock.Mock(
            spec=sushy.resources.system.simple_storage.SimpleStorage)
        mock_simple_storage.devices = [mock_simple_storage_device]
        system_mock.simple_storage.get_members.return_value = [
            mock_simple_storage]

        system_mock.simple_storage.disks_sizes_bytes = (
            1 * units.Gi, units.Gi * 3, units.Gi * 5)
        system_mock.storage.volumes_sizes_bytes = (
            2 * units.Gi, units.Gi * 4, units.Gi * 6)

        eth_interface_mock1 = mock.Mock(
            spec=sushy.resources.system.ethernet_interface.EthernetInterface)
        eth_interface_mock1.identity = 'NIC.Integrated.1-1'
        eth_interface_mock1.mac_address = '00:11:22:33:44:55'
        eth_interface_mock1.speed_mbps = 25000
        eth_interface_mock1.status.state = sushy.STATE_ENABLED
        eth_interface_mock1.status.health = sushy.HEALTH_OK

        eth_interface_mock2 = mock.Mock(
            spec=sushy.resources.system.ethernet_interface.EthernetInterface)
        eth_interface_mock2.identity = 'NIC.Integrated.2-1'
        eth_interface_mock2.mac_address = '66:77:88:99:AA:BB'
        eth_interface_mock2.speed_mbps = 25000
        eth_interface_mock2.status.state = sushy.STATE_DISABLED
        eth_interface_mock2.status.health = sushy.HEALTH_OK

        system_mock.ethernet_interfaces.get_members.return_value = [
            eth_interface_mock1,
            eth_interface_mock2
        ]

        # make the summary follow the data above by making it
        # a property like sushy and returning the same data
        type(system_mock.ethernet_interfaces).summary = mock.PropertyMock(
            side_effect=lambda: {
                obj.mac_address: obj.status.state
                for obj in
                system_mock.ethernet_interfaces.get_members.return_value
            }
        )

        # PCIe device mocks
        mock_pcie_function1 = mock.Mock()
        mock_pcie_function1.device_class = 'NetworkController'
        mock_pcie_function1.device_id = '0x16d7'
        mock_pcie_function1.vendor_id = '0x14e4'
        mock_pcie_function1.subsystem_id = '0x1402'
        mock_pcie_function1.subsystem_vendor_id = '0x14e4'
        mock_pcie_function1.revision_id = '0x01'

        mock_pcie_function2 = mock.Mock()
        mock_pcie_function2.device_class = 'MassStorageController'
        mock_pcie_function2.device_id = '0x1234'
        mock_pcie_function2.vendor_id = '0x1000'
        mock_pcie_function2.subsystem_id = None
        mock_pcie_function2.subsystem_vendor_id = None
        mock_pcie_function2.revision_id = '0x02'

        mock_pcie_device1 = mock.Mock()
        mock_pcie_device1.pcie_functions.get_members.return_value = [
            mock_pcie_function1]

        mock_pcie_device2 = mock.Mock()
        mock_pcie_device2.pcie_functions.get_members.return_value = [
            mock_pcie_function2]

        system_mock.pcie_devices.get_members.return_value = [
            mock_pcie_device1,
            mock_pcie_device2
        ]

        system_mock.name = 'System1'

        system_mock.serial_number = '123456'

        system_mock.manufacturer = 'Sushy Emulator'

        system_mock.sku = 'DELL123456'

        system_mock.uuid = '12345678-1234-1234-1234-12345'

        system_mock.model = 'PowerEdge R1234'

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

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_hardware_ok(self, mock_create_ports_if_not_exist,
                                 mock_get_system,
                                 mock_get_enabled_macs):
        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': 2048,
        }
        self.init_system_mock(mock_get_system.return_value)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            self.assertEqual(1, mock_create_ports_if_not_exist.call_count)
            mock_get_system.assert_called_once_with(task.node)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)

        system_vendor = inventory['inventory']['system_vendor']
        expected_product_name = 'PowerEdge R1234'
        expected_serial_number = '123456'
        expected_manufacturer = 'Sushy Emulator'
        expected_sku = 'DELL123456'
        expected_system_uuid = '12345678-1234-1234-1234-12345'
        self.assertEqual(expected_product_name,
                         system_vendor['product_name'])
        self.assertEqual(expected_serial_number,
                         system_vendor['serial_number'])
        self.assertEqual(expected_manufacturer,
                         system_vendor['manufacturer'])
        self.assertEqual(expected_sku,
                         system_vendor['sku'])
        self.assertEqual(expected_system_uuid,
                         system_vendor['system_uuid'])

        expected_interfaces = [{'mac_address': '00:11:22:33:44:55',
                                'name': 'NIC.Integrated.1-1',
                                'speed_mbps': 25000},
                               {'mac_address': '66:77:88:99:AA:BB',
                                'name': 'NIC.Integrated.2-1',
                                'speed_mbps': 25000}]
        self.assertEqual(expected_interfaces,
                         inventory['inventory']['interfaces'])

        expected_cpu = {'count': 8, 'model_name': 'test',
                        'frequency': 1234, 'architecture': 'x86_64'}
        self.assertEqual(expected_cpu,
                         inventory['inventory']['cpu'])

        expected_disks = [{'name': 'storage-drive', 'size': '128'}]
        self.assertEqual(expected_disks,
                         inventory["inventory"]['disks'])

        expected_pcie_devices = [
            {'class': 'NetworkController',
             'product_id': '0x16d7',
             'vendor_id': '0x14e4',
             'subsystem_id': '0x1402',
             'subsystem_vendor_id': '0x14e4',
             'revision': '0x01'},
            {'class': 'MassStorageController',
             'product_id': '0x1234',
             'vendor_id': '0x1000',
             'revision': '0x02'}
        ]
        self.assertEqual(expected_pcie_devices,
                         inventory['inventory']['pci_devices'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_port_creation(self, mock_create_ports_if_not_exist,
                                   mock_get_system,
                                   mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            result = task.driver.management.get_mac_addresses(task)
            inspect_utils.create_ports_if_not_exist.assert_called_once_with(
                task, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_fail_missing_cpu_arch(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_processor = system_mock.processors.get_members.return_value[0]
        mock_processor.processor_architecture = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties.pop('cpu_arch')
            # self.assertRaises(exception.HardwareInspectionFailure,
            #                  task.driver.inspect.inspect_hardware, task)
            # TODO(cardoe):
            # not a valid test currently because the normal inspection
            # path requires that architecture is filled out and populates
            # any value so this passes so need to reconcile that behavior
            # difference and return here.
            task.driver.inspect.inspect_hardware(task)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpu_count(self, mock_get_system,
                                                       mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_processor = system_mock.processors.get_members.return_value[0]
        mock_processor.total_threads = 0

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64', 'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertIn('count', inventory['inventory']['cpu'])
        self.assertEqual(0, inventory['inventory']['cpu']['count'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpu_model(self, mock_get_system,
                                                       mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_processor = system_mock.processors.get_members.return_value[0]
        mock_processor.model = None

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('model', inventory['inventory']['cpu'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpu_frequency(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_processor = system_mock.processors.get_members.return_value[0]
        mock_processor.max_speed_mhz = None

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('frequency', inventory['inventory']['cpu'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpu_instruction_set(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_processor = system_mock.processors.get_members.return_value[0]
        mock_processor.instruction_set = None

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': '',
            'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertIn('architecture', inventory['inventory']['cpu'])
        self.assertEqual('', inventory['inventory']['cpu']['architecture'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_local_gb(self, mock_get_system,
                                                      mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.simple_storage.disks_sizes_bytes = None
        system_mock.storage.volumes_sizes_bytes = None

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '0', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_simple_storage_and_storage(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.simple_storage = {}
        system_mock.storage = {}

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '0', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('disks', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_simple_storage(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.simple_storage = {}

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertIn('disks', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_storage(self, mock_get_system,
                                                     mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.storage = {}

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '4', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertIn('disks', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_fail_missing_memory_mb(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.memory_summary.size_gib = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties.pop('memory_mb')
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_memory_mb(self, mock_get_system,
                                                       mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.memory_summary.size_gib = None

        expected_properties = {
            'capabilities': 'boot_mode:uefi',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': '4096'
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('memory', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    @mock.patch.object(inspect_utils, 'create_ports_if_not_exist',
                       autospec=True)
    def test_inspect_hardware_ignore_missing_nics(
            self, mock_create_ports_if_not_exist, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.ethernet_interfaces.get_members.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)
            self.assertFalse(mock_create_ports_if_not_exist.called)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_cpus(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.processors = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertIn('cpu', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_preserve_boot_mode(self, mock_get_system,
                                                 mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)

        expected_properties = {
            'capabilities': 'boot_mode:bios',
            'cpu_arch': 'x86_64',
            'local_gb': '3', 'memory_mb': 2048
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.properties = {
                'capabilities': 'boot_mode:bios'
            }

            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        expected_boot_mode = {'current_boot_mode': 'uefi'}
        self.assertEqual(expected_boot_mode,
                         inventory['inventory']['boot'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_boot_mode(self, mock_get_system,
                                                       mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.boot.mode = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            expected_properties = {
                'cpu_arch': 'x86_64',
                'local_gb': '3', 'memory_mb': 2048
            }
            task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_properties, self.node.properties)
        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('boot', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_set_port_pxe_enabled(
            self, mock_get_system,
            mock_list_by_node_id,
            mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)

        pxe_disabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid, node_id=self.node.id,
            address='00:11:22:33:44:55', pxe_enabled=False)
        mock_list_by_node_id.return_value = [pxe_disabled_port]
        port = mock_list_by_node_id.return_value
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = \
                ['00:11:22:33:44:55']
            task.driver.inspect.inspect_hardware(task)
            self.assertTrue(port[0].pxe_enabled)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_set_port_pxe_disabled(
            self, mock_get_system,
            mock_list_by_node_id, mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)

        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='00:11:22:33:44:55',
            pxe_enabled=True)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = \
                []
            task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertFalse(port[0].pxe_enabled)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_conf_update_pxe_disabled_false(
            self, mock_get_system,
            mock_list_by_node_id, mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)
        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='00:11:22:33:44:55',
            pxe_enabled=False)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        self.config(update_pxe_enabled=False, group='inspector')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = \
                ['00:11:22:33:44:55']
            task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertFalse(port[0].pxe_enabled)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_no_mac(self, mock_get_system):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_eths = system_mock.ethernet_interfaces.get_members.return_value
        mock_eths[1].mac_address = ''
        mock_eths[1].status.state = sushy.STATE_ENABLED

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            ports = objects.Port.list_by_node_id(task.context, self.node.id)
            self.assertEqual(1, len(ports))

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_empty_pxe_port_macs(
            self, mock_get_system,
            mock_list_by_node_id, mock_get_enabled_macs):
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

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(objects.Port, 'list_by_node_id') # noqa
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_with_none_pxe_port_macs(
            self, mock_get_system,
            mock_list_by_node_id, mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)

        pxe_enabled_port = obj_utils.create_test_port(
            self.context, uuid=self.node.uuid,
            node_id=self.node.id, address='00:11:22:33:44:55',
            pxe_enabled=True)
        mock_list_by_node_id.return_value = [pxe_enabled_port]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs = mock.Mock()
            task.driver.inspect._get_pxe_port_macs.return_value = None
            task.driver.inspect.inspect_hardware(task)
            port = mock_list_by_node_id.return_value
            self.assertFalse(port[0].pxe_enabled)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_create_port_when_its_state_is_none(self, mock_get_system,
                                                mock_get_enabled_macs):
        self.init_system_mock(mock_get_system.return_value)
        expected_port_mac_list = ["00:11:22:33:44:55", "66:77:88:99:aa:bb"]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)
            ports = objects.Port.list_by_node_id(task.context, self.node.id)
            for port in ports:
                self.assertIn(port.address, expected_port_mac_list)

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_system_vendor(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.name = None
        system_mock.serial_number = None
        system_mock.manufacturer = None
        system_mock.sku = None
        system_mock.uuid = None
        system_mock.model = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('system_vendor', inventory['inventory'])

    def test_get_pxe_port_macs(self):
        expected_properties = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect._get_pxe_port_macs(task)
            self.assertEqual(expected_properties,
                             task.driver.inspect._get_pxe_port_macs(task))

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_missing_pcie_devices(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.pcie_devices = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('pci_devices', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_empty_pcie_devices(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        system_mock.pcie_devices.get_members.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('pci_devices', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_ignore_pcie_device_without_functions(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        mock_pcie_device = mock.Mock()
        mock_pcie_device.pcie_functions = None
        system_mock.pcie_devices.get_members.return_value = [mock_pcie_device]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        self.assertNotIn('pci_devices', inventory['inventory'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_inspect_hardware_pcie_partial_data(
            self, mock_get_system, mock_get_enabled_macs):
        system_mock = self.init_system_mock(mock_get_system.return_value)
        # Create a PCIe function with partial data, some fields None
        mock_pcie_function = mock.Mock()
        mock_pcie_function.device_class = 'NetworkController'
        mock_pcie_function.device_id = '0x16d7'
        mock_pcie_function.vendor_id = None
        mock_pcie_function.subsystem_id = '0x1402'
        mock_pcie_function.subsystem_vendor_id = None
        mock_pcie_function.revision_id = '0x01'

        mock_pcie_device = mock.Mock()
        mock_pcie_device.pcie_functions.get_members.return_value = [
            mock_pcie_function]
        system_mock.pcie_devices.get_members.return_value = [mock_pcie_device]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node,
                                                      self.context)
        expected_pcie_devices = [
            {'class': 'NetworkController',
             'product_id': '0x16d7',
             'subsystem_id': '0x1402',
             'revision': '0x01'}
        ]
        self.assertEqual(expected_pcie_devices,
                         inventory['inventory']['pci_devices'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_with_complete_lldp(
            self, mock_get_system, mock_get_enabled_macs):
        """Test LLDP collection with complete LLDP data"""
        system_mock = self.init_system_mock(mock_get_system.return_value)

        # Mock NetworkAdapters and Ports with LLDP data
        mock_chassis = mock.Mock()
        mock_chassis.identity = 'System.Embedded.1'

        # Mock Port with complete LLDP data
        mock_lldp = mock.Mock()
        mock_lldp.chassis_id = 'c4:7e:e0:e4:55:3f'
        mock_lldp.chassis_id_subtype = mock.Mock(value='MacAddr')
        mock_lldp.port_id = 'Ethernet1/8'
        mock_lldp.port_id_subtype = mock.Mock(value='IfName')
        mock_lldp.system_name = 'switch-01.example.com'
        mock_lldp.system_description = 'Cisco IOS XE'
        mock_lldp.system_capabilities = [
            mock.Mock(value='Bridge'),
            mock.Mock(value='Router')]
        mock_lldp.management_address_ipv4 = '192.168.1.1'
        mock_lldp.management_address_ipv6 = None
        mock_lldp.management_address_mac = None
        mock_lldp.management_vlan_id = 100

        mock_ethernet = mock.Mock()
        mock_ethernet.lldp_receive = mock_lldp
        mock_ethernet.associated_mac_addresses = ['14:23:F3:F5:3B:A0']

        mock_port = mock.Mock()
        mock_port.identity = 'NIC.Slot.1-1'
        mock_port.ethernet = mock_ethernet

        mock_adapter = mock.Mock()
        mock_adapter.identity = 'NIC.Slot.1'
        mock_adapter.ports.get_members.return_value = [mock_port]

        mock_chassis.network_adapters.get_members.return_value = [mock_adapter]
        system_mock.chassis = [mock_chassis]

        # Mock ethernet interface for mapping
        mock_iface = mock.Mock()
        mock_iface.identity = 'NIC.Slot.1-1-1'
        mock_iface.mac_address = '14:23:F3:F5:3B:A0'
        system_mock.ethernet_interfaces.get_members.return_value = [mock_iface]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node, self.context)

        # Verify parsed_lldp was collected
        self.assertIn('parsed_lldp', inventory['plugin_data'])
        parsed_lldp = inventory['plugin_data']['parsed_lldp']

        # Should have one interface with LLDP data using Port ID as name
        self.assertEqual(1, len(parsed_lldp))
        self.assertIn('NIC.Slot.1-1', parsed_lldp)

        # Verify parsed LLDP format
        lldp_data = parsed_lldp['NIC.Slot.1-1']
        self.assertIsInstance(lldp_data, dict)
        self.assertIn('switch_chassis_id', lldp_data)
        self.assertIn('switch_port_id', lldp_data)
        self.assertIn('switch_system_name', lldp_data)
        self.assertIn('switch_system_description', lldp_data)

        # Verify expected values
        self.assertEqual('c4:7e:e0:e4:55:3f', lldp_data['switch_chassis_id'])
        self.assertEqual('Ethernet1/8', lldp_data['switch_port_id'])
        self.assertEqual('switch-01.example.com',
                         lldp_data['switch_system_name'])
        self.assertEqual('Cisco IOS XE',
                         lldp_data['switch_system_description'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_empty_lldp_receive(
            self, mock_get_system, mock_get_enabled_macs):
        """Test LLDP collection with empty LLDPReceive (Dell scenario)"""
        system_mock = self.init_system_mock(mock_get_system.return_value)

        mock_chassis = mock.Mock()
        mock_chassis.identity = 'System.Embedded.1'

        # Mock Port with None lldp_receive
        mock_ethernet = mock.Mock()
        mock_ethernet.lldp_receive = None

        mock_port = mock.Mock()
        mock_port.identity = 'NIC.Slot.1-1'
        mock_port.ethernet = mock_ethernet

        mock_adapter = mock.Mock()
        mock_adapter.ports.get_members.return_value = [mock_port]

        mock_chassis.network_adapters.get_members.return_value = [mock_adapter]
        system_mock.chassis = [mock_chassis]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node, self.context)

        # parsed_lldp should not be in plugin_data when empty
        self.assertNotIn('parsed_lldp', inventory['plugin_data'])

    @mock.patch.object(redfish_utils, 'get_enabled_macs', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_collect_lldp_data_no_network_adapters(
            self, mock_get_system, mock_get_enabled_macs):
        """Test LLDP collection when NetworkAdapters not available"""
        system_mock = self.init_system_mock(mock_get_system.return_value)

        mock_chassis = mock.Mock()
        mock_chassis.identity = 'System.Embedded.1'
        # Raise exception when accessing network_adapters
        mock_chassis.network_adapters.get_members.side_effect = (
            Exception('Not found'))
        system_mock.chassis = [mock_chassis]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.inspect.inspect_hardware(task)

        inventory = inspect_utils.get_inspection_data(self.node, self.context)

        # Should handle gracefully and not include parsed_lldp
        self.assertNotIn('parsed_lldp', inventory['plugin_data'])

    def test_convert_lldp_receive_to_dict_complete(self):
        """Test dict conversion with complete LLDP data"""
        mock_lldp = mock.Mock()
        mock_lldp.chassis_id = 'c4:7e:e0:e4:55:3f'
        mock_lldp.chassis_id_subtype = mock.Mock(value='MacAddr')
        mock_lldp.port_id = 'Ethernet1/8'
        mock_lldp.port_id_subtype = mock.Mock(value='IfName')
        mock_lldp.system_name = 'switch-01'
        mock_lldp.system_description = 'Cisco IOS'
        mock_lldp.system_capabilities = [mock.Mock(value='Bridge')]
        mock_lldp.management_address_ipv4 = '192.168.1.1'
        mock_lldp.management_address_ipv6 = None
        mock_lldp.management_address_mac = None
        mock_lldp.management_vlan_id = 100

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            lldp_dict = task.driver.inspect._convert_lldp_receive_to_dict(
                mock_lldp)

        # Verify dict format
        self.assertIsInstance(lldp_dict, dict)
        self.assertIn('switch_chassis_id', lldp_dict)
        self.assertIn('switch_port_id', lldp_dict)
        self.assertIn('switch_system_name', lldp_dict)
        self.assertIn('switch_system_description', lldp_dict)
        self.assertIn('switch_vlan_id', lldp_dict)

        # Verify expected values
        self.assertEqual('c4:7e:e0:e4:55:3f', lldp_dict['switch_chassis_id'])
        self.assertEqual('Ethernet1/8', lldp_dict['switch_port_id'])
        self.assertEqual('switch-01', lldp_dict['switch_system_name'])
        self.assertEqual('Cisco IOS', lldp_dict['switch_system_description'])
        self.assertEqual(100, lldp_dict['switch_vlan_id'])

    def test_convert_lldp_receive_to_dict_minimal(self):
        """Test dict conversion with minimal LLDP data"""
        mock_lldp = mock.Mock()
        mock_lldp.chassis_id = 'aa:bb:cc:dd:ee:ff'
        mock_lldp.chassis_id_subtype = None
        mock_lldp.port_id = 'port-1'
        mock_lldp.port_id_subtype = None
        mock_lldp.system_name = None
        mock_lldp.system_description = None
        mock_lldp.system_capabilities = None
        mock_lldp.management_address_ipv4 = None
        mock_lldp.management_address_ipv6 = None
        mock_lldp.management_address_mac = None
        mock_lldp.management_vlan_id = None

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            lldp_dict = task.driver.inspect._convert_lldp_receive_to_dict(
                mock_lldp)

        # Should have Chassis ID and Port ID only
        self.assertEqual(2, len(lldp_dict))
        self.assertIn('switch_chassis_id', lldp_dict)
        self.assertIn('switch_port_id', lldp_dict)
        self.assertEqual('aa:bb:cc:dd:ee:ff', lldp_dict['switch_chassis_id'])
        self.assertEqual('port-1', lldp_dict['switch_port_id'])



class ContinueInspectionTestCase(db_base.DbTestCase):
    def setUp(self):
        super(ContinueInspectionTestCase, self).setUp()
        CONF.set_override('enabled_inspect_interfaces',
                          ['redfish', 'no-inspect'])
        self.config(inspection_hooks='validate-interfaces,'
                                     'ports,architecture',
                    group='redfish')
        self.config(enabled_hardware_types=['redfish'])
        self.config(enabled_power_interfaces=['redfish'])
        self.config(enabled_management_interfaces=['redfish'])
        self.node = obj_utils.create_test_node(
            self.context,
            driver='redfish',
            inspect_interface='redfish',
            driver_info=INFO_DICT,
            provision_state=states.INSPECTING)
        self.iface = inspect.RedfishInspect()

    def test(self):
        with task_manager.acquire(self.context, self.node.id) as task:
            self.assertRaises(
                exception.UnsupportedDriverExtension,
                self.iface.continue_inspection,
                task,
                mock.sentinel.inventory,
                mock.sentinel.plugin_data
            )
