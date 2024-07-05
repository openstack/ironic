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

from unittest import mock

from oslo_utils import importutils
import sushy
import tenacity

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import raid as drac_raid
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import raid as redfish_raid
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy_oem_idrac = importutils.try_import('sushy_oem_idrac')

INFO_DICT = test_utils.INFO_DICT


class DracCreateRaidConfigurationHelpersTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracCreateRaidConfigurationHelpersTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
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
            'status': 'ok',
            'raid_status': 'ready',
            'sas_address': '500056B37789ABE3',
            'device_protocol': None}

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


class DracRedfishRAIDTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracRedfishRAIDTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)
        self.raid = drac_raid.DracRedfishRAID()

    @mock.patch.object(drac_raid, '_wait_till_realtime_ready', autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID, 'create_configuration',
                       autospec=True)
    def test_create_configuration(self, mock_redfish_create, mock_wait):
        task = mock.Mock(node=self.node, context=self.context)

        self.raid.create_configuration(task)

        mock_wait.assert_called_once_with(task)
        mock_redfish_create.assert_called_once_with(
            self.raid, task, True, True, False)

    @mock.patch.object(drac_raid, '_wait_till_realtime_ready', autospec=True)
    @mock.patch.object(redfish_raid.RedfishRAID, 'delete_configuration',
                       autospec=True)
    def test_delete_configuration(self, mock_redfish_delete, mock_wait):
        task = mock.Mock(node=self.node, context=self.context)

        self.raid.delete_configuration(task)

        mock_wait.assert_called_once_with(task)
        mock_redfish_delete.assert_called_once_with(self.raid, task)

    @mock.patch.object(drac_raid, '_retry_till_realtime_ready', autospec=True)
    def test__wait_till_realtime_ready(self, mock_ready):
        self.node.set_driver_internal_info('cleaning_disable_ramdisk', True)
        task = mock.Mock(node=self.node, context=self.context)
        task.driver.power.get_power_state.return_value = states.POWER_OFF
        drac_raid._wait_till_realtime_ready(task)
        task.driver.power.set_power_state.assert_called_once_with(
            task, states.POWER_ON)
        mock_ready.assert_called_once_with(task)

    @mock.patch.object(drac_raid, 'LOG', autospec=True)
    @mock.patch.object(drac_raid, '_retry_till_realtime_ready', autospec=True)
    def test__wait_till_realtime_ready_retryerror(self, mock_ready, mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        mock_ready.side_effect = tenacity.RetryError(3)
        drac_raid._wait_till_realtime_ready(task)
        mock_ready.assert_called_once_with(task)
        self.assertEqual(mock_log.debug.call_count, 1)

    @mock.patch.object(drac_raid, '_is_realtime_ready', autospec=True)
    def test__retry_till_realtime_ready_retry_exceeded(self, mock_ready):
        drac_raid._retry_till_realtime_ready.retry.sleep = mock.Mock()
        drac_raid._retry_till_realtime_ready.retry.stop =\
            tenacity.stop_after_attempt(3)
        task = mock.Mock(node=self.node, context=self.context)
        mock_ready.return_value = False

        self.assertRaises(
            tenacity.RetryError,
            drac_raid._retry_till_realtime_ready, task)

        self.assertEqual(3, mock_ready.call_count)

    @mock.patch.object(drac_raid, '_is_realtime_ready', autospec=True)
    def test__retry_till_realtime_ready_retry_fails(self, mock_ready):
        drac_raid._retry_till_realtime_ready.retry.sleep = mock.Mock()
        drac_raid._retry_till_realtime_ready.retry.stop =\
            tenacity.stop_after_attempt(3)
        task = mock.Mock(node=self.node, context=self.context)
        mock_ready.side_effect = [False, exception.RedfishError]

        self.assertRaises(
            exception.RedfishError,
            drac_raid._retry_till_realtime_ready, task)

        self.assertEqual(2, mock_ready.call_count)

    @mock.patch.object(drac_raid, '_is_realtime_ready', autospec=True)
    def test__retry_till_realtime_ready(self, mock_ready):
        drac_raid._retry_till_realtime_ready.retry.sleep = mock.Mock()
        task = mock.Mock(node=self.node, context=self.context)
        mock_ready.side_effect = [False, True]

        is_ready = drac_raid._retry_till_realtime_ready(task)

        self.assertTrue(is_ready)
        self.assertEqual(2, mock_ready.call_count)

    @mock.patch.object(drac_utils, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__is_realtime_ready(self, mock_get_system, mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.lifecycle_service.is_realtime_ready.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        fake_manager_oem2 = mock.Mock()
        fake_manager_oem2.lifecycle_service.is_realtime_ready.return_value = (
            True)
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        fake_system = mock.Mock(managers=[fake_manager1, fake_manager2])
        mock_get_system.return_value = fake_system

        is_ready = drac_raid._is_realtime_ready(task)

        self.assertTrue(is_ready)
        self.assertEqual(mock_log.debug.call_count, 1)

    def test_validate_correct_vendor(self):
        task = mock.Mock(node=self.node, context=self.context)
        self.node.properties['vendor'] = 'Dell Inc.'
        self.raid.validate(task)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_pre_create_configuration(self, mock_get_system):
        mock_task_mon1 = mock.Mock(check_is_processing=True)
        mock_task_mon2 = mock.Mock(check_is_processing=False)
        fake_oem_system = mock.Mock()
        fake_oem_system.change_physical_disk_state.return_value = [
            mock_task_mon1, mock_task_mon2]
        fake_system = mock.Mock()
        fake_system.get_oem_extension.return_value = fake_oem_system

        mock_drive1 = mock.Mock(
            identity='Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1')
        mock_drive2 = mock.Mock(
            identity='Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            capacity_bytes=599550590976)  # mocked size in RAID mode
        mock_drive3 = mock.Mock(
            identity='Disk.Direct.0-0:AHCI.Slot.2-1')

        mock_controller1 = mock.Mock()
        mock_storage1 = mock.Mock(controllers=[mock_controller1],
                                  drives=[mock_drive1, mock_drive2],
                                  identity='RAID.Integrated.1-1')
        mock_storage1.controllers = mock.MagicMock()
        mock_storage1.controllers.get_members.return_value = [
            mock_controller1]

        mock_controller2 = mock.Mock()
        mock_storage2 = mock.Mock(controllers=[mock_controller2],
                                  drives=[mock_drive3],
                                  identity='AHCI.Slot.2-1')
        mock_storage2.controllers = mock.MagicMock()
        mock_storage2.controllers.get_members.return_value = [
            mock_controller2]

        fake_system.storage.get_members.return_value = [
            mock_storage1, mock_storage2]

        mock_get_system.return_value = fake_system
        task = mock.Mock(node=self.node, context=self.context)

        logical_disks_to_create = [{
            'raid_level': '0',
            'size_bytes': 600087461888,  # before RAID conversion
            'physical_disks': [
                'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
            'span_depth': 1,
            'span_length': 1.0,
            'controller': 'RAID.Integrated.1-1'}]

        result = self.raid.pre_create_configuration(
            task, logical_disks_to_create)

        self.assertEqual(
            [{'controller': 'RAID.Integrated.1-1',
              'physical_disks': [
                  'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
              'raid_level': '0',
              'size_bytes': 599550590976,  # recalculated after RAID conversion
              'span_depth': 1,
              'span_length': 1.0}], result)
        fake_oem_system.change_physical_disk_state.assert_called_once_with(
            sushy_oem_idrac.PHYSICAL_DISK_STATE_MODE_RAID,
            {mock_controller1: [mock_drive2]})
        mock_task_mon1.wait.assert_called_once_with(CONF.drac.raid_job_timeout)
        mock_task_mon2.wait.assert_not_called()

    def test__get_storage_controller_invalid_identity(self):
        fake_system = mock.Mock()

        mock_storage1 = mock.Mock(storage_controllers=[mock.Mock()],
                                  identity='RAID.Integrated.1-1')
        mock_storage2 = mock.Mock(storage_controllers=[mock.Mock()],
                                  identity='AHCI.Slot.2-1')

        fake_system.storage.get_members.return_value = [
            mock_storage1, mock_storage2]

        self.assertRaises(
            exception.IronicException,
            drac_raid.DracRedfishRAID._get_storage_controller,
            fake_system, 'NonExisting')

    @mock.patch.object(drac_raid.LOG, 'warning', autospec=True)
    def test__change_physical_disk_state_attribute_error(self, mock_log):
        fake_oem_system = mock.Mock(spec=[])
        fake_system = mock.Mock()
        fake_system.get_oem_extension.return_value = fake_oem_system

        result = drac_raid.DracRedfishRAID._change_physical_disk_state(
            fake_system, sushy_oem_idrac.PHYSICAL_DISK_STATE_MODE_RAID
        )

        self.assertEqual(False, result)
        mock_log.assert_called_once()

    @mock.patch.object(deploy_utils, 'reboot_to_finish_step',
                       autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode(
            self, mock_get_system, mock_reboot):
        mock_task_mon = mock.Mock(task_monitor_uri='/TaskService/1')
        mock_oem_controller = mock.Mock()
        mock_oem_controller.convert_to_raid.return_value = mock_task_mon
        mock_controller = mock.Mock()
        mock_controller.get_oem_extension.return_value = mock_oem_controller
        mock_controllers_col = mock.Mock()
        mock_controllers_col.get_members.return_value = [mock_controller]
        mock_storage = mock.Mock(controllers=mock_controllers_col)
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertEqual(
                ['/TaskService/1'],
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertEqual(mock_reboot.return_value, result)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode_no_conversion(
            self, mock_get_system):
        mock_oem_controller = mock.Mock()
        mock_oem_controller.convert_to_raid.return_value = None
        mock_controller = mock.Mock()
        mock_controller.get_oem_extension.return_value = mock_oem_controller
        mock_controllers_col = mock.Mock()
        mock_controllers_col.get_members.return_value = [mock_controller]
        mock_storage = mock.Mock(controllers=mock_controllers_col)
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(result)

    @mock.patch.object(drac_raid.LOG, 'warning', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode_not_raid(
            self, mock_get_system, mock_log):
        mock_storage = mock.Mock(storage_controllers=None)
        mock_controllers = mock.PropertyMock(
            side_effect=sushy.exceptions.MissingAttributeError)
        type(mock_storage).controllers = mock_controllers
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(result)
            mock_log.assert_not_called()

    @mock.patch.object(drac_raid.LOG, 'warning', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode_old_idrac(
            self, mock_get_system, mock_log):
        mock_storage = mock.Mock(storage_controllers=mock.Mock())
        mock_controllers = mock.PropertyMock(
            side_effect=sushy.exceptions.MissingAttributeError)
        type(mock_storage).controllers = mock_controllers
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(result)
            mock_log.assert_called_once()

    @mock.patch.object(drac_raid.LOG, 'warning', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode_old_sushy(
            self, mock_get_system, mock_log):
        mock_storage = mock.Mock(spec=[])
        mock_storage.identity = "Storage 1"
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(result)
            mock_log.assert_called_once()

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test__convert_controller_to_raid_mode_old_sushy_oem(
            self, mock_get_system):
        mock_controller = mock.Mock()
        mock_controller.get_oem_extension.side_effect =\
            sushy.exceptions.ExtensionError
        mock_controllers_col = mock.Mock()
        mock_controllers_col.get_members.return_value = [mock_controller]
        mock_storage = mock.Mock(controllers=mock_controllers_col)
        mock_storage_col = mock.Mock()
        mock_storage_col.get_members.return_value = [mock_storage]
        mock_system = mock.Mock(storage=mock_storage_col)
        mock_get_system.return_value = mock_system

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            result = self.raid._convert_controller_to_raid_mode(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(result)

    @mock.patch.object(drac_raid.DracRedfishRAID,
                       '_convert_controller_to_raid_mode', autospec=True)
    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_delete_configuration_foreign_async(
            self, mock_get_system, mock_build_agent_options,
            mock_get_async_step_return_state, mock_convert):
        fake_oem_system = mock.Mock()
        fake_system = mock.Mock()
        fake_system.get_oem_extension.return_value = fake_oem_system
        mock_get_system.return_value = fake_system
        task = mock.Mock(node=self.node, context=self.context)
        mock_return_state1 = mock.Mock()
        mock_return_state2 = mock.Mock()
        mock_get_async_step_return_state.return_value = mock_return_state2
        mock_oem_task1 = mock.Mock(
            job_type=sushy_oem_idrac.JOB_TYPE_RT_NO_REBOOT_CONF)
        mock_task1 = mock.Mock()
        mock_task1.get_oem_extension.return_value = mock_oem_task1
        mock_task_mon1 = mock.Mock(check_is_processing=True)
        mock_task_mon1.task_monitor_uri = '/TaskService/1'
        mock_task_mon1.get_task.return_value = mock_task1
        mock_oem_task2 = mock.Mock(job_type=sushy_oem_idrac.JOB_TYPE_RAID_CONF)
        mock_task2 = mock.Mock()
        mock_task2.get_oem_extension.return_value = mock_oem_task2
        mock_task_mon2 = mock.Mock(check_is_processing=False)
        mock_task_mon2.task_monitor_uri = '/TaskService/2'
        mock_task_mon2.get_task.return_value = mock_task2
        fake_oem_system.clear_foreign_config.return_value = [
            mock_task_mon1, mock_task_mon2]

        result = self.raid.post_delete_configuration(
            task, None, return_state=mock_return_state1)

        self.assertEqual(result, mock_return_state2)
        fake_oem_system.clear_foreign_config.assert_called_once()
        mock_build_agent_options.assert_called_once_with(task.node)
        mock_get_async_step_return_state.assert_called_once_with(task.node)
        mock_task_mon1.wait.assert_not_called()
        mock_task_mon2.wait.assert_not_called()
        mock_convert.assert_not_called()

    @mock.patch.object(drac_raid.DracRedfishRAID,
                       '_convert_controller_to_raid_mode', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_delete_configuration_foreign_sync(
            self, mock_get_system, mock_convert):
        fake_oem_system = mock.Mock()
        fake_system = mock.Mock()
        fake_system.get_oem_extension.return_value = fake_oem_system
        mock_get_system.return_value = fake_system
        task = mock.Mock(node=self.node, context=self.context)
        mock_return_state1 = mock.Mock()
        mock_oem_task1 = mock.Mock(
            job_type=sushy_oem_idrac.JOB_TYPE_RT_NO_REBOOT_CONF)
        mock_task1 = mock.Mock()
        mock_task1.get_oem_extension.return_value = mock_oem_task1
        mock_task_mon1 = mock.Mock(check_is_processing=True)
        mock_task_mon1.get_task.return_value = mock_task1
        mock_oem_task2 = mock.Mock(
            job_type=sushy_oem_idrac.JOB_TYPE_RT_NO_REBOOT_CONF)
        mock_task2 = mock.Mock()
        mock_task2.get_oem_extension.return_value = mock_oem_task2
        mock_task_mon2 = mock.Mock(check_is_processing=False)
        mock_task_mon2.get_task.return_value = mock_task2
        fake_oem_system.clear_foreign_config.return_value = [
            mock_task_mon1, mock_task_mon2]
        mock_convert_state = mock.Mock()
        mock_convert.return_value = mock_convert_state

        result = self.raid.post_delete_configuration(
            task, None, return_state=mock_return_state1)

        self.assertEqual(result, mock_convert_state)
        fake_oem_system.clear_foreign_config.assert_called_once()
        mock_task_mon1.wait.assert_called_once_with(CONF.drac.raid_job_timeout)
        mock_task_mon2.wait.assert_not_called()

    @mock.patch.object(drac_raid.DracRedfishRAID,
                       '_convert_controller_to_raid_mode', autospec=True)
    @mock.patch.object(drac_raid.DracRedfishRAID,
                       '_clear_foreign_config', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_delete_configuration_no_subtasks(
            self, mock_get_system, mock_foreign, mock_convert):
        mock_foreign.return_value = False
        mock_convert.return_value = None
        task = mock.Mock(node=self.node, context=self.context)
        mock_return_state1 = mock.Mock()

        result = self.raid.post_delete_configuration(
            task, None, return_state=mock_return_state1)

        self.assertEqual(mock_return_state1, result)

    @mock.patch.object(drac_raid.LOG, 'warning', autospec=True)
    def test__clear_foreign_config_attribute_error(self, mock_log):
        fake_oem_system = mock.Mock(spec=[])
        fake_system = mock.Mock()
        fake_system.get_oem_extension.return_value = fake_oem_system

        result = drac_raid.DracRedfishRAID._clear_foreign_config(
            fake_system, mock.Mock())

        self.assertEqual(False, result)
        mock_log.assert_called_once()

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_tasks_status(self, mock_acquire):
        driver_internal_info = {'raid_task_monitor_uris': ['/TaskService/123']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(raid=self.raid))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.raid._check_raid_tasks_status = mock.Mock()

        self.raid._query_raid_tasks_status(mock_manager, self.context)

        self.raid._check_raid_tasks_status.assert_called_once_with(
            task, ['/TaskService/123'])

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_tasks_status_no_task_monitor_url(self, mock_acquire):
        driver_internal_info = {'something': 'else'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(raid=self.raid))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.raid._check_raid_tasks_status = mock.Mock()

        self.raid._query_raid_tasks_status(mock_manager, self.context)

        self.raid._check_raid_tasks_status.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_raid_tasks_status(self, mock_get_task_monitor):
        driver_internal_info = {
            'raid_task_monitor_uris': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Clear foreign config done'
        mock_config_task = mock.Mock()
        mock_config_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_config_task.task_status = sushy.HEALTH_OK
        mock_config_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_config_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.raid._set_success = mock.Mock()
        self.raid._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._check_raid_tasks_status(
                task, ['/TaskService/123'])

            self.raid._set_success.assert_called_once_with(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.raid._set_failed.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_raid_tasks_status_task_still_processing(
            self, mock_get_task_monitor):
        driver_internal_info = {
            'raid_task_monitor_uris': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Clear foreign config done'
        mock_config_task = mock.Mock()
        mock_config_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_config_task.task_status = sushy.HEALTH_OK
        mock_config_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_config_task
        mock_task_monitor2 = mock.Mock()
        mock_task_monitor2.is_processing = True
        mock_get_task_monitor.side_effect = [
            mock_task_monitor, mock_task_monitor2]

        self.raid._set_success = mock.Mock()
        self.raid._set_failed = mock.Mock()
        self.raid._substep_change_physical_disk_state_nonraid = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._check_raid_tasks_status(
                task, ['/TaskService/123', '/TaskService/456'])

            (self.raid._substep_change_physical_disk_state_nonraid
                .assert_not_called())
            self.raid._set_success.assert_not_called()
            self.assertEqual(
                ['/TaskService/456'],
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.raid._set_failed.assert_not_called()

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_raid_tasks_status_task_failed(self, mock_get_task_monitor):
        driver_internal_info = {
            'raid_task_monitor_uris': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Clear foreign config failed'
        mock_config_task = mock.Mock()
        mock_config_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_config_task.task_status = 'Failed'
        mock_config_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_config_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.raid._set_success = mock.Mock()
        self.raid._set_failed = mock.Mock()
        self.raid._substep_change_physical_disk_state_nonraid = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._check_raid_tasks_status(
                task, ['/TaskService/123'])

            (self.raid._substep_change_physical_disk_state_nonraid
                .assert_not_called())
            self.raid._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.raid._set_failed.assert_called_once()

    @mock.patch.object(drac_raid.DracRedfishRAID,
                       '_convert_controller_to_raid_mode', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_raid_tasks_status_convert_controller(
            self, mock_get_task_monitor, mock_convert):
        driver_internal_info = {
            'raid_task_monitor_uris': '/TaskService/1',
            'raid_config_substep': 'clear_foreign_config'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_config_task = mock.Mock()
        mock_config_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_config_task.task_status = sushy.HEALTH_OK
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_config_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.raid._set_success = mock.Mock()
        self.raid._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._check_raid_tasks_status(
                task, ['/TaskService/1'])

            mock_convert.assert_called_once_with(task)
            self.raid._set_success.assert_not_called()
            self.raid._set_failed.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_task_monitor_uris'))
            self.assertIsNone(
                task.node.driver_internal_info.get('raid_config_substep'))

    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test__set_success_clean(self, mock_notify_clean, mock_notify_deploy):
        self.node.clean_step = {'test': 'value'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._set_success(task)

            mock_notify_clean.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test__set_success_deploy(self, mock_notify_clean, mock_notify_deploy):
        self.node.clean_step = None
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._set_success(task)

            mock_notify_deploy.assert_called_once_with(task)

    @mock.patch.object(manager_utils, 'deploying_error_handler',
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler',
                       autospec=True)
    def test__set_failed_clean(self, mock_clean_handler, mock_deploy_handler):
        self.node.clean_step = {'test': 'value'}
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._set_failed(task, 'error', 'log message')

            mock_clean_handler.assert_called_once_with(
                task, 'error', 'log message')

    @mock.patch.object(manager_utils, 'deploying_error_handler',
                       autospec=True)
    @mock.patch.object(manager_utils, 'cleaning_error_handler',
                       autospec=True)
    def test__set_failed_deploy(self, mock_clean_handler, mock_deploy_handler):
        self.node.clean_step = None
        self.node.save()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.raid._set_failed(task, 'error', 'log message')

            mock_deploy_handler.assert_called_once_with(
                task, 'error', 'log message')
