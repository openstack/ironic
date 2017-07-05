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

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.oneview import common
from ironic.drivers.modules.oneview import deploy_utils
from ironic.drivers.modules.oneview import management
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

oneview_models = importutils.try_import('oneview_client.models')
oneview_exceptions = importutils.try_import('oneview_client.exceptions')

POWER_ON = 'On'
POWER_OFF = 'Off'
ERROR = 'error'


@mock.patch.object(common, 'get_oneview_client', spec_set=True, autospec=True)
class OneViewPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(OneViewPowerDriverTestCase, self).setUp()
        self.config(manager_url='https://1.2.3.4', group='oneview')
        self.config(username='user', group='oneview')
        self.config(password='password', group='oneview')

        mgr_utils.mock_the_extension_manager(driver='fake_oneview')
        self.driver = driver_factory.get_driver('fake_oneview')

        self.node = obj_utils.create_test_node(
            self.context, driver='fake_oneview',
            properties=db_utils.get_test_oneview_properties(),
            driver_info=db_utils.get_test_oneview_driver_info(),
        )
        self.info = common.get_oneview_info(self.node)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview',
                       spect_set=True, autospec=True)
    def test_power_interface_validate(self, mock_is_node_in_use_by_oneview,
                                      mock_validate, mock_get_ov_client):
        mock_is_node_in_use_by_oneview.return_value = False
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.validate(task)
            self.assertTrue(mock_validate.called)

    def test_power_interface_validate_fail(self, mock_get_ov_client):
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          id=999,
                                          driver='fake_oneview')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.power.validate, task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    def test_power_interface_validate_fail_exception(self, mock_validate,
                                                     mock_get_ov_client):
        mock_validate.side_effect = exception.OneViewError('message')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview',
                       spect_set=True, autospec=True)
    def test_power_validate_fail_node_used_by_oneview(
            self, mock_is_node_in_use_by_oneview, mock_validate,
            mock_get_ov_client):
        mock_validate.return_value = True
        mock_is_node_in_use_by_oneview.return_value = True
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(common, 'validate_oneview_resources_compatibility',
                       spect_set=True, autospec=True)
    @mock.patch.object(deploy_utils, 'is_node_in_use_by_oneview',
                       spect_set=True, autospec=True)
    def test_validate_fail_node_in_use_by_oneview(
            self, mock_is_node_in_use_by_oneview, mock_validate,
            mock_get_ov_client):
        mock_validate.return_value = True
        mock_is_node_in_use_by_oneview.side_effect = (
            exception.OneViewError('message'))
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    def test_power_interface_get_properties(self, mock_get_ov_client):
        expected = common.COMMON_PROPERTIES
        self.assertItemsEqual(expected, self.driver.power.get_properties())

    def test_get_power_state(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        oneview_client.get_node_power_state.return_value = POWER_ON
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.power.get_power_state(task)
        oneview_client.get_node_power_state.assert_called_once_with(self.info)

    def test_get_power_state_fail(self, mock_get_ov_client):
        oneview_client = mock_get_ov_client()
        oneview_client.get_node_power_state.side_effect = \
            oneview_exceptions.OneViewException()
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.OneViewError,
                self.driver.power.get_power_state,
                task
            )

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_on(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client = mock_get_ov_client.return_value
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        oneview_client.power_on.return_value = POWER_ON
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.driver.power.set_power_state(task, states.POWER_ON)
            mock_set_boot_device.assert_called_once_with(task)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_on.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_off(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client = mock_get_ov_client.return_value
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        oneview_client.power_off.return_value = POWER_OFF
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.driver.power.set_power_state(task, states.POWER_OFF)
            self.assertFalse(mock_set_boot_device.called)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_off.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_on_fail(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        exc = oneview_exceptions.OneViewException()
        oneview_client.power_on.side_effect = exc
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.assertRaises(exception.OneViewError,
                              self.driver.power.set_power_state, task,
                              states.POWER_ON)
            mock_set_boot_device.assert_called_once_with(task)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_on.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_off_fail(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        exc = oneview_exceptions.OneViewException()
        oneview_client.power_off.side_effect = exc
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.assertRaises(exception.OneViewError,
                              self.driver.power.set_power_state, task,
                              states.POWER_OFF)
            self.assertFalse(mock_set_boot_device.called)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_off.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_invalid_state(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        exc = oneview_exceptions.OneViewException()
        oneview_client.power_off.side_effect = exc
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.power.set_power_state, task,
                              'fake state')
            self.assertFalse(mock_set_boot_device.called)

    @mock.patch.object(management, 'set_boot_device')
    def test_set_power_reboot(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        oneview_client.power_off.return_value = POWER_OFF
        oneview_client.power_on.return_value = POWER_ON
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.driver.power.set_power_state(task, states.REBOOT)
            mock_set_boot_device.assert_called_once_with(task)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_off.assert_called_once_with(self.info)
            oneview_client.power_off.assert_called_once_with(self.info)
            oneview_client.power_on.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_reboot(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        oneview_client.power_off.return_value = POWER_OFF
        oneview_client.power_on.return_value = POWER_ON
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.driver.power.reboot(task)
            mock_set_boot_device.assert_called_once_with(task)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_off.assert_called_once_with(self.info)
            oneview_client.power_on.assert_called_once_with(self.info)

    @mock.patch.object(management, 'set_boot_device')
    def test_reboot_fail(
            self, mock_set_boot_device, mock_get_ov_client):

        sp_uri = '/any/server-profile'
        oneview_client = mock_get_ov_client()
        fake_sh = oneview_models.ServerHardware()
        fake_sh.server_profile_uri = sp_uri
        oneview_client.get_server_hardware_by_uuid.return_value = fake_sh
        exc = oneview_exceptions.OneViewException()
        oneview_client.power_off.side_effect = exc
        self.driver.power.oneview_client = oneview_client

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['applied_server_profile_uri'] = sp_uri
            task.node.driver_info = driver_info
            self.assertRaises(exception.OneViewError,
                              self.driver.power.reboot, task)
            self.assertFalse(mock_set_boot_device.called)
            self.info['applied_server_profile_uri'] = sp_uri
            oneview_client.power_off.assert_called_once_with(self.info)
            self.assertFalse(oneview_client.power_on.called)
