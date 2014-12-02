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
Test class for DRAC ManagementInterface
"""

import mock

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import management as drac_mgmt
from ironic.drivers.modules.drac import resource_uris
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.drivers.drac import utils as test_utils
from ironic.tests.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_client, 'pywsman')
class DracManagementInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracManagementInternalMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)

    def test__get_next_boot_mode(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_BootConfigSetting':
                                                    {'InstanceID': 'IPL',
                                                     'IsNext':
                                                       drac_mgmt.PERSISTENT}}],
                                          resource_uris.DCIM_BootConfigSetting)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        expected = {'instance_id': 'IPL', 'is_next': drac_mgmt.PERSISTENT}
        result = drac_mgmt._get_next_boot_mode(self.node)

        self.assertEqual(expected, result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootConfigSetting)

    def test__get_next_boot_mode_onetime(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_BootConfigSetting':
                                                    {'InstanceID': 'IPL',
                                                     'IsNext':
                                                    drac_mgmt.PERSISTENT}},
                                                {'DCIM_BootConfigSetting':
                                                    {'InstanceID': 'OneTime',
                                                     'IsNext':
                                                    drac_mgmt.ONE_TIME_BOOT}}],
                                          resource_uris.DCIM_BootConfigSetting)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        expected = {'instance_id': 'OneTime',
                    'is_next': drac_mgmt.ONE_TIME_BOOT}
        result = drac_mgmt._get_next_boot_mode(self.node)

        self.assertEqual(expected, result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootConfigSetting)

    def test__check_for_config_job(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_LifecycleJob':
                                                    {'Name': 'fake'}}],
                                          resource_uris.DCIM_LifecycleJob)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        result = drac_mgmt._check_for_config_job(self.node)

        self.assertIsNone(result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_LifecycleJob)

    def test__check_for_config_job_already_exist(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'DCIM_LifecycleJob':
                                                    {'Name': 'BIOS.Setup.1-1',
                                                     'JobStatus': 'scheduled',
                                                     'InstanceID': 'fake'}}],
                                          resource_uris.DCIM_LifecycleJob)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        self.assertRaises(exception.DracConfigJobCreationError,
                          drac_mgmt._check_for_config_job, self.node)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_LifecycleJob)

    def test__create_config_job(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                    drac_common.RET_SUCCESS}],
                                               resource_uris.DCIM_BIOSService)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.invoke.return_value = mock_xml

        result = drac_mgmt._create_config_job(self.node)

        self.assertIsNone(result)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BIOSService, 'CreateTargetedConfigJob')

    def test__create_config_job_error(self, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                    drac_common.RET_ERROR,
                                                 'Message': 'E_FAKE'}],
                                               resource_uris.DCIM_BIOSService)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.invoke.return_value = mock_xml

        self.assertRaises(exception.DracConfigJobCreationError,
                          drac_mgmt._create_config_job, self.node)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BIOSService, 'CreateTargetedConfigJob')


@mock.patch.object(drac_client, 'pywsman')
class DracManagementTestCase(db_base.DbTestCase):

    def setUp(self):
        super(DracManagementTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_drac')
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_drac',
                                               driver_info=INFO_DICT)
        self.driver = drac_mgmt.DracManagement()
        self.task = mock.Mock()
        self.task.node = self.node

    def test_get_properties(self, mock_client_pywsman):
        expected = drac_common.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.get_properties())

    def test_get_supported_boot_devices(self, mock_client_pywsman):
        expected = [boot_devices.PXE, boot_devices.DISK, boot_devices.CDROM]
        self.assertEqual(sorted(expected),
                         sorted(self.driver.get_supported_boot_devices()))

    @mock.patch.object(drac_mgmt, '_get_next_boot_mode')
    def test_get_boot_device(self, mock_gnbm, mock_client_pywsman):
        mock_gnbm.return_value = {'instance_id': 'OneTime',
                                  'is_next': drac_mgmt.ONE_TIME_BOOT}

        result_xml = test_utils.build_soap_xml([{'InstanceID': 'HardDisk'}],
                                      resource_uris.DCIM_BootSourceSetting)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        result = self.driver.get_boot_device(self.task)
        expected = {'boot_device': boot_devices.DISK, 'persistent': False}

        self.assertEqual(expected, result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootSourceSetting)

    @mock.patch.object(drac_mgmt, '_get_next_boot_mode')
    def test_get_boot_device_persistent(self, mock_gnbm, mock_client_pywsman):
        mock_gnbm.return_value = {'instance_id': 'IPL',
                                  'is_next': drac_mgmt.PERSISTENT}

        result_xml = test_utils.build_soap_xml([{'InstanceID': 'NIC'}],
                                      resource_uris.DCIM_BootSourceSetting)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml

        result = self.driver.get_boot_device(self.task)
        expected = {'boot_device': boot_devices.PXE, 'persistent': True}

        self.assertEqual(expected, result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootSourceSetting)

    @mock.patch.object(drac_client.Client, 'wsman_enumerate')
    @mock.patch.object(drac_mgmt, '_get_next_boot_mode')
    def test_get_boot_device_client_error(self, mock_gnbm, mock_we,
                                          mock_client_pywsman):
        mock_gnbm.return_value = {'instance_id': 'OneTime',
                                  'is_next': drac_mgmt.ONE_TIME_BOOT}
        mock_we.side_effect = exception.DracClientError('E_FAKE')

        self.assertRaises(exception.DracClientError,
                          self.driver.get_boot_device, self.task)
        mock_we.assert_called_once_with(resource_uris.DCIM_BootSourceSetting,
                                        mock.ANY, filter_query=mock.ANY)

    @mock.patch.object(drac_mgmt, '_check_for_config_job')
    @mock.patch.object(drac_mgmt, '_create_config_job')
    def test_set_boot_device(self, mock_ccj, mock_cfcj, mock_client_pywsman):
        result_xml_enum = test_utils.build_soap_xml([{'InstanceID': 'NIC'}],
                                      resource_uris.DCIM_BootSourceSetting)
        result_xml_invk = test_utils.build_soap_xml([{'ReturnValue':
                                                     drac_common.RET_SUCCESS}],
                                      resource_uris.DCIM_BootConfigSetting)

        mock_xml_enum = test_utils.mock_wsman_root(result_xml_enum)
        mock_xml_invk = test_utils.mock_wsman_root(result_xml_invk)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml_enum
        mock_pywsman.invoke.return_value = mock_xml_invk

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            result = self.driver.set_boot_device(task, boot_devices.PXE)

        self.assertIsNone(result)
        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootSourceSetting)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BootConfigSetting,
            'ChangeBootOrderByInstanceID')
        mock_cfcj.assert_called_once_with(self.node)
        mock_ccj.assert_called_once_with(self.node)

    @mock.patch.object(drac_mgmt, '_check_for_config_job')
    @mock.patch.object(drac_mgmt, '_create_config_job')
    def test_set_boot_device_fail(self, mock_ccj, mock_cfcj,
                                  mock_client_pywsman):
        result_xml_enum = test_utils.build_soap_xml([{'InstanceID': 'NIC'}],
                                      resource_uris.DCIM_BootSourceSetting)
        result_xml_invk = test_utils.build_soap_xml([{'ReturnValue':
                                                         drac_common.RET_ERROR,
                                                      'Message': 'E_FAKE'}],
                                      resource_uris.DCIM_BootConfigSetting)

        mock_xml_enum = test_utils.mock_wsman_root(result_xml_enum)
        mock_xml_invk = test_utils.mock_wsman_root(result_xml_invk)
        mock_pywsman = mock_client_pywsman.Client.return_value
        mock_pywsman.enumerate.return_value = mock_xml_enum
        mock_pywsman.invoke.return_value = mock_xml_invk
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracOperationError,
                              self.driver.set_boot_device, task,
                              boot_devices.PXE)

        mock_pywsman.enumerate.assert_called_once_with(mock.ANY, mock.ANY,
            resource_uris.DCIM_BootSourceSetting)
        mock_pywsman.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_BootConfigSetting,
            'ChangeBootOrderByInstanceID')
        mock_cfcj.assert_called_once_with(self.node)
        self.assertFalse(mock_ccj.called)

    @mock.patch.object(drac_client.Client, 'wsman_enumerate')
    @mock.patch.object(drac_mgmt, '_check_for_config_job')
    def test_set_boot_device_client_error(self, mock_cfcj, mock_we,
                                          mock_client_pywsman):
        mock_we.side_effect = exception.DracClientError('E_FAKE')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.node = self.node
            self.assertRaises(exception.DracClientError,
                              self.driver.set_boot_device, task,
                              boot_devices.PXE)
        mock_we.assert_called_once_with(resource_uris.DCIM_BootSourceSetting,
                                        mock.ANY, filter_query=mock.ANY)

    def test_get_sensors_data(self, mock_client_pywsman):
        self.assertRaises(NotImplementedError,
                          self.driver.get_sensors_data, self.task)
