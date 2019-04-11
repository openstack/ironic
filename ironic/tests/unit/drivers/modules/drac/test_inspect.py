#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test class for DRAC inspection interface
"""

from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import inspect as drac_inspect
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracInspectionTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracInspectionTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)
        memory = [{'id': 'DIMM.Socket.A1',
                   'size_mb': 16384,
                   'speed': 2133,
                   'manufacturer': 'Samsung',
                   'model': 'DDR4 DIMM',
                   'state': 'ok'},
                  {'id': 'DIMM.Socket.B1',
                   'size_mb': 16384,
                   'speed': 2133,
                   'manufacturer': 'Samsung',
                   'model': 'DDR4 DIMM',
                   'state': 'ok'}]
        cpus = [{'id': 'CPU.Socket.1',
                 'cores': 6,
                 'speed': 2400,
                 'model': 'Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz',
                 'state': 'ok',
                 'ht_enabled': True,
                 'turbo_enabled': True,
                 'vt_enabled': True,
                 'arch64': True},
                {'id': 'CPU.Socket.2',
                 'cores': 6,
                 'speed': 2400,
                 'model': 'Intel(R) Xeon(R) CPU E5-2620 v3 @ 2.40GHz',
                 'state': 'ok',
                 'ht_enabled': False,
                 'turbo_enabled': True,
                 'vt_enabled': True,
                 'arch64': True}]
        virtual_disks = [
            {'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
             'name': 'disk 0',
             'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
             'controller': 'RAID.Integrated.1-1',
             'raid_level': '1',
             'size_mb': 1143552,
             'state': 'ok',
             'raid_state': 'online',
             'span_depth': 1,
             'span_length': 2,
             'pending_operations': None}]
        physical_disks = [
            {'id': 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
             'description': ('Disk 1 in Backplane 1 of '
                             'Integrated RAID Controller 1'),
             'controller': 'RAID.Integrated.1-1',
             'manufacturer': 'SEAGATE',
             'model': 'ST600MM0006',
             'media_type': 'hdd',
             'interface_type': 'sas',
             'size_mb': 571776,
             'free_size_mb': 571776,
             'serial_number': 'S0M3EY2Z',
             'firmware_version': 'LS0A',
             'state': 'ok',
             'raid_state': 'ready'},
            {'id': 'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
             'description': ('Disk 1 in Backplane 1 of '
                             'Integrated RAID Controller 1'),
             'controller': 'RAID.Integrated.1-1',
             'manufacturer': 'SEAGATE',
             'model': 'ST600MM0006',
             'media_type': 'hdd',
             'interface_type': 'sas',
             'size_mb': 285888,
             'free_size_mb': 285888,
             'serial_number': 'S0M3EY2Z',
             'firmware_version': 'LS0A',
             'state': 'ok',
             'raid_state': 'ready'}]
        nics = [
            {'id': 'NIC.Embedded.1-1-1',
             'mac': 'B0:83:FE:C6:6F:A1',
             'model': 'Broadcom Gigabit Ethernet BCM5720 - B0:83:FE:C6:6F:A1',
             'speed': '1000 Mbps',
             'duplex': 'full duplex',
             'media_type': 'Base T'},
            {'id': 'NIC.Embedded.2-1-1',
             'mac': 'B0:83:FE:C6:6F:A2',
             'model': 'Broadcom Gigabit Ethernet BCM5720 - B0:83:FE:C6:6F:A2',
             'speed': '1000 Mbps',
             'duplex': 'full duplex',
             'media_type': 'Base T'}]
        self.memory = [test_utils.dict_to_namedtuple(values=m) for m in memory]
        self.cpus = [test_utils.dict_to_namedtuple(values=c) for c in cpus]
        self.virtual_disks = [test_utils.dict_to_namedtuple(values=vd)
                              for vd in virtual_disks]
        self.physical_disks = [test_utils.dict_to_namedtuple(values=pd)
                               for pd in physical_disks]
        self.nics = [test_utils.dict_to_namedtuple(values=n) for n in nics]

    def test_get_properties(self):
        expected = drac_common.COMMON_PROPERTIES
        driver = drac_inspect.DracInspect()
        self.assertEqual(expected, driver.get_properties())

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_inspect_hardware(self, mock_port_create, mock_get_drac_client):
        expected_node_properties = {
            'memory_mb': 32768,
            'local_gb': 1116,
            'cpus': 18,
            'cpu_arch': 'x86_64'}
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_memory.return_value = self.memory
        mock_client.list_cpus.return_value = self.cpus
        mock_client.list_virtual_disks.return_value = self.virtual_disks
        mock_client.list_nics.return_value = self.nics

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            return_value = task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_node_properties, self.node.properties)
        self.assertEqual(states.MANAGEABLE, return_value)
        self.assertEqual(2, mock_port_create.call_count)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_inspect_hardware_fail(self, mock_port_create,
                                   mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_memory.return_value = self.memory
        mock_client.list_cpus.return_value = self.cpus
        mock_client.list_virtual_disks.side_effect = (
            drac_exceptions.BaseClientException('boom'))

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_inspect_hardware_no_virtual_disk(self, mock_port_create,
                                              mock_get_drac_client):
        expected_node_properties = {
            'memory_mb': 32768,
            'local_gb': 279,
            'cpus': 18,
            'cpu_arch': 'x86_64'}
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_memory.return_value = self.memory
        mock_client.list_cpus.return_value = self.cpus
        mock_client.list_virtual_disks.return_value = []
        mock_client.list_physical_disks.return_value = self.physical_disks
        mock_client.list_nics.return_value = self.nics

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            return_value = task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_node_properties, self.node.properties)
        self.assertEqual(states.MANAGEABLE, return_value)
        self.assertEqual(2, mock_port_create.call_count)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_inspect_hardware_no_cpu(
            self, mock_port_create, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_memory.return_value = self.memory
        mock_client.list_cpus.return_value = []
        mock_client.list_virtual_disks.return_value = []
        mock_client.list_physical_disks.return_value = self.physical_disks
        mock_client.list_nics.return_value = self.nics

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.HardwareInspectionFailure,
                              task.driver.inspect.inspect_hardware, task)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(objects.Port, 'create', spec_set=True, autospec=True)
    def test_inspect_hardware_with_existing_ports(self, mock_port_create,
                                                  mock_get_drac_client):
        expected_node_properties = {
            'memory_mb': 32768,
            'local_gb': 1116,
            'cpus': 18,
            'cpu_arch': 'x86_64'}
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_memory.return_value = self.memory
        mock_client.list_cpus.return_value = self.cpus
        mock_client.list_virtual_disks.return_value = self.virtual_disks
        mock_client.list_nics.return_value = self.nics
        mock_port_create.side_effect = exception.MACAlreadyExists("boom")

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            return_value = task.driver.inspect.inspect_hardware(task)

        self.node.refresh()
        self.assertEqual(expected_node_properties, self.node.properties)
        self.assertEqual(states.MANAGEABLE, return_value)
        self.assertEqual(2, mock_port_create.call_count)

    def test__guess_root_disk(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            root_disk = task.driver.inspect._guess_root_disk(
                self.physical_disks)

            self.assertEqual(285888, root_disk.size_mb)

    def test__calculate_cpus(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            cpu = task.driver.inspect._calculate_cpus(
                self.cpus[0])

            self.assertEqual(12, cpu)

    def test__calculate_cpus_without_ht_enabled(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            cpu = task.driver.inspect._calculate_cpus(
                self.cpus[1])

            self.assertEqual(6, cpu)
