# Copyright (2015-2017) Hewlett Packard Enterprise Development LP
# Copyright (2015-2017) Universidade Federal de Campina Grande
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
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import management
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

client_exception = importutils.try_import('hpOneView.exceptions')


@mock.patch.object(common, 'get_hponeview_client')
class OneViewManagementDriverFunctionsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewManagementDriverFunctionsTestCase, self).setUp()
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

    @mock.patch.object(common, 'get_ilorest_client')
    def test_set_boot_device(
            self, mock_get_ilo_client, mock_get_ov_client):
        ilo_client = mock_get_ilo_client()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'boot_device': boot_devices.PXE,
                                'persistent': True}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            management.set_boot_device(task)
            self.assertFalse(ilo_client.called)
            patch = ilo_client.patch
            self.assertFalse(patch.called)
            driver_internal_info = task.node.driver_internal_info
            self.assertNotIn('next_boot_device', driver_internal_info)

    @mock.patch.object(common, 'get_ilorest_client')
    def test_set_boot_device_not_persistent(
            self, mock_get_ilo_client, mock_get_ov_client):
        ilo_client = mock_get_ilo_client()
        client = mock_get_ov_client()
        server_profile = {'boot': {'order':
                          list(management.BOOT_DEVICE_MAP_ONEVIEW_REV)}}
        client.server_profiles.get.return_value = server_profile
        boot_device_map_ilo = management.BOOT_DEVICE_MAP_ILO
        boot_device = boot_device_map_ilo.get(boot_devices.PXE)
        body = {
            "Boot": {
                "BootSourceOverrideTarget": boot_device,
                "BootSourceOverrideEnabled": "Once"
            }
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            profile_uri = driver_info.get('applied_server_profile_uri')
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'boot_device': boot_devices.PXE,
                                'persistent': False}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            management.set_boot_device(task)
            update = client.server_profiles.update
            update.assert_called_once_with(server_profile, profile_uri)
            patch = ilo_client.patch
            patch.assert_called_once_with(
                path=management.ILO_SYSTEM_PATH,
                body=body,
                headers=management.ILO_REQUEST_HEADERS
            )
            driver_internal_info = task.node.driver_internal_info
            self.assertNotIn('next_boot_device', driver_internal_info)

    def test_set_boot_device_invalid_device(self, mock_get_ov_client):
        client = mock_get_ov_client()

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'boot_device': 'pixie-boots',
                                'persistent': True}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            self.assertRaises(exception.InvalidParameterValue,
                              management.set_boot_device,
                              task)
            self.assertFalse(client.set_boot_device.called)
            self.assertIn('next_boot_device', driver_internal_info)

    def test_set_boot_device_fail_to_get_server_profile(
            self, mock_get_ov_client):
        client = mock_get_ov_client()
        exc = client_exception.HPOneViewException()
        client.server_profiles.get.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'device': 'disk',
                                'persistent': True}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            self.assertRaises(
                exception.OneViewError,
                management.set_boot_device,
                task
            )
            self.assertIn('next_boot_device', driver_internal_info)

    @mock.patch.object(common, 'get_ilorest_client')
    def test_set_onetime_boot_persistent(
            self, mock_iloclient, mock_get_ov_client):
        ilo_client = mock_iloclient()
        driver_internal_info = self.node.driver_internal_info
        next_boot_device = {'device': 'disk', 'persistent': False}
        driver_internal_info['next_boot_device'] = next_boot_device
        with task_manager.acquire(self.context, self.node.uuid) as task:
            management.set_onetime_boot(task)
            self.assertFalse(ilo_client.called)
            self.assertFalse(ilo_client.patch.called)

    @mock.patch.object(common, 'get_ilorest_client')
    def test_set_onetime_boot_not_persistent(
            self, mock_iloclient, mock_get_ov_client):
        ilo_client = mock_iloclient()
        boot_device = management.BOOT_DEVICE_MAP_ILO.get(boot_devices.DISK)
        body = {
            "Boot": {
                "BootSourceOverrideTarget": boot_device,
                "BootSourceOverrideEnabled": "Once"
            }
        }
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'boot_device': 'disk', 'persistent': False}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            management.set_onetime_boot(task)
            self.assertTrue(mock_iloclient.called)
            ilo_client.patch.assert_called_once_with(
                path=management.ILO_SYSTEM_PATH,
                body=body,
                headers=management.ILO_REQUEST_HEADERS
            )

    @mock.patch.object(common, 'get_ilorest_client')
    def test__is_onetime_boot_true(
            self, mock_iloclient, mock_get_ov_client):

        class RestResponse(object):
            @property
            def dict(self):
                return {'Boot': {'BootSourceOverrideEnabled': "Once"}}

        ilo_client = mock_iloclient()
        ilo_client.get.return_value = RestResponse()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertTrue(management._is_onetime_boot(task))
            self.assertTrue(mock_iloclient.called)
            ilo_client.get.assert_called_with(
                path=management.ILO_SYSTEM_PATH,
                headers=management.ILO_REQUEST_HEADERS
            )

    @mock.patch.object(common, 'get_ilorest_client')
    def test__is_onetime_boot_false(
            self, mock_iloclient, mock_get_ov_client):

        class RestResponse(object):
            @property
            def dict(self):
                return {'Boot': {'BootSourceOverrideEnabled': "Disabled"}}

        ilo_client = mock_iloclient()
        ilo_client.get.return_value = RestResponse()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertFalse(management._is_onetime_boot(task))
            self.assertTrue(mock_iloclient.called)
            ilo_client.get.assert_called_with(
                path=management.ILO_SYSTEM_PATH,
                headers=management.ILO_REQUEST_HEADERS
            )


class OneViewManagementDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewManagementDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')
        self.config(tls_cacert_file='ca_file', group='oneview')
        self.config(allow_insecure_connections=False, group='oneview')

        mgr_utils.mock_the_extension_manager(driver="fake_oneview")
        self.driver = driver_factory.get_driver("fake_oneview")

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)

    @mock.patch.object(deploy_utils, 'is_node_in_use_by_ironic',
                       spect_set=True, autospec=True)
    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    def test_validate(self, mock_validate, mock_ironic_node):
        mock_ironic_node.return_value = True
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.management.validate(task)
            self.assertTrue(mock_validate.called)

    @mock.patch.object(deploy_utils, 'is_node_in_use_by_ironic',
                       spect_set=True, autospec=True)
    def test_validate_for_node_not_in_use_by_ironic(self, mock_ironic_node):
        mock_ironic_node.return_value = False
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate, task)

    def test_validate_fail(self):
        node = obj_utils.create_test_node(
            self.context, uuid=uuidutils.generate_uuid(),
            id=999, driver='fake_oneview'
        )
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility')
    def test_validate_fail_exception(self, mock_validate):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.validate,
                              task)

    def test_get_properties(self):
        expected = common.COMMON_PROPERTIES
        self.assertItemsEqual(expected,
                              self.driver.management.get_properties())

    def test_set_boot_device_persistent_true(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.set_boot_device(
                task, boot_devices.PXE, True)
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = driver_internal_info.get('next_boot_device')
            self.assertIn('next_boot_device', driver_internal_info)
            self.assertEqual(
                next_boot_device.get('boot_device'), boot_devices.PXE)
            self.assertTrue(next_boot_device.get('persistent'))

    def test_set_boot_device_persistent_false(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.set_boot_device(
                task, boot_devices.PXE, False)
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = driver_internal_info.get('next_boot_device')
            self.assertIn('next_boot_device', driver_internal_info)
            self.assertEqual(
                next_boot_device.get('boot_device'), boot_devices.PXE)
            self.assertFalse(next_boot_device.get('persistent'))

    def test_set_boot_device_invalid_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.management.set_boot_device,
                              task, 'unknown-device', False)
            driver_internal_info = task.node.driver_internal_info
            self.assertNotIn('next_boot_device', driver_internal_info)

    def test_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [
                boot_devices.PXE, boot_devices.DISK, boot_devices.CDROM
            ]
            self.assertItemsEqual(
                expected,
                task.driver.management.get_supported_boot_devices(task),
            )

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(common, 'get_ilorest_client')
    def test_get_boot_device(self, mock_iloclient, mock_get_ov_client):
        ilo_client = mock_iloclient()
        oneview_client = mock_get_ov_client()
        device_mapping = management.BOOT_DEVICE_MAP_ONEVIEW.items()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            # For each known device on OneView, Ironic should return its
            # counterpart value
            for ironic_device, oneview_device in device_mapping:
                profile = {'boot': {'order': [oneview_device]}}
                oneview_client.server_profiles.get.return_value = profile
                expected = {'boot_device': ironic_device, 'persistent': True}
                response = self.driver.management.get_boot_device(task)
                self.assertEqual(expected, response)
                self.assertTrue(oneview_client.server_profiles.get.called)
                self.assertTrue(ilo_client.get.called)

    @mock.patch.object(common, 'get_ilorest_client')
    def test_get_boot_device_from_next_boot_device(self, mock_iloclient):
        ilo_client = mock_iloclient()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_internal_info = task.node.driver_internal_info
            next_boot_device = {'boot_device': boot_devices.DISK,
                                'persistent': True}
            driver_internal_info['next_boot_device'] = next_boot_device
            task.node.driver_internal_info = driver_internal_info
            expected_response = {
                'boot_device': boot_devices.DISK,
                'persistent': True
            }
            response = self.driver.management.get_boot_device(task)
            self.assertEqual(expected_response, response)
            self.assertFalse(ilo_client.get.called)

    @mock.patch.object(common, 'get_hponeview_client')
    @mock.patch.object(common, 'get_ilorest_client')
    def test_get_boot_device_fail(self, mock_iloclient, mock_get_ov_client):
        client = mock_get_ov_client()
        ilo_client = mock_iloclient()
        exc = client_exception.HPOneViewException()
        client.server_profiles.get.side_effect = exc
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.management.get_boot_device,
                task
            )
            self.assertTrue(client.server_profiles.get.called)
            self.assertFalse(ilo_client.get.called)

    @mock.patch.object(common, 'get_ilorest_client')
    def test_get_boot_device_unknown_device(self, mock_iloclient):
        ilo_client = mock_iloclient()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.management.get_boot_device,
                task
            )
            self.assertFalse(ilo_client.get.called)

    def test_get_sensors_data_not_implemented(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                NotImplementedError,
                task.driver.management.get_sensors_data,
                task
            )
