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
Test class for DRAC Power Driver
"""

import mock

from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.drivers.modules.drac import client as drac_client
from ironic.drivers.modules.drac import common as drac_common
from ironic.drivers.modules.drac import power as drac_power
from ironic.drivers.modules.drac import resource_uris
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils as db_utils
from ironic.tests.drivers.drac import utils as test_utils

INFO_DICT = db_utils.get_test_drac_info()


@mock.patch.object(drac_client, 'pywsman')
@mock.patch.object(drac_power, 'pywsman')
class DracPowerInternalMethodsTestCase(base.DbTestCase):

    def setUp(self):
        super(DracPowerInternalMethodsTestCase, self).setUp()
        driver_info = INFO_DICT
        self.node = db_utils.create_test_node(
            driver='fake_drac',
            driver_info=driver_info,
            instance_uuid='instance_uuid_123')

    def test__get_power_state(self, mock_power_pywsman, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'EnabledState': '2'}],
                                             resource_uris.DCIM_ComputerSystem)
        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.enumerate.return_value = mock_xml

        self.assertEqual(states.POWER_ON,
                         drac_power._get_power_state(self.node))

        mock_pywsman_client.enumerate.assert_called_once_with(mock.ANY,
            mock.ANY, resource_uris.DCIM_ComputerSystem)

    def test__set_power_state(self, mock_power_pywsman, mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                     drac_common.RET_SUCCESS}],
                                             resource_uris.DCIM_ComputerSystem)
        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.invoke.return_value = mock_xml

        mock_pywsman_clientopts = mock_power_pywsman.ClientOptions.return_value

        drac_power._set_power_state(self.node, states.POWER_ON)

        mock_pywsman_clientopts.add_selector.assert_has_calls([
            mock.call('CreationClassName', 'DCIM_ComputerSystem'),
            mock.call('Name', 'srv:system')
        ])
        mock_pywsman_clientopts.add_property.assert_called_once_with(
            'RequestedState', '2')

        mock_pywsman_client.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_ComputerSystem, 'RequestStateChange')

    def test__set_power_state_fail(self, mock_power_pywsman,
                                   mock_client_pywsman):
        result_xml = test_utils.build_soap_xml([{'ReturnValue':
                                                         drac_common.RET_ERROR,
                                                'Message': 'error message'}],
                                             resource_uris.DCIM_ComputerSystem)

        mock_xml = test_utils.mock_wsman_root(result_xml)
        mock_pywsman_client = mock_client_pywsman.Client.return_value
        mock_pywsman_client.invoke.return_value = mock_xml

        mock_pywsman_clientopts = mock_power_pywsman.ClientOptions.return_value

        self.assertRaises(exception.DracOperationError,
                          drac_power._set_power_state, self.node,
                          states.POWER_ON)

        mock_pywsman_clientopts.add_selector.assert_has_calls([
            mock.call('CreationClassName', 'DCIM_ComputerSystem'),
            mock.call('Name', 'srv:system')
        ])
        mock_pywsman_clientopts.add_property.assert_called_once_with(
            'RequestedState', '2')

        mock_pywsman_client.invoke.assert_called_once_with(mock.ANY,
            resource_uris.DCIM_ComputerSystem, 'RequestStateChange')


class DracPowerTestCase(base.DbTestCase):

    def setUp(self):
        super(DracPowerTestCase, self).setUp()
        driver_info = INFO_DICT
        mgr_utils.mock_the_extension_manager(driver="fake_drac")
        self.node = db_utils.create_test_node(
            driver='fake_drac',
            driver_info=driver_info,
            instance_uuid='instance_uuid_123')

    def test_get_properties(self):
        expected = drac_common.COMMON_PROPERTIES
        driver = drac_power.DracPower()
        self.assertEqual(expected, driver.get_properties())

    @mock.patch.object(drac_power, '_get_power_state')
    def test_get_power_state(self, mock_get_power_state):
        mock_get_power_state.return_value = states.POWER_ON
        driver = drac_power.DracPower()
        task = mock.Mock()
        task.node.return_value = self.node

        self.assertEqual(states.POWER_ON, driver.get_power_state(task))
        mock_get_power_state.assert_called_once_with(task.node)

    @mock.patch.object(drac_power, '_set_power_state')
    def test_set_power_state(self, mock_set_power_state):
        mock_set_power_state.return_value = states.POWER_ON
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.set_power_state(task, states.POWER_ON)
            mock_set_power_state.assert_called_once_with(task.node,
                                                         states.POWER_ON)

    @mock.patch.object(drac_power, '_set_power_state')
    def test_reboot(self, mock_set_power_state):
        mock_set_power_state.return_value = states.REBOOT
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            task.driver.power.reboot(task)
            mock_set_power_state.assert_called_once_with(task.node,
                                                         states.REBOOT)
