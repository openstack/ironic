# -*- coding: utf-8 -*-
#
# Copyright 2014 Red Hat, Inc.
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

"""
Test class for DRAC management interface
"""

import mock

import ironic.common.boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import job as drac_job
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracManagementInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracManagementInternalMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)
        self.boot_mode_ipl = {'id': 'IPL', 'name': 'BootSeq',
                              'is_current': True, 'is_next': True}
        self.boot_mode_one_time = {'id': 'OneTime', 'name': 'OneTimeBootMode',
                                   'is_current': False, 'is_next': False}

        self.boot_device_pxe = {
            'id': 'BIOS.Setup.1-1#BootSeq#NIC.Embedded.1-1-1',
            'boot_mode': 'IPL',
            'current_assigned_sequence': 0,
            'pending_assigned_sequence': 0,
            'bios_boot_string': 'Embedded NIC 1 Port 1 Partition 1'}
        self.boot_device_disk = {
            'id': 'BIOS.Setup.1-1#BootSeq#HardDisk.List.1-1',
            'boot_mode': 'IPL',
            'current_assigned_sequence': 1,
            'pending_assigned_sequence': 1,
            'bios_boot_string': 'Hard drive C: BootSeq'}

    def test__get_boot_device(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = [
            test_utils.dict_to_namedtuple(values=self.boot_mode_ipl),
            test_utils.dict_to_namedtuple(values=self.boot_mode_one_time)]
        mock_client.list_boot_devices.return_value = {
            'IPL': [test_utils.dict_to_namedtuple(values=self.boot_device_pxe),
                    test_utils.dict_to_namedtuple(
                        values=self.boot_device_disk)]}

        boot_device = drac_mgmt._get_boot_device(self.node)

        expected_boot_device = {'boot_device': 'pxe', 'persistent': True}
        self.assertEqual(expected_boot_device, boot_device)
        mock_client.list_boot_modes.assert_called_once_with()
        mock_client.list_boot_devices.assert_called_once_with()

    def test__get_boot_device_not_persistent(self, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        self.boot_mode_one_time['is_next'] = True
        mock_client.list_boot_modes.return_value = [
            test_utils.dict_to_namedtuple(values=self.boot_mode_ipl),
            test_utils.dict_to_namedtuple(values=self.boot_mode_one_time)]
        mock_client.list_boot_devices.return_value = {
            'OneTime': [
                test_utils.dict_to_namedtuple(values=self.boot_device_pxe),
                test_utils.dict_to_namedtuple(values=self.boot_device_disk)]}

        boot_device = drac_mgmt._get_boot_device(self.node)

        expected_boot_device = {'boot_device': 'pxe', 'persistent': False}
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

    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_boot_device(self, mock_validate_job_queue,
                             mock__get_boot_device, mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = [
            test_utils.dict_to_namedtuple(values=self.boot_mode_ipl),
            test_utils.dict_to_namedtuple(values=self.boot_mode_one_time)]
        mock_client.list_boot_devices.return_value = {
            'IPL': [test_utils.dict_to_namedtuple(values=self.boot_device_pxe),
                    test_utils.dict_to_namedtuple(
                        values=self.boot_device_disk)]}
        boot_device = {'boot_device': ironic.common.boot_devices.DISK,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device

        boot_device = drac_mgmt.set_boot_device(
            self.node, ironic.common.boot_devices.PXE, persistent=False)

        mock_validate_job_queue.assert_called_once_with(self.node)
        mock_client.change_boot_device_order.assert_called_once_with(
            'OneTime', 'BIOS.Setup.1-1#BootSeq#NIC.Embedded.1-1-1')
        mock_client.commit_pending_bios_changes.assert_called_once_with()

    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_boot_device_called_with_no_change(
            self, mock_validate_job_queue, mock__get_boot_device,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_client.list_boot_modes.return_value = [
            test_utils.dict_to_namedtuple(values=self.boot_mode_ipl),
            test_utils.dict_to_namedtuple(values=self.boot_mode_one_time)]
        mock_client.list_boot_devices.return_value = {
            'IPL': [test_utils.dict_to_namedtuple(values=self.boot_device_pxe),
                    test_utils.dict_to_namedtuple(
                        values=self.boot_device_disk)]}
        boot_device = {'boot_device': ironic.common.boot_devices.PXE,
                       'persistent': True}
        mock__get_boot_device.return_value = boot_device

        boot_device = drac_mgmt.set_boot_device(
            self.node, ironic.common.boot_devices.PXE, persistent=True)

        mock_validate_job_queue.assert_called_once_with(self.node)
        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)

    @mock.patch.object(drac_mgmt, '_get_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(drac_job, 'validate_job_queue', spec_set=True,
                       autospec=True)
    def test_set_boot_device_with_invalid_job_queue(
            self, mock_validate_job_queue, mock__get_boot_device,
            mock_get_drac_client):
        mock_client = mock.Mock()
        mock_get_drac_client.return_value = mock_client
        mock_validate_job_queue.side_effect = exception.DracOperationError(
            'boom')

        self.assertRaises(exception.DracOperationError,
                          drac_mgmt.set_boot_device, self.node,
                          ironic.common.boot_devices.PXE, persistent=True)

        self.assertEqual(0, mock_client.change_boot_device_order.call_count)
        self.assertEqual(0, mock_client.commit_pending_bios_changes.call_count)


@mock.patch.object(drac_common, 'get_drac_client', spec_set=True,
                   autospec=True)
class DracManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracManagementTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
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
