# Copyright 2015, Cisco Systems.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules import ipmitool
from ironic.tests.unit.drivers.modules.intel_ipmi import base


class IntelIPMIManagementTestCase(base.IntelIPMITestCase):
    def test_configure_intel_speedselect_empty(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.management.configure_intel_speedselect,
                task)

    @mock.patch.object(ipmitool, "send_raw", spec_set=True,
                       autospec=True)
    def test_configure_intel_speedselect(self, send_raw_mock):
        send_raw_mock.return_value = [None, None]
        config = {"intel_speedselect_config": "0x02", "socket_count": 1}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = task.driver.management.configure_intel_speedselect(task,
                                                                     **config)
        self.assertIsNone(ret)
        send_raw_mock.assert_called_once_with(task,
                                              '0x2c 0x41 0x04 0x00 0x00 0x02')

    @mock.patch.object(ipmitool, "send_raw", spec_set=True,
                       autospec=True)
    def test_configure_intel_speedselect_more_socket(self, send_raw_mock):
        send_raw_mock.return_value = [None, None]
        config = {"intel_speedselect_config": "0x02", "socket_count": 4}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = task.driver.management.configure_intel_speedselect(task,
                                                                     **config)
        self.assertIsNone(ret)
        self.assertEqual(send_raw_mock.call_count, 4)
        calls = [
            mock.call(task, '0x2c 0x41 0x04 0x00 0x00 0x02'),
            mock.call(task, '0x2c 0x41 0x04 0x00 0x01 0x02'),
            mock.call(task, '0x2c 0x41 0x04 0x00 0x02 0x02'),
            mock.call(task, '0x2c 0x41 0x04 0x00 0x03 0x02')
        ]
        send_raw_mock.assert_has_calls(calls)

    @mock.patch.object(ipmitool, "send_raw", spec_set=True,
                       autospec=True)
    def test_configure_intel_speedselect_error(self, send_raw_mock):
        send_raw_mock.side_effect = exception.IPMIFailure('err')
        config = {"intel_speedselect_config": "0x02", "socket_count": 1}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaisesRegex(
                exception.IPMIFailure,
                "Failed to set Intel SST-PP configuration",
                task.driver.management.configure_intel_speedselect,
                task, **config)

    def test_configure_intel_speedselect_invalid_input(self):
        config = {"intel_speedselect_config": "0", "socket_count": 1}
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(
                exception.InvalidParameterValue,
                task.driver.management.configure_intel_speedselect,
                task, **config)
        for value in (-1, None):
            config = {"intel_speedselect_config": "0x00",
                      "socket_count": value}
            with task_manager.acquire(self.context, self.node.uuid) as task:
                self.assertRaises(
                    exception.InvalidParameterValue,
                    task.driver.management.configure_intel_speedselect,
                    task, **config)
