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

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.xclarity import common
from ironic.drivers.modules.xclarity import power
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

STATE_POWER_ON = "power on"
STATE_POWER_OFF = "power off"
STATE_POWERING_ON = "power on"
STATE_POWERING_OFF = "power on"

xclarity_constants = importutils.try_import('xclarity_client.constants')
xclarity_client_exceptions = importutils.try_import(
    'xclarity_client.exceptions')


@mock.patch.object(common, 'get_xclarity_client',
                   spect_set=True, autospec=True)
class XClarityPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(XClarityPowerDriverTestCase, self).setUp()
        self.config(enabled_hardware_types=['xclarity'],
                    enabled_power_interfaces=['xclarity'],
                    enabled_management_interfaces=['xclarity'])
        self.node = obj_utils.create_test_node(
            self.context,
            driver='xclarity',
            driver_info=db_utils.get_test_xclarity_driver_info())

    def test_get_properties(self, mock_get_xc_client):
        expected = common.COMMON_PROPERTIES
        driver = power.XClarityPower()
        self.assertEqual(expected, driver.get_properties())

    @mock.patch.object(common, 'get_server_hardware_id',
                       spect_set=True, autospec=True)
    def test_validate(self, mock_validate_driver_info, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.validate(task)
        common.get_server_hardware_id(task.node)
        mock_validate_driver_info.assert_called_with(task.node)

    @mock.patch.object(power.XClarityPower, 'get_power_state',
                       return_value=STATE_POWER_ON)
    def test_get_power_state(self, mock_get_power_state, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            result = power.XClarityPower.get_power_state(task)
        self.assertEqual(STATE_POWER_ON, result)

    @mock.patch.object(common, 'translate_xclarity_power_state',
                       spec_set=True, autospec=True)
    def test_get_power_state_fail(self, mock_translate_state, mock_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            xclarity_client_exceptions.XClarityError = Exception
            sys.modules['xclarity_client.exceptions'] = (
                xclarity_client_exceptions)
            if 'ironic.drivers.modules.xclarity' in sys.modules:
                importlib.reload(
                    sys.modules['ironic.drivers.modules.xclarity'])
            ex = exception.XClarityError('E')
            mock_xc_client.return_value.get_node_power_status.side_effect = ex
            self.assertRaises(exception.XClarityError,
                              task.driver.power.get_power_state,
                              task)
            self.assertFalse(mock_translate_state.called)

    @mock.patch.object(power.LOG, 'warning')
    @mock.patch.object(power.XClarityPower, 'get_power_state',
                       return_value=states.POWER_ON)
    def test_set_power(self, mock_set_power_state, mock_log,
                       mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
            expected = task.driver.power.get_power_state(task)
        self.assertEqual(expected, states.POWER_ON)
        self.assertFalse(mock_log.called)

    @mock.patch.object(power.LOG, 'warning')
    @mock.patch.object(power.XClarityPower, 'get_power_state',
                       return_value=states.POWER_ON)
    def test_set_power_timeout(self, mock_set_power_state, mock_log,
                               mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.set_power_state(task, states.POWER_ON,
                                              timeout=21)
            expected = task.driver.power.get_power_state(task)
        self.assertEqual(expected, states.POWER_ON)
        self.assertTrue(mock_log.called)

    def test_set_power_fail(self, mock_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            xclarity_client_exceptions.XClarityError = Exception
            sys.modules['xclarity_client.exceptions'] = (
                xclarity_client_exceptions)
            if 'ironic.drivers.modules.xclarity' in sys.modules:
                importlib.reload(
                    sys.modules['ironic.drivers.modules.xclarity'])
            ex = exception.XClarityError('E')
            mock_xc_client.return_value.set_node_power_status.side_effect = ex
            self.assertRaises(exception.XClarityError,
                              task.driver.power.set_power_state,
                              task, states.POWER_OFF)

    @mock.patch.object(power.LOG, 'warning')
    @mock.patch.object(power.XClarityPower, 'set_power_state')
    def test_reboot(self, mock_set_power_state, mock_log, mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.reboot(task)
            mock_set_power_state.assert_called_with(task, states.REBOOT)
            self.assertFalse(mock_log.called)

    @mock.patch.object(power.LOG, 'warning')
    @mock.patch.object(power.XClarityPower, 'set_power_state')
    def test_reboot_timeout(self, mock_set_power_state, mock_log,
                            mock_get_xc_client):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.power.reboot(task, timeout=55)
            mock_set_power_state.assert_called_with(task, states.REBOOT)
            self.assertTrue(mock_log.called)
