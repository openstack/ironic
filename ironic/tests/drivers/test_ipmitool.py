# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
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

"""Test class for IPMITool driver module."""

import mock
import os
import stat

from oslo.config import cfg

from ironic.openstack.common import jsonutils as json

from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.db import api as db_api
from ironic.drivers.modules import ipmitool as ipmi
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils

CONF = cfg.CONF

INFO_DICT = json.loads(db_utils.ipmi_info)


class IPMIToolPrivateMethodTestCase(base.TestCase):

    def setUp(self):
        super(IPMIToolPrivateMethodTestCase, self).setUp()
        self.node = db_utils.get_test_node(
                driver='fake_ipmitool',
                driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    def test__make_password_file(self):
        with ipmi._make_password_file(self.info.get('password')) as pw_file:
            del_chk_pw_file = pw_file
            self.assertTrue(os.path.isfile(pw_file))
            self.assertEqual(os.stat(pw_file)[stat.ST_MODE] & 0o777, 0o600)
            with open(pw_file, "r") as f:
                password = f.read()
            self.assertEqual(password, self.info.get('password'))
        self.assertFalse(os.path.isfile(del_chk_pw_file))

    def test__parse_driver_info(self):
        # make sure we get back the expected things
        self.assertIsNotNone(self.info.get('address'))
        self.assertIsNotNone(self.info.get('username'))
        self.assertIsNotNone(self.info.get('password'))
        self.assertIsNotNone(self.info.get('uuid'))

        # make sure error is raised when info, eg. username, is missing
        info = dict(INFO_DICT)
        del info['ipmi_username']

        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info,
                          node)

    def test__exec_ipmitool(self):
        pw_file = '/tmp/password_file'
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-U', self.info['username'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        with mock.patch.object(ipmi, '_make_password_file',
                               autospec=True) as mock_pwf:
            mock_pwf.return_value = file_handle
            with mock.patch.object(utils, 'execute',
                                   autospec=True) as mock_exec:
                mock_exec.return_value = (None, None)

                ipmi._exec_ipmitool(self.info, 'A B C')

                mock_pwf.assert_called_once_with(self.info['password'])
                mock_exec.assert_called_once_with(*args, attempts=3)

    def test__power_status_on(self):
        with mock.patch.object(ipmi, '_exec_ipmitool',
                               autospec=True) as mock_exec:
            mock_exec.return_value = ["Chassis Power is on\n", None]

            state = ipmi._power_status(self.info)

            mock_exec.assert_called_once_with(self.info, "power status")
            self.assertEqual(state, states.POWER_ON)

    def test__power_status_off(self):
        with mock.patch.object(ipmi, '_exec_ipmitool',
                               autospec=True) as mock_exec:
            mock_exec.return_value = ["Chassis Power is off\n", None]

            state = ipmi._power_status(self.info)

            mock_exec.assert_called_once_with(self.info, "power status")
            self.assertEqual(state, states.POWER_OFF)

    def test__power_status_error(self):
        with mock.patch.object(ipmi, '_exec_ipmitool',
                               autospec=True) as mock_exec:
            mock_exec.return_value = ["Chassis Power is badstate\n", None]

            state = ipmi._power_status(self.info)

            mock_exec.assert_called_once_with(self.info, "power status")
            self.assertEqual(state, states.ERROR)

    def test__power_on_max_retries(self):
        self.config(ipmi_power_retry=2)

        def side_effect(driver_info, command):
            resp_dict = {"power status": ["Chassis Power is off\n", None],
                         "power on": [None, None]}
            return resp_dict.get(command, ["Bad\n", None])

        with mock.patch.object(ipmi, '_exec_ipmitool',
                               autospec=True) as mock_exec:
            mock_exec.side_effect = side_effect

            expected = [mock.call(self.info, "power status"),
                        mock.call(self.info, "power on"),
                        mock.call(self.info, "power status"),
                        mock.call(self.info, "power status"),
                        mock.call(self.info, "power status")]

            state = ipmi._power_on(self.info)

            self.assertEqual(mock_exec.call_args_list, expected)
            self.assertEqual(state, states.ERROR)


class IPMIToolDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIToolDriverTestCase, self).setUp()
        self.dbapi = db_api.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager(driver='fake_ipmitool')

        self.node = db_utils.get_test_node(
                driver='fake_ipmitool',
                driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)
        self.dbapi.create_node(self.node)

    def test_get_power_state(self):
        returns = [["Chassis Power is off\n", None],
                   ["Chassis Power is on\n", None],
                   ["\n", None]]
        expected = [mock.call(self.info, "power status"),
                    mock.call(self.info, "power status"),
                    mock.call(self.info, "power status")]
        with mock.patch.object(ipmi, '_exec_ipmitool', side_effect=returns,
                               autospec=True) as mock_exec:

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(pstate, states.POWER_OFF)

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(pstate, states.POWER_ON)

            pstate = self.driver.power.get_power_state(None, self.node)
            self.assertEqual(pstate, states.ERROR)

            self.assertEqual(mock_exec.call_args_list, expected)

    def test_set_power_on_ok(self):
        self.config(ipmi_power_retry=0)

        with mock.patch.object(ipmi, '_power_on', autospec=True) as mock_on:
            mock_on.return_value = states.POWER_ON
            with mock.patch.object(ipmi, '_power_off',
                                   autospec=True) as mock_off:

                with task_manager.acquire([self.node['uuid']]) as task:
                    self.driver.power.set_power_state(
                            task, self.node, states.POWER_ON)

                mock_on.assert_called_once_with(self.info)
                self.assertFalse(mock_off.called)

    def test_set_power_off_ok(self):
        self.config(ipmi_power_retry=0)

        with mock.patch.object(ipmi, '_power_on', autospec=True) as mock_on:
            with mock.patch.object(ipmi, '_power_off',
                                   autospec=True) as mock_off:
                mock_off.return_value = states.POWER_OFF

                with task_manager.acquire([self.node['uuid']]) as task:
                    self.driver.power.set_power_state(
                            task, self.node, states.POWER_OFF)

                mock_off.assert_called_once_with(self.info)
                self.assertFalse(mock_on.called)

    def test_set_power_on_fail(self):
        self.config(ipmi_power_retry=0)

        with mock.patch.object(ipmi, '_power_on', autospec=True) as mock_on:
            mock_on.return_value = states.ERROR
            with mock.patch.object(ipmi, '_power_off',
                                   autospec=True) as mock_off:

                with task_manager.acquire([self.node['uuid']]) as task:
                    self.assertRaises(exception.PowerStateFailure,
                            self.driver.power.set_power_state,
                            task,
                            self.node,
                            states.POWER_ON)

                mock_on.assert_called_once_with(self.info)
                self.assertFalse(mock_off.called)

    def test_set_power_invalid_state(self):
        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.IronicException,
                    self.driver.power.set_power_state,
                    task,
                    self.node,
                    "fake state")

    def test_set_boot_device_ok(self):
        with mock.patch.object(ipmi, '_exec_ipmitool',
                               autospec=True) as mock_exec:
            mock_exec.return_value = [None, None]

            with task_manager.acquire([self.node['uuid']]) as task:
                self.driver.power._set_boot_device(task, self.node, 'pxe')

            mock_exec.assert_called_once_with(self.info, "chassis bootdev pxe")

    def test_set_boot_device_bad_device(self):
        with task_manager.acquire([self.node['uuid']]) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.power._set_boot_device,
                    task,
                    self.node,
                    'fake-device')

    def test_reboot_ok(self):
        manager = mock.MagicMock()
        #NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        with mock.patch.object(ipmi, '_power_off', autospec=False) as mock_off:
            with mock.patch.object(ipmi, '_power_on',
                                   autospec=False) as mock_on:
                mock_on.return_value = states.POWER_ON
                manager.attach_mock(mock_off, 'power_off')
                manager.attach_mock(mock_on, 'power_on')
                expected = [mock.call.power_off(self.info),
                            mock.call.power_on(self.info)]

                with task_manager.acquire([self.node['uuid']]) as task:
                    self.driver.power.reboot(task, self.node)

                self.assertEqual(manager.mock_calls, expected)

    def test_reboot_fail(self):
        manager = mock.MagicMock()
        #NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        with mock.patch.object(ipmi, '_power_off', autospec=False) as mock_off:
            with mock.patch.object(ipmi, '_power_on',
                                   autospec=False) as mock_on:
                mock_on.return_value = states.ERROR
                manager.attach_mock(mock_off, 'power_off')
                manager.attach_mock(mock_on, 'power_on')
                expected = [mock.call.power_off(self.info),
                            mock.call.power_on(self.info)]

                with task_manager.acquire([self.node['uuid']]) as task:
                    self.assertRaises(exception.PowerStateFailure,
                            self.driver.power.reboot,
                            task,
                            self.node)

                self.assertEqual(manager.mock_calls, expected)
