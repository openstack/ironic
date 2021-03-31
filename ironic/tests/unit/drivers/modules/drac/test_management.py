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

import json
from unittest import mock

from oslo_utils import importutils

import ironic.common.boot_devices
from ironic.common import exception
from ironic.common import molds
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

dracclient_exceptions = importutils.try_import('dracclient.exceptions')
sushy = importutils.try_import('sushy')

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

    @mock.patch('time.time', autospec=True)
    @mock.patch('time.sleep', autospec=True)
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


class DracRedfishManagementTestCase(test_utils.BaseDracTest):

    def setUp(self):
        super(DracRedfishManagementTestCase, self).setUp()
        self.node = obj_utils.create_test_node(self.context,
                                               driver='idrac',
                                               driver_info=INFO_DICT)
        self.management = drac_mgmt.DracRedfishManagement()

    def test_export_configuration_name_missing(self):
        task = mock.Mock(node=self.node, context=self.context)
        self.assertRaises(exception.MissingParameterValue,
                          self.management.export_configuration, task, None)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_no_managers(self, mock_get_system):
        task = mock.Mock(node=self.node, context=self.context)
        mock_get_system.return_value.managers = []

        self.assertRaises(exception.DracOperationError,
                          self.management.export_configuration, task, 'edge')

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_oem_not_found(self, mock_get_system,
                                                mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError)
        mock_get_system.return_value.managers = [fake_manager1]

        self.assertRaises(exception.RedfishError,
                          self.management.export_configuration, task, 'edge')
        self.assertEqual(mock_log.error.call_count, 1)

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_all_managers_fail(self, mock_get_system,
                                                    mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.export_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        fake_manager_oem2 = mock.Mock()
        fake_manager_oem2.export_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]

        self.assertRaises(exception.DracOperationError,
                          self.management.export_configuration,
                          task, 'edge')
        self.assertEqual(mock_log.debug.call_count, 2)

    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_export_failed(self, mock_get_system):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.export_system_configuration = mock.Mock()
        fake_manager_oem1.export_system_configuration.status_code = 500
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        mock_get_system.return_value.managers = [fake_manager1]

        self.assertRaises(exception.DracOperationError,
                          self.management.export_configuration, task, 'edge')

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(molds, 'save_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_export_configuration_success(self, mock_get_system,
                                          mock_save_configuration,
                                          mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.export_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1

        configuration = mock.Mock(status_code=200)
        configuration.json.return_value = (
            json.loads('{"prop1":"value1", "prop2":2}'))
        fake_manager_oem2 = mock.Mock()
        fake_manager_oem2.export_system_configuration.return_value = (
            configuration)
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]
        self.management.export_configuration(task, 'edge')

        mock_save_configuration.assert_called_once_with(
            task,
            'edge',
            {"oem": {"interface": "idrac-redfish",
             "data": {"prop1": "value1", "prop2": 2}}})
        self.assertEqual(mock_log.debug.call_count, 1)
        self.assertEqual(mock_log.info.call_count, 1)

    def test_import_configuration_name_missing(self):
        task = mock.Mock(node=self.node, context=self.context)
        self.assertRaises(exception.MissingParameterValue,
                          self.management.import_configuration, task, None)

    @mock.patch.object(molds, 'get_configuration', autospec=True)
    def test_import_configuration_file_not_found(self, mock_get_configuration):
        task = mock.Mock(node=self.node, context=self.context)
        mock_get_configuration.return_value = None

        self.assertRaises(exception.DracOperationError,
                          self.management.import_configuration, task, 'edge')

    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_no_managers(self, mock_get_system,
                                              mock_get_configuration):
        task = mock.Mock(node=self.node, context=self.context)
        fake_system = mock.Mock(managers=[])
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-redfish", '
            '"data": {"prop1": "value1", "prop2": 2}}}')
        mock_get_system.return_value = fake_system

        self.assertRaises(exception.DracOperationError,
                          self.management.import_configuration, task, 'edge')

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_oem_not_found(self, mock_get_system,
                                                mock_get_configuration,
                                                mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.side_effect = (
            sushy.exceptions.OEMExtensionNotFoundError)
        fake_system = mock.Mock(managers=[fake_manager1])
        mock_get_system.return_value = fake_system
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-redfish", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        self.assertRaises(exception.RedfishError,
                          self.management.import_configuration, task, 'edge')
        self.assertEqual(mock_log.error.call_count, 1)

    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_all_managers_fail(self, mock_get_system,
                                                    mock_get_configuration,
                                                    mock_log):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.import_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        fake_manager_oem2 = mock.Mock()
        fake_manager_oem2.import_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-redfish", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        self.assertRaises(exception.DracOperationError,
                          self.management.import_configuration, task, 'edge')
        self.assertEqual(mock_log.debug.call_count, 2)

    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_incorrect_interface(self, mock_get_system,
                                                      mock_get_configuration):
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        mock_get_system.return_value.managers = [fake_manager1]
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-wsman", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        self.assertRaises(exception.DracOperationError,
                          self.management.import_configuration, task, 'edge')

    @mock.patch.object(deploy_utils, 'get_async_step_return_state',
                       autospec=True)
    @mock.patch.object(deploy_utils, 'set_async_step_flags', autospec=True)
    @mock.patch.object(deploy_utils, 'build_agent_options', autospec=True)
    @mock.patch.object(manager_utils, 'node_power_action', autospec=True)
    @mock.patch.object(drac_mgmt, 'LOG', autospec=True)
    @mock.patch.object(molds, 'get_configuration', autospec=True)
    @mock.patch.object(redfish_utils, 'get_system', autospec=True)
    def test_import_configuration_success(
            self, mock_get_system, mock_get_configuration, mock_log,
            mock_power, mock_build_agent_options,
            mock_set_async_step_flags, mock_get_async_step_return_state):
        deploy_opts = mock.Mock()
        mock_build_agent_options.return_value = deploy_opts
        step_result = mock.Mock()
        mock_get_async_step_return_state.return_value = step_result
        task = mock.Mock(node=self.node, context=self.context)
        fake_manager_oem1 = mock.Mock()
        fake_manager_oem1.import_system_configuration.side_effect = (
            sushy.exceptions.SushyError)
        fake_manager1 = mock.Mock()
        fake_manager1.get_oem_extension.return_value = fake_manager_oem1
        fake_manager_oem2 = mock.Mock()
        fake_manager2 = mock.Mock()
        fake_manager2.get_oem_extension.return_value = fake_manager_oem2
        mock_get_system.return_value.managers = [fake_manager1, fake_manager2]
        mock_get_configuration.return_value = json.loads(
            '{"oem": {"interface": "idrac-redfish", '
            '"data": {"prop1": "value1", "prop2": 2}}}')

        result = self.management.import_configuration(task, 'edge')

        fake_manager_oem2.import_system_configuration.assert_called_once_with(
            '{"prop1": "value1", "prop2": 2}')
        self.assertEqual(mock_log.debug.call_count, 1)

        mock_set_async_step_flags.assert_called_once_with(
            task.node, reboot=True, skip_current_step=True, polling=True)
        mock_build_agent_options.assert_called_once_with(task.node)
        task.driver.boot.prepare_ramdisk.assert_called_once_with(
            task, deploy_opts)
        mock_get_async_step_return_state.assert_called_once_with(task.node)
        self.assertEqual(step_result, result)

    @mock.patch.object(drac_mgmt.DracRedfishManagement,
                       'import_configuration', autospec=True)
    def test_import_export_configuration_success(self, mock_import):
        task = mock.Mock(node=self.node, context=self.context)

        self.management.import_export_configuration(
            task, 'https://server/edge_import', 'https://server/edge_export')

        mock_import.assert_called_once_with(self.management, task,
                                            'https://server/edge_import')
        self.assertEqual(
            'https://server/edge_export',
            self.node.driver_internal_info.get(
                'export_configuration_location'))

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_not_drac(self, mock_acquire):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'not-idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=mock.Mock()))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_no_task_monitor_url(
            self, mock_acquire):
        driver_internal_info = {'something': 'else'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()

    @mock.patch.object(drac_mgmt.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_node_notfound(
            self, mock_acquire, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeNotFound
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()
        self.assertTrue(mock_log.called)

    @mock.patch.object(drac_mgmt.LOG, 'info', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status_node_locked(
            self, mock_acquire, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        mock_acquire.side_effect = exception.NodeLocked
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        self.management._check_import_configuration_task.assert_not_called()
        self.assertTrue(mock_log.called)

    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test__query_import_configuration_status(self, mock_acquire):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()
        mock_manager = mock.Mock()
        node_list = [(self.node.uuid, 'idrac', '', driver_internal_info)]
        mock_manager.iter_nodes.return_value = node_list
        task = mock.Mock(node=self.node,
                         driver=mock.Mock(management=self.management))
        mock_acquire.return_value = mock.MagicMock(
            __enter__=mock.MagicMock(return_value=task))
        self.management._check_import_configuration_task = mock.Mock()

        self.management._query_import_configuration_status(mock_manager,
                                                           self.context)

        (self.management
            ._check_import_configuration_task
            .assert_called_once_with(task, '/TaskService/123'))

    @mock.patch.object(drac_mgmt.LOG, 'debug', autospec=True)
    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_still_processing(
            self, mock_get_task_monitor, mock_log):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = True
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_success.assert_not_called()
            self.management._set_failed.assert_not_called()
            self.assertTrue(mock_log.called)
            self.assertEqual(
                '/TaskService/123',
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_failed(
            self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Firmware upgrade failed'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = 'Failed'
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_failed.assert_called_once_with(
                task, mock.ANY,
                "Failed import configuration task: /TaskService/123. Message: "
                "'Firmware upgrade failed'.")
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task(self, mock_get_task_monitor):
        driver_internal_info = {'import_task_monitor_url': '/TaskService/123'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Configuration import done'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management._set_success.assert_called_once_with(task)
            self.management._set_failed.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_with_export_failed(
            self, mock_get_task_monitor):
        driver_internal_info = {
            'import_task_monitor_url': '/TaskService/123',
            'export_configuration_location': 'https://server/export1'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Configuration import done'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()
        mock_export = mock.Mock()
        mock_export.side_effect = exception.IronicException
        self.management.export_configuration = mock_export

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management.export_configuration.assert_called_once_with(
                task, 'https://server/export1')
            self.management._set_success.assert_not_called()
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))
            self.assertIsNone(
                task.node.driver_internal_info.get(
                    'export_configuration_location'))
            self.management._set_failed.assert_called_with(
                task, mock.ANY,
                'Failed export configuration. An unknown exception occurred.')

    @mock.patch.object(redfish_utils, 'get_task_monitor', autospec=True)
    def test__check_import_configuration_task_with_export(
            self, mock_get_task_monitor):
        driver_internal_info = {
            'import_task_monitor_url': '/TaskService/123',
            'export_configuration_location': 'https://server/export1'}
        self.node.driver_internal_info = driver_internal_info
        self.node.save()

        mock_message = mock.Mock()
        mock_message.message = 'Configuration import done'
        mock_import_task = mock.Mock()
        mock_import_task.task_state = sushy.TASK_STATE_COMPLETED
        mock_import_task.task_status = sushy.HEALTH_OK
        mock_import_task.messages = [mock_message]
        mock_task_monitor = mock.Mock()
        mock_task_monitor.is_processing = False
        mock_task_monitor.get_task.return_value = mock_import_task
        mock_get_task_monitor.return_value = mock_task_monitor

        self.management._set_success = mock.Mock()
        self.management._set_failed = mock.Mock()
        self.management.export_configuration = mock.Mock()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._check_import_configuration_task(
                task, '/TaskService/123')

            self.management.export_configuration.assert_called_once_with(
                task, 'https://server/export1')
            self.management._set_success.assert_called_once_with(task)
            self.assertIsNone(
                task.node.driver_internal_info.get('import_task_monitor_url'))
            self.assertIsNone(
                task.node.driver_internal_info.get(
                    'export_configuration_location'))
            self.management._set_failed.assert_not_called()

    @mock.patch.object(manager_utils, 'notify_conductor_resume_deploy',
                       autospec=True)
    @mock.patch.object(manager_utils, 'notify_conductor_resume_clean',
                       autospec=True)
    def test__set_success_clean(self, mock_notify_clean, mock_notify_deploy):
        self.node.clean_step = {'test': 'value'}
        self.node.save()
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.management._set_success(task)

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
            self.management._set_success(task)

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
            self.management._set_failed(task, 'error', 'log message')

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
            self.management._set_failed(task, 'error', 'log message')

            mock_deploy_handler.assert_called_once_with(
                task, 'error', 'log message')
