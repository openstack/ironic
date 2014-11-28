# coding=utf-8

# Copyright 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2014 International Business Machines Corporation
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

import os
import stat
import tempfile
import time

import mock
from oslo.concurrency import processutils
from oslo.config import cfg

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import ipmitool as ipmi
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF

CONF.import_opt('min_command_interval',
                'ironic.drivers.modules.ipminative',
                group='ipmi')

INFO_DICT = db_utils.get_test_ipmi_info()

# BRIDGE_INFO_DICT will have all the bridging parameters appended
BRIDGE_INFO_DICT = INFO_DICT.copy()
BRIDGE_INFO_DICT.update(db_utils.get_test_ipmi_bridging_parameters())


class IPMIToolCheckOptionSupportedTestCase(base.TestCase):

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_timing_pass(self, mock_exc, mock_support):
        mock_exc.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('timing'),
                    mock.call('timing', True)]

        ipmi._check_option_support(['timing'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_timing_fail(self, mock_exc, mock_support):
        mock_exc.side_effect = processutils.ProcessExecutionError()
        mock_support.return_value = None
        expected = [mock.call('timing'),
                    mock.call('timing', False)]

        ipmi._check_option_support(['timing'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_timing_no_ipmitool(self, mock_exc, mock_support):
        mock_exc.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('timing')]

        self.assertRaises(OSError, ipmi._check_option_support, ['timing'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_single_bridge_pass(self, mock_exc, mock_support):
        mock_exc.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('single_bridge'),
                    mock.call('single_bridge', True)]

        ipmi._check_option_support(['single_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_single_bridge_fail(self, mock_exc, mock_support):
        mock_exc.side_effect = processutils.ProcessExecutionError()
        mock_support.return_value = None
        expected = [mock.call('single_bridge'),
                    mock.call('single_bridge', False)]

        ipmi._check_option_support(['single_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_single_bridge_no_ipmitool(self, mock_exc,
                                             mock_support):
        mock_exc.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('single_bridge')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['single_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_dual_bridge_pass(self, mock_exc, mock_support):
        mock_exc.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('dual_bridge'),
                    mock.call('dual_bridge', True)]

        ipmi._check_option_support(['dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_dual_bridge_fail(self, mock_exc, mock_support):
        mock_exc.side_effect = processutils.ProcessExecutionError()
        mock_support.return_value = None
        expected = [mock.call('dual_bridge'),
                    mock.call('dual_bridge', False)]

        ipmi._check_option_support(['dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_dual_bridge_no_ipmitool(self, mock_exc, mock_support):
        mock_exc.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('dual_bridge')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_all_options_pass(self, mock_exc, mock_support):
        mock_exc.return_value = (None, None)
        mock_support.return_value = None
        expected = [
            mock.call('timing'), mock.call('timing', True),
            mock.call('single_bridge'),
            mock.call('single_bridge', True),
            mock.call('dual_bridge'), mock.call('dual_bridge', True)]

        ipmi._check_option_support(['timing', 'single_bridge', 'dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_all_options_fail(self, mock_exc, mock_support):
        mock_exc.side_effect = processutils.ProcessExecutionError()
        mock_support.return_value = None
        expected = [
            mock.call('timing'), mock.call('timing', False),
            mock.call('single_bridge'),
            mock.call('single_bridge', False),
            mock.call('dual_bridge'),
            mock.call('dual_bridge', False)]

        ipmi._check_option_support(['timing', 'single_bridge', 'dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(utils, 'execute')
    def test_check_all_options_no_ipmitool(self, mock_exc, mock_support):
        mock_exc.side_effect = OSError()
        mock_support.return_value = None
        # exception is raised once ipmitool was not found for an command
        expected = [mock.call('timing')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['timing', 'single_bridge', 'dual_bridge'])
        self.assertTrue(mock_exc.called)
        self.assertEqual(expected, mock_support.call_args_list)


@mock.patch.object(time, 'sleep')
class IPMIToolPrivateMethodTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIToolPrivateMethodTestCase, self).setUp()
        self.node = obj_utils.get_test_node(
                self.context,
                driver='fake_ipmitool',
                driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    def test__make_password_file(self, mock_sleep):
        with ipmi._make_password_file(self.info.get('password')) as pw_file:
            del_chk_pw_file = pw_file
            self.assertTrue(os.path.isfile(pw_file))
            self.assertEqual(0o600, os.stat(pw_file)[stat.ST_MODE] & 0o777)
            with open(pw_file, "r") as f:
                password = f.read()
            self.assertEqual(self.info.get('password'), password)
        self.assertFalse(os.path.isfile(del_chk_pw_file))

    def test__parse_driver_info(self, mock_sleep):
        # make sure we get back the expected things
        _OPTIONS = ['address', 'username', 'password', 'uuid']
        for option in _OPTIONS:
            self.assertIsNotNone(self.info.get(option))

        info = dict(INFO_DICT)

        # test the default value for 'priv_level'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ret = ipmi._parse_driver_info(node)
        self.assertEqual('ADMINISTRATOR', ret['priv_level'])

        # ipmi_username / ipmi_password are not mandatory
        del info['ipmi_username']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ipmi._parse_driver_info(node)
        del info['ipmi_password']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ipmi._parse_driver_info(node)

        # make sure error is raised when ipmi_address is missing
        info = dict(INFO_DICT)
        del info['ipmi_address']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.MissingParameterValue,
                          ipmi._parse_driver_info,
                          node)

        # test the invalid priv_level value
        info = dict(INFO_DICT)
        info['ipmi_priv_level'] = 'ABCD'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info,
                          node)

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_invalid_bridging_type(self,
            mock_support, mock_sleep):
        info = BRIDGE_INFO_DICT.copy()
        # make sure error is raised when ipmi_bridging has unexpected value
        info['ipmi_bridging'] = 'junk'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info,
                          node)
        self.assertFalse(mock_support.called)

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_no_bridging(self,
            mock_support, mock_sleep):
        _OPTIONS = ['address', 'username', 'password', 'uuid']
        _BRIDGING_OPTIONS = ['local_address', 'transit_channel',
                             'transit_address',
                             'target_channel', 'target_address']
        info = BRIDGE_INFO_DICT.copy()
        info['ipmi_bridging'] = 'no'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=info)
        ret = ipmi._parse_driver_info(node)

        # ensure that _is_option_supported was not called
        self.assertFalse(mock_support.called)
        # check if we got all the required options
        for option in _OPTIONS:
            self.assertIsNotNone(ret[option])
        # test the default value for 'priv_level'
        self.assertEqual('ADMINISTRATOR', ret['priv_level'])

        # check if bridging parameters were set to None
        for option in _BRIDGING_OPTIONS:
            self.assertIsNone(ret[option])

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_dual_bridging_pass(self,
            mock_support, mock_sleep):
        _OPTIONS = ['address', 'username', 'password', 'uuid',
                    'local_address', 'transit_channel', 'transit_address',
                    'target_channel', 'target_address']
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=BRIDGE_INFO_DICT)

        expected = [mock.call('dual_bridge')]

        # test double bridging and make sure we get back expected result
        mock_support.return_value = True
        ret = ipmi._parse_driver_info(node)
        self.assertEqual(expected, mock_support.call_args_list)
        for option in _OPTIONS:
            self.assertIsNotNone(ret[option])
        # test the default value for 'priv_level'
        self.assertEqual('ADMINISTRATOR', ret['priv_level'])

        info = BRIDGE_INFO_DICT.copy()
        # ipmi_local_address / ipmi_username / ipmi_password are not mandatory
        for optional_arg in ['ipmi_local_address', 'ipmi_username',
                             'ipmi_password']:
            del info[optional_arg]
            node = obj_utils.get_test_node(self.context, driver_info=info)
            ipmi._parse_driver_info(node)
            self.assertEqual(mock.call('dual_bridge'), mock_support.call_args)

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_dual_bridging_not_supported(self,
            mock_support, mock_sleep):
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=BRIDGE_INFO_DICT)
        # if dual bridge is not supported then check if error is raised
        mock_support.return_value = False
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)
        mock_support.assert_called_once_with('dual_bridge')

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_dual_bridging_missing_parameters(self,
            mock_support, mock_sleep):
        info = BRIDGE_INFO_DICT.copy()
        mock_support.return_value = True
        # make sure error is raised when dual bridging is selected and the
        # required parameters for dual bridging are not provided
        for param in ['ipmi_transit_channel', 'ipmi_target_address',
                      'ipmi_transit_address', 'ipmi_target_channel']:
            del info[param]
            node = obj_utils.get_test_node(self.context, driver_info=info)
            self.assertRaises(exception.MissingParameterValue,
                              ipmi._parse_driver_info, node)
            self.assertEqual(mock.call('dual_bridge'),
                             mock_support.call_args)

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_single_bridging_pass(self,
            mock_support, mock_sleep):
        _OPTIONS = ['address', 'username', 'password', 'uuid',
                    'local_address', 'target_channel', 'target_address']

        info = BRIDGE_INFO_DICT.copy()
        info['ipmi_bridging'] = 'single'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=info)

        expected = [mock.call('single_bridge')]

        # test single bridging and make sure we get back expected things
        mock_support.return_value = True
        ret = ipmi._parse_driver_info(node)
        self.assertEqual(expected, mock_support.call_args_list)
        for option in _OPTIONS:
            self.assertIsNotNone(ret[option])
        # test the default value for 'priv_level'
        self.assertEqual('ADMINISTRATOR', ret['priv_level'])

        # check if dual bridge params are set to None
        self.assertIsNone(ret['transit_channel'])
        self.assertIsNone(ret['transit_address'])

        # ipmi_local_address / ipmi_username / ipmi_password are not mandatory
        for optional_arg in ['ipmi_local_address', 'ipmi_username',
                             'ipmi_password']:
            del info[optional_arg]
            node = obj_utils.get_test_node(self.context, driver_info=info)
            ipmi._parse_driver_info(node)
            self.assertEqual(mock.call('single_bridge'),
                             mock_support.call_args)

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_single_bridging_not_supported(self,
            mock_support, mock_sleep):
        info = BRIDGE_INFO_DICT.copy()
        info['ipmi_bridging'] = 'single'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=info)

        # if single bridge is not supported then check if error is raised
        mock_support.return_value = False
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)
        mock_support.assert_called_once_with('single_bridge')

    @mock.patch.object(ipmi, '_is_option_supported')
    def test__parse_driver_info_with_single_bridging_missing_parameters(
            self, mock_support, mock_sleep):
        info = dict(BRIDGE_INFO_DICT)
        info['ipmi_bridging'] = 'single'
        mock_support.return_value = True
        # make sure error is raised when single bridging is selected and the
        # required parameters for single bridging are not provided
        for param in ['ipmi_target_channel', 'ipmi_target_address']:
            del info[param]
            node = obj_utils.get_test_node(self.context, driver_info=info)
            self.assertRaises(exception.MissingParameterValue,
                              ipmi._parse_driver_info,
                              node)
            self.assertEqual(mock.call('single_bridge'),
                             mock_support.call_args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_first_call_to_address(self, mock_exec, mock_pwf,
            mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_pwf.assert_called_once_with(self.info['password'])
        mock_exec.assert_called_once_with(*args)
        self.assertFalse(mock_sleep.called)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_second_call_to_address_sleep(self, mock_exec,
            mock_pwf, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        pw_file_handle1 = tempfile.NamedTemporaryFile()
        pw_file1 = pw_file_handle1.name
        file_handle1 = open(pw_file1, "w")
        pw_file_handle2 = tempfile.NamedTemporaryFile()
        pw_file2 = pw_file_handle2.name
        file_handle2 = open(pw_file2, "w")
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle1,
            'A', 'B', 'C',
        ],
        [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle2,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_pwf.side_effect = iter([file_handle1, file_handle2])
        mock_exec.side_effect = iter([(None, None), (None, None)])

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])

        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertTrue(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_second_call_to_address_no_sleep(self, mock_exec,
            mock_pwf, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        pw_file_handle1 = tempfile.NamedTemporaryFile()
        pw_file1 = pw_file_handle1.name
        file_handle1 = open(pw_file1, "w")
        pw_file_handle2 = tempfile.NamedTemporaryFile()
        pw_file2 = pw_file_handle2.name
        file_handle2 = open(pw_file2, "w")
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle1,
            'A', 'B', 'C',
        ],
        [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle2,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_pwf.side_effect = iter([file_handle1, file_handle2])
        mock_exec.side_effect = iter([(None, None), (None, None)])

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])
        # act like enough time has passed
        ipmi.LAST_CMD_TIME[self.info['address']] = (time.time() -
                CONF.ipmi.min_command_interval)
        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertFalse(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_two_calls_to_diff_address(self, mock_exec,
            mock_pwf, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        pw_file_handle1 = tempfile.NamedTemporaryFile()
        pw_file1 = pw_file_handle1.name
        file_handle1 = open(pw_file1, "w")
        pw_file_handle2 = tempfile.NamedTemporaryFile()
        pw_file2 = pw_file_handle2.name
        file_handle2 = open(pw_file2, "w")
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle1,
            'A', 'B', 'C',
        ],
        [
            'ipmitool',
            '-I', 'lanplus',
            '-H', '127.127.127.127',
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle2,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_pwf.side_effect = iter([file_handle1, file_handle2])
        mock_exec.side_effect = iter([(None, None), (None, None)])

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])
        self.info['address'] = '127.127.127.127'
        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertFalse(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_without_timing(self, mock_exec, mock_pwf,
            mock_support, mock_sleep):
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")

        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_pwf.assert_called_once_with(self.info['password'])
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_timing(self, mock_exec, mock_pwf,
            mock_support, mock_sleep):
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-R', '12',
            '-N', '5',
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        mock_support.return_value = True
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_pwf.assert_called_once_with(self.info['password'])
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_without_username(self, mock_exec, mock_pwf,
            mock_support, mock_sleep):
        self.info['username'] = None
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        self.assertTrue(mock_pwf.called)
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_dual_bridging(self,
                                               mock_exec, mock_pwf,
                                               mock_support,
                                               mock_sleep):

        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=BRIDGE_INFO_DICT)
        # when support for dual bridge command is called returns True
        mock_support.return_value = True
        info = ipmi._parse_driver_info(node)
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', info['address'],
            '-L', info['priv_level'],
            '-U', info['username'],
            '-m', info['local_address'],
            '-B', info['transit_channel'],
            '-T', info['transit_address'],
            '-b', info['target_channel'],
            '-t', info['target_address'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        expected = [mock.call('dual_bridge'),
                    mock.call('timing')]
        # When support for timing command is called returns False
        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(info, 'A B C')
        self.assertEqual(expected, mock_support.call_args_list)
        self.assertTrue(mock_pwf.called)
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_single_bridging(self,
                                                 mock_exec, mock_pwf,
                                                 mock_support,
                                                 mock_sleep):
        single_bridge_info = dict(BRIDGE_INFO_DICT)
        single_bridge_info['ipmi_bridging'] = 'single'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=single_bridge_info)
        # when support for single bridge command is called returns True
        mock_support.return_value = True
        info = ipmi._parse_driver_info(node)
        info['transit_channel'] = info['transit_address'] = None

        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', info['address'],
            '-L', info['priv_level'],
            '-U', info['username'],
            '-m', info['local_address'],
            '-b', info['target_channel'],
            '-t', info['target_address'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        expected = [mock.call('single_bridge'),
                    mock.call('timing')]
        # When support for timing command is called returns False
        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(info, 'A B C')
        self.assertEqual(expected, mock_support.call_args_list)
        self.assertTrue(mock_pwf.called)
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported')
    @mock.patch.object(ipmi, '_make_password_file', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_exception(self, mock_exec, mock_pwf,
            mock_support, mock_sleep):
        pw_file_handle = tempfile.NamedTemporaryFile()
        pw_file = pw_file_handle.name
        file_handle = open(pw_file, "w")
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', file_handle,
            'A', 'B', 'C',
            ]

        mock_support.return_value = False
        mock_pwf.return_value = file_handle
        mock_exec.side_effect = processutils.ProcessExecutionError("x")
        self.assertRaises(processutils.ProcessExecutionError,
                          ipmi._exec_ipmitool,
                          self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        mock_pwf.assert_called_once_with(self.info['password'])
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__power_status_on(self, mock_exec, mock_sleep):
        mock_exec.return_value = ["Chassis Power is on\n", None]

        state = ipmi._power_status(self.info)

        mock_exec.assert_called_once_with(self.info, "power status")
        self.assertEqual(states.POWER_ON, state)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__power_status_off(self, mock_exec, mock_sleep):
        mock_exec.return_value = ["Chassis Power is off\n", None]

        state = ipmi._power_status(self.info)

        mock_exec.assert_called_once_with(self.info, "power status")
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__power_status_error(self, mock_exec, mock_sleep):
        mock_exec.return_value = ["Chassis Power is badstate\n", None]

        state = ipmi._power_status(self.info)

        mock_exec.assert_called_once_with(self.info, "power status")
        self.assertEqual(states.ERROR, state)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__power_status_exception(self, mock_exec, mock_sleep):
        mock_exec.side_effect = processutils.ProcessExecutionError("error")
        self.assertRaises(exception.IPMIFailure,
                          ipmi._power_status,
                          self.info)
        mock_exec.assert_called_once_with(self.info, "power status")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    @mock.patch('eventlet.greenthread.sleep')
    def test__power_on_max_retries(self, sleep_mock, mock_exec, mock_sleep):
        self.config(retry_timeout=2, group='ipmi')

        def side_effect(driver_info, command):
            resp_dict = {"power status": ["Chassis Power is off\n", None],
                         "power on": [None, None]}
            return resp_dict.get(command, ["Bad\n", None])

        mock_exec.side_effect = side_effect

        expected = [mock.call(self.info, "power on"),
                    mock.call(self.info, "power status"),
                    mock.call(self.info, "power status")]

        state = ipmi._power_on(self.info)

        self.assertEqual(mock_exec.call_args_list, expected)
        self.assertEqual(states.ERROR, state)


class IPMIToolDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIToolDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_ipmitool")
        self.driver = driver_factory.get_driver("fake_ipmitool")

        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ipmitool',
                                               driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    def test_get_properties(self):
        expected = ipmi.COMMON_PROPERTIES
        self.assertEqual(expected, self.driver.power.get_properties())

        expected = list(ipmi.COMMON_PROPERTIES) + list(ipmi.CONSOLE_PROPERTIES)
        self.assertEqual(sorted(expected),
                         sorted(self.driver.console.get_properties().keys()))
        self.assertEqual(sorted(expected),
                         sorted(self.driver.get_properties().keys()))

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_get_power_state(self, mock_exec):
        returns = iter([["Chassis Power is off\n", None],
                        ["Chassis Power is on\n", None],
                        ["\n", None]])
        expected = [mock.call(self.info, "power status"),
                    mock.call(self.info, "power status"),
                    mock.call(self.info, "power status")]
        mock_exec.side_effect = returns

        with task_manager.acquire(self.context, self.node.uuid) as task:
            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_OFF, pstate)

            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.POWER_ON, pstate)

            pstate = self.driver.power.get_power_state(task)
            self.assertEqual(states.ERROR, pstate)

        self.assertEqual(mock_exec.call_args_list, expected)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_get_power_state_exception(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError("error")
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.power.get_power_state,
                              task)
        mock_exec.assert_called_once_with(self.info, "power status")

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.return_value = states.POWER_ON
        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_ON)

        mock_on.assert_called_once_with(self.info)
        self.assertFalse(mock_off.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_off_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_OFF)

        mock_off.assert_called_once_with(self.info)
        self.assertFalse(mock_on.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_fail(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.return_value = states.ERROR
        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.set_power_state,
                              task,
                              states.POWER_ON)

        mock_on.assert_called_once_with(self.info)
        self.assertFalse(mock_off.called)

    def test_set_power_invalid_state(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.power.set_power_state,
                    task,
                    "fake state")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__send_raw_bytes_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.vendor.send_raw(task, http_method='POST',
                                        raw_bytes='0x00 0x01')

        mock_exec.assert_called_once_with(self.info, 'raw 0x00 0x01')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__send_raw_bytes_fail(self, mock_exec):
        mock_exec.side_effect = exception.PasswordFileFailedToCreate('error')

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.vendor.send_raw,
                              task,
                              http_method='POST',
                              raw_bytes='0x00 0x01')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.vendor.bmc_reset(task, 'POST')

        mock_exec.assert_called_once_with(self.info, 'bmc reset warm')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_cold(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.vendor.bmc_reset(task, 'POST', warm=False)

        mock_exec.assert_called_once_with(self.info, 'bmc reset cold')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_fail(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError()

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.vendor.bmc_reset,
                              task, 'POST')

    @mock.patch.object(ipmi, '_power_off', autospec=False)
    @mock.patch.object(ipmi, '_power_on', autospec=False)
    def test_reboot_ok(self, mock_on, mock_off):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_on.return_value = states.POWER_ON
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')
        expected = [mock.call.power_off(self.info),
                    mock.call.power_on(self.info)]

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.reboot(task)

        self.assertEqual(manager.mock_calls, expected)

    @mock.patch.object(ipmi, '_power_off', autospec=False)
    @mock.patch.object(ipmi, '_power_on', autospec=False)
    def test_reboot_fail(self, mock_on, mock_off):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_on.return_value = states.ERROR
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')
        expected = [mock.call.power_off(self.info),
                    mock.call.power_on(self.info)]

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.reboot,
                              task)

        self.assertEqual(manager.mock_calls, expected)

    @mock.patch.object(ipmi, '_parse_driver_info')
    def test_vendor_passthru_validate__parse_driver_info_fail(self, info_mock):
        info_mock.side_effect = exception.InvalidParameterValue("bad")
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.vendor.validate,
                              task, method='send_raw', raw_bytes='0x00 0x01')
            info_mock.assert_called_once_with(task.node)

    def test_vendor_passthru_validate__send_raw_bytes_good(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.driver.vendor.validate(task,
                                        method='send_raw',
                                        http_method='POST',
                                        raw_bytes='0x00 0x01')

    def test_vendor_passthru_validate__send_raw_bytes_fail(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.vendor.validate,
                              task, method='send_raw')

    @mock.patch.object(ipmi.VendorPassthru, 'send_raw')
    def test_vendor_passthru_call_send_raw_bytes(self, raw_bytes_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.driver.vendor.send_raw(task, http_method='POST',
                                        raw_bytes='0x00 0x01')
            raw_bytes_mock.assert_called_once_with(task, http_method='POST',
                                                   raw_bytes='0x00 0x01')

    def test_vendor_passthru_validate__bmc_reset_good(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset')

    def test_vendor_passthru_validate__bmc_reset_warm_good(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset',
                                        warm=True)

    def test_vendor_passthru_validate__bmc_reset_cold_good(self):
        with task_manager.acquire(self.context, self.node['uuid']) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset',
                                        warm=False)

    @mock.patch.object(ipmi.VendorPassthru, 'bmc_reset')
    def test_vendor_passthru_call_bmc_reset_warm(self, bmc_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.driver.vendor.bmc_reset(task, 'POST', warm=True)
            bmc_mock.assert_called_once_with(task, 'POST', warm=True)

    @mock.patch.object(ipmi.VendorPassthru, 'bmc_reset')
    def test_vendor_passthru_call_bmc_reset_cold(self, bmc_mock):
        with task_manager.acquire(self.context, self.node['uuid'],
                                  shared=False) as task:
            self.driver.vendor.bmc_reset(task, 'POST', warm=False)
            bmc_mock.assert_called_once_with(task, 'POST', warm=False)

    def test_vendor_passthru_vendor_routes(self):
        expected = ['send_raw', 'bmc_reset']
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            vendor_routes = task.driver.vendor.vendor_routes
            self.assertIsInstance(vendor_routes, dict)
            self.assertEqual(sorted(expected), sorted(vendor_routes))

    def test_vendor_passthru_driver_routes(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_routes = task.driver.vendor.driver_routes
            self.assertIsInstance(driver_routes, dict)
            self.assertEqual({}, driver_routes)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console(self, mock_exec):
        mock_exec.return_value = None

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.console.start_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'],
                                          self.info['port'],
                                          mock.ANY)
        self.assertTrue(mock_exec.called)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail(self, mock_exec):
        mock_exec.side_effect = exception.ConsoleSubprocessFailed(
                error='error')

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console.start_console,
                              task)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test_start_console_fail_nodir(self, mock_exec):
        mock_exec.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.start_console,
                              task)
        mock_exec.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_exec):
        mock_exec.return_value = None

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.console.stop_console(task)

        mock_exec.assert_called_once_with(self.info['uuid'])
        self.assertTrue(mock_exec.called)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console_fail(self, mock_stop):
        mock_stop.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.stop_console,
                              task)

        mock_stop.assert_called_once_with(self.node.uuid)

    @mock.patch.object(console_utils, 'get_shellinabox_console_url',
                       utospec=True)
    def test_get_console(self, mock_exec):
        url = 'http://localhost:4201'
        mock_exec.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_exec.assert_called_once_with(self.info['port'])
        self.assertTrue(mock_exec.called)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)

        mock_calls = [mock.call(self.info, "raw 0x00 0x08 0x03 0x08"),
                      mock.call(self.info, "chassis bootdev pxe")]
        mock_exec.assert_has_calls(mock_calls)

    def test_management_interface_set_boot_device_bad_device(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                    self.driver.management.set_boot_device,
                    task, 'fake-device')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_exec_failed(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError()
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                    self.driver.management.set_boot_device,
                    task, boot_devices.PXE)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_unknown_exception(self,
            mock_exec):

        class FakeException(Exception):
            pass

        mock_exec.side_effect = FakeException('boom')
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(FakeException,
                    self.driver.management.set_boot_device,
                    task, boot_devices.PXE)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM, boot_devices.BIOS,
                        boot_devices.SAFE]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices()))

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_get_boot_device(self, mock_exec):
        # output, expected boot device
        bootdevs = [('Boot Device Selector : '
                     'Force Boot from default Hard-Drive\n',
                     boot_devices.DISK),
                    ('Boot Device Selector : '
                     'Force Boot from default Hard-Drive, request Safe-Mode\n',
                     boot_devices.SAFE),
                    ('Boot Device Selector : '
                     'Force Boot into BIOS Setup\n',
                     boot_devices.BIOS),
                    ('Boot Device Selector : '
                     'Force PXE\n',
                     boot_devices.PXE),
                    ('Boot Device Selector : '
                     'Force Boot from CD/DVD\n',
                     boot_devices.CDROM)]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            for out, expected_device in bootdevs:
                mock_exec.return_value = (out, '')
                expected_response = {'boot_device': expected_device,
                                     'persistent': False}
                self.assertEqual(expected_response,
                                 task.driver.management.get_boot_device(task))
                mock_exec.assert_called_with(mock.ANY,
                                             "chassis bootparam get 5")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_get_boot_device_unknown_dev(self, mock_exec):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_exec.return_value = ('Boot Device Selector : Fake\n', '')
            response = task.driver.management.get_boot_device(task)
            self.assertIsNone(response['boot_device'])
            mock_exec.assert_called_with(mock.ANY, "chassis bootparam get 5")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_get_boot_device_fail(self, mock_exec):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_exec.side_effect = processutils.ProcessExecutionError()
            self.assertRaises(exception.IPMIFailure,
                              task.driver.management.get_boot_device, task)
            mock_exec.assert_called_with(mock.ANY, "chassis bootparam get 5")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_get_boot_device_persistent(self, mock_exec):
        outputs = [('Options apply to only next boot\n'
                    'Boot Device Selector : Force PXE\n',
                    False),
                    ('Options apply to all future boots\n'
                    'Boot Device Selector : Force PXE\n',
                    True)]
        with task_manager.acquire(self.context, self.node.uuid) as task:
            for out, expected_persistent in outputs:
                mock_exec.return_value = (out, '')
                expected_response = {'boot_device': boot_devices.PXE,
                                     'persistent': expected_persistent}
                self.assertEqual(expected_response,
                                 task.driver.management.get_boot_device(task))
                mock_exec.assert_called_with(mock.ANY,
                                             "chassis bootparam get 5")

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing IPMI driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=utils.generate_uuid(),
                                          driver='fake_ipmitool')
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    def test__parse_ipmi_sensor_data_ok(self):
        fake_sensors_data = """
                            Sensor ID              : Temp (0x1)
                             Entity ID             : 3.1 (Processor)
                             Sensor Type (Analog)  : Temperature
                             Sensor Reading        : -58 (+/- 1) degrees C
                             Status                : ok
                             Nominal Reading       : 50.000
                             Normal Minimum        : 11.000
                             Normal Maximum        : 69.000
                             Upper critical        : 90.000
                             Upper non-critical    : 85.000
                             Positive Hysteresis   : 1.000
                             Negative Hysteresis   : 1.000

                            Sensor ID              : Temp (0x2)
                             Entity ID             : 3.2 (Processor)
                             Sensor Type (Analog)  : Temperature
                             Sensor Reading        : 50 (+/- 1) degrees C
                             Status                : ok
                             Nominal Reading       : 50.000
                             Normal Minimum        : 11.000
                             Normal Maximum        : 69.000
                             Upper critical        : 90.000
                             Upper non-critical    : 85.000
                             Positive Hysteresis   : 1.000
                             Negative Hysteresis   : 1.000

                            Sensor ID              : FAN MOD 1A RPM (0x30)
                             Entity ID             : 7.1 (System Board)
                             Sensor Type (Analog)  : Fan
                             Sensor Reading        : 8400 (+/- 75) RPM
                             Status                : ok
                             Nominal Reading       : 5325.000
                             Normal Minimum        : 10425.000
                             Normal Maximum        : 14775.000
                             Lower critical        : 4275.000
                             Positive Hysteresis   : 375.000
                             Negative Hysteresis   : 375.000

                            Sensor ID              : FAN MOD 1B RPM (0x31)
                             Entity ID             : 7.1 (System Board)
                             Sensor Type (Analog)  : Fan
                             Sensor Reading        : 8550 (+/- 75) RPM
                             Status                : ok
                             Nominal Reading       : 7800.000
                             Normal Minimum        : 10425.000
                             Normal Maximum        : 14775.000
                             Lower critical        : 4275.000
                             Positive Hysteresis   : 375.000
                             Negative Hysteresis   : 375.000
                             """
        expected_return = {
                             'Fan': {
                                 'FAN MOD 1A RPM (0x30)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '8400 (+/- 75) RPM',
                                     'Entity ID': '7.1 (System Board)',
                                     'Normal Minimum': '10425.000',
                                     'Positive Hysteresis': '375.000',
                                     'Normal Maximum': '14775.000',
                                     'Sensor Type (Analog)': 'Fan',
                                     'Lower critical': '4275.000',
                                     'Negative Hysteresis': '375.000',
                                     'Sensor ID': 'FAN MOD 1A RPM (0x30)',
                                     'Nominal Reading': '5325.000'
                                 },
                                 'FAN MOD 1B RPM (0x31)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '8550 (+/- 75) RPM',
                                     'Entity ID': '7.1 (System Board)',
                                     'Normal Minimum': '10425.000',
                                     'Positive Hysteresis': '375.000',
                                     'Normal Maximum': '14775.000',
                                     'Sensor Type (Analog)': 'Fan',
                                     'Lower critical': '4275.000',
                                     'Negative Hysteresis': '375.000',
                                     'Sensor ID': 'FAN MOD 1B RPM (0x31)',
                                     'Nominal Reading': '7800.000'
                                 }
                             },
                             'Temperature': {
                                 'Temp (0x1)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '-58 (+/- 1) degrees C',
                                     'Entity ID': '3.1 (Processor)',
                                     'Normal Minimum': '11.000',
                                     'Positive Hysteresis': '1.000',
                                     'Upper non-critical': '85.000',
                                     'Normal Maximum': '69.000',
                                     'Sensor Type (Analog)': 'Temperature',
                                     'Negative Hysteresis': '1.000',
                                     'Upper critical': '90.000',
                                     'Sensor ID': 'Temp (0x1)',
                                     'Nominal Reading': '50.000'
                                 },
                                 'Temp (0x2)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '50 (+/- 1) degrees C',
                                     'Entity ID': '3.2 (Processor)',
                                     'Normal Minimum': '11.000',
                                     'Positive Hysteresis': '1.000',
                                     'Upper non-critical': '85.000',
                                     'Normal Maximum': '69.000',
                                     'Sensor Type (Analog)': 'Temperature',
                                     'Negative Hysteresis': '1.000',
                                     'Upper critical': '90.000',
                                     'Sensor ID': 'Temp (0x2)',
                                     'Nominal Reading': '50.000'
                                 }
                             }
                          }
        ret = ipmi._parse_ipmi_sensors_data(self.node, fake_sensors_data)

        self.assertEqual(expected_return, ret)

    def test__parse_ipmi_sensor_data_missing_sensor_reading(self):
        fake_sensors_data = """
                            Sensor ID              : Temp (0x1)
                             Entity ID             : 3.1 (Processor)
                             Sensor Type (Analog)  : Temperature
                             Status                : ok
                             Nominal Reading       : 50.000
                             Normal Minimum        : 11.000
                             Normal Maximum        : 69.000
                             Upper critical        : 90.000
                             Upper non-critical    : 85.000
                             Positive Hysteresis   : 1.000
                             Negative Hysteresis   : 1.000

                            Sensor ID              : Temp (0x2)
                             Entity ID             : 3.2 (Processor)
                             Sensor Type (Analog)  : Temperature
                             Sensor Reading        : 50 (+/- 1) degrees C
                             Status                : ok
                             Nominal Reading       : 50.000
                             Normal Minimum        : 11.000
                             Normal Maximum        : 69.000
                             Upper critical        : 90.000
                             Upper non-critical    : 85.000
                             Positive Hysteresis   : 1.000
                             Negative Hysteresis   : 1.000

                            Sensor ID              : FAN MOD 1A RPM (0x30)
                             Entity ID             : 7.1 (System Board)
                             Sensor Type (Analog)  : Fan
                             Sensor Reading        : 8400 (+/- 75) RPM
                             Status                : ok
                             Nominal Reading       : 5325.000
                             Normal Minimum        : 10425.000
                             Normal Maximum        : 14775.000
                             Lower critical        : 4275.000
                             Positive Hysteresis   : 375.000
                             Negative Hysteresis   : 375.000
                             """
        expected_return = {
                             'Fan': {
                                 'FAN MOD 1A RPM (0x30)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '8400 (+/- 75) RPM',
                                     'Entity ID': '7.1 (System Board)',
                                     'Normal Minimum': '10425.000',
                                     'Positive Hysteresis': '375.000',
                                     'Normal Maximum': '14775.000',
                                     'Sensor Type (Analog)': 'Fan',
                                     'Lower critical': '4275.000',
                                     'Negative Hysteresis': '375.000',
                                     'Sensor ID': 'FAN MOD 1A RPM (0x30)',
                                     'Nominal Reading': '5325.000'
                                  }
                             },
                             'Temperature': {
                                 'Temp (0x2)': {
                                     'Status': 'ok',
                                     'Sensor Reading': '50 (+/- 1) degrees C',
                                     'Entity ID': '3.2 (Processor)',
                                     'Normal Minimum': '11.000',
                                     'Positive Hysteresis': '1.000',
                                     'Upper non-critical': '85.000',
                                     'Normal Maximum': '69.000',
                                     'Sensor Type (Analog)': 'Temperature',
                                     'Negative Hysteresis': '1.000',
                                     'Upper critical': '90.000',
                                     'Sensor ID': 'Temp (0x2)',
                                     'Nominal Reading': '50.000'
                                 }
                             }
                          }
        ret = ipmi._parse_ipmi_sensors_data(self.node, fake_sensors_data)

        self.assertEqual(expected_return, ret)

    def test__parse_ipmi_sensor_data_failed(self):
        fake_sensors_data = "abcdef"
        self.assertRaises(exception.FailedToParseSensorData,
                          ipmi._parse_ipmi_sensors_data,
                          self.node,
                          fake_sensors_data)

        fake_sensors_data = "abc:def:ghi"
        self.assertRaises(exception.FailedToParseSensorData,
                          ipmi._parse_ipmi_sensors_data,
                          self.node,
                          fake_sensors_data)
