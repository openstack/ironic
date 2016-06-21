# -*- encoding: utf-8 -*-
#
# Copyright 2015 Hewlett Packard Development Company, LP
# Copyright 2015 Universidade Federal de Campina Grande
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

import mock
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import management
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils


oneview_exceptions = importutils.try_import('oneview_client.exceptions')


@mock.patch.object(common, 'get_oneview_client', spect_set=True, autospec=True)
class OneViewManagementDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewManagementDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver="fake_oneview")
        self.driver = driver_factory.get_driver("fake_oneview")

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    def test_validate(self, mock_validate, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)
            self.assertTrue(mock_validate.called)

    def test_validate_fail(self, mock_get_ov_client):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          id=999,
                                          driver='fake_oneview')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    def test_validate_fail_exception(self, mock_validate, mock_get_ov_client):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate,
                              task)

    def test_get_properties(self, mock_get_ov_client):
        expected = common.COMMON_PROPERTIES
        self.assertItemsEqual(expected,
                              self.driver.management.get_properties())

    def test_set_boot_device(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)
        oneview_client.set_boot_device.assert_called_once_with(
            self.info,
            management.BOOT_DEVICE_MAPPING_TO_OV[boot_devices.PXE]
        )

    def test_set_boot_device_invalid_device(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.management.set_boot_device,
                              task, 'fake-device')
        self.assertFalse(oneview_client.set_boot_device.called)

    def test_set_boot_device_fail_to_get_server_profile(self,
                                                        mock_get_ov_client):
        oneview_client = mock_get_ov_client()

        oneview_client.get_server_profile_from_hardware.side_effect = \
            oneview_exceptions.OneViewException()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.OneViewError,
                              self.driver.management.set_boot_device,
                              task, 'disk')
        self.assertFalse(oneview_client.set_boot_device.called)

    def test_set_boot_device_without_server_profile(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        oneview_client.get_server_profile_from_hardware.return_value = False
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected_msg = (
                'A Server Profile is not associated with node %s.'
                % self.node.uuid
            )
            self.assertRaisesRegex(
                exception.OperationNotPermitted,
                expected_msg,
                self.driver.management.set_boot_device,
                task,
                'disk'
            )

    def test_get_supported_boot_devices(self, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM]
            self.assertItemsEqual(
                expected,
                task.driver.management.get_supported_boot_devices(task),
            )

    def test_get_boot_device(self, mock_get_ov_client):
        device_mapping = management.BOOT_DEVICE_MAPPING_TO_OV
        oneview_client = mock_get_ov_client()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            # For each known device on OneView, Ironic should return its
            # counterpart value
            for device_ironic, device_ov in device_mapping.items():
                oneview_client.get_boot_order.return_value = [device_ov]
                expected_response = {
                    'boot_device': device_ironic,
                    'persistent': True
                }
                response = self.driver.management.get_boot_device(task)
                self.assertEqual(expected_response, response)
        oneview_client.get_boot_order.assert_called_with(self.info)

    def test_get_boot_device_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        oneview_client.get_boot_order.side_effect = \
            oneview_exceptions.OneViewException()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.OneViewError,
                              self.driver.management.get_boot_device,
                              task)
            oneview_client.get_boot_order.assert_called_with(self.info)

    def test_get_boot_device_unknown_device(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        oneview_client.get_boot_order.return_value = ["spam",
                                                      "bacon"]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.management.get_boot_device,
                task
            )

    def test_get_sensors_data_not_implemented(self, mock_get_ov_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                NotImplementedError,
                task.driver.management.get_sensors_data,
                task
            )
