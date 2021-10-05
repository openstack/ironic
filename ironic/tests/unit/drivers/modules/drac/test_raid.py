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

from collections import defaultdict
from unittest import mock

from dracclient import constants
from dracclient import exceptions as drac_exceptions
from oslo_utils import importutils
import tenacity

from ironic.common import exception
from ironic.common import states
from ironic.conductor import periodics
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.conf import CONF
from ironic.drivers import base
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import raid as drac_raid
from ironic.drivers.modules.drac import utils as drac_utils
from ironic.drivers.modules.redfish import raid as redfish_raid
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')
sushy_oem_idrac = importutils.try_import('sushy_oem_idrac')

INFO_DICT = test_utils.INFO_DICT


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracQueryRaidConfigurationTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracQueryRaidConfigurationTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        self.raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)

        virtual_disk_dict = {
            'id': 'Disk.Virtual.0:RAID.Integrated.1-1',
            'name': 'disk 0',
            'description': 'Virtual Disk 0 on Integrated RAID Controller 1',
            'controller': 'RAID.Integrated.1-1',
            'raid_level': '1',
            'size_mb': 571776,
            'status': 'ok',
            'raid_status': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None,
            'physical_disks': []}
        self.virtual_disk = test_utils.make_virtual_disk(virtual_disk_dict)

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
            'status': 'ok',
            'raid_status': 'ready',
            'sas_address': '500056B37789ABE3',
            'device_protocol': None}
        self.physical_disk = test_utils.make_physical_disk(physical_disk_dict)

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
class DracManageVirtualDisksTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracManageVirtualDisksTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_create_virtual_disk(self, mock_validate_job_queue,
                                 mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.create_virtual_disk(
            self.node, 'controller', ['disk1', 'disk2'], '1+0', 43008)

        mock_validate_job_queue.assert_called_once_with(
            self.node, name_prefix='Config:RAID:controller')
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

        mock_validate_job_queue.assert_called_once_with(
            self.node, name_prefix='Config:RAID:controller')
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

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test__reset_raid_config(self, mock_validate_job_queue,
                                mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid._reset_raid_config(
            self.node, 'controller')

        mock_validate_job_queue.assert_called_once_with(
            self.node, name_prefix='Config:RAID:controller')
        mock_client.reset_raid_config.assert_called_once_with(
            'controller')

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test__reset_raid_config_fail(self, mock_validate_job_queue,
                                     mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        exc = drac_exceptions.BaseClientException('boom')
        mock_client.reset_raid_config.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid._reset_raid_config,
            self.node, 'RAID.Integrated.1-1')

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_clear_foreign_config(self, mock_validate_job_queue,
                                  mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.clear_foreign_config(
            self.node, 'RAID.Integrated.1-1')

        mock_validate_job_queue.assert_called_once_with(
            self.node, 'Config:RAID:RAID.Integrated.1-1')
        mock_client.clear_foreign_config.assert_called_once_with(
            'RAID.Integrated.1-1')

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_clear_foreign_config_fail(self, mock_validate_job_queue,
                                       mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        exc = drac_exceptions.BaseClientException('boom')
        mock_client.clear_foreign_config.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.clear_foreign_config,
            self.node, 'RAID.Integrated.1-1')

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_raid_settings(self, mock_validate_job_queue,
                               mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        controller_fqdd = "RAID.Integrated.1-1"
        raid_cntrl_attr = "RAID.Integrated.1-1:RAIDRequestedControllerMode"
        raid_settings = {raid_cntrl_attr: 'RAID'}
        drac_raid.set_raid_settings(self.node, controller_fqdd, raid_settings)

        mock_validate_job_queue.assert_called_once_with(
            self.node)
        mock_client.set_raid_settings.assert_called_once_with(
            controller_fqdd, raid_settings)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_list_raid_settings(self, mock_validate_job_queue,
                                mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        drac_raid.list_raid_settings(self.node)
        mock_validate_job_queue.assert_called_once_with(
            self.node)
        mock_client.list_raid_settings.assert_called_once_with()

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_change_physical_disk_state(self,
                                        mock_validate_job_queue,
                                        mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        controllers_to_physical_disk_ids = {'RAID.Integrated.1-1': [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1']}
        expected_change_disk_state = {
            'is_reboot_required': True,
            'conversion_results': {
                'RAID.Integrated.1-1': {'is_reboot_required': 'optional',
                                        'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}
        mode = constants.RaidStatus.raid
        mock_client.change_physical_disk_state.return_value = \
            expected_change_disk_state
        actual_change_disk_state = drac_raid.change_physical_disk_state(
            self.node,
            mode=mode,
            controllers_to_physical_disk_ids=controllers_to_physical_disk_ids)

        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.change_physical_disk_state.assert_called_once_with(
            mode, controllers_to_physical_disk_ids)
        self.assertEqual(expected_change_disk_state, actual_change_disk_state)

    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test__change_physical_disk_mode(self,
                                        mock_commit_config,
                                        mock_change_physical_disk_state,
                                        mock_get_drac_client):
        mock_commit_config.return_value = '42'
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        actual_change_disk_state = drac_raid._change_physical_disk_mode(
            self.node, mode=constants.RaidStatus.raid)
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual('completed',
                         self.node.driver_internal_info['raid_config_substep'])
        self.assertEqual(
            ['RAID.Integrated.1-1'],
            self.node.driver_internal_info['raid_config_parameters'])
        mock_commit_config.assert_called_once_with(
            self.node, raid_controller='RAID.Integrated.1-1', reboot=False,
            realtime=True)
        self.assertEqual(states.DEPLOYWAIT, actual_change_disk_state)

    def test_commit_config(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.commit_config(self.node, 'controller1')

        mock_client.commit_pending_raid_changes.assert_called_once_with(
            raid_controller='controller1', reboot=False, realtime=False)

    def test_commit_config_with_reboot(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.commit_config(self.node, 'controller1', reboot=True,
                                realtime=False)

        mock_client.commit_pending_raid_changes.assert_called_once_with(
            raid_controller='controller1', reboot=True, realtime=False)

    def test_commit_config_with_realtime(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        drac_raid.commit_config(self.node, 'RAID.Integrated.1-1', reboot=False,
                                realtime=True)

        mock_client.commit_pending_raid_changes.assert_called_once_with(
            raid_controller='RAID.Integrated.1-1', reboot=False, realtime=True)

    def test_commit_config_fail(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = drac_exceptions.BaseClientException('boom')
        mock_client.commit_pending_raid_changes.side_effect = exc

        self.assertRaises(
            exception.DracOperationError, drac_raid.commit_config, self.node,
            'controller1')

    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test__commit_to_controllers_with_config_job(self, mock_commit_config,
                                                    mock_get_drac_client):
        controllers = [{'is_reboot_required': 'true',
                        'is_commit_required': True,
                        'is_ehba_mode': False,
                        'raid_controller': 'AHCI.Slot.3-1'}]
        substep = "delete_foreign_config"

        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_commit_config.return_value = "42"
        drac_raid._commit_to_controllers(self.node,
                                         controllers=controllers,
                                         substep=substep)

        self.assertEqual(1, mock_commit_config.call_count)
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual(substep,
                         self.node.driver_internal_info['raid_config_substep'])

    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test__commit_to_controllers_without_config_job(
            self, mock_commit_config, mock_get_drac_client):
        controllers = [{'is_reboot_required': 'true',
                        'is_commit_required': False,
                        'raid_controller': 'AHCI.Slot.3-1'}]
        substep = "delete_foreign_config"

        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_commit_config.return_value = None
        drac_raid._commit_to_controllers(self.node,
                                         controllers=controllers,
                                         substep=substep)

        self.assertEqual(0, mock_commit_config.call_count)
        self.assertNotIn('raid_config_job_ids', self.node.driver_internal_info)
        self.assertEqual(substep,
                         self.node.driver_internal_info['raid_config_substep'])

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

    def _generate_physical_disks(self):
        physical_disks = []

        for disk in self.physical_disks:
            physical_disks.append(test_utils.make_physical_disk(disk))

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
                                                      physical_disks,
                                                      False)

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
                                                      physical_disks,
                                                      False)

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
                                                      physical_disks,
                                                      False)

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

    def test__find_configuration_pending_delete(self):
        logical_disks = [
            {'size_mb': 102400,
             'raid_level': '5',
             'is_root_volume': True,
             'disk_type': 'hdd'}
        ]
        physical_disks = self._generate_physical_disks()
        # No free space, but deletion pending means they're still usable.
        physical_disks = [disk._replace(free_size_mb=0)
                          for disk in physical_disks]

        expected_contoller = 'RAID.Integrated.1-1'
        expected_physical_disk_ids = [
            'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
            'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1']

        logical_disks = drac_raid._find_configuration(logical_disks,
                                                      physical_disks,
                                                      True)

        self.assertEqual(expected_contoller,
                         logical_disks[0]['controller'])
        self.assertEqual(expected_physical_disk_ids,
                         logical_disks[0]['physical_disks'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    def test__validate_volume_size_requested_more_than_actual_size(
            self, mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        self.logical_disk = {
            'physical_disks': [
                'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.7:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
            'raid_level': '1+0', 'is_root_volume': True,
            'size_mb': 102400000,
            'controller': 'RAID.Integrated.1-1'}

        self.logical_disks = [self.logical_disk.copy()]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        processed_logical_disks = drac_raid._validate_volume_size(
            self.node, self.node.target_raid_config['logical_disks'])

        self.assertEqual(2287104, processed_logical_disks[0]['size_mb'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    def test__validate_volume_size_requested_less_than_actual_size(
            self, mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        self.logical_disk = {
            'physical_disks': [
                'Disk.Bay.0:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.1:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.2:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.3:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.4:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.5:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.6:Enclosure.Internal.0-1:RAID.Integrated.1-1',
                'Disk.Bay.7:Enclosure.Internal.0-1:RAID.Integrated.1-1'],
            'raid_level': '1+0', 'is_root_volume': True,
            'size_mb': 204800,
            'controller': 'RAID.Integrated.1-1'}

        self.logical_disks = [self.logical_disk.copy()]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        processed_logical_disks = drac_raid._validate_volume_size(
            self.node, self.node.target_raid_config['logical_disks'])

        self.assertEqual(self.logical_disk, processed_logical_disks[0])


class DracRaidInterfaceTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracRaidInterfaceTestCase, self).setUp()
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
        self.node.clean_step = {'foo': 'bar'}
        self.node.save()

    def _generate_physical_disks(self):
        physical_disks = []

        for disk in self.physical_disks:
            physical_disks.append(test_utils.make_physical_disk(disk))

        return physical_disks

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def _test_create_configuration(
            self, expected_state,
            mock_commit_config,
            mock_change_physical_disk_state,
            mock_validate_job_queue,
            mock_list_physical_disks,
            mock__reset_raid_config, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)
        mock_client.list_raid_controllers.return_value = [raid_controller]
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}
        mock_commit_config.side_effect = ['42']
        next_substep = "create_virtual_disks"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=False)

            mock_commit_config.assert_called_with(
                task.node, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

            self.assertEqual(expected_state, return_value)
            self.assertEqual(1, mock_commit_config.call_count)
            self.assertEqual(1, mock_change_physical_disk_state.call_count)

            self.node.refresh()
            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            self.assertEqual(next_substep,
                             task.node.driver_internal_info[
                                 'raid_config_substep'])
            self.assertEqual(['42'],
                             task.node.driver_internal_info[
                                 'raid_config_job_ids'])

    def test_create_configuration_in_clean(self):
        self._test_create_configuration(states.CLEANWAIT)

    def test_create_configuration_in_deploy(self):
        self.node.clean_step = None
        self.node.save()
        self._test_create_configuration(states.DEPLOYWAIT)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_without_drives_conversion(
            self, mock_commit_config,
            mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock__reset_raid_config, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)
        mock_client.list_raid_controllers.return_value = [raid_controller]
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.false,
            'is_commit_required': True}
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.false,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.false,
                    'is_commit_required': False}},
            'commit_required_ids': ['RAID.Integrated.1-1']}
        mock_client.create_virtual_disk.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}
        mock_commit_config.side_effect = ['42']
        next_substep = "completed"

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=False)

            mock_commit_config.assert_called_with(
                task.node, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

            self.assertEqual(states.CLEANWAIT, return_value)
            self.assertEqual(1, mock_commit_config.call_count)
            self.assertEqual(1, mock_change_physical_disk_state.call_count)
            self.assertEqual(1, mock_client.create_virtual_disk.call_count)

            self.node.refresh()
            self.assertEqual(False,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            self.assertEqual(next_substep,
                             task.node.driver_internal_info[
                                 'raid_config_substep'])
            self.assertEqual(['42'],
                             task.node.driver_internal_info[
                                 'raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_no_change(
            self, mock_commit_config,
            mock_change_physical_disk_state,
            mock_list_physical_disks, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.false,
                    'is_commit_required': False}},
            'commit_required_ids': ['RAID.Integrated.1-1']}
        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=False, create_nonroot_volumes=False,
                delete_existing=False)

            self.assertEqual(False,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            self.assertEqual(0, mock_client.create_virtual_disk.call_count)
            self.assertEqual(0, mock_commit_config.call_count)

        self.assertIsNone(return_value)

        self.node.refresh()
        self.assertNotIn('raid_config_job_ids', self.node.driver_internal_info)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_virtual_disks', autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_settings', autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_delete_existing(
            self, mock_commit_config,
            mock_validate_job_queue,
            mock_change_physical_disk_state,
            mock_list_physical_disks,
            mock_list_raid_settings,
            mock_list_virtual_disks,
            mock__reset_raid_config,
            mock_get_drac_client):
        self.node.clean_step = None
        self.node.save()
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        physical_disks = self._generate_physical_disks()
        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)

        raid_attr = "RAID.Integrated.1-1:RAIDCurrentControllerMode"
        raid_controller_config = {
            'id': 'RAID.Integrated.1-1:RAIDCurrentControllerMode',
            'current_value': ['RAID'],
            'read_only': True,
            'name': 'RAIDCurrentControllerMode',
            'possible_values': ['RAID', 'Enhanced HBA']}
        raid_cntrl_settings = {
            raid_attr: test_utils.create_raid_setting(raid_controller_config)}

        mock_list_raid_settings.return_value = raid_cntrl_settings
        mock_list_physical_disks.return_value = physical_disks
        mock_commit_config.side_effect = ['12']
        mock_client.list_raid_controllers.return_value = [raid_controller]
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}

        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=False,
                delete_existing=True)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            mock_commit_config.assert_called_with(
                task.node, raid_controller='RAID.Integrated.1-1',
                realtime=True, reboot=False)

            self.assertEqual(1, mock_commit_config.call_count)

        self.assertEqual(states.DEPLOYWAIT, return_value)
        self.node.refresh()
        self.assertEqual(['12'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_nested_raid_level(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.root_logical_disk = {
            'size_gb': 100,
            'raid_level': '5+0',
            'is_root_volume': True
        }

        self.logical_disks = [self.root_logical_disk]
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks
        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

            self.assertEqual(1, mock_commit_config.call_count)
            self.assertEqual(1, mock_change_physical_disk_state.call_count)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_nested_raid_10(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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

        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

            self.assertEqual(1, mock_commit_config.call_count)
            self.assertEqual(1, mock_change_physical_disk_state.call_count)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_multiple_controllers(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        self.physical_disks[0]['controller'] = 'controller-2'
        self.physical_disks[1]['controller'] = 'controller-2'
        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.side_effect = ['42']

        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_backing_physical_disks(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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

        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1',
                reboot=False, realtime=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_predefined_number_of_physical_disks(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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
        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1',
                reboot=False, realtime=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_max_size(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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
        self.logical_disks = ([self.root_logical_disk]
                              + self.nonroot_logical_disks)
        self.target_raid_configuration = {'logical_disks': self.logical_disks}
        self.node.target_raid_config = self.target_raid_configuration
        self.node.save()

        physical_disks = self._generate_physical_disks()
        mock_list_physical_disks.return_value = physical_disks

        mock_commit_config.side_effect = ['12']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

        self.node.refresh()
        self.assertEqual(['12'],
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
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_share_physical_disks(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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

        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_with_sharing_disabled(
            self, mock_commit_config, mock_validate_job_queue,
            mock_list_physical_disks, mock__reset_raid_config,
            mock_get_drac_client):
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
        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)
        mock_client.list_raid_controllers.return_value = [raid_controller]
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
    @mock.patch.object(drac_raid, 'change_physical_disk_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_with_max_size_and_share_physical_disks(
            self, mock_commit_config, mock_change_physical_disk_state,
            mock_validate_job_queue, mock_list_physical_disks,
            mock_get_drac_client):
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

        mock_commit_config.side_effect = ['42']
        mock_change_physical_disk_state.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'conversion_results': {
                'RAID.Integrated.1-1': {
                    'is_reboot_required': constants.RebootRequired.optional,
                    'is_commit_required': True}},
            'commit_required_ids': ['RAID.Integrated.1-1']}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.create_configuration(
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

            self.assertEqual(True,
                             task.node.driver_internal_info[
                                 'volume_validation'])
            # Commits to the controller
            mock_commit_config.assert_called_with(
                mock.ANY, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

        self.node.refresh()
        self.assertEqual(['42'], self.node.driver_internal_info[
            'raid_config_job_ids'])

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
                task, create_root_volume=True, create_nonroot_volumes=True,
                delete_existing=False)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_if_not_enough_space(
            self, mock_commit_config,
            mock_validate_job_queue, mock_list_physical_disks,
            mock__reset_raid_config, mock_get_drac_client):
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
        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)
        mock_client.list_raid_controllers.return_value = [raid_controller]
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}

        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_physical_disks', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_create_configuration_fails_if_disk_already_reserved(
            self, mock_commit_config,
            mock_validate_job_queue, mock_list_physical_disks,
            mock__reset_raid_config, mock_get_drac_client):
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

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}
        raid_controller = test_utils.make_raid_controller(
            raid_controller_dict)
        mock_client.list_raid_controllers.return_value = [raid_controller]

        mock_commit_config.return_value = '42'
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(
                exception.DracOperationError,
                task.driver.raid.create_configuration,
                task, create_root_volume=True, create_nonroot_volumes=True)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_controllers', autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_settings', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def _test_delete_configuration(self, expected_state,
                                   mock_commit_config,
                                   mock_validate_job_queue,
                                   mock_list_raid_settings,
                                   mock_list_raid_controllers,
                                   mock__reset_raid_config,
                                   mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        raid_attr = "RAID.Integrated.1-1:RAIDCurrentControllerMode"
        raid_controller_config = {
            'id': 'RAID.Integrated.1-1:RAIDCurrentControllerMode',
            'current_value': ['RAID'],
            'read_only': True,
            'name': 'RAIDCurrentControllerMode',
            'possible_values': ['RAID', 'Enhanced HBA']}

        raid_cntrl_settings = {
            raid_attr: test_utils.create_raid_setting(raid_controller_config)}

        raid_controller_dict = {
            'id': 'RAID.Integrated.1-1',
            'description': 'Integrated RAID Controller 1',
            'manufacturer': 'DELL',
            'model': 'PERC H710 Mini',
            'primary_status': 'ok',
            'firmware_version': '21.3.0-0009',
            'bus': '1',
            'supports_realtime': True}

        mock_list_raid_controllers.return_value = [
            test_utils.make_raid_controller(raid_controller_dict)]
        mock_list_raid_settings.return_value = raid_cntrl_settings
        mock_commit_config.return_value = '42'
        mock__reset_raid_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)

            mock_commit_config.assert_called_once_with(
                task.node, raid_controller='RAID.Integrated.1-1', reboot=False,
                realtime=True)

        self.assertEqual(expected_state, return_value)
        self.node.refresh()
        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    def test_delete_configuration_in_clean(self):
        self._test_delete_configuration(states.CLEANWAIT)

    def test_delete_configuration_in_deploy(self):
        self.node.clean_step = None
        self.node.save()
        self._test_delete_configuration(states.DEPLOYWAIT)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_controllers', autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_settings', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', spec_set=True,
                       autospec=True)
    def test_delete_configuration_with_mix_realtime_controller_in_raid_mode(
            self, mock__reset_raid_config, mock_commit_config,
            mock_validate_job_queue, mock_list_raid_settings,
            mock_list_raid_controllers, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        expected_raid_config_params = ['AHCI.Slot.3-1', 'RAID.Integrated.1-1']
        mix_controllers = [{'id': 'AHCI.Slot.3-1',
                            'description': 'AHCI controller in slot 3',
                            'manufacturer': 'DELL',
                            'model': 'BOSS-S1',
                            'primary_status': 'unknown',
                            'firmware_version': '2.5.13.3016',
                            'bus': '5E',
                            'supports_realtime': False},
                           {'id': 'RAID.Integrated.1-1',
                            'description': 'Integrated RAID Controller 1',
                            'manufacturer': 'DELL',
                            'model': 'PERC H740 Mini',
                            'primary_status': 'unknown',
                            'firmware_version': '50.5.0-1750',
                            'bus': '3C',
                            'supports_realtime': True}]

        mock_list_raid_controllers.return_value = [
            test_utils.make_raid_controller(controller) for
            controller in mix_controllers]

        raid_controller_config = [
            {'id': 'AHCI.Slot.3-1:RAIDCurrentControllerMode',
             'current_value': ['RAID'],
             'read_only': True,
             'name': 'RAIDCurrentControllerMode',
             'possible_values': ['RAID', 'Enhanced HBA']},
            {'id': 'RAID.Integrated.1-1:RAIDCurrentControllerMode',
             'current_value': ['RAID'],
             'read_only': True,
             'name': 'RAIDCurrentControllerMode',
             'possible_values': ['RAID', 'Enhanced HBA']}]

        raid_settings = defaultdict()
        for sett in raid_controller_config:
            raid_settings[sett.get('id')] = test_utils.create_raid_setting(
                sett)

        mock_list_raid_settings.return_value = raid_settings

        mock_commit_config.side_effect = ['42', '12']
        mock__reset_raid_config.side_effect = [{
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True
        }, {
            'is_reboot_required': constants.RebootRequired.true,
            'is_commit_required': True
        }]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)

            mock_commit_config.assert_has_calls(
                [mock.call(mock.ANY, raid_controller='AHCI.Slot.3-1',
                           reboot=False, realtime=False),
                 mock.call(mock.ANY, raid_controller='RAID.Integrated.1-1',
                           reboot=True, realtime=False)],
                any_order=True)

        self.assertEqual(states.CLEANWAIT, return_value)
        self.node.refresh()
        self.assertEqual(expected_raid_config_params,
                         self.node.driver_internal_info[
                             'raid_config_parameters'])
        self.assertEqual(['42', '12'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_controllers', autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_settings', autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'set_raid_settings', autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, '_reset_raid_config', spec_set=True,
                       autospec=True)
    def test_delete_configuration_with_mix_realtime_controller_in_ehba_mode(
            self, mock__reset_raid_config, mock_commit_config,
            mock_set_raid_settings, mock_validate_job_queue,
            mock_list_unfinished_jobs, mock_list_raid_settings,
            mock_list_raid_controllers, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        expected_raid_config_params = ['RAID.Integrated.1-1', 'AHCI.Slot.3-1']
        mix_controllers = [{'id': 'RAID.Integrated.1-1',
                            'description': 'Integrated RAID Controller 1',
                            'manufacturer': 'DELL',
                            'model': 'PERC H740 Mini',
                            'primary_status': 'unknown',
                            'firmware_version': '50.5.0-1750',
                            'bus': '3C',
                            'supports_realtime': True},
                           {'id': 'AHCI.Slot.3-1',
                            'description': 'AHCI controller in slot 3',
                            'manufacturer': 'DELL',
                            'model': 'BOSS-S1',
                            'primary_status': 'unknown',
                            'firmware_version': '2.5.13.3016',
                            'bus': '5E',
                            'supports_realtime': False}]

        mock_list_raid_controllers.return_value = [
            test_utils.make_raid_controller(controller) for
            controller in mix_controllers]
        raid_controller_config = [
            {'id': 'RAID.Integrated.1-1:RAIDCurrentControllerMode',
             'current_value': ['Enhanced HBA'],
             'read_only': True,
             'name': 'RAIDCurrentControllerMode',
             'possible_values': ['RAID', 'Enhanced HBA']},
            {'id': 'AHCI.Slot.3-1:RAIDCurrentControllerMode',
             'current_value': ['RAID'],
             'read_only': True,
             'name': 'RAIDCurrentControllerMode',
             'possible_values': ['RAID', 'Enhanced HBA']}]

        raid_settings = defaultdict()
        for sett in raid_controller_config:
            raid_settings[sett.get('id')] = test_utils.create_raid_setting(
                sett)

        mock_list_raid_settings.return_value = raid_settings
        mock_list_unfinished_jobs.return_value = []
        mock_commit_config.side_effect = ['42', '12', '13']
        mock__reset_raid_config.side_effect = [{
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True
        }, {
            'is_reboot_required': constants.RebootRequired.true,
            'is_commit_required': True
        }]
        mock_set_raid_settings.return_value = {
            'is_reboot_required': constants.RebootRequired.true,
            'is_commit_required': True}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)
            mock_commit_config.assert_has_calls(
                [mock.call(mock.ANY, raid_controller='RAID.Integrated.1-1',
                           reboot=False, realtime=True),
                 mock.call(mock.ANY, raid_controller='AHCI.Slot.3-1',
                           reboot=False, realtime=False),
                 mock.call(mock.ANY, raid_controller='RAID.Integrated.1-1',
                           reboot=True, realtime=False)],
                any_order=True)

        self.assertEqual(states.CLEANWAIT, return_value)
        self.node.refresh()
        self.assertEqual(expected_raid_config_params,
                         self.node.driver_internal_info[
                             'raid_config_parameters'])
        self.assertEqual(['42', '12', '13'],
                         self.node.driver_internal_info['raid_config_job_ids'])

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'list_raid_controllers', autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test_delete_configuration_no_change(self, mock_commit_config,
                                            mock_validate_job_queue,
                                            mock_list_raid_controllers,
                                            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_list_raid_controllers.return_value = []

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid.delete_configuration(task)

            self.assertEqual(0, mock_client._reset_raid_config.call_count)
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
            'status': 'ok',
            'raid_status': 'online',
            'span_depth': 1,
            'span_length': 2,
            'pending_operations': None,
            'physical_disks': []}
        mock_list_virtual_disks.return_value = [
            test_utils.make_virtual_disk(virtual_disk_dict)]
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

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'clear_foreign_config', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test__execute_foreign_drives_with_no_foreign_drives(
            self, mock_validate_job_queue,
            mock_clear_foreign_config,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        raid_config_params = ['RAID.Integrated.1-1']
        raid_config_substep = 'clear_foreign_config'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['raid_config_parameters'] = raid_config_params
        driver_internal_info['raid_config_substep'] = raid_config_substep
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_clear_foreign_config.return_value = {
            'is_reboot_required': constants.RebootRequired.false,
            'is_commit_required': False
        }

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid._execute_foreign_drives(
                task, self.node)

        self.assertIsNone(return_value)

    @mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'clear_foreign_config', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_raid, 'commit_config', spec_set=True,
                       autospec=True)
    def test__execute_foreign_drives_with_foreign_drives(
            self, mock_commit_config,
            mock_validate_job_queue,
            mock_clear_foreign_config,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        raid_config_params = ['RAID.Integrated.1-1']
        raid_config_substep = 'clear_foreign_config'
        driver_internal_info = self.node.driver_internal_info
        driver_internal_info['raid_config_parameters'] = raid_config_params
        driver_internal_info['raid_config_substep'] = raid_config_substep
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_clear_foreign_config.return_value = {
            'is_reboot_required': constants.RebootRequired.optional,
            'is_commit_required': True
        }
        mock_commit_config.return_value = '42'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.raid._execute_foreign_drives(
                task, self.node)

            self.assertEqual(states.CLEANWAIT, return_value)

        self.assertEqual(['42'],
                         self.node.driver_internal_info['raid_config_job_ids'])
        self.assertEqual('physical_disk_conversion',
                         self.node.driver_internal_info['raid_config_substep'])
        self.assertEqual(
            ['RAID.Integrated.1-1'],
            self.node.driver_internal_info['raid_config_parameters'])
        mock_commit_config.assert_called_once_with(
            self.node, raid_controller='RAID.Integrated.1-1', reboot=False,
            realtime=True)

    @mock.patch.object(base.RAIDInterface, 'apply_configuration',
                       autospec=True)
    def test_apply_configuration(self, mock_apply_configuration):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.raid.apply_configuration(
                task, self.target_raid_configuration,
                create_root_volume=False, create_nonroot_volumes=True,
                delete_existing=False)

            mock_apply_configuration.assert_called_once_with(
                task.driver.raid, task,
                self.target_raid_configuration, False, True, False)


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
        task = mock.Mock(node=self.node, context=self.context)
        drac_raid._wait_till_realtime_ready(task)
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
        mock_storage1 = mock.Mock(storage_controllers=[mock_controller1],
                                  drives=[mock_drive1, mock_drive2],
                                  identity='RAID.Integrated.1-1')
        mock_controller2 = mock.Mock()
        mock_storage2 = mock.Mock(storage_controllers=[mock_controller2],
                                  drives=[mock_drive3],
                                  identity='AHCI.Slot.2-1')

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

    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_delete_configuration_foreign_async(
            self, mock_get_system, mock_build_agent_options,
            mock_get_async_step_return_state):
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

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_post_delete_configuration_foreign_sync(self, mock_get_system):
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

        result = self.raid.post_delete_configuration(
            task, None, return_state=mock_return_state1)

        self.assertEqual(result, mock_return_state1)
        fake_oem_system.clear_foreign_config.assert_called_once()
        mock_task_mon1.wait.assert_called_once_with(CONF.drac.raid_job_timeout)
        mock_task_mon2.wait.assert_not_called()

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
    def test__query_raid_tasks_status_not_drac(self, mock_acquire):
        driver_internal_info = {'raid_task_monitor_uris': ['/TaskService/123']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'not-idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(raid=mock.Mock()))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.raid._check_raid_tasks_status = mock.Mock()

        self.raid._query_raid_tasks_status(mock_manager, self.context)

        self.raid._check_raid_tasks_status.assert_not_called()

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

    @mock.patch.object(periodics.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_tasks_status_node_notfound(
            self, mock_acquire, mock_log):
        driver_internal_info = {'raid_task_monitor_uris': ['/TaskService/123']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeNotFound
        self.raid._check_raid_tasks_status = mock.Mock()

        self.raid._query_raid_tasks_status(mock_manager, self.context)

        self.raid._check_raid_tasks_status.assert_not_called()
        self.assertTrue(mock_log.called)

    @mock.patch.object(periodics.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_raid_tasks_status_node_locked(
            self, mock_acquire, mock_log):
        driver_internal_info = {'raid_task_monitor_uris': ['/TaskService/123']}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeLocked
        self.raid._check_raid_tasks_status = mock.Mock()

        self.raid._query_raid_tasks_status(mock_manager, self.context)

        self.raid._check_raid_tasks_status.assert_not_called()
        self.assertTrue(mock_log.called)

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
