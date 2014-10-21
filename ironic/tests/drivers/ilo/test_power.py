# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""Test class for IloPower module."""

import mock
from oslo.config import cfg
from oslo.utils import importutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import deploy as ilo_deploy
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')

INFO_DICT = db_utils.get_test_ilo_info()
CONF = cfg.CONF


@mock.patch.object(ilo_common, 'ilo_client')
@mock.patch.object(ilo_power, 'ilo_client')
class IloPowerInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPowerInternalMethodsTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_ilo")
        self.node = db_utils.create_test_node(
            driver='fake_ilo',
            driver_info=driver_info,
            instance_uuid='instance_uuid_123')
        CONF.set_override('power_retry', 2, 'ilo')
        CONF.set_override('power_wait', 0, 'ilo')

    def test__get_power_state(self, power_ilo_client_mock,
                              common_ilo_client_mock):
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_host_power_status.return_value = 'ON'

        self.assertEqual(
            states.POWER_ON, ilo_power._get_power_state(self.node))

        ilo_mock_object.get_host_power_status.return_value = 'OFF'
        self.assertEqual(
            states.POWER_OFF, ilo_power._get_power_state(self.node))

        ilo_mock_object.get_host_power_status.return_value = 'ERROR'
        self.assertEqual(states.ERROR, ilo_power._get_power_state(self.node))

    def test__get_power_state_fail(self, power_ilo_client_mock,
                                   common_ilo_client_mock):
        power_ilo_client_mock.IloError = Exception
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_host_power_status.side_effect = [Exception()]

        self.assertRaises(exception.IloOperationError,
                         ilo_power._get_power_state,
                         self.node)
        ilo_mock_object.get_host_power_status.assert_called_once_with()

    def test__set_power_state_invalid_state(self, power_ilo_client_mock,
                                            common_ilo_client_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            power_ilo_client_mock.IloError = Exception
            self.assertRaises(exception.IloOperationError,
                              ilo_power._set_power_state,
                              task,
                              states.ERROR)

    def test__set_power_state_reboot_fail(self, power_ilo_client_mock,
                                          common_ilo_client_mock):
        power_ilo_client_mock.IloError = Exception
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.reset_server.side_effect = Exception()

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_power._set_power_state,
                              task,
                              states.REBOOT)
        ilo_mock_object.reset_server.assert_called_once_with()

    def test__set_power_state_reboot_ok(self, power_ilo_client_mock,
                                        common_ilo_client_mock):
        power_ilo_client_mock.IloError = Exception
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_host_power_status.side_effect = ['ON', 'OFF', 'ON']

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_power._set_power_state(task, states.REBOOT)

        ilo_mock_object.reset_server.assert_called_once_with()

    def test__set_power_state_off_fail(self, power_ilo_client_mock,
                                       common_ilo_client_mock):
        power_ilo_client_mock.IloError = Exception
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_host_power_status.return_value = 'ON'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.PowerStateFailure,
                              ilo_power._set_power_state,
                              task,
                              states.POWER_OFF)

        ilo_mock_object.get_host_power_status.assert_called_with()
        ilo_mock_object.hold_pwr_btn.assert_called_once_with()

    def test__set_power_state_on_ok(self, power_ilo_client_mock,
                                    common_ilo_client_mock):
        power_ilo_client_mock.IloError = Exception
        ilo_mock_object = common_ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_host_power_status.side_effect = ['OFF', 'ON']

        target_state = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_power._set_power_state(task, target_state)
        ilo_mock_object.get_host_power_status.assert_called_with()
        ilo_mock_object.set_host_power.assert_called_once_with('ON')

    @mock.patch.object(manager_utils, 'node_set_boot_device')
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot')
    def test__attach_boot_iso(self, setup_vmedia_mock, set_boot_device_mock,
                              power_ilo_client_mock, common_ilo_client_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.instance_info['ilo_boot_iso'] = 'boot-iso'
            ilo_power._attach_boot_iso(task)
            setup_vmedia_mock.assert_called_once_with(task, 'boot-iso')
            set_boot_device_mock.assert_called_once_with(task,
                                 boot_devices.CDROM)


class IloPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPowerTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_ilo")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ilo',
                                               driver_info=driver_info)

    def test_get_properties(self):
        expected = ilo_common.COMMON_PROPERTIES
        expected.update(ilo_deploy.COMMON_PROPERTIES)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(ilo_common, 'parse_driver_info')
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(ilo_common, 'parse_driver_info')
    def test_validate_fail(self, mock_drvinfo):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        mock_drvinfo.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(ilo_power, '_get_power_state')
    def test_get_power_state(self, mock_get_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_get_power.return_value = states.POWER_ON
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            mock_get_power.assert_called_once_with(task.node)

    @mock.patch.object(ilo_power, '_set_power_state')
    def test_set_power_state(self, mock_set_power):
        mock_set_power.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
        mock_set_power.assert_called_once_with(task, states.POWER_ON)

    @mock.patch.object(ilo_power, '_set_power_state')
    @mock.patch.object(ilo_power, '_get_power_state')
    def test_reboot(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_ON
            mock_set_power.return_value = states.POWER_ON
            task.driver.power.reboot(task)
            mock_get_power.assert_called_once_with(task.node)
            mock_set_power.assert_called_once_with(task, states.REBOOT)
