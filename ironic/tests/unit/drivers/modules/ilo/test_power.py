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
from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.conductor import utils as manager_utils
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.drivers.modules.ilo import power as ilo_power
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

ilo_error = importutils.try_import('proliantutils.exception')

INFO_DICT = db_utils.get_test_ilo_info()
CONF = cfg.CONF


@mock.patch.object(ilo_common, 'get_ilo_object', spec_set=True, autospec=True)
class IloPowerInternalMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IloPowerInternalMethodsTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_ilo")
        self.node = db_utils.create_test_node(
            driver='fake_ilo',
            driver_info=driver_info,
            instance_uuid=uuidutils.generate_uuid())
        CONF.set_override('power_retry', 2, 'ilo')
        CONF.set_override('power_wait', 0, 'ilo')

    def test__get_power_state(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        ilo_mock_object.get_host_power_status.return_value = 'ON'

        self.assertEqual(
            states.POWER_ON, ilo_power._get_power_state(self.node))

        ilo_mock_object.get_host_power_status.return_value = 'OFF'
        self.assertEqual(
            states.POWER_OFF, ilo_power._get_power_state(self.node))

        ilo_mock_object.get_host_power_status.return_value = 'ERROR'
        self.assertEqual(states.ERROR, ilo_power._get_power_state(self.node))

    def test__get_power_state_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.get_host_power_status.side_effect = exc

        self.assertRaises(exception.IloOperationError,
                          ilo_power._get_power_state,
                          self.node)
        ilo_mock_object.get_host_power_status.assert_called_once_with()

    def test__set_power_state_invalid_state(self, get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              ilo_power._set_power_state,
                              task,
                              states.ERROR)

    def test__set_power_state_reboot_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        exc = ilo_error.IloError('error')
        ilo_mock_object.reset_server.side_effect = exc

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.IloOperationError,
                              ilo_power._set_power_state,
                              task,
                              states.REBOOT)
        ilo_mock_object.reset_server.assert_called_once_with()

    def test__set_power_state_reboot_ok(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        ilo_mock_object.get_host_power_status.side_effect = ['ON', 'OFF', 'ON']

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_power._set_power_state(task, states.REBOOT)

        ilo_mock_object.reset_server.assert_called_once_with()

    def test__set_power_state_off_fail(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        ilo_mock_object.get_host_power_status.return_value = 'ON'

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.PowerStateFailure,
                              ilo_power._set_power_state,
                              task,
                              states.POWER_OFF)

        ilo_mock_object.get_host_power_status.assert_called_with()
        ilo_mock_object.hold_pwr_btn.assert_called_once_with()

    def test__set_power_state_on_ok(self, get_ilo_object_mock):
        ilo_mock_object = get_ilo_object_mock.return_value
        ilo_mock_object.get_host_power_status.side_effect = ['OFF', 'ON']

        target_state = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            ilo_power._set_power_state(task, target_state)
        ilo_mock_object.get_host_power_status.assert_called_with()
        ilo_mock_object.set_host_power.assert_called_once_with('ON')

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    def test__attach_boot_iso_if_needed(
            self, setup_vmedia_mock, set_boot_device_mock,
            get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.ACTIVE
            task.node.instance_info['ilo_boot_iso'] = 'boot-iso'
            ilo_power._attach_boot_iso_if_needed(task)
            setup_vmedia_mock.assert_called_once_with(task, 'boot-iso')
            set_boot_device_mock.assert_called_once_with(task,
                                                         boot_devices.CDROM)

    @mock.patch.object(manager_utils, 'node_set_boot_device', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_common, 'setup_vmedia_for_boot', spec_set=True,
                       autospec=True)
    def test__attach_boot_iso_if_needed_on_rebuild(
            self, setup_vmedia_mock, set_boot_device_mock,
            get_ilo_object_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.provision_state = states.DEPLOYING
            task.node.instance_info['ilo_boot_iso'] = 'boot-iso'
            ilo_power._attach_boot_iso_if_needed(task)
            self.assertFalse(setup_vmedia_mock.called)
            self.assertFalse(set_boot_device_mock.called)


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
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.power.get_properties())

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(ilo_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail(self, mock_drvinfo):
        side_effect = exception.InvalidParameterValue("Invalid Input")
        mock_drvinfo.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(ilo_power, '_get_power_state', spec_set=True,
                       autospec=True)
    def test_get_power_state(self, mock_get_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_get_power.return_value = states.POWER_ON
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            mock_get_power.assert_called_once_with(task.node)

    @mock.patch.object(ilo_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test_set_power_state(self, mock_set_power):
        mock_set_power.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
        mock_set_power.assert_called_once_with(task, states.POWER_ON)

    @mock.patch.object(ilo_power, '_set_power_state', spec_set=True,
                       autospec=True)
    @mock.patch.object(ilo_power, '_get_power_state', spec_set=True,
                       autospec=True)
    def test_reboot(self, mock_get_power, mock_set_power):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            mock_get_power.return_value = states.POWER_ON
            mock_set_power.return_value = states.POWER_ON
            task.driver.power.reboot(task)
            mock_get_power.assert_called_once_with(task.node)
            mock_set_power.assert_called_once_with(task, states.REBOOT)
