# Copyright 2017 Lenovo, Inc.
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

import importlib
import sys

import mock
from oslo_utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.xclarity import common
from ironic.drivers.modules.xclarity import management
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


xclarity_client_exceptions = importutils.try_import(
    'xclarity_client.exceptions')


@mock.patch.object(common, 'get_xclarity_client', spect_set=True,
                   autospec=True)
class XClarityManagementDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(XClarityManagementDriverTestCase, self).setUp()
        self.config(enabled_hardware_types=['xclarity'],
                    enabled_power_interfaces=['xclarity'],
                    enabled_management_interfaces=['xclarity'])
        self.node = obj_utils.create_test_node(
            self.context,
            driver='xclarity',
            driver_info=db_utils.get_test_xclarity_driver_info())

    @mock.patch.object(common, 'get_server_hardware_id',
                       spect_set=True, autospec=True)
    def test_validate(self, mock_validate, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)
        common.get_server_hardware_id(task.node)
        mock_validate.assert_called_with(task.node)

    def test_get_properties(self, mock_get_xc_client):
        expected = common.COMMON_PROPERTIES
        driver = management.XClarityManagement()
        self.assertEqual(expected, driver.get_properties())

    @mock.patch.object(management.XClarityManagement, 'get_boot_device',
                       return_value='pxe')
    def test_set_boot_device(self, mock_get_boot_device,
                             mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.set_boot_device(task, 'pxe')
            result = task.driver.management.get_boot_device(task)
        self.assertEqual(result, 'pxe')

    def test_set_boot_device_fail(self, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            xclarity_client_exceptions.XClarityError = Exception
            sys.modules['xclarity_client.exceptions'] = (
                xclarity_client_exceptions)
            if 'ironic.drivers.modules.xclarity' in sys.modules:
                importlib.reload(
                    sys.modules['ironic.drivers.modules.xclarity'])
            ex = exception.XClarityError('E')
            mock_get_xc_client.return_value.set_node_boot_info.side_effect = ex
            self.assertRaises(exception.XClarityError,
                              task.driver.management.set_boot_device,
                              task,
                              "pxe")

    def test_get_supported_boot_devices(self, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.BIOS,
                        boot_devices.DISK, boot_devices.CDROM]
            self.assertCountEqual(
                expected,
                task.driver.management.get_supported_boot_devices(task))

    @mock.patch.object(
        management.XClarityManagement,
        'get_boot_device',
        return_value={'boot_device': 'pxe', 'persistent': False})
    def test_get_boot_device(self, mock_get_boot_device, mock_get_xc_client):
        reference = {'boot_device': 'pxe', 'persistent': False}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected_boot_device = task.driver.management.get_boot_device(
                task=task)

        self.assertEqual(reference, expected_boot_device)

    def test_get_boot_device_fail(self, mock_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            xclarity_client_exceptions.XClarityError = Exception
            sys.modules['xclarity_client.exceptions'] = (
                xclarity_client_exceptions)
            if 'ironic.drivers.modules.xclarity' in sys.modules:
                importlib.reload(
                    sys.modules['ironic.drivers.modules.xclarity'])
            ex = exception.XClarityError('E')
            mock_xc_client.return_value.get_node_all_boot_info.side_effect = ex
            self.assertRaises(
                exception.XClarityError,
                task.driver.management.get_boot_device,
                task)

    def test_get_boot_device_current_none(self, mock_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            reference = {'boot_device': None, 'persistent': None}
            mock_xc_client.return_value.get_node_all_boot_info.return_value = \
                {
                    'bootOrder': {
                        'bootOrderList': [{
                            'fakeBootOrderDevices': []
                        }]
                    }
                }
            expected_boot_device = task.driver.management.get_boot_device(
                task=task)
            self.assertEqual(reference, expected_boot_device)

    def test_get_boot_device_primary_none(self, mock_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            reference = {'boot_device': None, 'persistent': None}
            mock_xc_client.return_value.get_node_all_boot_info.return_value = \
                {
                    'bootOrder': {
                        'bootOrderList': [
                            {
                                'bootType': 'SingleUse',
                                'CurrentBootOrderDevices': []
                            },
                            {
                                'bootType': 'Permanent',
                                'CurrentBootOrderDevices': []
                            },
                        ]
                    }
                }
            expected_boot_device = task.driver.management.get_boot_device(
                task=task)
            self.assertEqual(reference, expected_boot_device)
