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
#

"""Test class for IPMITool driver module."""

import contextlib
import os
import random
import stat
import subprocess
import tempfile
import time
import types

from ironic_lib import utils as ironic_utils
import mock
from oslo_concurrency import processutils
from oslo_utils import uuidutils
import six

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils
from ironic.conductor import task_manager
import ironic.conf
from ironic.drivers.modules import console_utils
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import ipmitool as ipmi
from ironic.drivers import utils as driver_utils
from ironic.tests import base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = ironic.conf.CONF

INFO_DICT = db_utils.get_test_ipmi_info()

# BRIDGE_INFO_DICT will have all the bridging parameters appended
BRIDGE_INFO_DICT = INFO_DICT.copy()
BRIDGE_INFO_DICT.update(db_utils.get_test_ipmi_bridging_parameters())


class IPMIToolCheckInitTestCase(base.TestCase):

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_power_init_calls(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        ipmi.IPMIPower()
        mock_support.assert_called_with(mock.ANY)
        mock_check_dir.assert_called_once_with()

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_power_init_calls_raises_1(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        mock_check_dir.side_effect = exception.PathNotFound(dir="foo_dir")
        self.assertRaises(exception.PathNotFound, ipmi.IPMIPower)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_power_init_calls_raises_2(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        mock_check_dir.side_effect = exception.DirectoryNotWritable(
            dir="foo_dir")
        self.assertRaises(exception.DirectoryNotWritable, ipmi.IPMIPower)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_power_init_calls_raises_3(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        mock_check_dir.side_effect = exception.InsufficientDiskSpace(
            path="foo_dir", required=1, actual=0)
        self.assertRaises(exception.InsufficientDiskSpace, ipmi.IPMIPower)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_power_init_calls_already_checked(self,
                                              mock_check_dir,
                                              mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = True
        ipmi.IPMIPower()
        mock_support.assert_called_with(mock.ANY)
        self.assertFalse(mock_check_dir.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_management_init_calls(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None

        ipmi.IPMIManagement()
        mock_support.assert_called_with(mock.ANY)
        mock_check_dir.assert_called_once_with()

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_management_init_calls_already_checked(self,
                                                   mock_check_dir,
                                                   mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = False

        ipmi.IPMIManagement()
        mock_support.assert_called_with(mock.ANY)
        self.assertFalse(mock_check_dir.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_vendor_passthru_init_calls(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        ipmi.VendorPassthru()
        mock_support.assert_called_with(mock.ANY)
        mock_check_dir.assert_called_once_with()

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_vendor_passthru_init_calls_already_checked(self,
                                                        mock_check_dir,
                                                        mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = True
        ipmi.VendorPassthru()
        mock_support.assert_called_with(mock.ANY)
        self.assertFalse(mock_check_dir.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_console_init_calls(self, mock_check_dir, mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = None
        ipmi.IPMIShellinaboxConsole()
        mock_support.assert_called_with(mock.ANY)
        mock_check_dir.assert_called_once_with()

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_console_init_calls_already_checked(self,
                                                mock_check_dir,
                                                mock_support):
        mock_support.return_value = True
        ipmi.TMP_DIR_CHECKED = True
        ipmi.IPMIShellinaboxConsole()
        mock_support.assert_called_with(mock.ANY)
        self.assertFalse(mock_check_dir.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_console_init_calls_for_socat(self, mock_check_dir, mock_support):
        with mock.patch.object(ipmi, 'TMP_DIR_CHECKED'):
            mock_support.return_value = True
            ipmi.TMP_DIR_CHECKED = None
            ipmi.IPMISocatConsole()
            mock_support.assert_called_with(mock.ANY)
            mock_check_dir.assert_called_once_with()

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'check_dir', autospec=True)
    def test_console_init_calls_for_socat_already_checked(self,
                                                          mock_check_dir,
                                                          mock_support):
        with mock.patch.object(ipmi, 'TMP_DIR_CHECKED'):
            mock_support.return_value = True
            ipmi.TMP_DIR_CHECKED = True
            ipmi.IPMISocatConsole()
            mock_support.assert_called_with(mock.ANY)
            self.assertFalse(mock_check_dir.called)


@mock.patch.object(ipmi, '_is_option_supported', autospec=True)
@mock.patch.object(subprocess, 'check_call', autospec=True)
class IPMIToolCheckOptionSupportedTestCase(base.TestCase):

    def test_check_timing_pass(self, mock_chkcall, mock_support):
        mock_chkcall.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('timing'),
                    mock.call('timing', True)]

        ipmi._check_option_support(['timing'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_timing_fail(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = subprocess.CalledProcessError(1, 'ipmitool')
        mock_support.return_value = None
        expected = [mock.call('timing'),
                    mock.call('timing', False)]

        ipmi._check_option_support(['timing'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_timing_no_ipmitool(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('timing')]

        self.assertRaises(OSError, ipmi._check_option_support, ['timing'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_single_bridge_pass(self, mock_chkcall, mock_support):
        mock_chkcall.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('single_bridge'),
                    mock.call('single_bridge', True)]

        ipmi._check_option_support(['single_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_single_bridge_fail(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = subprocess.CalledProcessError(1, 'ipmitool')
        mock_support.return_value = None
        expected = [mock.call('single_bridge'),
                    mock.call('single_bridge', False)]

        ipmi._check_option_support(['single_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_single_bridge_no_ipmitool(self, mock_chkcall,
                                             mock_support):
        mock_chkcall.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('single_bridge')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['single_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_dual_bridge_pass(self, mock_chkcall, mock_support):
        mock_chkcall.return_value = (None, None)
        mock_support.return_value = None
        expected = [mock.call('dual_bridge'),
                    mock.call('dual_bridge', True)]

        ipmi._check_option_support(['dual_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_dual_bridge_fail(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = subprocess.CalledProcessError(1, 'ipmitool')
        mock_support.return_value = None
        expected = [mock.call('dual_bridge'),
                    mock.call('dual_bridge', False)]

        ipmi._check_option_support(['dual_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_dual_bridge_no_ipmitool(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = OSError()
        mock_support.return_value = None
        expected = [mock.call('dual_bridge')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['dual_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_all_options_pass(self, mock_chkcall, mock_support):
        mock_chkcall.return_value = (None, None)
        mock_support.return_value = None
        expected = [
            mock.call('timing'), mock.call('timing', True),
            mock.call('single_bridge'),
            mock.call('single_bridge', True),
            mock.call('dual_bridge'), mock.call('dual_bridge', True)]

        ipmi._check_option_support(['timing', 'single_bridge', 'dual_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_all_options_fail(self, mock_chkcall, mock_support):
        options = ['timing', 'single_bridge', 'dual_bridge']
        mock_chkcall.side_effect = [subprocess.CalledProcessError(
            1, 'ipmitool')] * len(options)
        mock_support.return_value = None
        expected = [
            mock.call('timing'), mock.call('timing', False),
            mock.call('single_bridge'),
            mock.call('single_bridge', False),
            mock.call('dual_bridge'),
            mock.call('dual_bridge', False)]

        ipmi._check_option_support(options)
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)

    def test_check_all_options_no_ipmitool(self, mock_chkcall, mock_support):
        mock_chkcall.side_effect = OSError()
        mock_support.return_value = None
        # exception is raised once ipmitool was not found for an command
        expected = [mock.call('timing')]

        self.assertRaises(OSError, ipmi._check_option_support,
                          ['timing', 'single_bridge', 'dual_bridge'])
        self.assertTrue(mock_chkcall.called)
        self.assertEqual(expected, mock_support.call_args_list)


awesome_password_filename = 'awesome_password_filename'


@contextlib.contextmanager
def _make_password_file_stub(password):
    yield awesome_password_filename


@mock.patch.object(time, 'sleep', autospec=True)
class IPMIToolPrivateMethodTestCase(db_base.DbTestCase):

    def setUp(self):
        super(IPMIToolPrivateMethodTestCase, self).setUp()
        self.driver_name = "fake_ipmitool"
        mgr_utils.mock_the_extension_manager(driver=self.driver_name)
        self.driver = driver_factory.get_driver(self.driver_name)
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake_ipmitool',
            driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

        # power actions use oslo_service.BackoffLoopingCall,
        # mock random.SystemRandom gauss distribution
        self._mock_system_random_distribution()

    def _mock_system_random_distribution(self):
        # random.SystemRandom with gauss distribution is used by oslo_service's
        # BackoffLoopingCall, it multiplies default interval (equals to 1) by
        # 2 * return_value, so if you want BackoffLoopingCall to "sleep" for
        # 1 second, return_value should be 0.5.
        m = mock.patch.object(random.SystemRandom, 'gauss', return_value=0.5)
        m.start()
        self.addCleanup(m.stop)

    def _test__make_password_file(self, mock_sleep, input_password,
                                  exception_to_raise=None):
        pw_file = None
        try:
            with ipmi._make_password_file(input_password) as pw_file:
                if exception_to_raise is not None:
                    raise exception_to_raise
                self.assertTrue(os.path.isfile(pw_file))
                self.assertEqual(0o600, os.stat(pw_file)[stat.ST_MODE] & 0o777)
                with open(pw_file, "r") as f:
                    password = f.read()
                self.assertEqual(str(input_password), password)
        finally:
            if pw_file is not None:
                self.assertFalse(os.path.isfile(pw_file))

    def test__make_password_file_str_password(self, mock_sleep):
        self._test__make_password_file(mock_sleep, self.info['password'])

    def test__make_password_file_with_numeric_password(self, mock_sleep):
        self._test__make_password_file(mock_sleep, 12345)

    def test__make_password_file_caller_exception(self, mock_sleep):
        # Test caller raising exception
        result = self.assertRaises(
            ValueError,
            self._test__make_password_file,
            mock_sleep, 12345, ValueError('we should fail'))
        self.assertEqual('we should fail', six.text_type(result))

    @mock.patch.object(tempfile, 'NamedTemporaryFile',
                       new=mock.MagicMock(side_effect=OSError('Test Error')))
    def test__make_password_file_tempfile_known_exception(self, mock_sleep):
        # Test OSError exception in _make_password_file for
        # tempfile.NamedTemporaryFile
        self.assertRaises(
            exception.PasswordFileFailedToCreate,
            self._test__make_password_file, mock_sleep, 12345)

    @mock.patch.object(
        tempfile, 'NamedTemporaryFile',
        new=mock.MagicMock(side_effect=OverflowError('Test Error')))
    def test__make_password_file_tempfile_unknown_exception(self, mock_sleep):
        # Test exception in _make_password_file for tempfile.NamedTemporaryFile
        result = self.assertRaises(
            OverflowError,
            self._test__make_password_file, mock_sleep, 12345)
        self.assertEqual('Test Error', six.text_type(result))

    def test__make_password_file_write_exception(self, mock_sleep):
        # Test exception in _make_password_file for write()
        mock_namedtemp = mock.mock_open(mock.MagicMock(name='JLV'))
        with mock.patch('tempfile.NamedTemporaryFile', mock_namedtemp):
            mock_filehandle = mock_namedtemp.return_value
            mock_write = mock_filehandle.write
            mock_write.side_effect = OSError('Test 2 Error')
            self.assertRaises(
                exception.PasswordFileFailedToCreate,
                self._test__make_password_file, mock_sleep, 12345)

    def test__parse_driver_info(self, mock_sleep):
        # make sure we get back the expected things
        _OPTIONS = ['address', 'username', 'password', 'uuid']
        for option in _OPTIONS:
            self.assertIsNotNone(self.info[option])

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

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_invalid_bridging_type(
            self, mock_support, mock_sleep):
        info = BRIDGE_INFO_DICT.copy()
        # make sure error is raised when ipmi_bridging has unexpected value
        info['ipmi_bridging'] = 'junk'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info,
                          node)
        self.assertFalse(mock_support.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_no_bridging(
            self, mock_support, mock_sleep):
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

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_dual_bridging_pass(
            self, mock_support, mock_sleep):
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

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_dual_bridging_not_supported(
            self, mock_support, mock_sleep):
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=BRIDGE_INFO_DICT)
        # if dual bridge is not supported then check if error is raised
        mock_support.return_value = False
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)
        mock_support.assert_called_once_with('dual_bridge')

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_dual_bridging_missing_parameters(
            self, mock_support, mock_sleep):
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

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_single_bridging_pass(
            self, mock_support, mock_sleep):
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

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    def test__parse_driver_info_with_single_bridging_not_supported(
            self, mock_support, mock_sleep):
        info = BRIDGE_INFO_DICT.copy()
        info['ipmi_bridging'] = 'single'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=info)

        # if single bridge is not supported then check if error is raised
        mock_support.return_value = False
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)
        mock_support.assert_called_once_with('single_bridge')

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
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

    def test__parse_driver_info_numeric_password(
            self, mock_sleep):
        # ipmi_password must not be converted to int / float
        # even if it includes just numbers.
        info = dict(INFO_DICT)
        info['ipmi_password'] = 12345678
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ret = ipmi._parse_driver_info(node)
        self.assertEqual(six.u('12345678'), ret['password'])
        self.assertIsInstance(ret['password'], six.text_type)

    def test__parse_driver_info_ipmi_prot_version_1_5(self, mock_sleep):
        info = dict(INFO_DICT)
        info['ipmi_protocol_version'] = '1.5'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ret = ipmi._parse_driver_info(node)
        self.assertEqual('1.5', ret['protocol_version'])

    def test__parse_driver_info_invalid_ipmi_prot_version(self, mock_sleep):
        info = dict(INFO_DICT)
        info['ipmi_protocol_version'] = '9000'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)

    def test__parse_driver_info_invalid_ipmi_port(self, mock_sleep):
        info = dict(INFO_DICT)
        info['ipmi_port'] = '700000'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          ipmi._parse_driver_info, node)

    def test__parse_driver_info_ipmi_port_valid(self, mock_sleep):
        info = dict(INFO_DICT)
        info['ipmi_port'] = '623'
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ret = ipmi._parse_driver_info(node)
        self.assertEqual(623, ret['dest_port'])

    @mock.patch.object(ipmi.LOG, 'warning', spec_set=True, autospec=True)
    def test__parse_driver_info_undefined_credentials(
            self, mock_log, mock_sleep):
        info = dict(INFO_DICT)
        del info['ipmi_username']
        del info['ipmi_password']
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ipmi._parse_driver_info(node)
        calls = [
            mock.call(u'ipmi_username is not defined or empty for node '
                      u'%s: NULL user will be utilized.', self.node.uuid),
            mock.call(u'ipmi_password is not defined or empty for node '
                      u'%s: NULL password will be utilized.', self.node.uuid),
        ]
        mock_log.assert_has_calls(calls)

    @mock.patch.object(ipmi.LOG, 'warning', spec_set=True, autospec=True)
    def test__parse_driver_info_have_credentials(
            self, mock_log, mock_sleep):
        """Ensure no warnings generated if have credentials"""
        info = dict(INFO_DICT)
        node = obj_utils.get_test_node(self.context, driver_info=info)
        ipmi._parse_driver_info(node)
        self.assertFalse(mock_log.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_first_call_to_address(self, mock_exec,
                                                  mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)
        self.assertFalse(mock_sleep.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_second_call_to_address_sleep(
            self, mock_exec, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ], [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_exec.side_effect = [(None, None), (None, None)]

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])

        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertTrue(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_second_call_to_address_no_sleep(
            self, mock_exec, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ], [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_exec.side_effect = [(None, None), (None, None)]

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])
        # act like enough time has passed
        ipmi.LAST_CMD_TIME[self.info['address']] = (
            time.time() - CONF.ipmi.min_command_interval)
        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertFalse(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_two_calls_to_diff_address(
            self, mock_exec, mock_support, mock_sleep):
        ipmi.LAST_CMD_TIME = {}
        args = [[
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ], [
            'ipmitool',
            '-I', 'lanplus',
            '-H', '127.127.127.127',
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'D', 'E', 'F',
        ]]

        expected = [mock.call('timing'),
                    mock.call('timing')]
        mock_support.return_value = False
        mock_exec.side_effect = [(None, None), (None, None)]

        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_exec.assert_called_with(*args[0])
        self.info['address'] = '127.127.127.127'
        ipmi._exec_ipmitool(self.info, 'D E F')
        self.assertFalse(mock_sleep.called)
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_with(*args[1])

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_without_timing(
            self, mock_exec, mock_support, mock_sleep):
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_timing(
            self, mock_exec, mock_support, mock_sleep):
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-R', '12',
            '-N', '5',
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = True
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_without_username(
            self, mock_exec, mock_support, mock_sleep):
        # An undefined username is treated the same as an empty username and
        # will cause no user (-U) to be specified.
        self.info['username'] = None
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_empty_username(
            self, mock_exec, mock_support, mock_sleep):
        # An empty username is treated the same as an undefined username and
        # will cause no user (-U) to be specified.
        self.info['username'] = ""
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(
        ipmi, '_make_password_file', wraps=_make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_without_password(self, mock_exec,
                                             _make_password_file_mock,
                                             mock_support, mock_sleep):
        # An undefined password is treated the same as an empty password and
        # will cause a NULL (\0) password to be used"""
        self.info['password'] = None
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)
        _make_password_file_mock.assert_called_once_with('\0')

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(
        ipmi, '_make_password_file', wraps=_make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_empty_password(self, mock_exec,
                                                _make_password_file_mock,
                                                mock_support, mock_sleep):
        # An empty password is treated the same as an undefined password and
        # will cause a NULL (\0) password to be used"""
        self.info['password'] = ""
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_support.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)
        _make_password_file_mock.assert_called_once_with('\0')

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_dual_bridging(self,
                                               mock_exec,
                                               mock_support,
                                               mock_sleep):

        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=BRIDGE_INFO_DICT)
        # when support for dual bridge command is called returns True
        mock_support.return_value = True
        info = ipmi._parse_driver_info(node)
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
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        expected = [mock.call('dual_bridge'),
                    mock.call('timing')]
        # When support for timing command is called returns False
        mock_support.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(info, 'A B C')
        self.assertEqual(expected, mock_support.call_args_list)
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_single_bridging(self,
                                                 mock_exec,
                                                 mock_pass,
                                                 mock_support):
        single_bridge_info = dict(BRIDGE_INFO_DICT)
        single_bridge_info['ipmi_bridging'] = 'single'
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=single_bridge_info)
        # when support for single bridge command is called returns True
        mock_pass.return_value = True
        info = ipmi._parse_driver_info(node)
        info['transit_channel'] = info['transit_address'] = None

        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', info['address'],
            '-L', info['priv_level'],
            '-U', info['username'],
            '-m', info['local_address'],
            '-b', info['target_channel'],
            '-t', info['target_address'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        expected = [mock.call('single_bridge'),
                    mock.call('timing')]
        # When support for timing command is called returns False
        mock_pass.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(info, 'A B C')
        self.assertEqual(expected, mock_pass.call_args_list)
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_exception(
            self, mock_exec, mock_pass, mock_support):
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_pass.return_value = False
        mock_exec.side_effect = processutils.ProcessExecutionError("x")
        self.assertRaises(processutils.ProcessExecutionError,
                          ipmi._exec_ipmitool,
                          self.info, 'A B C')
        mock_pass.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)
        self.assertEqual(1, mock_exec.call_count)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_exception_retry(
            self, mock_exec, mock_support, mock_sleep):

        ipmi.LAST_CMD_TIME = {}
        mock_support.return_value = False
        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr="insufficient resources for session"
            ),
            (None, None)
        ]

        # Directly set the configuration values such that
        # the logic will cause _exec_ipmitool to retry twice.
        self.config(min_command_interval=1, group='ipmi')
        self.config(retry_timeout=2, group='ipmi')

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_support.assert_called_once_with('timing')
        self.assertEqual(2, mock_exec.call_count)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_exception_retries_exceeded(
            self, mock_exec, mock_support, mock_sleep):

        ipmi.LAST_CMD_TIME = {}
        mock_support.return_value = False

        mock_exec.side_effect = [processutils.ProcessExecutionError(
            stderr="insufficient resources for session"
        )]

        # Directly set the configuration values such that
        # the logic will cause _exec_ipmitool to timeout.
        self.config(min_command_interval=1, group='ipmi')
        self.config(retry_timeout=1, group='ipmi')

        self.assertRaises(processutils.ProcessExecutionError,
                          ipmi._exec_ipmitool,
                          self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        self.assertEqual(1, mock_exec.call_count)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_exception_non_retryable_failure(
            self, mock_exec, mock_support, mock_sleep):

        ipmi.LAST_CMD_TIME = {}
        mock_support.return_value = False

        # Return a retryable error, then an error that cannot
        # be retried thus resulting in a single retry
        # attempt by _exec_ipmitool.
        mock_exec.side_effect = [
            processutils.ProcessExecutionError(
                stderr="insufficient resources for session"
            ),
            processutils.ProcessExecutionError(
                stderr="Unknown"
            ),
        ]

        # Directly set the configuration values such that
        # the logic will cause _exec_ipmitool to retry up
        # to 3 times.
        self.config(min_command_interval=1, group='ipmi')
        self.config(retry_timeout=3, group='ipmi')

        self.assertRaises(processutils.ProcessExecutionError,
                          ipmi._exec_ipmitool,
                          self.info, 'A B C')
        mock_support.assert_called_once_with('timing')
        self.assertEqual(2, mock_exec.call_count)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_IPMI_version_1_5(
            self, mock_exec, mock_pass, mock_support):
        self.info['protocol_version'] = '1.5'
        # Assert it uses "-I lan" (1.5) instead of "-I lanplus" (2.0)
        args = [
            'ipmitool',
            '-I', 'lan',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_pass.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C')
        mock_pass.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_port(self, mock_exec, mock_pass,
                                      mock_support):
        self.info['dest_port'] = '1623'
        ipmi.LAST_CMD_TIME = {}
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-p', '1623',
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]

        mock_pass.return_value = False
        mock_exec.return_value = (None, None)

        ipmi._exec_ipmitool(self.info, 'A B C')

        mock_pass.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args)
        self.assertFalse(mock_support.called)

    @mock.patch.object(ipmi, '_is_option_supported', autospec=True)
    @mock.patch.object(ipmi, '_make_password_file', _make_password_file_stub)
    @mock.patch.object(utils, 'execute', autospec=True)
    def test__exec_ipmitool_with_check_exit_code(self, mock_exec,
                                                 mock_pass, mock_support):
        args = [
            'ipmitool',
            '-I', 'lanplus',
            '-H', self.info['address'],
            '-L', self.info['priv_level'],
            '-U', self.info['username'],
            '-f', awesome_password_filename,
            'A', 'B', 'C',
        ]
        mock_pass.return_value = False
        mock_exec.return_value = (None, None)
        ipmi._exec_ipmitool(self.info, 'A B C', check_exit_code=[0, 1])
        mock_pass.assert_called_once_with('timing')
        mock_exec.assert_called_once_with(*args, check_exit_code=[0, 1])

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
    @mock.patch('eventlet.greenthread.sleep', autospec=True)
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

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              ipmi._power_on, task, self.info, timeout=2)

        self.assertEqual(expected, mock_exec.call_args_list)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    @mock.patch('eventlet.greenthread.sleep', autospec=True)
    def test__soft_power_off(self, sleep_mock, mock_exec,
                             mock_sleep):

        def side_effect(driver_info, command):
            resp_dict = {"power status": ["Chassis Power is off\n", None],
                         "power soft": [None, None]}
            return resp_dict.get(command, ["Bad\n", None])

        mock_exec.side_effect = side_effect

        expected = [mock.call(self.info, "power soft"),
                    mock.call(self.info, "power status")]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            state = ipmi._soft_power_off(task, self.info)

        self.assertEqual(expected, mock_exec.call_args_list)
        self.assertEqual(states.POWER_OFF, state)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    @mock.patch('eventlet.greenthread.sleep', autospec=True)
    def test__soft_power_off_max_retries(self, sleep_mock, mock_exec,
                                         mock_sleep):

        def side_effect(driver_info, command):
            resp_dict = {"power status": ["Chassis Power is on\n", None],
                         "power soft": [None, None]}
            return resp_dict.get(command, ["Bad\n", None])

        mock_exec.side_effect = side_effect

        expected = [mock.call(self.info, "power soft"),
                    mock.call(self.info, "power status"),
                    mock.call(self.info, "power status")]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              ipmi._soft_power_off, task, self.info, timeout=2)

        self.assertEqual(expected, mock_exec.call_args_list)

    @mock.patch.object(ipmi, '_power_status', autospec=True)
    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    @mock.patch('eventlet.greenthread.sleep', autospec=True)
    def test___set_and_wait_no_needless_status_polling(
            self, sleep_mock, mock_exec, mock_status, mock_sleep):
        # Check that if the call to power state change fails, it doesn't
        # call power_status().
        self.config(retry_timeout=2, group='ipmi')

        mock_exec.side_effect = exception.IPMIFailure(cmd='power on')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure, ipmi._power_on, task,
                              self.info)
        self.assertFalse(mock_status.called)


class IPMIToolDriverTestCase(db_base.DbTestCase):

    def setUp(self, terminal=None):
        super(IPMIToolDriverTestCase, self).setUp()
        if terminal is None:
            self.driver_name = "fake_ipmitool"
        else:
            self.driver_name = "fake_ipmitool_socat"

        mgr_utils.mock_the_extension_manager(driver=self.driver_name)
        self.driver = driver_factory.get_driver(self.driver_name)

        self.node = obj_utils.create_test_node(self.context,
                                               driver=self.driver_name,
                                               driver_info=INFO_DICT)
        self.info = ipmi._parse_driver_info(self.node)

    @mock.patch.object(ipmi, "_parse_driver_info", autospec=True)
    def test_power_validate(self, mock_parse):
        node = obj_utils.get_test_node(self.context, driver='fake_ipmitool',
                                       driver_info=INFO_DICT)
        mock_parse.return_value = {}

        with task_manager.acquire(self.context, node.uuid) as task:
            task.driver.power.validate(task)
            mock_parse.assert_called_once_with(mock.ANY)

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
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_ON)

            mock_on.assert_called_once_with(task, self.info, timeout=None)
        self.assertFalse(mock_off.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_timeout_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.return_value = states.POWER_ON
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_ON,
                                              timeout=2)

            mock_on.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_off.called)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_with_next_boot(self, mock_off, mock_on,
                                         mock_next_boot):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.return_value = states.POWER_ON
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_ON)
            mock_next_boot.assert_called_once_with(task, self.info)

            mock_on.assert_called_once_with(task, self.info, timeout=None)
        self.assertFalse(mock_off.called)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_with_next_boot_timeout(self, mock_off, mock_on,
                                                 mock_next_boot):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.return_value = states.POWER_ON
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_ON,
                                              timeout=2)
            mock_next_boot.assert_called_once_with(task, self.info)

            mock_on.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_off.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_off_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_OFF)

            mock_off.assert_called_once_with(task, self.info, timeout=None)
        self.assertFalse(mock_on.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_off_timeout_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.power.set_power_state(task,
                                              states.POWER_OFF,
                                              timeout=2)

            mock_off.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_on.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_soft_power_off', autospec=True)
    def test_set_soft_power_off_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.SOFT_POWER_OFF)

            mock_off.assert_called_once_with(task, self.info, timeout=None)
        self.assertFalse(mock_on.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_soft_power_off', autospec=True)
    def test_set_soft_power_off_timeout_ok(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.SOFT_POWER_OFF,
                                              timeout=2)

            mock_off.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_on.called)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_soft_power_off', autospec=True)
    def test_set_soft_reboot_ok(self, mock_off, mock_on, mock_next_boot):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF
        mock_on.return_value = states.POWER_ON

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.SOFT_REBOOT)
            mock_next_boot.assert_called_once_with(task, self.info)
            mock_off.assert_called_once_with(task, self.info, timeout=None)
            mock_on.assert_called_once_with(task, self.info, timeout=None)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_soft_power_off', autospec=True)
    def test_set_soft_reboot_timeout_ok(self, mock_off, mock_on,
                                        mock_next_boot):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.return_value = states.POWER_OFF
        mock_on.return_value = states.POWER_ON

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.driver.power.set_power_state(task,
                                              states.SOFT_REBOOT,
                                              timeout=2)
            mock_next_boot.assert_called_once_with(task, self.info)
            mock_off.assert_called_once_with(task, self.info, timeout=2)
            mock_on.assert_called_once_with(task, self.info, timeout=2)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_soft_power_off', autospec=True)
    def test_set_soft_reboot_timeout_fail(self, mock_off, mock_on,
                                          mock_next_boot):
        self.config(retry_timeout=0, group='ipmi')

        mock_off.side_effect = exception.PowerStateFailure(
            pstate=states.POWER_ON)

        with task_manager.acquire(self.context,
                                  self.node['uuid']) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.set_power_state,
                              task,
                              states.SOFT_REBOOT,
                              timeout=2)

            mock_off.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_next_boot.called)
        self.assertFalse(mock_on.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_fail(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.side_effect = exception.PowerStateFailure(
            pstate=states.POWER_ON)
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.set_power_state,
                              task,
                              states.POWER_ON)

            mock_on.assert_called_once_with(task, self.info, timeout=None)
        self.assertFalse(mock_off.called)

    @mock.patch.object(ipmi, '_power_on', autospec=True)
    @mock.patch.object(ipmi, '_power_off', autospec=True)
    def test_set_power_on_timeout_fail(self, mock_off, mock_on):
        self.config(retry_timeout=0, group='ipmi')

        mock_on.side_effect = exception.PowerStateFailure(pstate=states.ERROR)
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.set_power_state,
                              task,
                              states.POWER_ON,
                              timeout=2)

            mock_on.assert_called_once_with(task, self.info, timeout=2)
        self.assertFalse(mock_off.called)

    def test_set_power_invalid_state(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.power.set_power_state,
                              task,
                              "fake state")

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_send_raw_bytes_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.vendor.send_raw(task, http_method='POST',
                                        raw_bytes='0x00 0x01')

        mock_exec.assert_called_once_with(self.info, 'raw 0x00 0x01')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_send_raw_bytes_fail(self, mock_exec):
        mock_exec.side_effect = exception.PasswordFileFailedToCreate('error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.vendor.send_raw,
                              task,
                              http_method='POST',
                              raw_bytes='0x00 0x01')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.vendor.bmc_reset(task, 'POST')

        mock_exec.assert_called_once_with(self.info, 'bmc reset warm')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_cold(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.vendor.bmc_reset(task, 'POST', warm=False)

        mock_exec.assert_called_once_with(self.info, 'bmc reset cold')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__bmc_reset_fail(self, mock_exec):
        mock_exec.side_effect = processutils.ProcessExecutionError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.IPMIFailure,
                              self.driver.vendor.bmc_reset,
                              task, 'POST')

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_ON)
    def test_reboot_ok(self, mock_on, mock_off, mock_next_boot):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_off.return_value = states.POWER_OFF
        mock_on.return_value = states.POWER_ON
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_off(task, self.info, timeout=None),
                        mock.call.power_on(task, self.info, timeout=None)]
            self.driver.power.reboot(task)
            mock_next_boot.assert_called_once_with(task, self.info)

        self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_OFF)
    def test_reboot_already_off(self, mock_on, mock_off, mock_next_boot):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_off.return_value = states.POWER_OFF
        mock_on.return_value = states.POWER_ON
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_on(task, self.info, timeout=None)]
            self.driver.power.reboot(task)
            mock_next_boot.assert_called_once_with(task, self.info)

        self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(driver_utils, 'ensure_next_boot_device', autospec=True)
    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_ON)
    def test_reboot_timeout_ok(self, mock_on, mock_off, mock_next_boot):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_off(task, self.info, timeout=2),
                        mock.call.power_on(task, self.info, timeout=2)]

            self.driver.power.reboot(task, timeout=2)
            mock_next_boot.assert_called_once_with(task, self.info)

            self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_ON)
    def test_reboot_fail_power_off(self, mock_on, mock_off):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_off.side_effect = exception.PowerStateFailure(
            pstate=states.POWER_OFF)
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_off(task, self.info, timeout=None)]
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.reboot,
                              task)

        self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_ON)
    def test_reboot_fail_power_on(self, mock_on, mock_off):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_off.return_value = states.POWER_OFF
        mock_on.side_effect = exception.PowerStateFailure(
            pstate=states.POWER_ON)
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_off(task, self.info, timeout=None),
                        mock.call.power_on(task, self.info, timeout=None)]
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.reboot,
                              task)

        self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(ipmi, '_power_off', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_on', spec_set=types.FunctionType)
    @mock.patch.object(ipmi, '_power_status',
                       lambda driver_info: states.POWER_ON)
    def test_reboot_timeout_fail(self, mock_on, mock_off):
        manager = mock.MagicMock()
        # NOTE(rloo): if autospec is True, then manager.mock_calls is empty
        mock_on.side_effect = exception.PowerStateFailure(
            pstate=states.POWER_ON)
        manager.attach_mock(mock_off, 'power_off')
        manager.attach_mock(mock_on, 'power_on')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            expected = [mock.call.power_off(task, self.info, timeout=2),
                        mock.call.power_on(task, self.info, timeout=2)]
            self.assertRaises(exception.PowerStateFailure,
                              self.driver.power.reboot,
                              task, timeout=2)

        self.assertEqual(expected, manager.mock_calls)

    @mock.patch.object(ipmi, '_parse_driver_info', autospec=True)
    def test_vendor_passthru_validate__parse_driver_info_fail(self, info_mock):
        info_mock.side_effect = exception.InvalidParameterValue("bad")
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.InvalidParameterValue,
                              self.driver.vendor.validate,
                              task, method='send_raw', raw_bytes='0x00 0x01')
            info_mock.assert_called_once_with(task.node)

    def test_vendor_passthru_validate__send_raw_bytes_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task,
                                        method='send_raw',
                                        http_method='POST',
                                        raw_bytes='0x00 0x01')

    def test_vendor_passthru_validate__send_raw_bytes_fail(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              self.driver.vendor.validate,
                              task, method='send_raw')

    @mock.patch.object(ipmi.VendorPassthru, 'send_raw', autospec=True)
    def test_vendor_passthru_call_send_raw_bytes(self, raw_bytes_mock):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.driver.vendor.send_raw(task, http_method='POST',
                                        raw_bytes='0x00 0x01')
            raw_bytes_mock.assert_called_once_with(
                self.driver.vendor, task, http_method='POST',
                raw_bytes='0x00 0x01')

    def test_vendor_passthru_validate__bmc_reset_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset')

    def test_vendor_passthru_validate__bmc_reset_warm_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset',
                                        warm=True)

    def test_vendor_passthru_validate__bmc_reset_cold_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.vendor.validate(task,
                                        method='bmc_reset',
                                        warm=False)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def _vendor_passthru_call_bmc_reset(self, warm, expected,
                                        mock_exec):
        mock_exec.return_value = [None, None]
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            self.driver.vendor.bmc_reset(task, 'POST', warm=warm)
            mock_exec.assert_called_once_with(
                mock.ANY, 'bmc reset %s' % expected)

    def test_vendor_passthru_call_bmc_reset_warm(self):
        for param in (True, 'true', 'on', 'y', 'yes'):
            self._vendor_passthru_call_bmc_reset(param, 'warm')

    def test_vendor_passthru_call_bmc_reset_cold(self):
        for param in (False, 'false', 'off', 'n', 'no'):
            self._vendor_passthru_call_bmc_reset(param, 'cold')

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

    def test_console_validate(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ipmi_terminal_port'] = 123
            task.driver.console.validate(task)

    def test_console_validate_missing_port(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info.pop('ipmi_terminal_port', None)
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.console.validate, task)

    def test_console_validate_invalid_port(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ipmi_terminal_port'] = ''
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.console.validate, task)

    def test_console_validate_wrong_ipmi_protocol_version(self):
        with task_manager.acquire(
                self.context, self.node.uuid, shared=True) as task:
            task.node.driver_info['ipmi_terminal_port'] = 123
            task.node.driver_info['ipmi_protocol_version'] = '1.5'
            self.assertRaises(exception.InvalidParameterValue,
                              task.driver.console.validate, task)

    def test__get_ipmi_cmd(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            ipmi_cmd = self.driver.console._get_ipmi_cmd(driver_info,
                                                         'pw_file')
            expected_ipmi_cmd = ("/:%(uid)s:%(gid)s:HOME:ipmitool "
                                 "-H %(address)s -I lanplus -U %(user)s "
                                 "-f pw_file" %
                                 {'uid': os.getuid(), 'gid': os.getgid(),
                                  'address': driver_info['address'],
                                  'user': driver_info['username']})
        self.assertEqual(expected_ipmi_cmd, ipmi_cmd)

    def test__get_ipmi_cmd_without_user(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            driver_info['username'] = None
            ipmi_cmd = self.driver.console._get_ipmi_cmd(driver_info,
                                                         'pw_file')
            expected_ipmi_cmd = ("/:%(uid)s:%(gid)s:HOME:ipmitool "
                                 "-H %(address)s -I lanplus "
                                 "-f pw_file" %
                                 {'uid': os.getuid(), 'gid': os.getgid(),
                                  'address': driver_info['address']})
        self.assertEqual(expected_ipmi_cmd, ipmi_cmd)

    @mock.patch.object(ipmi.IPMIConsole, '_start_console', autospec=True)
    def test_start_console(self, mock_start):
        mock_start.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)
            driver_info = ipmi._parse_driver_info(task.node)
        mock_start.assert_called_once_with(
            self.driver.console, driver_info,
            console_utils.start_shellinabox_console)

    @mock.patch.object(ipmi.IPMIConsole, '_get_ipmi_cmd', autospec=True)
    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test__start_console(self, mock_start, mock_ipmi_cmd):
        mock_start.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console._start_console(
                driver_info, console_utils.start_shellinabox_console)

        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)
        mock_ipmi_cmd.assert_called_once_with(self.driver.console,
                                              driver_info, mock.ANY)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test__start_console_fail(self, mock_start):
        mock_start.side_effect = exception.ConsoleSubprocessFailed(
            error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console._start_console,
                              driver_info,
                              console_utils.start_shellinabox_console)

    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test__start_console_fail_nodir(self, mock_start):
        mock_start.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.assertRaises(exception.ConsoleError,
                              self.driver.console._start_console,
                              driver_info,
                              console_utils.start_shellinabox_console)
        mock_start.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(console_utils, 'make_persistent_password_file',
                       autospec=True)
    @mock.patch.object(console_utils, 'start_shellinabox_console',
                       autospec=True)
    def test__start_console_empty_password(self, mock_start, mock_pass):
        driver_info = self.node.driver_info
        del driver_info['ipmi_password']
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console._start_console(
                driver_info, console_utils.start_shellinabox_console)

        mock_pass.assert_called_once_with(mock.ANY, '\0')
        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)

    @mock.patch.object(console_utils, 'stop_shellinabox_console',
                       autospec=True)
    def test_stop_console(self, mock_stop):
        mock_stop.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.stop_console(task)

        mock_stop.assert_called_once_with(self.info['uuid'])

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
                       autospec=True)
    def test_get_console(self, mock_get):
        url = 'http://localhost:4201'
        mock_get.return_value = url
        expected = {'type': 'shellinabox', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_get.assert_called_once_with(self.info['port'])

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)

        mock_calls = [mock.call(self.info, "raw 0x00 0x08 0x03 0x08"),
                      mock.call(self.info, "chassis bootdev pxe")]
        mock_exec.assert_has_calls(mock_calls)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_force_set_boot_device_ok(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['ipmi_force_boot_device'] = True
            task.node.driver_info = driver_info
            self.info['force_boot_device'] = True
            self.driver.management.set_boot_device(task, boot_devices.PXE)
            task.node.refresh()
            self.assertIs(
                False,
                task.node.driver_internal_info['is_next_boot_persistent']
            )

        mock_calls = [mock.call(self.info, "raw 0x00 0x08 0x03 0x08"),
                      mock.call(self.info, "chassis bootdev pxe")]
        mock_exec.assert_has_calls(mock_calls)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_persistent(self, mock_exec):
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = task.node.driver_info
            driver_info['ipmi_force_boot_device'] = True
            task.node.driver_info = driver_info
            self.info['force_boot_device'] = True
            self.driver.management.set_boot_device(task,
                                                   boot_devices.PXE,
                                                   True)
            self.assertEqual(
                boot_devices.PXE,
                task.node.driver_internal_info['persistent_boot_device'])

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

    @mock.patch.object(deploy_utils, 'get_boot_mode_for_deploy')
    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_uefi(self, mock_exec,
                                                       mock_boot_mode):
        mock_boot_mode.return_value = 'uefi'
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE)

        mock_calls = [
            mock.call(self.info, "raw 0x00 0x08 0x03 0x08"),
            mock.call(self.info, "chassis bootdev pxe options=efiboot")
        ]
        mock_exec.assert_has_calls(mock_calls)

    @mock.patch.object(deploy_utils, 'get_boot_mode_for_deploy')
    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_set_boot_device_uefi_and_persistent(
            self, mock_exec, mock_boot_mode):
        mock_boot_mode.return_value = 'uefi'
        mock_exec.return_value = [None, None]

        with task_manager.acquire(self.context, self.node.uuid) as task:
            self.driver.management.set_boot_device(task, boot_devices.PXE,
                                                   persistent=True)
        mock_calls = [
            mock.call(self.info, "raw 0x00 0x08 0x03 0x08"),
            mock.call(self.info, "raw 0x00 0x08 0x05 0xe0 0x04 0x00 0x00 0x00")
        ]
        mock_exec.assert_has_calls(mock_calls)

    def test_management_interface_get_supported_boot_devices(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            expected = [boot_devices.PXE, boot_devices.DISK,
                        boot_devices.CDROM, boot_devices.BIOS,
                        boot_devices.SAFE]
            self.assertEqual(sorted(expected), sorted(task.driver.management.
                             get_supported_boot_devices(task)))

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

    def test_get_force_boot_device_persistent(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.node.driver_info['ipmi_force_boot_device'] = True
            task.node.driver_internal_info['persistent_boot_device'] = 'pxe'
            bootdev = self.driver.management.get_boot_device(task)
            self.assertEqual('pxe', bootdev['boot_device'])
            self.assertTrue(bootdev['persistent'])

    def test_management_interface_validate_good(self):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            task.driver.management.validate(task)

    def test_management_interface_validate_fail(self):
        # Missing IPMI driver_info information
        node = obj_utils.create_test_node(self.context,
                                          uuid=uuidutils.generate_uuid(),
                                          driver=self.driver_name)
        with task_manager.acquire(self.context, node.uuid) as task:
            self.assertRaises(exception.MissingParameterValue,
                              task.driver.management.validate, task)

    @mock.patch.object(ipmi.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_inject_nmi_ok(self, mock_exec, mock_log):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.management.inject_nmi(task)

            mock_exec.assert_called_once_with(driver_info, "power diag")
            self.assertFalse(mock_log.called)

    @mock.patch.object(ipmi.LOG, 'error', spec_set=True, autospec=True)
    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_management_interface_inject_nmi_fail(self, mock_exec, mock_log):
        mock_exec.side_effect = exception.PasswordFileFailedToCreate('error')

        with task_manager.acquire(self.context, self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.assertRaises(exception.IPMIFailure,
                              self.driver.management.inject_nmi,
                              task)

            mock_exec.assert_called_once_with(driver_info, "power diag")
            self.assertTrue(mock_log.called)

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

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_dump_sdr_ok(self, mock_exec):
        mock_exec.return_value = (None, None)

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ipmi.dump_sdr(task, 'foo_file')

        mock_exec.assert_called_once_with(self.info, 'sdr dump foo_file')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_dump_sdr_fail(self, mock_exec):
        with task_manager.acquire(self.context, self.node.uuid) as task:
            mock_exec.side_effect = processutils.ProcessExecutionError()
            self.assertRaises(exception.IPMIFailure, ipmi.dump_sdr, task,
                              'foo_file')
        mock_exec.assert_called_once_with(self.info, 'sdr dump foo_file')

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test_send_raw_bytes_returns(self, mock_exec):
        fake_ret = ('foo', 'bar')
        mock_exec.return_value = fake_ret

        with task_manager.acquire(self.context, self.node.uuid) as task:
            ret = ipmi.send_raw(task, 'fake raw')

        self.assertEqual(fake_ret, ret)


class IPMIToolSocatDriverTestCase(IPMIToolDriverTestCase):

    def setUp(self):
        super(IPMIToolSocatDriverTestCase, self).setUp(terminal="socat")

    def test__get_ipmi_cmd(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            ipmi_cmd = self.driver.console._get_ipmi_cmd(driver_info,
                                                         'pw_file')
            expected_ipmi_cmd = ("ipmitool -H %(address)s -I lanplus "
                                 "-U %(user)s -f pw_file" %
                                 {'address': driver_info['address'],
                                  'user': driver_info['username']})
        self.assertEqual(expected_ipmi_cmd, ipmi_cmd)

    def test__get_ipmi_cmd_without_user(self):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            driver_info['username'] = None
            ipmi_cmd = self.driver.console._get_ipmi_cmd(driver_info,
                                                         'pw_file')
            expected_ipmi_cmd = ("ipmitool -H %(address)s -I lanplus "
                                 "-f pw_file" %
                                 {'address': driver_info['address']})
        self.assertEqual(expected_ipmi_cmd, ipmi_cmd)

    @mock.patch.object(ipmi.IPMIConsole, '_start_console', autospec=True)
    @mock.patch.object(ipmi.IPMISocatConsole, '_exec_stop_console',
                       autospec=True)
    def test_start_console(self, mock_stop, mock_start):
        mock_start.return_value = None
        mock_stop.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.driver.console.start_console(task)
            driver_info = ipmi._parse_driver_info(task.node)
        mock_stop.assert_called_once_with(self.driver.console, driver_info)
        mock_start.assert_called_once_with(
            self.driver.console, driver_info,
            console_utils.start_socat_console)

    @mock.patch.object(ipmi.IPMISocatConsole, '_get_ipmi_cmd', autospec=True)
    @mock.patch.object(console_utils, 'start_socat_console',
                       autospec=True)
    def test__start_console(self, mock_start, mock_ipmi_cmd):
        mock_start.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console._start_console(
                driver_info, console_utils.start_socat_console)

        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)
        mock_ipmi_cmd.assert_called_once_with(self.driver.console,
                                              driver_info, mock.ANY)

    @mock.patch.object(console_utils, 'start_socat_console',
                       autospec=True)
    def test__start_console_fail(self, mock_start):
        mock_start.side_effect = exception.ConsoleSubprocessFailed(
            error='error')

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.assertRaises(exception.ConsoleSubprocessFailed,
                              self.driver.console._start_console,
                              driver_info,
                              console_utils.start_socat_console)

        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)

    @mock.patch.object(console_utils, 'start_socat_console',
                       autospec=True)
    def test__start_console_fail_nodir(self, mock_start):
        mock_start.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.assertRaises(exception.ConsoleError,
                              self.driver.console._start_console,
                              driver_info,
                              console_utils.start_socat_console)
        mock_start.assert_called_once_with(self.node.uuid, mock.ANY, mock.ANY)

    @mock.patch.object(console_utils, 'make_persistent_password_file',
                       autospec=True)
    @mock.patch.object(console_utils, 'start_socat_console',
                       autospec=True)
    def test__start_console_empty_password(self, mock_start, mock_pass):
        driver_info = self.node.driver_info
        del driver_info['ipmi_password']
        self.node.driver_info = driver_info
        self.node.save()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console._start_console(
                driver_info, console_utils.start_socat_console)

        mock_pass.assert_called_once_with(mock.ANY, '\0')
        mock_start.assert_called_once_with(self.info['uuid'],
                                           self.info['port'],
                                           mock.ANY)

    @mock.patch.object(ipmi.IPMISocatConsole, '_exec_stop_console',
                       autospec=True)
    @mock.patch.object(console_utils, 'stop_socat_console',
                       autospec=True)
    def test_stop_console(self, mock_stop, mock_exec_stop):
        mock_stop.return_value = None

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console.stop_console(task)

        mock_stop.assert_called_once_with(self.info['uuid'])
        mock_exec_stop.assert_called_once_with(self.driver.console,
                                               driver_info)

    @mock.patch.object(ipmi.IPMISocatConsole, '_exec_stop_console',
                       autospec=True)
    @mock.patch.object(ironic_utils, 'unlink_without_raise',
                       autospec=True)
    @mock.patch.object(console_utils, 'stop_socat_console',
                       autospec=True)
    def test_stop_console_fail(self, mock_stop, mock_unlink, mock_exec_stop):
        mock_stop.side_effect = exception.ConsoleError()

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            self.assertRaises(exception.ConsoleError,
                              self.driver.console.stop_console,
                              task)

        mock_stop.assert_called_once_with(self.node.uuid)
        mock_unlink.assert_called_once_with(
            ipmi._console_pwfile_path(self.node.uuid))
        self.assertFalse(mock_exec_stop.called)

    @mock.patch.object(ipmi, '_exec_ipmitool', autospec=True)
    def test__exec_stop_console(self, mock_exec):
        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:

            driver_info = ipmi._parse_driver_info(task.node)
            self.driver.console._exec_stop_console(driver_info)

        mock_exec.assert_called_once_with(
            driver_info, 'sol deactivate', check_exit_code=[0, 1])

    @mock.patch.object(console_utils, 'get_socat_console_url',
                       autospec=True)
    def test_get_console(self, mock_get_url):
        url = 'tcp://localhost:4201'
        mock_get_url.return_value = url
        expected = {'type': 'socat', 'url': url}

        with task_manager.acquire(self.context,
                                  self.node.uuid) as task:
            console_info = self.driver.console.get_console(task)

        self.assertEqual(expected, console_info)
        mock_get_url.assert_called_once_with(self.info['port'])
