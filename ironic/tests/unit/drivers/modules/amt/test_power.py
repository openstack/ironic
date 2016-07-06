#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test class for AMT ManagementInterface
"""

import mock
from oslo_config import cfg

from ironic.common import boot_devices
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.amt import common as amt_common
from ironic.drivers.modules.amt import management as amt_mgmt
from ironic.drivers.modules.amt import power as amt_power
from ironic.drivers.modules.amt import resource_uris
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.amt import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_amt_info()
CONF = cfg.CONF


class AMTPowerInteralMethodsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AMTPowerInteralMethodsTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_amt')
        self.info = INFO_DICT
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_amt',
                                               driver_info=self.info)
        CONF.set_override('max_attempts', 2, 'amt')
        CONF.set_override('action_wait', 0, 'amt')

    @mock.patch.object(amt_common, 'awake_amt_interface', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_common, 'get_wsman_client', spec_set=True,
                       autospec=True)
    def test__set_power_state(self, mock_client_pywsman, mock_aw):
        namespace = resource_uris.CIM_PowerManagementService
        mock_client = mock_client_pywsman.return_value
        amt_power._set_power_state(self.node, states.POWER_ON)
        mock_client.wsman_invoke.assert_called_once_with(
            mock.ANY, namespace, 'RequestPowerStateChange', mock.ANY)
        self.assertTrue(mock_aw.called)

    @mock.patch.object(amt_common, 'awake_amt_interface', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_common, 'get_wsman_client', spec_set=True,
                       autospec=True)
    def test__set_power_state_fail(self, mock_client_pywsman, mock_aw):
        mock_client = mock_client_pywsman.return_value
        mock_client.wsman_invoke.side_effect = exception.AMTFailure('x')
        self.assertRaises(exception.AMTFailure,
                          amt_power._set_power_state,
                          self.node, states.POWER_ON)
        self.assertTrue(mock_aw.called)

    @mock.patch.object(amt_common, 'awake_amt_interface', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_common, 'get_wsman_client', spec_set=True,
                       autospec=True)
    def test__power_status(self, mock_gwc, mock_aw):
        namespace = resource_uris.CIM_AssociatedPowerManagementService
        result_xml = test_utils.build_soap_xml([{'PowerState':
                                                 '2'}],
                                               namespace)
        mock_doc = test_utils.mock_wsman_root(result_xml)
        mock_client = mock_gwc.return_value
        mock_client.wsman_get.return_value = mock_doc
        self.assertEqual(
            states.POWER_ON, amt_power._power_status(self.node))

        result_xml = test_utils.build_soap_xml([{'PowerState':
                                                 '8'}],
                                               namespace)
        mock_doc = test_utils.mock_wsman_root(result_xml)
        mock_client = mock_gwc.return_value
        mock_client.wsman_get.return_value = mock_doc
        self.assertEqual(
            states.POWER_OFF, amt_power._power_status(self.node))

        result_xml = test_utils.build_soap_xml([{'PowerState':
                                                 '4'}],
                                               namespace)
        mock_doc = test_utils.mock_wsman_root(result_xml)
        mock_client = mock_gwc.return_value
        mock_client.wsman_get.return_value = mock_doc
        self.assertEqual(
            states.ERROR, amt_power._power_status(self.node))
        self.assertTrue(mock_aw.called)

    @mock.patch.object(amt_common, 'awake_amt_interface', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_common, 'get_wsman_client', spec_set=True,
                       autospec=True)
    def test__power_status_fail(self, mock_gwc, mock_aw):
        mock_client = mock_gwc.return_value
        mock_client.wsman_get.side_effect = exception.AMTFailure('x')
        self.assertRaises(exception.AMTFailure,
                          amt_power._power_status,
                          self.node)
        self.assertTrue(mock_aw.called)

    @mock.patch.object(amt_mgmt.AMTManagement, 'ensure_next_boot_device',
                       spec_set=True, autospec=True)
    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test__set_and_wait_power_on_with_boot_device(self, mock_sps,
                                                     mock_ps, mock_enbd):
        target_state = states.POWER_ON
        boot_device = boot_devices.PXE
        mock_ps.side_effect = [states.POWER_OFF, states.POWER_ON]
        mock_enbd.return_value = None
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_internal_info['amt_boot_device'] = boot_device
            result = amt_power._set_and_wait(task, target_state)
            self.assertEqual(states.POWER_ON, result)
            mock_enbd.assert_called_with(task.driver.management, task.node,
                                         boot_devices.PXE)
            mock_sps.assert_called_once_with(task.node, states.POWER_ON)
            mock_ps.assert_called_with(task.node)

    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test__set_and_wait_power_on_without_boot_device(self, mock_sps,
                                                        mock_ps):
        target_state = states.POWER_ON
        mock_ps.side_effect = [states.POWER_OFF, states.POWER_ON]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             amt_power._set_and_wait(task, target_state))
            mock_sps.assert_called_once_with(task.node, states.POWER_ON)
            mock_ps.assert_called_with(task.node)

        boot_device = boot_devices.DISK
        self.node.driver_internal_info['amt_boot_device'] = boot_device
        mock_ps.side_effect = [states.POWER_OFF, states.POWER_ON]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             amt_power._set_and_wait(task, target_state))
            mock_sps.assert_called_with(task.node, states.POWER_ON)
            mock_ps.assert_called_with(task.node)

    def test__set_and_wait_wrong_target_state(self):
        target_state = 'fake-state'
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              amt_power._set_and_wait, task, target_state)

    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test__set_and_wait_exceed_iterations(self, mock_sps,
                                             mock_ps):
        target_state = states.POWER_ON
        mock_ps.side_effect = [states.POWER_OFF, states.POWER_OFF,
                               states.POWER_OFF]
        mock_sps.return_value = exception.AMTFailure('x')
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.PowerStateFailure,
                              amt_power._set_and_wait, task, target_state)
            mock_sps.assert_called_with(task.node, states.POWER_ON)
            mock_ps.assert_called_with(task.node)
            self.assertEqual(3, mock_ps.call_count)

    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    def test__set_and_wait_already_target_state(self, mock_ps):
        target_state = states.POWER_ON
        mock_ps.side_effect = [states.POWER_ON]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_ON,
                             amt_power._set_and_wait(task, target_state))
            mock_ps.assert_called_with(task.node)

    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    @mock.patch.object(amt_power, '_set_power_state', spec_set=True,
                       autospec=True)
    def test__set_and_wait_power_off(self, mock_sps, mock_ps):
        target_state = states.POWER_OFF
        mock_ps.side_effect = [states.POWER_ON, states.POWER_OFF]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(states.POWER_OFF,
                             amt_power._set_and_wait(task, target_state))
            mock_sps.assert_called_once_with(task.node, states.POWER_OFF)
            mock_ps.assert_called_with(task.node)


class AMTPowerTestCase(db_base.DbTestCase):

    def setUp(self):
        super(AMTPowerTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_amt')
        self.info = INFO_DICT
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_amt',
                                               driver_info=self.info)

    def test_get_properties(self):
        expected = amt_common.COMMON_PROPERTIES
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertEqual(expected, task.driver.get_properties())

    @mock.patch.object(amt_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.driver.power.validate(task)
            mock_drvinfo.assert_called_once_with(task.node)

    @mock.patch.object(amt_common, 'parse_driver_info', spec_set=True,
                       autospec=True)
    def test_validate_fail(self, mock_drvinfo):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_drvinfo.side_effect = exception.InvalidParameterValue('x')
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.power.validate,
                              task)

    @mock.patch.object(amt_power, '_power_status', spec_set=True,
                       autospec=True)
    def test_get_power_state(self, mock_ps):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            mock_ps.return_value = states.POWER_ON
            self.assertEqual(states.POWER_ON,
                             task.driver.power.get_power_state(task))
            mock_ps.assert_called_once_with(task.node)

    @mock.patch.object(amt_power, '_set_and_wait', spec_set=True,
                       autospec=True)
    def test_set_power_state(self, mock_saw):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            pstate = states.POWER_ON
            mock_saw.return_value = states.POWER_ON
            task.driver.power.set_power_state(task, pstate)
            mock_saw.assert_called_once_with(task, pstate)

    @mock.patch.object(amt_power, '_set_and_wait', spec_set=True,
                       autospec=True)
    def test_set_power_state_fail(self, mock_saw):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            pstate = states.POWER_ON
            mock_saw.side_effect = exception.PowerStateFailure('x')
            self.assertRaises(exception.PowerStateFailure,
                              task.driver.power.set_power_state,
                              task, pstate)
            mock_saw.assert_called_once_with(task, pstate)

    @mock.patch.object(amt_power, '_set_and_wait', spec_set=True,
                       autospec=True)
    def test_reboot(self, mock_saw):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)
            calls = [mock.call(task, states.POWER_OFF),
                     mock.call(task, states.POWER_ON)]
            mock_saw.assert_has_calls(calls)
