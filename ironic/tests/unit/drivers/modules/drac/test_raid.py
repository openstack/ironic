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
Test class for DRAC RAID interface
"""

from dracclient import exceptions as drac_exceptions
import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import raid as drac_raid
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracQueryRaidConfigurationTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracQueryRaidConfigurationTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'firmware_version': '21.3.0-0009'}
        self.raid_controller = test_utils.dict_to_namedtuple(
            values=raid_controller_dict)

        virtual_disk_dict = {
            'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
            'name': 'disk 0',
            'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
            'controller': 'RAID.Integrated.1-1',
            'raid_level': '1',
            'size_mb': 571776,
            'state': 'ok',
            'raid_state': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None}
        self.virtual_disk = test_utils.dict_to_namedtuple(
            values=virtual_disk_dict)

        physical_disk_dict = {
            'id': 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
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
            'raid_state': 'ready'}
        self.physical_disk = test_utils.dict_to_namedtuple(
            values=physical_disk_dict)

    def test_list_raid_controllers(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_raid_controllers.return_value = [self.raid_controller]

        raid_controllers = drac_raid.list_raid_controllers(self.node)

        mock_client.list_raid_controllers.assert_called_once_with()
        self.assertEqual(self.raid_controller, raid_controllers[0])

    def test_list_raid_controllers_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.list_raid_controllers.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_raid.list_raid_controllers, self.node)

    def test_list_virtual_disks(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_virtual_disks.return_value = [self.virtual_disk]

        virtual_disks = drac_raid.list_virtual_disks(self.node)

        mock_client.list_virtual_disks.assert_called_once_with()
        self.assertEqual(self.virtual_disk, virtual_disks[0])

    def test_list_virtual_disks_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.list_virtual_disks.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_raid.list_virtual_disks, self.node)

    def test_list_physical_disks(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_physical_disks.return_value = [self.physical_disk]

        physical_disks = drac_raid.list_physical_disks(self.node)

        mock_client.list_physical_disks.assert_called_once_with()
        self.assertEqual(self.physical_disk, physical_disks[0])

    def test_list_physical_disks_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = exception.DracOperationError('boom')
        mock_client.list_physical_disks.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_raid.list_physical_disks, self.node)


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracManageVirtualDisksTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracManageVirtualDisksTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_create_virtual_disk(self, mock_validate_job_queue,
                                 mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.create_virtual_disk(
            self.node, 'controller', ['disk1', 'disk2'], '1+0', 43008)

        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.create_virtual_disk.assert_called_once_with(
            'controller', ['disk1', 'disk2'], '1+0', 43008, None, None, None)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_create_virtual_disk_with_optional_attrs(self,
                                                     mock_validate_job_queue,
                                                     mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.create_virtual_disk(
            self.node, 'controller', ['disk1', 'disk2'], '1+0', 43008,
            disk_name='name', span_length=3, span_depth=2)

        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.create_virtual_disk.assert_called_once_with(
            'controller', ['disk1', 'disk2'], '1+0', 43008, 'name', 3, 2)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_create_virtual_disk_fail(self, mock_validate_job_queue,
                                      mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.create_virtual_disk.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.create_virtual_disk,
            self.node, 'controller', ['disk1', 'disk2'], '1+0', 42)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_delete_virtual_disk(self, mock_validate_job_queue,
                                 mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.delete_virtual_disk(self.node, 'disk1')

        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.delete_virtual_disk.assert_called_once_with('disk1')

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_delete_virtual_disk_fail(self, mock_validate_job_queue,
                                      mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.delete_virtual_disk.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.delete_virtual_disk,
            self.node, 'disk1')

    def test_commit_config(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.commit_config(self.node, 'controller1')

        mock_client.commit_pending_raid_changes.assert_called_once_with(
            'controller1', False)

    def test_commit_config_with_reboot(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.commit_config(self.node, 'controller1', reboot=True)

        mock_client.commit_pending_raid_changes.assert_called_once_with(
            'controller1', True)

    def test_commit_config_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.commit_pending_raid_changes.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.commit_config, self.node,
            'controller1')

    def test_abandon_config(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.abandon_config(self.node, 'controller1')

        mock_client.abandon_pending_raid_changes.assert_called_once_with(
            'controller1')

    def test_abandon_config_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.abandon_pending_raid_changes.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.abandon_config, self.node,
            'controller1')


class DracCreateRaidConfigurationHelpersTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracCreateRaidConfigurationHelpersTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

        self.physical_disk = {
            'id': 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
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
            'raid_state': 'ready'}

        self.physical_disks = []
        for i in range(8):
            disk = self.physical_disk.copy()
            disk['id'] = ('Disk.Bay.%s:Enclosure.Internal.0-1:'
                          'RAID.Integrated.1-1' % i)
            disk['serial_number'] = 'serial%s' % i

            self.physical_disks.append(disk)

        self.root_logical_disk = {
            'size_gb': 50,
            'raid_level': '1',
            'disk_type': 'hdd',
            'interface_type': 'sas',
            'volume_name': 'root_volume',
            'is_root_volume': True
        }
        self.nonroot_logical_disks = [
            {'size_gb': 100,
             'raid_level': '5',
             'disk_type': 'hdd',
             'interface_type': 'sas',
             'volume_name': 'data_volume1'},
            {'size_gb': 100,
             'raid_level': '5',
             'disk_type': 'hdd',
             'interface_type': 'sas',
             'volume_name': 'data_volume2'}
        ]

        self.logical_disks = (
            [self.root_logical_disk] + self.nonroot_logical_disks)
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

    def _generate_physical_disks(self):
        physical_disks = []

        for disk in self.physical_disks:
            physical_disks.append(
                test_utils.dict_to_namedtuple(values=disk))

        return physical_disks

    def test__filter_logical_disks_root_only(self):
        logical_disks = drac_raid._filter_logical_disks(
            self.target_raid_configuration['logical_disks'], True, False)

        self.assertEqual(1, len(logical_disks))
        self.assertEqual('root_volume', logical_disks[0]['volume_name'])

    def test__filter_logical_disks_nonroot_only(self):
        logical_disks = drac_raid._filter_logical_disks(
            self.target_raid_configuration['logical_disks'], False, True)

        self.assertEqual(2, len(logical_disks))
        self.assertEqual('data_volume1', logical_disks[0]['volume_name'])
        self.assertEqual('data_volume2', logical_disks[1]['volume_name'])

    def test__filter_logical_disks_excelude_all(self):
        logical_disks = drac_raid._filter_logical_disks(
            self.target_raid_configuration['logical_disks'], False, False)

        self.assertEqual(0, len(logical_disks))

    def test__calculate_spans_for_2_disk_and_raid_level_1(self):
        raid_level = '1'
        disks_count = 2

        spans_count = drac_raid._calculate_spans(raid_level, disks_count)
        self.assertEqual(1, spans_count)

    def test__calculate_spans_for_7_disk_and_raid_level_50(self):
        raid_level = '5+0'
        disks_count = 7

        spans_count = drac_raid._calculate_spans(raid_level, disks_count)

        self.assertEqual(2, spans_count)

    def test__calculate_spans_for_7_disk_and_raid_level_10(self):
        raid_level = '1+0'
        disks_count = 7

        spans_count = drac_raid._calculate_spans(raid_level, disks_count)
        self.assertEqual(3, spans_count)

    def test__calculate_spans_for_invalid_raid_level(self):
        raid_level = 'foo'
        disks_count = 7

        self.assertRaises(exception.DracOperationError,
                          drac_raid._calculate_spans, raid_level, disks_count)

    def test__max_volume_size_mb(self):
        physical_disks = self._generate_physical_disks()
        physical_disk_free_space_mb = {}
        for disk in physical_disks:
            physical_disk_free_space_mb[disk] = disk.free_size_mb

        max_size = drac_raid._max_volume_size_mb(
            '5', physical_disks[0:3], physical_disk_free_space_mb)

        self.assertEqual(1143552, max_size)

    def test__volume_usage_per_disk_mb(self):
        logical_disk = {
            'size_mb': 102400,
            'raid_level': '5',
            'disk_type': 'hdd',
            'interface_type': 'sas',
            'volume_name': 'data_volume1'}
        physical_disks = self._generate_physical_disks()

        usage_per_disk = drac_raid._volume_usage_per_disk_mb(logical_disk,
                                                             physical_disks)

        self.assertEqual(14656, usage_per_disk)

    def test__find_configuration(self):
        logical_disks = [
            {'size_mb': 102400,
             'raid_level': '5',
             'is_root_volume': True,
             'disk_type': 'hdd'}
        ]
        physical_disks = self._generate_physical_disks()
        expected_contoller = 'RAID.Integrated.1-1'
        expected_physical_disk_ids = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1']

        logical_disks = drac_raid._find_configuration(logical_disks,
                                                      physical_disks)

        self.assertEqual(expected_contoller,
                         logical_disks[0]['controller'])
        self.assertEqual(expected_physical_disk_ids,
                         logical_disks[0]['physical_disks'])

    def test__find_configuration_with_more_than_min_disks_for_raid_level(self):
        logical_disks = [
            {'size_mb': 3072000,
             'raid_level': '5',
             'is_root_volume': True,
             'disk_type': 'hdd'}
        ]
        physical_disks = self._generate_physical_disks()
        expected_contoller = 'RAID.Integrated.1-1'
        expected_physical_disk_ids = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1']

        logical_disks = drac_raid._find_configuration(logical_disks,
                                                      physical_disks)

        self.assertEqual(expected_contoller,
                         logical_disks[0]['controller'])
        self.assertEqual(expected_physical_disk_ids,
                         logical_disks[0]['physical_disks'])

    def test__find_configuration_all_steps(self):
        logical_disks = [
            # step 1
            {'size_mb': 102400,
             'raid_level': '1',
             'physical_disks': [
                 'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1']},
            # step 2
            {'size_mb': 51200,
             'raid_level': '5'},
            # step 3
            {'size_mb': 'MAX',
             'raid_level': '0',
             'physical_disks': [
                 'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1']},
        ]
        physical_disks = self._generate_physical_disks()

        logical_disks = drac_raid._find_configuration(logical_disks,
                                                      physical_disks)

        self.assertEqual(3, len(logical_disks))
        # step 1
        self.assertIn(
            {'raid_level': '1',
             'size_mb': 102400,
             'controller': 'RAID.Integrated.1-1',
             'span_depth': 1,
             'span_length': 2,
             'physical_disks': [
                 'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1']},
            logical_disks)
        # step 2
        self.assertIn(
            {'raid_level': '5',
             'size_mb': 51200,
             'controller': 'RAID.Integrated.1-1',
             'span_depth': 1,
             'span_length': 3,
             'physical_disks': [
                 'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1']},
            logical_disks)
        # step 3
        self.assertIn(
            {'raid_level': '0',
             'size_mb': 1143552,
             'controller': 'RAID.Integrated.1-1',
             'span_depth': 1,
             'span_length': 2,
             'physical_disks': [
                 'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1']},
            logical_disks)


class DracRaidInterfaceTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracRaidInterfaceTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

        self.physical_disk = {
            'id': 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
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
            'raid_state': 'ready'}

        self.physical_disks = []
        for i in range(8):
            disk = self.physical_disk.copy()
            disk['id'] = ('Disk.Bay.%s:Enclosure.Internal.0-1:'
                          'RAID.Integrated.1-1' % i)
            disk['serial_number'] = 'serial%s' % i

            self.physical_disks.append(disk)

        self.root_logical_disk = {
            'size_gb': 50,
            'raid_level': '1',
            'disk_type': 'hdd',
            'interface_type': 'sas',
            'volume_name': 'root_volume',
            'is_root_volume': True
        }
        self.nonroot_logical_disks = [
            {'size_gb': 100,
             'raid_level': '5',
             'disk_type': 'hdd',
             'interface_type': 'sas',
             'volume_name': 'data_volume1'},
            {'size_gb': 100,
             'raid_level': '5',
             'disk_type': 'hdd',
             'interface_type': 'sas',
             'volume_name': 'data_volume2'}
        ]

        self.logical_disks = (
            [self.root_logical_disk] + self.nonroot_logical_disks)
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

    def _generate_physical_disks(self):
        physical_disks = []

        for disk in self.physical_disks:
            physical_disks.append(
                test_utils.dict_to_namedtuple(values=disk))

        return physical_disks

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks
        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=False)

            mock_client.create_virtual_disk.assert_called_once_with(
                'RAID.Integrated.1-1',
                ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                '1', 51200, None, 2, 1)
            mock_commit_config.assert_called_once_with(
                task.node, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_no_change(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=False, create_nonroot_volumes=False)

            self.assertEqual(0, mock_client.create_virtual_disk.call_count)
            self.assertEqual(0, mock_commit_config.call_count)

        self.assertIsNone(return_value)

        self.node.refresh()
        self.assertNotIn('raid_config_job_ids', self.node.driver_internal_info)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_nested_raid_level(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk = {
            'size_gb': 100,
            'raid_level': '1+0',
            'is_root_volume': True
        }
        self.logical_disks = [self.root_logical_disk]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_called_once_with(
                'RAID.Integrated.1-1',
                ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                 'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                '1+0', 102400, None, 2, 2)

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_multiple_controllers(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.physical_disks[0]['controller'] = 'controller-2'
        self.physical_disks[1]['controller'] = 'controller-2'
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.side_effect = ['42', '12']

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'controller-2',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '1', 51200, None, 2, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.7:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)
                 ],
                any_order=True)
            # Commits to both controller
            mock_commit_config.assert_has_calls(
                [mock.call(mock.ANY, raid_controller='controller-2',
                           reboot=mock.ANY),
                 mock.call(mock.ANY, raid_controller='RAID.Integrated.1-1',
                           reboot=mock.ANY)],
                any_order=True)
            # One of the config jobs should issue a reboot
            mock_commit_config.assert_has_calls(
                [mock.call(mock.ANY, raid_controller=mock.ANY,
                           reboot=False),
                 mock.call(mock.ANY, raid_controller=mock.ANY,
                           reboot=True)],
                any_order=True)

        self.node.refresh()
        self.assertEqual(['42', '12'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_backing_physical_disks(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk['physical_disks'] = [
            'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1']
        self.logical_disks = (
            [self.root_logical_disk] + self.nonroot_logical_disks)
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '1', 51200, None, 2, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.7:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)],
                any_order=True)

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_predefined_number_of_phyisical_disks(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk['raid_level'] = '0'
        self.root_logical_disk['number_of_physical_disks'] = 3
        self.logical_disks = (
            [self.root_logical_disk, self.nonroot_logical_disks[0]])
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '0', 51200, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)],
                any_order=True)

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_max_size(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk = {
            'size_gb': 'MAX',
            'raid_level': '1',
            'physical_disks': [
                'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
            'is_root_volume': True
        }
        self.logical_disks = ([self.root_logical_disk] +
                              self.nonroot_logical_disks)
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '1', 571776, None, 2, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.7:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)],
                any_order=True)

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    def test_create_configuration_with_max_size_without_backing_disks(
            self, mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk = {
            'size_gb': 'MAX',
            'raid_level': '1',
            'is_root_volume': True
        }
        self.logical_disks = [self.root_logical_disk]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:2]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.raid.create_configuration,
                task)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_share_physical_disks(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.nonroot_logical_disks[0]['share_physical_disks'] = True
        self.nonroot_logical_disks[1]['share_physical_disks'] = True
        self.logical_disks = self.nonroot_logical_disks
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:3]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)])

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_with_sharing_disabled(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.nonroot_logical_disks[0]['share_physical_disks'] = False
        self.nonroot_logical_disks[1]['share_physical_disks'] = False
        self.logical_disks = self.nonroot_logical_disks
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:3]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_max_size_and_share_physical_disks(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.nonroot_logical_disks[0]['share_physical_disks'] = True
        self.nonroot_logical_disks[0]['size_gb'] = 'MAX'
        self.nonroot_logical_disks[0]['physical_disks'] = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1']
        self.nonroot_logical_disks[1]['share_physical_disks'] = True
        self.logical_disks = self.nonroot_logical_disks
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:3]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True)

            mock_client.create_virtual_disk.assert_has_calls(
                [mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 1041152, None, 3, 1),
                 mock.call(
                    'RAID.Integrated.1-1',
                    ['Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                     'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
                    '5', 102400, None, 3, 1)],
                any_order=True)

            # Commits to the controller
            mock_commit_config.assert_called_once_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_multiple_max_and_sharing_same_disks(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.nonroot_logical_disks[0]['share_physical_disks'] = True
        self.nonroot_logical_disks[0]['size_gb'] = 'MAX'
        self.nonroot_logical_disks[0]['physical_disks'] = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1']
        self.nonroot_logical_disks[1]['share_physical_disks'] = True
        self.nonroot_logical_disks[1]['size_gb'] = 'MAX'
        self.nonroot_logical_disks[1]['physical_disks'] = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1']
        self.logical_disks = self.nonroot_logical_disks
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:3]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_if_not_enough_space(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.logical_disk = {
            'size_gb': 500,
            'raid_level': '1'
        }
        self.logical_disks = [self.logical_disk, self.logical_disk]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        self.physical_disks = self.physical_disks[0:3]
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_if_disk_already_reserved(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.logical_disk = {
            'size_gb': 500,
            'raid_level': '1',
            'physical_disks': [
                'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
        }
        self.logical_disks = [self.logical_disk, self.logical_disk.copy()]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_virtual_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_delete_configuration(self, mock_commit_config,
                                  mock_validate_job_queue,
                                  mock_list_virtual_disks,
                                  mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        virtual_disk_dict = {
            'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
            'name': 'disk 0',
            'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
            'controller': 'RAID.Integrated.1-1',
            'raid_level': '1',
            'size_mb': 571776,
            'state': 'ok',
            'raid_state': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None}
        mock_list_virtual_disks.return_value = [
            test_utils.dict_to_namedtuple(values=virtual_disk_dict)]
        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)

            mock_client.delete_virtual_disk.assert_called_once_with(
                'Disk.Virtual.0:RAID.Integrated.1-1')
            mock_commit_config.assert_called_once_with(
                task.node, raid_controller='RAID.Integrated.1-1', reboot=True)

        self.assertEqual(states.CLEANWAIT, return_value)
        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_virtual_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_delete_configuration_no_change(self, mock_commit_config,
                                            mock_validate_job_queue,
                                            mock_list_virtual_disks,
                                            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_list_virtual_disks.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)

            self.assertEqual(0, mock_client.delete_virtual_disk.call_count)
            self.assertEqual(0, mock_commit_config.call_count)

        self.assertIsNone(return_value)

        self.node.refresh()
        self.assertNotIn('raid_config_job_ids', self.node.driver_internal_info)

    @mock.patch.object(drac_raid, 'list_virtual_disks', autospec=True)
    def test_get_logical_disks(self, mock_list_virtual_disks):
        virtual_disk_dict = {
            'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
            'name': 'disk 0',
            'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
            'controller': 'RAID.Integrated.1-1',
            'raid_level': '1',
            'size_mb': 571776,
            'state': 'ok',
            'raid_state': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None}
        mock_list_virtual_disks.return_value = [
            test_utils.dict_to_namedtuple(values=virtual_disk_dict)]
        expected_logical_disk = {'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
                                 'size_gb': 558,
                                 'raid_level': '1',
                                 'name': 'disk 0',
                                 'controller': 'RAID.Integrated.1-1'}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            props = task.driver.raid.get_logical_disks(task)

        self.assertEqual({'logical_disks': [expected_logical_disk]},
                         props)
