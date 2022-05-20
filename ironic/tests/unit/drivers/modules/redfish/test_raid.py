# Copyright 2021 DMTF. All rights reserved.
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
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.redfish import boot as redfish_boot
from ironic.drivers.modules.redfish import raid as redfish_raid
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


def _mock_drive(identity, block_size_bytes=None, capacity_bytes=None,
                media_type=None, name=None, protocol=None):
    return mock.MagicMock(
        _path='/redfish/v1/Systems/1/Storage/1/Drives/' + identity,
        identity=identity,
        block_size_bytes=block_size_bytes,
        capacity_bytes=capacity_bytes,
        media_type=media_type,
        name=name,
        protocol=protocol
    )


def _mock_volume(identity, volume_type=None, raid_type=None,
                 capacity_bytes=units.Gi):
    volume = mock.MagicMock(
        _path='/redfish/v1/Systems/1/Storage/1/Volumes/' + identity,
        identity=identity,
        volume_type=volume_type,
        raid_type=raid_type,
        capacity_bytes=capacity_bytes
    )
    volume.name = 'Volume ' + identity
    # Mocking Immediate that does not return anything
    volume.delete.return_value = None
    return volume


@mock.patch('oslo_utils.eventletutils.EventletEvent.wait',
            lambda *args, **kwargs: None)
@mock.patch.object(redfish_utils, 'get_system', autospec=True)
class RedfishRAIDTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishRAIDTestCase, self).setUp()
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'],
                    enabled_inspect_interfaces=['redfish'],
                    enabled_bios_interfaces=['redfish'],
                    enabled_raid_interfaces=['redfish']
                    )
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)
        self.mock_storage = mock.MagicMock(identity='RAID controller 1')
        self.drive_id1 = '35D38F11ACEF7BD3'
        self.drive_id2 = '3F5A8C54207B7233'
        self.drive_id3 = '32ADF365C6C1B7BD'
        self.drive_id4 = '3D58ECBC375FD9F2'
        self.drive_id5 = '5C966D719B0E1770'
        self.drive_id6 = '778B2A13449B8292'
        self.drive_id7 = 'E901FB234162E503'
        mock_drives = []
        for i in [self.drive_id1, self.drive_id2, self.drive_id3,
                  self.drive_id4]:
            mock_drives.append(_mock_drive(
                identity=i, block_size_bytes=512, capacity_bytes=899527000000,
                media_type='HDD', name='Drive',
                protocol='Serial Attached SCSI'))
        for i in [self.drive_id5, self.drive_id6, self.drive_id7]:
            mock_drives.append(_mock_drive(
                identity=i, block_size_bytes=512, capacity_bytes=479559942144,
                media_type='SSD', name='Solid State Drive',
                protocol='Serial AT Attachment'))
        self.mock_storage.drives = mock_drives
        mock_controller = mock.Mock()
        mock_controller.raid_types = ['RAID1', 'RAID5', 'RAID10']
        self.mock_storage.storage_controllers = [mock_controller]
        mock_volumes = mock.MagicMock()
        self.mock_storage.volumes = mock_volumes
        self.free_space_bytes = {d: d.capacity_bytes for d in
                                 mock_drives}
        self.physical_disks = mock_drives

    @mock.patch.object(redfish_raid, 'sushy', None)
    def test_loading_error(self, mock_get_system):
        self.assertRaisesRegex(
            exception.DriverLoadError,
            'Unable to import the sushy library',
            redfish_raid.RedfishRAID)

    def test__max_volume_size_bytes_raid0(self, mock_get_system):
        spans = redfish_raid._calculate_spans('0', 3)
        max_size = redfish_raid._max_volume_size_bytes(
            '0', self.physical_disks[0:3], self.free_space_bytes,
            spans_count=spans)
        self.assertEqual(2698380312576, max_size)

    def test__max_volume_size_bytes_raid1(self, mock_get_system):
        spans = redfish_raid._calculate_spans('1', 2)
        max_size = redfish_raid._max_volume_size_bytes(
            '1', self.physical_disks[0:2], self.free_space_bytes,
            spans_count=spans)
        self.assertEqual(899460104192, max_size)

    def test__max_volume_size_bytes_raid5(self, mock_get_system):
        spans = redfish_raid._calculate_spans('5', 3)
        max_size = redfish_raid._max_volume_size_bytes(
            '5', self.physical_disks[0:3], self.free_space_bytes,
            spans_count=spans)
        self.assertEqual(1798920208384, max_size)

    def test__max_volume_size_bytes_raid6(self, mock_get_system):
        spans = redfish_raid._calculate_spans('6', 4)
        max_size = redfish_raid._max_volume_size_bytes(
            '6', self.physical_disks[0:4], self.free_space_bytes,
            spans_count=spans)
        self.assertEqual(1798920208384, max_size)

    def test__volume_usage_per_disk_bytes_raid5(self, mock_get_system):
        logical_disk = {
            'size_gb': 100,
            'raid_level': '5',
            'controller': 'Smart Array P822 in Slot 3',
            'physical_disks': [
                '35D38F11ACEF7BD3',
                '3F5A8C54207B7233',
                '32ADF365C6C1B7BD'
            ],
            'is_root_volume': True
        }
        logical_disk['size_bytes'] = logical_disk['size_gb'] * units.Gi
        del logical_disk['size_gb']
        spans = redfish_raid._calculate_spans('5', 3)
        usage_bytes = redfish_raid._volume_usage_per_disk_bytes(
            logical_disk, self.physical_disks[0:3], spans_count=spans)
        self.assertEqual(53687091200, usage_bytes)

    def test__volume_usage_per_disk_bytes_raid10(self, mock_get_system):
        logical_disk = {
            'size_gb': 50,
            'raid_level': '1+0',
            'controller': 'RAID.Integrated.1-1',
            'volume_name': 'root_volume',
            'is_root_volume': True,
            'physical_disks': [
                '35D38F11ACEF7BD3',
                '3F5A8C54207B7233',
                '32ADF365C6C1B7BD',
                '3D58ECBC375FD9F2'
            ]
        }
        logical_disk['size_bytes'] = logical_disk['size_gb'] * units.Gi
        del logical_disk['size_gb']
        spans = redfish_raid._calculate_spans('1+0', 4)
        usage_bytes = redfish_raid._volume_usage_per_disk_bytes(
            logical_disk, self.physical_disks[0:4], spans_count=spans)
        self.assertEqual(26843545600, usage_bytes)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_1a(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 'MAX',
                    'raid_level': '5',
                    'is_root_volume': True
                }
            ]
        }
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                "'physical_disks' is missing from logical_disk while "
                "'size_gb'='MAX' was requested",
                task.driver.raid.create_configuration, task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_1b(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True
                }
            ]
        }
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3}
                    ]
                }
            }
            self.mock_storage.volumes.create.assert_called_once_with(
                expected_payload, apply_time=None
            )
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual({}, task.node.raid_config)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_1b_apply_time_immediate(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True
                }
            ]
        }
        created_volumes = [_mock_volume(
            '1', raid_type=sushy.RAID_TYPE_RAID5,
            capacity_bytes=100 * units.Gi)]
        volumes = mock.MagicMock()
        # Called after volumes created
        volumes.get_members.return_value = created_volumes
        op_apply_time_support = mock.MagicMock()
        op_apply_time_support.mapped_supported_values = [
            sushy.APPLY_TIME_IMMEDIATE, sushy.APPLY_TIME_ON_RESET]
        volumes.operation_apply_time_support = op_apply_time_support
        self.mock_storage.volumes = volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        resource = mock.MagicMock(spec=['resource_name'])
        resource.resource_name = 'volume'
        volumes.create.return_value = resource
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3}
                    ]
                }
            }
            self.mock_storage.volumes.create.assert_called_once_with(
                expected_payload, apply_time=sushy.APPLY_TIME_IMMEDIATE)
            mock_set_async_step_flags.assert_called_once_with(
                task.node, reboot=False, skip_current_step=True, polling=True)
            self.assertEqual(mock_get_async_step_return_state.call_count, 0)
            self.assertEqual(mock_node_power_action.call_count, 0)
            self.assertEqual(mock_build_agent_options.call_count, 0)
            self.assertEqual(mock_prepare_ramdisk.call_count, 0)
            self.assertEqual(
                [{'controller': 'RAID controller 1',
                  'id': '1',
                  'name': 'Volume 1',
                  'raid_level': '5',
                  'size_gb': 100}],
                task.node.raid_config['logical_disks'])

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_1b_apply_time_on_reset(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True
                }
            ]
        }
        volumes = mock.MagicMock()
        op_apply_time_support = mock.MagicMock()
        op_apply_time_support.mapped_supported_values = [
            sushy.APPLY_TIME_ON_RESET]
        volumes.operation_apply_time_support = op_apply_time_support
        self.mock_storage.volumes = volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        task_mon = mock.MagicMock()
        task_mon.task_monitor_uri = '/TaskService/123'
        volumes.create.return_value = task_mon
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3}
                    ]
                }
            }
            self.mock_storage.volumes.create.assert_called_once_with(
                expected_payload, apply_time=sushy.APPLY_TIME_ON_RESET)
            mock_set_async_step_flags.assert_called_once_with(
                task.node, reboot=True, skip_current_step=True, polling=True)
            mock_get_async_step_return_state.assert_called_once_with(
                task.node)
            mock_node_power_action.assert_called_once_with(task, states.REBOOT)
            mock_build_agent_options.assert_called_once_with(task.node)
            self.assertEqual(mock_prepare_ramdisk.call_count, 1)
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual({}, task.node.raid_config)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_2(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):

        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True,
                    'disk_type': 'ssd'
                },
                {
                    'size_gb': 500,
                    'raid_level': '1',
                    'disk_type': 'hdd'
                }
            ]
        }
        created_volumes = [
            _mock_volume('1', raid_type=sushy.RAID_TYPE_RAID5,
                         capacity_bytes=100 * units.Gi),
            _mock_volume('2', raid_type=sushy.RAID_TYPE_RAID1,
                         capacity_bytes=500 * units.Gi)]
        resource = mock.MagicMock(spec=['resource_name'])
        resource.resource_name = 'volume'
        self.mock_storage.volumes.create.return_value = resource
        # Called after volumes created
        self.mock_storage.volumes.get_members.return_value = created_volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload1 = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id5},
                        {'@odata.id': pre + self.drive_id6},
                        {'@odata.id': pre + self.drive_id7}
                    ]
                }
            }
            expected_payload2 = {
                'Encrypted': False,
                'VolumeType': 'Mirrored',
                'RAIDType': 'RAID1',
                'CapacityBytes': 536870912000,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2}
                    ]
                }
            }
            self.assertEqual(
                self.mock_storage.volumes.create.call_count, 2)
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload1, apply_time=None
            )
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload2, apply_time=None
            )
            self.assertEqual(
                [{'controller': 'RAID controller 1',
                  'id': '1',
                  'name': 'Volume 1',
                  'raid_level': '5',
                  'size_gb': 100},
                 {'controller': 'RAID controller 1',
                  'id': '2',
                  'name': 'Volume 2',
                  'raid_level': '1',
                  'size_gb': 500}],
                task.node.raid_config['logical_disks'])

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_2_on_reset(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):

        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True,
                    'disk_type': 'ssd'
                },
                {
                    'size_gb': 500,
                    'raid_level': '1',
                    'disk_type': 'hdd'
                }
            ]
        }
        volumes = mock.MagicMock()
        op_apply_time_support = mock.MagicMock()
        op_apply_time_support.mapped_supported_values = [
            sushy.APPLY_TIME_ON_RESET]
        volumes.operation_apply_time_support = op_apply_time_support
        self.mock_storage.volumes = volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        task_mon = mock.MagicMock()
        task_mon.task_monitor_uri = '/TaskService/123'
        volumes.create.return_value = task_mon
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload = {
                'Encrypted': False,
                'VolumeType': 'Mirrored',
                'RAIDType': 'RAID1',
                'CapacityBytes': 536870912000,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2}
                    ]
                }
            }
            expected_raid_configs = {
                'operation': 'create',
                'pending': {'RAID controller 1': [
                    {'controller': 'RAID controller 1',
                     'disk_type': 'ssd',
                     'is_root_volume': True,
                     'physical_disks': [self.drive_id5,
                                        self.drive_id6,
                                        self.drive_id7],
                     'raid_level': '5',
                     'size_bytes': 107374182400,
                     'span_depth': 1,
                     'span_length': 3.0}]},
                'task_monitor_uri': ['/TaskService/123']}
            self.assertEqual(
                self.mock_storage.volumes.create.call_count, 1)
            self.mock_storage.volumes.create.assert_called_with(
                expected_payload, apply_time=sushy.APPLY_TIME_ON_RESET)
            self.assertEqual(
                expected_raid_configs,
                task.node.driver_internal_info.get('raid_configs'))
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual({}, task.node.raid_config)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_3(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'controller': 'Smart Array P822 in Slot 3',
                    # 'physical_disks': ['6I:1:5', '6I:1:6', '6I:1:7'],
                    'physical_disks': [
                        '35D38F11ACEF7BD3',
                        '3F5A8C54207B7233',
                        '32ADF365C6C1B7BD'
                    ],
                    'is_root_volume': True
                }
            ]
        }
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3}
                    ]
                }
            }
            self.mock_storage.volumes.create.assert_called_once_with(
                expected_payload, apply_time=None
            )
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual({}, task.node.raid_config)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_4(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        # TODO(bdodd): update self.mock_storage to add more drives to satisfy
        #              both logical disks
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 50,
                    'raid_level': '1+0',
                    'controller': 'RAID.Integrated.1-1',
                    'volume_name': 'root_volume',
                    'is_root_volume': True,
                    # 'physical_disks': [
                    #     'Disk.Bay.0:Encl.Int.0-1:RAID.Integrated.1-1',
                    #     'Disk.Bay.1:Encl.Int.0-1:RAID.Integrated.1-1'
                    # ]
                    'physical_disks': [
                        '35D38F11ACEF7BD3',
                        '3F5A8C54207B7233',
                        '32ADF365C6C1B7BD',
                        '3D58ECBC375FD9F2'
                    ]
                },
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'controller': 'RAID.Integrated.1-1',
                    'volume_name': 'data_volume',
                    # 'physical_disks': [
                    #     'Disk.Bay.2:Encl.Int.0-1:RAID.Integrated.1-1',
                    #     'Disk.Bay.3:Encl.Int.0-1:RAID.Integrated.1-1',
                    #     'Disk.Bay.4:Encl.Int.0-1:RAID.Integrated.1-1'
                    # ]
                    'physical_disks': [
                        '3F5A8C54207B7233',
                        '32ADF365C6C1B7BD',
                        '3D58ECBC375FD9F2'
                    ]
                }
            ]
        }
        resource = mock.MagicMock(spec=['resource_name'])
        resource.resource_name = 'volume'
        self.mock_storage.volumes.create.return_value = resource
        created_volumes = [
            _mock_volume(
                '1', raid_type=sushy.RAID_TYPE_RAID10,
                capacity_bytes=50 * units.Gi),
            _mock_volume(
                '2', raid_type=sushy.RAID_TYPE_RAID5,
                capacity_bytes=100 * units.Gi)]
        # Called after volumes created
        self.mock_storage.volumes.get_members.return_value = created_volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload1 = {
                'Encrypted': False,
                'VolumeType': 'SpannedMirrors',
                'RAIDType': 'RAID10',
                'CapacityBytes': 53687091200,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3},
                        {'@odata.id': pre + self.drive_id4}
                    ]
                }
            }
            expected_payload2 = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id2},
                        {'@odata.id': pre + self.drive_id3},
                        {'@odata.id': pre + self.drive_id4}
                    ]
                }
            }
            self.assertEqual(
                self.mock_storage.volumes.create.call_count, 2)
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload1, apply_time=None
            )
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload2, apply_time=None
            )
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual(
                [{'controller': 'RAID controller 1',
                  'id': '1',
                  'name': 'Volume 1',
                  'raid_level': '1+0',
                  'size_gb': 50},
                 {'controller': 'RAID controller 1',
                  'id': '2',
                  'name': 'Volume 2',
                  'raid_level': '5',
                  'size_gb': 100}],
                task.node.raid_config['logical_disks'])

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_5a(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '1',
                    'controller': 'software'
                },
                {
                    'size_gb': 'MAX',
                    'raid_level': '0',
                    'controller': 'software'
                }
            ]
        }
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                "'physical_disks' is missing from logical_disk while "
                "'size_gb'='MAX' was requested",
                task.driver.raid.create_configuration, task)

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_5b(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '1',
                    'controller': 'software'
                },
                {
                    'size_gb': 500,
                    'raid_level': '0',
                    'controller': 'software'
                }
            ]
        }
        resource = mock.MagicMock(spec=['resource_name'])
        resource.resource_name = 'volume'
        self.mock_storage.volumes.create.return_value = resource
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload1 = {
                'Encrypted': False,
                'VolumeType': 'Mirrored',
                'RAIDType': 'RAID1',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2}
                    ]
                }
            }
            expected_payload2 = {
                'Encrypted': False,
                'VolumeType': 'NonRedundant',
                'RAIDType': 'RAID0',
                'CapacityBytes': 536870912000,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id3}
                    ]
                }
            }
            self.assertEqual(
                self.mock_storage.volumes.create.call_count, 2)
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload1, apply_time=None
            )
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload2, apply_time=None
            )

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_case_6(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 'MAX',
                    'raid_level': '0',
                    'controller': 'software',
                    'physical_disks': [
                        {'size': '> 100'},
                        {'size': '> 100'}
                    ]
                }
            ]
        }
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        # TODO(bdodd): update when impl can handle disk size evaluation
        #  (see _calculate_volume_props())
        """
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
        """

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_create_config_interface_type(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):

        target_raid_config = {
            'logical_disks': [
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True,
                    'interface_type': 'sata'
                },
                {
                    'size_gb': 500,
                    'raid_level': '1',
                    'interface_type': 'sas'
                }
            ]
        }
        resource = mock.MagicMock(spec=['resource_name'])
        resource.resource_name = 'volume'
        self.mock_storage.volumes.create.return_value = resource
        created_volumes = [
            _mock_volume(
                '1', raid_type=sushy.RAID_TYPE_RAID5,
                capacity_bytes=100 * units.Gi),
            _mock_volume(
                '2', raid_type=sushy.RAID_TYPE_RAID1,
                capacity_bytes=500 * units.Gi)]
        # Called after volumes created
        self.mock_storage.volumes.get_members.return_value = created_volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        self.node.target_raid_config = target_raid_config
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.create_configuration(task)
            pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
            expected_payload1 = {
                'Encrypted': False,
                'VolumeType': 'StripedWithParity',
                'RAIDType': 'RAID5',
                'CapacityBytes': 107374182400,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id5},
                        {'@odata.id': pre + self.drive_id6},
                        {'@odata.id': pre + self.drive_id7}
                    ]
                }
            }
            expected_payload2 = {
                'Encrypted': False,
                'VolumeType': 'Mirrored',
                'RAIDType': 'RAID1',
                'CapacityBytes': 536870912000,
                'Links': {
                    'Drives': [
                        {'@odata.id': pre + self.drive_id1},
                        {'@odata.id': pre + self.drive_id2}
                    ]
                }
            }
            self.assertEqual(
                self.mock_storage.volumes.create.call_count, 2)
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload1, apply_time=None
            )
            self.mock_storage.volumes.create.assert_any_call(
                expected_payload2, apply_time=None
            )
            self.assertEqual(
                [{'controller': 'RAID controller 1',
                  'id': '1',
                  'name': 'Volume 1',
                  'raid_level': '5',
                  'size_gb': 100},
                 {'controller': 'RAID controller 1',
                  'id': '2',
                  'name': 'Volume 2',
                  'raid_level': '1',
                  'size_gb': 500}],
                task.node.raid_config['logical_disks'])

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_delete_config_immediate(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        mock_volumes = []
        for i in ["1", "2"]:
            mock_volumes.append(_mock_volume(
                i, volume_type='Mirrored', raid_type=sushy.RAID_TYPE_RAID1))
        op_apply_time_support = mock.MagicMock()
        op_apply_time_support.mapped_supported_values = [
            sushy.APPLY_TIME_IMMEDIATE, sushy.APPLY_TIME_ON_RESET]
        self.mock_storage.volumes.operation_apply_time_support = (
            op_apply_time_support)
        # 2nd call to mock no volumes after delete
        self.mock_storage.volumes.get_members.side_effect = [mock_volumes, []]
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            last_updated = '2022-05-18 08:49:17.585443'
            task.node.raid_config = {
                'logical_disks': [{
                    'controller': 'RAID controller 1',
                    'id': '1',
                    'name': 'Volume 1',
                    'raid_level': '1',
                    'size_gb': 100}],
                'last_updated': last_updated}
            task.driver.raid.delete_configuration(task)
            self.assertEqual(mock_volumes[0].delete.call_count, 1)
            self.assertEqual(mock_volumes[1].delete.call_count, 1)
            mock_set_async_step_flags.assert_called_once_with(
                task.node, reboot=False, skip_current_step=True, polling=True)
            self.assertEqual(mock_get_async_step_return_state.call_count, 0)
            self.assertEqual(mock_node_power_action.call_count, 0)
            self.assertEqual(mock_build_agent_options.call_count, 0)
            self.assertEqual(mock_prepare_ramdisk.call_count, 0)
            self.assertEqual([], task.node.raid_config['logical_disks'])
            self.assertNotEqual(
                last_updated, task.node.raid_config['last_updated'])

    @mock.patch.object(redfish_boot.RedfishVirtualMediaBoot, 'prepare_ramdisk',
                       spec_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    def test_delete_config_on_reset(
            self,
            mock_set_async_step_flags,
            mock_get_async_step_return_state,
            mock_node_power_action,
            mock_build_agent_options,
            mock_prepare_ramdisk,
            mock_get_system):
        mock_volumes = []
        for i in ["1", "2"]:
            mock_volumes.append(_mock_volume(
                i, volume_type='Mirrored', raid_type=sushy.RAID_TYPE_RAID1))
        op_apply_time_support = mock.MagicMock()
        op_apply_time_support.mapped_supported_values = [
            sushy.APPLY_TIME_ON_RESET]
        self.mock_storage.volumes.operation_apply_time_support = (
            op_apply_time_support)
        self.mock_storage.volumes.get_members.return_value = mock_volumes
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        task_mon = mock.MagicMock()
        task_mon.task_monitor_uri = '/TaskService/123'
        mock_volumes[0].delete.return_value = task_mon
        mock_volumes[1].delete.return_value = task_mon
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            raid_config = {
                'logical_disks': [{
                    'controller': 'RAID controller 1',
                    'id': '1',
                    'name': 'Volume 1',
                    'raid_level': '1',
                    'size_gb': 100}],
                'last_updated': '2022-05-18 08:49:17.585443'}
            task.node.raid_config = raid_config
            task.driver.raid.delete_configuration(task)
            self.assertEqual(mock_volumes[0].delete.call_count, 1)
            self.assertEqual(mock_volumes[1].delete.call_count, 0)
            mock_set_async_step_flags.assert_called_once_with(
                task.node, reboot=True, skip_current_step=True, polling=True)
            mock_get_async_step_return_state.assert_called_once_with(
                task.node)
            mock_node_power_action.assert_called_once_with(task, states.REBOOT)
            mock_build_agent_options.assert_called_once_with(task.node)
            self.assertEqual(mock_prepare_ramdisk.call_count, 1)
            self.assertEqual(
                {'operation': 'delete',
                 'pending': True,
                 'task_monitor_uri': ['/TaskService/123']},
                task.node.driver_internal_info.get('raid_configs'))
            # Async operation, raid_config shouldn't be updated yet
            self.assertEqual(raid_config, task.node.raid_config)

    def test_volume_create_error_handler(self, mock_get_system):
        volume_collection = self.mock_storage.volumes
        sushy_error = sushy.exceptions.SushyError()
        volume_collection.create.side_effect = sushy_error
        mock_get_system.return_value.storage.get_members.return_value = [
            self.mock_storage]
        mock_error_handler = mock.Mock()
        drive_id = '35D38F11ACEF7BD3'
        physical_disks = [drive_id]
        capacity_bytes = 53739520000
        pre = '/redfish/v1/Systems/1/Storage/1/Drives/'
        expected_payload = {
            'Encrypted': False,
            'VolumeType': 'Mirrored',
            'RAIDType': 'RAID1',
            'CapacityBytes': capacity_bytes,
            'Links': {
                'Drives': [
                    {
                        '@odata.id': pre + drive_id
                    }
                ]
            }
        }
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            redfish_raid.create_virtual_disk(
                task, None, physical_disks, '1', capacity_bytes,
                error_handler=mock_error_handler)
            self.assertEqual(mock_error_handler.call_count, 1)
            mock_error_handler.assert_called_once_with(
                task, sushy_error, volume_collection, expected_payload
            )

    def test_validate_raid_config(self, mock_get_system):
        raid_config = {
            'logical_disks': [
                {
                    'size_gb': 500,
                    'raid_level': '1+0',
                    'interface_type': 'sata'
                },
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True,
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.raid.validate_raid_config(task, raid_config)

    def test_validate_raid_config_scsi(self, mock_get_system):
        raid_config = {
            'logical_disks': [
                {
                    'size_gb': 500,
                    'raid_level': '1+0',
                    'interface_type': 'sata'
                },
                {
                    'size_gb': 100,
                    'raid_level': '5',
                    'is_root_volume': True,
                    'interface_type': 'scsi'
                }
            ]
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaisesRegex(
                exception.InvalidParameterValue,
                "interface type `scsi` not supported by Redfish RAID",
                task.driver.raid.validate_raid_config, task, raid_config)

    def test_get_physical_disks(self, mock_get_system):
        nonraid_controller = mock.Mock()
        nonraid_controller.raid_types = []
        nonraid_storage = mock.MagicMock()
        nonraid_storage.storage_controllers = [nonraid_controller]
        nonraid_storage.drives = [_mock_drive(
            identity='Drive1', block_size_bytes=512,
            capacity_bytes=899527000000,
            media_type='HDD', name='Drive', protocol='SAS')]

        mock_get_system.return_value.storage.get_members.return_value = [
            nonraid_storage, self.mock_storage]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            disks, disk_to_controller = redfish_raid.get_physical_disks(
                task.node)

            for drive in self.mock_storage.drives:
                self.assertIn(drive, disks)
                self.assertIn(drive, disk_to_controller)

            self.assertNotIn(nonraid_storage.drives[0], disks)
            self.assertNotIn(nonraid_storage.drives[0], disk_to_controller)

    def test__get_storage_controller(self, mock_get_system):
        nonraid_controller = mock.Mock()
        nonraid_controller.raid_types = []
        nonraid_storage = mock.MagicMock()
        nonraid_storage.storage_controllers = [nonraid_controller]
        nonraid_storage.drives = mock.Mock()

        mock_get_system.return_value.storage.get_members.return_value = [
            nonraid_storage, self.mock_storage]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            storage = redfish_raid._get_storage_controller(
                task.node, mock_get_system.return_value, ['32ADF365C6C1B7BD'])

            self.assertEqual(storage, self.mock_storage)
            nonraid_storage.drives.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    @mock.patch.object(redfish_raid.LOG, 'info', autospec=True)
    def test__raid_config_in_progress_success(
            self, mock_info, mock_get_task_monitor, mock_get_system):
        mock_task = mock.Mock()
        mock_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_task.task_status = sushy.HEALTH_OK
        mock_task.messages = []
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_task
        mock_get_task_monitor.return_value = mock_task_monitor

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            raid = redfish_raid.RedfishRAID()
            result = raid._raid_config_in_progress(
                task, '/TaskService/123', 'create')
            self.assertEqual(False, result)
            mock_info.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    @mock.patch.object(redfish_raid.LOG, 'info', autospec=True)
    def test__raid_config_in_progress_task_mon_error(
            self, mock_info, mock_get_task_monitor, mock_get_system):
        mock_get_task_monitor.side_effect = exception.RedfishError(
            error='Task not found')

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            raid = redfish_raid.RedfishRAID()
            result = raid._raid_config_in_progress(
                task, '/TaskService/123', 'create')
            self.assertEqual(False, result)
            mock_info.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    @mock.patch.object(redfish_raid.LOG, 'debug', autospec=True)
    def test__raid_config_in_progress_still_processing(
            self, mock_debug, mock_get_task_monitor, mock_get_system):
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = True
        mock_get_task_monitor.return_value = mock_task_monitor

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            raid = redfish_raid.RedfishRAID()
            result = raid._raid_config_in_progress(
                task, '/TaskService/123', 'create')
            self.assertEqual(True, result)
            mock_debug.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    @mock.patch.object(redfish_raid.LOG, 'error', autospec=True)
    def test__raid_config_in_progress_failed(
            self, mock_error, mock_get_task_monitor, mock_get_system):
        mock_message = mock.Mock()
        mock_message.message = 'RAID configuration failed'
        mock_message.severity = sushy.SEVERITY_CRITICAL
        mock_task = mock.Mock()
        mock_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_task.task_status = sushy.HEALTH_CRITICAL
        mock_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_task
        mock_get_task_monitor.return_value = mock_task_monitor

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:

            raid = redfish_raid.RedfishRAID()
            result = raid._raid_config_in_progress(
                task, '/TaskService/123', 'create')
            self.assertEqual(False, result)
            mock_error.assert_called_once()

    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor',
                       autospec=True)
    def test__check_node_raid_config_deploy(
            self, mock_get_task_monitor, mock_resume_deploy,
            mock_resume_clean, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.deploy_step = {'priority': 100, 'interface': 'raid',
                                     'step': 'delete_configuration',
                                     'argsinfo': {}}
            info = task.node.driver_internal_info
            info['raid_configs'] = {'operation': 'delete', 'pending': {},
                                    'task_monitor_uri': ['/TaskService/123']}
            task.node.driver_internal_info = info
            task.node.save()

            mock_task_monitor = mock_get_task_monitor.return_value
            mock_task_monitor.is_processing = False
            mock_task_monitor.response.status_code = 200

            raid = redfish_raid.RedfishRAID()
            raid._check_node_raid_config(task)

            mock_resume_deploy.assert_called_with(task)
            mock_resume_clean.assert_not_called()
            self.assertEqual([], task.node.raid_config['logical_disks'])
            self.assertIsNotNone(task.node.raid_config.get('last_updated'))

    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor',
                       autospec=True)
    def test__check_node_raid_config_clean(
            self, mock_get_task_monitor, mock_resume_deploy,
            mock_resume_clean, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.clean_step = {'interface': 'raid',
                                    'step': 'delete_configuration',
                                    'argsinfo': {}}
            info = task.node.driver_internal_info
            info['raid_configs'] = {'operation': 'delete', 'pending': {},
                                    'task_monitor_uri': ['/TaskService/123']}
            task.node.driver_internal_info = info
            task.node.save()

            mock_task_monitor = mock_get_task_monitor.return_value
            mock_task_monitor.is_processing = False
            mock_task_monitor.response.status_code = 200

            raid = redfish_raid.RedfishRAID()
            raid._check_node_raid_config(task)

            mock_resume_deploy.assert_not_called()
            mock_resume_clean.assert_called_with(task)
            self.assertEqual([], task.node.raid_config['logical_disks'])
            self.assertIsNotNone(task.node.raid_config.get('last_updated'))

    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor',
                       autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID,
                       '_submit_create_configuration', autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID,
                       '_submit_delete_configuration', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    def test__check_node_raid_config_pending_create(
            self, mock_build_agent_opt, mock_submit_delete, mock_submit_create,
            mock_get_task_monitor, mock_node_power_action, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.clean_step = {'interface': 'raid',
                                    'step': 'create_configuration',
                                    'argsinfo': {}}
            info = task.node.driver_internal_info
            raid_configs = {
                'operation': 'create',
                'pending': {'RAID controller 1': [
                    {'controller': 'RAID controller 1',
                     'disk_type': 'ssd',
                     'is_root_volume': True,
                     'physical_disks': [self.drive_id5,
                                        self.drive_id6,
                                        self.drive_id7],
                     'raid_level': '5',
                     'size_bytes': 107374182400,
                     'span_depth': 1,
                     'span_length': 3.0}]},
                'task_monitor_uri': ['/TaskService/123']}
            info['raid_configs'] = raid_configs
            task.node.driver_internal_info = info
            task.node.save()

            mock_task_monitor = mock_get_task_monitor.return_value
            mock_task_monitor.is_processing = False
            mock_task_monitor.response.status_code = 200

            mock_submit_create.return_value = ({}, True)

            raid = redfish_raid.RedfishRAID()
            raid._check_node_raid_config(task)

            mock_submit_create.assert_called_with(
                raid, task, raid_configs['pending'])
            mock_submit_delete.assert_not_called()
            mock_build_agent_opt.assert_called_with(task.node)
            # Not yet updated as in progress
            self.assertEqual({}, task.node.raid_config)

    @mock.patch.object(redfish_utils, 'get_task_monitor',
                       autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID,
                       '_submit_create_configuration', autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID,
                       '_submit_delete_configuration', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    def test__check_node_raid_config_pending_delete(
            self, mock_build_agent_opt, mock_submit_delete, mock_submit_create,
            mock_get_task_monitor, mock_get_system):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.clean_step = {'interface': 'raid',
                                    'step': 'delete_configuration',
                                    'argsinfo': {}}
            info = task.node.driver_internal_info
            raid_configs = {
                'operation': 'delete',
                'pending': True,
                'task_monitor_uri': ['/TaskService/123']}
            info['raid_configs'] = raid_configs
            task.node.driver_internal_info = info
            task.node.save()

            mock_task_monitor = mock_get_task_monitor.return_value
            mock_task_monitor.is_processing = False
            mock_task_monitor.response.status_code = 200

            mock_submit_delete.return_value = ({}, False)

            raid = redfish_raid.RedfishRAID()
            raid._check_node_raid_config(task)

            mock_submit_create.assert_not_called()
            mock_submit_delete.assert_called_with(raid, task)
            mock_build_agent_opt.assert_not_called()
            # Not yet updated as in progress
            self.assertEqual({}, task.node.raid_config)
