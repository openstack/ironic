# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
# All Rights Reserved.
# Copyright (c) 2017-2018 Dell Inc. or its subsidiaries.
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

"""
Test class for DRAC management interface
"""

from unittest import mock

from oslo_utils import importutils

import ironic.common.boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

dracclient_exceptions = importutils.try_import('dracclient.exceptions')

INFO_DICT = test_utils.INFO_DICT


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracManagementInternalMethodsTestCase(test_utils.BaseDracTest):

    def boot_modes(self, *next_modes):
        modes = [
            {'id': 'IPL', 'name': 'BootSeq',
             'is_current': True, 'is_next': False},
            {'id': 'OneTime', 'name': 'OneTimeBootMode',
             'is_current': False, 'is_next': False}]
        for mode in modes:
            if mode['id'] in next_modes:
                mode['is_next'] = True
        return [test_utils.dict_to_namedtuple(values=mode) for mode in modes]

    def setUp(self):
        super(DracManagementInternalMethodsTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

        boot_device_ipl_pxe = {
            'id': 'BIOS.Setup.1-1#BootSeq#NIC.Embedded.1-1-1',
            'boot_mode': 'IPL',
            'current_assigned_sequence': 0,
            'pending_assigned_sequence': 0,
            'bios_boot_string': 'Embedded NIC 1 Port 1 Partition 1'}
        boot_device_ipl_disk = {
            'id': 'BIOS.Setup.1-1#BootSeq#HardDisk.List.1-1',
            'boot_mode': 'IPL',
            'current_assigned_sequence': 1,
            'pending_assigned_sequence': 1,
            'bios_boot_string': 'Hard drive C: BootSeq'}
        ipl_boot_device_namedtuples = [
            test_utils.dict_to_namedtuple(values=boot_device_ipl_pxe),
            test_utils.dict_to_namedtuple(values=boot_device_ipl_disk)]
        ipl_boot_devices = {'IPL': ipl_boot_device_namedtuples,
                            'OneTime': ipl_boot_device_namedtuples}

        boot_device_uefi_pxe = {
            'id': 'UEFI:BIOS.Setup.1-1#UefiBootSeq#NIC.PxeDevice.1-1',
            'boot_mode': 'UEFI',
            'current_assigned_sequence': 0,
            'pending_assigned_sequence': 0,
            'bios_boot_string':
                'PXE Device 1: Integrated NIC 1 Port 1 Partition 1'}
        uefi_boot_device_namedtuples = [
            test_utils.dict_to_namedtuple(values=boot_device_uefi_pxe)]
        uefi_boot_devices = {'UEFI': uefi_boot_device_namedtuples,
                             'OneTime': uefi_boot_device_namedtuples}

        self.boot_devices = {'IPL': ipl_boot_devices,
                             'UEFI': uefi_boot_devices}

    def test__get_boot_device(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = self.boot_modes('IPL')
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']

        boot_device = drac_mgmt._get_boot_device(self.node)

        expected_boot_device = {'boot_device': 'pxe', 'persistent': True}
        self.assertEqual(expected_boot_device, boot_device)
        mock_client.list_boot_modes.assert_called_once_with()
        mock_client.list_boot_devices.assert_called_once_with()

    def test__get_boot_device_not_persistent(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        # if a non-persistent boot mode is marked as "next", it over-rides any
        # persistent boot modes
        mock_client.list_boot_modes.return_value = self.boot_modes('IPL',
                                                                   'OneTime')
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']

        boot_device = drac_mgmt._get_boot_device(self.node)

        expected_boot_device = {'boot_device': 'pxe', 'persistent': False}
        self.assertEqual(expected_boot_device, boot_device)
        mock_client.list_boot_modes.assert_called_once_with()
        mock_client.list_boot_devices.assert_called_once_with()

    def test__get_boot_device_with_no_boot_device(self,
                                                  mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = self.boot_modes('IPL')
        mock_client.list_boot_devices.return_value = {}

        boot_device = drac_mgmt._get_boot_device(self.node)

        expected_boot_device = {'boot_device': None, 'persistent': True}
        self.assertEqual(expected_boot_device, boot_device)
        mock_client.list_boot_modes.assert_called_once_with()
        mock_client.list_boot_devices.assert_called_once_with()

    def test__get_boot_device_with_empty_boot_mode_list(self,
                                                        mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = []

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt._get_boot_device, self.node)

    def test__get_next_persistent_boot_mode(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = self.boot_modes('IPL')

        boot_mode = drac_mgmt._get_next_persistent_boot_mode(self.node)

        mock_get_drac_client.assert_called_once_with(self.node)
        mock_client.list_boot_modes.assert_called_once_with()
        expected_boot_mode = 'IPL'
        self.assertEqual(expected_boot_mode, boot_mode)

    def test__get_next_persistent_boot_mode_with_non_persistent_boot_mode(
            self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = self.boot_modes('IPL',
                                                                   'OneTime')

        boot_mode = drac_mgmt._get_next_persistent_boot_mode(self.node)

        mock_get_drac_client.assert_called_once_with(self.node)
        mock_client.list_boot_modes.assert_called_once_with()
        expected_boot_mode = 'IPL'
        self.assertEqual(expected_boot_mode, boot_mode)

    def test__get_next_persistent_boot_mode_list_boot_modes_fail(
            self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        exc = dracclient_exceptions.BaseClientException('boom')
        mock_client.list_boot_modes.side_effect = exc

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt._get_next_persistent_boot_mode, self.node)

        mock_get_drac_client.assert_called_once_with(self.node)
        mock_client.list_boot_modes.assert_called_once_with()

    def test__get_next_persistent_boot_mode_with_empty_boot_mode_list(
            self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = []

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt._get_next_persistent_boot_mode, self.node)

        mock_get_drac_client.assert_called_once_with(self.node)
        mock_client.list_boot_modes.assert_called_once_with()

    def test__is_boot_order_flexibly_programmable(self, mock_get_drac_client):
        self.assertTrue(drac_mgmt._is_boot_order_flexibly_programmable(
            persistent=True, bios_settings={'SetBootOrderFqdd1': ()}))

    def test__is_boot_order_flexibly_programmable_not_persistent(
            self, mock_get_drac_client):
        self.assertFalse(drac_mgmt._is_boot_order_flexibly_programmable(
            persistent=False, bios_settings={'SetBootOrderFqdd1': ()}))

    def test__is_boot_order_flexibly_programmable_with_no_bios_setting(
            self, mock_get_drac_client):
        self.assertFalse(drac_mgmt._is_boot_order_flexibly_programmable(
            persistent=True, bios_settings={}))

    def test__flexibly_program_boot_order_for_disk_and_bios(
            self, mock_get_drac_client):
        settings = drac_mgmt._flexibly_program_boot_order(
            ironic.common.boot_devices.DISK, drac_boot_mode='Bios')

        expected_settings = {'SetBootOrderFqdd1': 'HardDisk.List.1-1'}
        self.assertEqual(expected_settings, settings)

    def test__flexibly_program_boot_order_for_disk_and_uefi(
            self, mock_get_drac_client):
        settings = drac_mgmt._flexibly_program_boot_order(
            ironic.common.boot_devices.DISK, drac_boot_mode='Uefi')

        expected_settings = {
            'SetBootOrderFqdd1': '*.*.*',
            'SetBootOrderFqdd2': 'NIC.*.*',
            'SetBootOrderFqdd3': 'Optical.*.*',
            'SetBootOrderFqdd4': 'Floppy.*.*',
        }
        self.assertEqual(expected_settings, settings)

    def test__flexibly_program_boot_order_for_pxe(self, mock_get_drac_client):
        settings = drac_mgmt._flexibly_program_boot_order(
            ironic.common.boot_devices.PXE, drac_boot_mode='Uefi')

        expected_settings = {'SetBootOrderFqdd1': 'NIC.*.*'}
        self.assertEqual(expected_settings, settings)

    def test__flexibly_program_boot_order_for_cdrom(self,
                                                    mock_get_drac_client):
        settings = drac_mgmt._flexibly_program_boot_order(
            ironic.common.boot_devices.CDROM, drac_boot_mode='Uefi')

        expected_settings = {'SetBootOrderFqdd1': 'Optical.*.*'}
        self.assertEqual(expected_settings, settings)

    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_boot_device(self, mock_validate_job_queue,
                             mock_list_unfinished_jobs,
                             mock__get_boot_device,
                             mock__get_next_persistent_boot_mode,
                             mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        mock_list_unfinished_jobs.return_value = []

        mock_job = mock.Mock()
        mock_job.status = "Scheduled"
        mock_client.get_job.return_value = mock_job

        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'
        self.node.driver_internal_info['clean_steps'] = []

        boot_device = drac_mgmt.set_boot_device(
            self.node, ironic.common.boot_devices.PXE, persistent=False)

        self.assertEqual(0, mock_list_unfinished_jobs.call_count)
        self.assertEqual(0, mock_client.delete_jobs.call_count)
        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.change_boot_device_order.assert_called_once_with(
            'OneTime', 'BIOS.Setup.1-1#BootSeq#NIC.Embedded.1-1-1')
        self.assertEqual(0, mock_client.set_bios_settings.call_count)
        mock_client.commit_pending_bios_changes.assert_called_once_with()

    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_called_with_no_change(
            self, mock_list_unfinished_jobs, mock__get_boot_device,
            mock__get_next_persistent_boot_mode, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        boot_device = {'boot_device': ironic.common.boot_devices.PXE,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'
        mock_list_unfinished_jobs.return_value = []

        boot_device = drac_mgmt.set_boot_device(
            self.node, ironic.common.boot_devices.PXE, persistent=True)

        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.set_bios_settings.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)

    @mock.patch.object(drac_mgmt, '_flexibly_program_boot_order',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_is_boot_order_flexibly_programmable',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_called_with_no_drac_boot_device(
            self, mock_list_unfinished_jobs,
            mock__get_boot_device, mock__get_next_persistent_boot_mode,
            mock__is_boot_order_flexibly_programmable,
            mock__flexibly_program_boot_order,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_devices.return_value = self.boot_devices['UEFI']
        mock_list_unfinished_jobs.return_value = []

        mock_job = mock.Mock()
        mock_job.status = "Scheduled"
        mock_client.get_job.return_value = mock_job
        boot_device = {'boot_device': ironic.common.boot_devices.PXE,
                       'persistent': False}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'UEFI'
        settings = [
            {
                'name': 'BootMode',
                'instance_id': 'BIOS.Setup.1-1:BootMode',
                'current_value': 'Uefi',
                'pending_value': None,
                'read_only': False,
                'possible_values': ['Bios', 'Uefi']
            },
        ]
        bios_settings = {
            s['name']: test_utils.dict_to_namedtuple(
                values=s) for s in settings}
        mock_client.list_bios_settings.return_value = bios_settings
        mock__is_boot_order_flexibly_programmable.return_value = True
        flexibly_program_settings = {
            'SetBootOrderFqdd1': '*.*.*',
            'SetBootOrderFqdd2': 'NIC.*.*',
            'SetBootOrderFqdd3': 'Optical.*.*',
            'SetBootOrderFqdd4': 'Floppy.*.*',
        }
        mock__flexibly_program_boot_order.return_value = \
            flexibly_program_settings

        drac_mgmt.set_boot_device(self.node, ironic.common.boot_devices.DISK,
                                  persistent=True)

        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        mock_client.set_bios_settings.assert_called_once_with(
            flexibly_program_settings)
        mock_client.commit_pending_bios_changes.assert_called_once_with()

    @mock.patch.object(drac_mgmt, '_is_boot_order_flexibly_programmable',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_called_with_not_flexibly_programmable(
            self, mock_list_unfinished_jobs,
            mock__get_boot_device, mock__get_next_persistent_boot_mode,
            mock__is_boot_order_flexibly_programmable,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_list_unfinished_jobs.return_value = []
        mock_client.list_boot_devices.return_value = self.boot_devices['UEFI']
        boot_device = {'boot_device': ironic.common.boot_devices.PXE,
                       'persistent': False}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'UEFI'
        mock__is_boot_order_flexibly_programmable.return_value = False

        self.assertRaises(exception.InvalidParameterValue,
                          drac_mgmt.set_boot_device, self.node,
                          ironic.common.boot_devices.CDROM, persistent=False)

        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.set_bios_settings.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)

    @mock.patch.object(drac_mgmt, '_is_boot_order_flexibly_programmable',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_called_with_unknown_boot_mode(
            self, mock_list_unfinished_jobs, mock__get_boot_device,
            mock__get_next_persistent_boot_mode,
            mock__is_boot_order_flexibly_programmable,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        mock_client.list_boot_devices.return_value = self.boot_devices['UEFI']
        boot_device = {'boot_device': ironic.common.boot_devices.PXE,
                       'persistent': False}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'UEFI'
        settings = [
            {
                'name': 'BootMode',
                'instance_id': 'BIOS.Setup.1-1:BootMode',
                'current_value': 'Bad',
                'pending_value': None,
                'read_only': False,
                'possible_values': ['Bios', 'Uefi', 'Bad']
            },
        ]
        bios_settings = {
            s['name']: test_utils.dict_to_namedtuple(
                values=s) for s in settings}
        mock_client.list_bios_settings.return_value = bios_settings
        mock__is_boot_order_flexibly_programmable.return_value = True
        mock_list_unfinished_jobs.return_value = []
        self.assertRaises(exception.DracOperationError,
                          drac_mgmt.set_boot_device, self.node,
                          ironic.common.boot_devices.DISK, persistent=True)
        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.set_bios_settings.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)

    @mock.patch('time.time')
    @mock.patch('time.sleep')
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_job_not_scheduled(
            self,
            mock_list_unfinished_jobs,
            mock__get_boot_device,
            mock__get_next_persistent_boot_mode,
            mock_sleep,
            mock_time,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_list_unfinished_jobs.return_value = []
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        mock_job = mock.Mock()
        mock_job.status = "New"
        mock_client.get_job.return_value = mock_job
        mock_time.side_effect = [10, 50]

        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt.set_boot_device, self.node,
                          ironic.common.boot_devices.PXE,
                          persistent=True)
        mock_list_unfinished_jobs.assert_called_once_with(self.node)

    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    def test_set_boot_device_with_list_unfinished_jobs_fail(
            self, mock_list_unfinished_jobs, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        mock_list_unfinished_jobs.side_effect = exception.DracOperationError(
            'boom')

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt.set_boot_device, self.node,
                          ironic.common.boot_devices.PXE, persistent=True)

        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.set_bios_settings.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    def test_set_boot_device_with_list_unfinished_jobs_without_clean_step(
            self, mock__get_next_persistent_boot_mode, mock__get_boot_device,
            mock_list_unfinished_jobs, mock_validate_job_queue,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        bios_job_dict = {
            'id': 'JID_602553293345',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        bios_job = test_utils.make_job(bios_job_dict)

        mock_list_unfinished_jobs.return_value = [bios_job]
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}

        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'

        self.node.driver_internal_info['clean_steps'] = []

        drac_mgmt.set_boot_device(self.node, ironic.common.boot_devices.DISK,
                                  persistent=True)
        self.assertEqual(0, mock_list_unfinished_jobs.call_count)
        self.assertEqual(0, mock_client.delete_jobs.call_count)

        mock_validate_job_queue.assert_called_once_with(self.node)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    def test_set_boot_device_with_multiple_unfinished_jobs_without_clean_step(
            self, mock__get_next_persistent_boot_mode, mock__get_boot_device,
            mock_list_unfinished_jobs, mock_validate_job_queue,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        job_dict = {
            'id': 'JID_602553293345',
            'name': 'Config:RAID:RAID.Integrated.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        job = test_utils.make_job(job_dict)

        bios_job_dict = {
            'id': 'JID_602553293346',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        bios_job = test_utils.make_job(bios_job_dict)

        mock_list_unfinished_jobs.return_value = [job, bios_job]
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}

        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'

        self.node.driver_internal_info['clean_steps'] = []
        drac_mgmt.set_boot_device(self.node, ironic.common.boot_devices.DISK,
                                  persistent=True)
        self.assertEqual(0, mock_list_unfinished_jobs.call_count)
        self.assertEqual(0, mock_client.delete_jobs.call_count)

        mock_validate_job_queue.assert_called_once_with(self.node)

    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_boot_device_with_list_unfinished_jobs_with_clean_step(
            self, mock_validate_job_queue,
            mock_list_unfinished_jobs,
            mock__get_boot_device,
            mock__get_next_persistent_boot_mode,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']

        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'

        mock_job = mock.Mock()
        mock_job.status = "Scheduled"
        mock_client.get_job.return_value = mock_job

        bios_job_dict = {
            'id': 'JID_602553293345',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        bios_job = test_utils.make_job(bios_job_dict)
        mock_list_unfinished_jobs.return_value = [bios_job]

        self.node.driver_internal_info['clean_steps'] = [{
            u'interface': u'management', u'step': u'clear_job_queue'}]
        boot_device = drac_mgmt.set_boot_device(
            self.node, ironic.common.boot_devices.PXE, persistent=False)
        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        mock_client.delete_jobs.assert_called_once_with(
            job_ids=['JID_602553293345'])

        self.assertEqual(0, mock_validate_job_queue.call_count)

    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'list_unfinished_jobs', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_mgmt, '_get_next_persistent_boot_mode',
                       spec_set=True, autospec=True)
    def test_set_boot_device_with_multiple_unfinished_jobs_with_clean_step(
            self, mock__get_next_persistent_boot_mode, mock__get_boot_device,
            mock_list_unfinished_jobs, mock_validate_job_queue,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        job_dict = {
            'id': 'JID_602553293345',
            'name': 'Config:RAID:RAID.Integrated.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        job = test_utils.make_job(job_dict)

        bios_job_dict = {
            'id': 'JID_602553293346',
            'name': 'ConfigBIOS:BIOS.Setup.1-1',
            'start_time': 'TIME_NOW',
            'until_time': 'TIME_NA',
            'message': 'Task successfully scheduled.',
            'status': 'Scheduled',
            'percent_complete': 0}
        bios_job = test_utils.make_job(bios_job_dict)

        mock_list_unfinished_jobs.return_value = [job, bios_job]
        mock_client.list_boot_devices.return_value = self.boot_devices['IPL']
        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}

        mock__get_boot_device.return_value = boot_device
        mock__get_next_persistent_boot_mode.return_value = 'IPL'

        self.node.driver_internal_info['clean_steps'] = [{
            u'interface': u'management', u'step': u'clear_job_queue'}]

        drac_mgmt.set_boot_device(self.node, ironic.common.boot_devices.DISK,
                                  persistent=True)
        mock_list_unfinished_jobs.assert_called_once_with(self.node)
        mock_client.delete_jobs.assert_called_once_with(
            job_ids=['JID_602553293345', 'JID_602553293346'])

        self.assertEqual(0, mock_validate_job_queue.call_count)


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracManagementTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracManagementTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)

    def test_get_properties(self, mock_get_drac_client):
        expected = drac_common.COMMON_PROPERTIES
        driver = drac_mgmt.DracManagement()
        self.assertEqual(expected, driver.get_properties())

    def test_get_supported_boot_devices(self, mock_get_drac_client):
        expected_boot_devices = [ironic.common.boot_devices.PXE,
                                 ironic.common.boot_devices.DISK,
                                 ironic.common.boot_devices.CDROM]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            boot_devices = (
                task.driver.management.get_supported_boot_devices(task))

        self.assertEqual(sorted(expected_boot_devices), sorted(boot_devices))

    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    def test_get_boot_device(self, mock__get_boot_device,
                             mock_get_drac_client):
        expected_boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                                'persistent': True}
        mock__get_boot_device.return_value = expected_boot_device

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            boot_device = task.driver.management.get_boot_device(task)

            self.assertEqual(expected_boot_device, boot_device)
            mock__get_boot_device.assert_called_once_with(task.node)

    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    def test_get_boot_device_from_driver_internal_info(self,
                                                       mock__get_boot_device,
                                                       mock_get_drac_client):
        expected_boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                                'persistent': True}

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info['drac_boot_device'] = (
                expected_boot_device)
            boot_device = task.driver.management.get_boot_device(task)

            self.assertEqual(expected_boot_device, boot_device)
            self.assertEqual(0, mock__get_boot_device.call_count)

    def test_set_boot_device(self, mock_get_drac_client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.set_boot_device(
                task, ironic.common.boot_devices.DISK, persistent=True)

            expected_boot_device = {
                'boot_device': ironic.common.boot_devices.DISK,
                'persistent': True}

        self.node.refresh()
        self.assertEqual(
            self.node.driver_internal_info['drac_boot_device'],
            expected_boot_device)

    def test_set_boot_device_fail(self, mock_get_drac_client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device, task,
                              'foo')

    def test_get_sensors_data(self, mock_get_drac_client):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.assertRaises(NotImplementedError,
                              task.driver.management.get_sensors_data, task)

    def test_reset_idrac(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.management.reset_idrac(task)
            mock_client.reset_idrac.assert_called_once_with(
                force=True, wait=True)

            self.assertIsNone(return_value)

    def test_known_good_state(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.management.known_good_state(task)
            mock_client.reset_idrac.assert_called_once_with(
                force=True, wait=True)
            mock_client.delete_jobs.assert_called_once_with(
                job_ids=['JID_CLEARALL_FORCE'])

            self.assertIsNone(return_value)

    def test_clear_job_queue(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            return_value = task.driver.management.clear_job_queue(task)
            mock_client.delete_jobs.assert_called_once_with(
                job_ids=['JID_CLEARALL_FORCE'])

            self.assertIsNone(return_value)
