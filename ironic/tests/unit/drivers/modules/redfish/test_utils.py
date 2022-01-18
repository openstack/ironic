# Copyright 2017 Red Hat, Inc.
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

import collections
import copy
import os
import time

import mock
from oslo_config import cfg
from oslo_utils import importutils
import requests

from ironic.common import exception
from ironic.drivers.modules.redfish import utils as redfish_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

sushy = importutils.try_import('sushy')

INFO_DICT = db_utils.get_test_redfish_info()


class RedfishUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishUtilsTestCase, self).setUp()
        # Default configurations
        self.config(enabled_hardware_types=['redfish'],
                    enabled_power_interfaces=['redfish'],
                    enabled_boot_interfaces=['redfish-virtual-media'],
                    enabled_management_interfaces=['redfish'])
        # Redfish specific configurations
        self.config(connection_attempts=1, group='redfish')
        self.node = obj_utils.create_test_node(
            self.context, driver='redfish', driver_info=INFO_DICT)
        self.parsed_driver_info = {
            'address': 'https://example.com',
            'system_id': '/redfish/v1/Systems/FAKESYSTEM',
            'username': 'username',
            'password': 'password',
            'verify_ca': True,
            'auth_type': 'auto',
            'node_uuid': self.node.uuid
        }

    def test_parse_driver_info(self):
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme(self):
        self.node.driver_info['redfish_address'] = 'example.com'
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme_with_port(self):
        self.node.driver_info['redfish_address'] = 'example.com:42'
        self.parsed_driver_info['address'] = 'https://example.com:42'
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_missing_info(self):
        for prop in redfish_utils.REQUIRED_PROPERTIES:
            self.node.driver_info = INFO_DICT.copy()
            self.node.driver_info.pop(prop)
            self.assertRaises(exception.MissingParameterValue,
                              redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_address(self):
        for value in ['/banana!', 42]:
            self.node.driver_info['redfish_address'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'Invalid Redfish address',
                                   redfish_utils.parse_driver_info, self.node)

    @mock.patch.object(os.path, 'isdir', autospec=True)
    def test_parse_driver_info_path_verify_ca(self,
                                              mock_isdir):
        mock_isdir.return_value = True
        fake_path = '/path/to/a/valid/CA'
        self.node.driver_info['redfish_verify_ca'] = fake_path
        self.parsed_driver_info['verify_ca'] = fake_path

        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)
        mock_isdir.assert_called_once_with(fake_path)

    @mock.patch.object(os.path, 'isfile', autospec=True)
    def test_parse_driver_info_valid_capath(self, mock_isfile):
        mock_isfile.return_value = True
        fake_path = '/path/to/a/valid/CA.pem'
        self.node.driver_info['redfish_verify_ca'] = fake_path
        self.parsed_driver_info['verify_ca'] = fake_path

        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)
        mock_isfile.assert_called_once_with(fake_path)

    def test_parse_driver_info_invalid_value_verify_ca(self):
        # Integers are not supported
        self.node.driver_info['redfish_verify_ca'] = 123456
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Invalid value type',
                               redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_system_id(self):
        # Integers are not supported
        self.node.driver_info['redfish_system_id'] = 123
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'The value should be a path',
                               redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_missing_system_id(self):
        self.node.driver_info.pop('redfish_system_id')
        redfish_utils.parse_driver_info(self.node)

    def test_parse_driver_info_valid_string_value_verify_ca(self):
        for value in ('0', 'f', 'false', 'off', 'n', 'no'):
            self.node.driver_info['redfish_verify_ca'] = value
            response = redfish_utils.parse_driver_info(self.node)
            parsed_driver_info = copy.deepcopy(self.parsed_driver_info)
            parsed_driver_info['verify_ca'] = False
            self.assertEqual(parsed_driver_info, response)

        for value in ('1', 't', 'true', 'on', 'y', 'yes'):
            self.node.driver_info['redfish_verify_ca'] = value
            response = redfish_utils.parse_driver_info(self.node)
            self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_invalid_string_value_verify_ca(self):
        for value in ('xyz', '*', '!123', '123'):
            self.node.driver_info['redfish_verify_ca'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'The value should be a Boolean',
                                   redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_valid_auth_type(self):
        for value in 'basic', 'session', 'auto':
            self.node.driver_info['redfish_auth_type'] = value
            response = redfish_utils.parse_driver_info(self.node)
            self.parsed_driver_info['auth_type'] = value
            self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_invalid_auth_type(self):
        for value in 'BasiC', 'SESSION', 'Auto':
            self.node.driver_info['redfish_auth_type'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'The value should be one of ',
                                   redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_with_root_prefix(self):
        test_redfish_address = 'https://example.com/test/redfish/v0/'
        self.node.driver_info['redfish_address'] = test_redfish_address
        self.parsed_driver_info['root_prefix'] = '/test/redfish/v0/'
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system(self, mock_sushy):
        fake_conn = mock_sushy.return_value
        fake_system = fake_conn.get_system.return_value
        response = redfish_utils.get_system(self.node)
        self.assertEqual(fake_system, response)
        fake_conn.get_system.assert_called_once_with(
            '/redfish/v1/Systems/FAKESYSTEM')

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system_resource_not_found(self, mock_sushy):
        fake_conn = mock_sushy.return_value
        fake_conn.get_system.side_effect = (
            sushy.exceptions.ResourceNotFoundError('GET',
                                                   '/',
                                                   requests.Response()))

        self.assertRaises(exception.RedfishError,
                          redfish_utils.get_system, self.node)
        fake_conn.get_system.assert_called_once_with(
            '/redfish/v1/Systems/FAKESYSTEM')

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system_multiple_systems(self, mock_sushy):
        self.node.driver_info.pop('redfish_system_id')
        fake_conn = mock_sushy.return_value
        redfish_utils.get_system(self.node)
        fake_conn.get_system.assert_called_once_with(None)

    @mock.patch('time.sleep', autospec=True)
    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system_resource_connection_error_retry(self, mock_sushy,
                                                        mock_sleep):
        # Redfish specific configurations
        self.config(connection_attempts=3, group='redfish')

        fake_conn = mock.Mock()
        fake_conn.get_system.side_effect = sushy.exceptions.ConnectionError()
        mock_sushy.return_value = fake_conn

        self.assertRaises(exception.RedfishConnectionError,
                          redfish_utils.get_system, self.node)

        expected_get_system_calls = [
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
        ]
        fake_conn.get_system.assert_has_calls(expected_get_system_calls)
        mock_sleep.assert_called_with(
            redfish_utils.CONF.redfish.connection_retry_interval)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system_resource_access_error_retry(self, mock_sushy):

        # Sushy access errors HTTP Errors
        class fake_response(object):
            status_code = 401
            body = None

            def json():
                return {}

        fake_conn = mock_sushy.return_value
        fake_system = mock.Mock()
        fake_conn.get_system.side_effect = iter(
            [
                sushy.exceptions.AccessError(
                    method='GET',
                    url='http://path/to/url',
                    response=fake_response),
                fake_system,
            ])

        self.assertRaises(exception.RedfishError,
                          redfish_utils.get_system, self.node)
        # Retry, as in next power sync perhaps
        client = redfish_utils.get_system(self.node)
        client('foo')

        expected_get_system_calls = [
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
        ]
        fake_conn.get_system.assert_has_calls(expected_get_system_calls)
        fake_system.assert_called_with('foo')
        self.assertEqual(fake_conn.get_system.call_count, 2)

    @mock.patch.object(time, 'sleep', lambda seconds: None)
    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_get_system_resource_attribute_error(self, mock_sushy):

        fake_conn = mock_sushy.return_value
        fake_system = mock.Mock()
        fake_conn.get_system.side_effect = iter(
            [
                AttributeError,
                fake_system,
            ])
        # We need to check for AttributeError explicitly as
        # otherwise we break existing tests if we try to catch
        # it explicitly.
        self.assertRaises(exception.RedfishError,
                          redfish_utils.get_system, self.node)
        # Retry, as in next power sync perhaps
        client = redfish_utils.get_system(self.node)
        client('bar')
        expected_get_system_calls = [
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
        ]

        fake_conn.get_system.assert_has_calls(expected_get_system_calls)
        fake_system.assert_called_once_with('bar')
        self.assertEqual(fake_conn.get_system.call_count, 2)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_ensure_session_reuse(self, mock_sushy):
        redfish_utils.get_system(self.node)
        redfish_utils.get_system(self.node)
        self.assertEqual(1, mock_sushy.call_count)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    def test_ensure_new_session_address(self, mock_sushy):
        self.node.driver_info['redfish_address'] = 'http://bmc.foo'
        redfish_utils.get_system(self.node)
        self.node.driver_info['redfish_address'] = 'http://bmc.bar'
        redfish_utils.get_system(self.node)
        self.assertEqual(2, mock_sushy.call_count)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    def test_ensure_new_session_username(self, mock_sushy):
        self.node.driver_info['redfish_username'] = 'foo'
        redfish_utils.get_system(self.node)
        self.node.driver_info['redfish_username'] = 'bar'
        redfish_utils.get_system(self.node)
        self.assertEqual(2, mock_sushy.call_count)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache.AUTH_CLASSES', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.SessionCache._sessions',
                collections.OrderedDict())
    def test_ensure_basic_session_caching(self, mock_auth, mock_sushy):
        self.node.driver_info['redfish_auth_type'] = 'basic'
        mock_session_or_basic_auth = mock_auth['auto']
        redfish_utils.get_system(self.node)
        mock_sushy.assert_called_with(
            mock.ANY, verify=mock.ANY,
            auth=mock_session_or_basic_auth.return_value,
        )
        self.assertEqual(len(redfish_utils.SessionCache._sessions), 1)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    def test_expire_old_sessions(self, mock_sushy):
        cfg.CONF.set_override('connection_cache_size', 10, 'redfish')
        for num in range(20):
            self.node.driver_info['redfish_username'] = 'foo-%d' % num
            redfish_utils.get_system(self.node)

        self.assertEqual(mock_sushy.call_count, 20)
        self.assertEqual(len(redfish_utils.SessionCache._sessions), 10)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_disabled_sessions_cache(self, mock_sushy):
        cfg.CONF.set_override('connection_cache_size', 0, 'redfish')
        for num in range(2):
            self.node.driver_info['redfish_username'] = 'foo-%d' % num
            redfish_utils.get_system(self.node)

        self.assertEqual(mock_sushy.call_count, 2)
        self.assertEqual(len(redfish_utils.SessionCache._sessions), 0)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache.AUTH_CLASSES', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_auth_auto(self, mock_auth, mock_sushy):
        redfish_utils.get_system(self.node)
        mock_session_or_basic_auth = mock_auth['auto']
        mock_session_or_basic_auth.assert_called_with(
            username=self.parsed_driver_info['username'],
            password=self.parsed_driver_info['password']
        )
        mock_sushy.assert_called_with(
            self.parsed_driver_info['address'],
            auth=mock_session_or_basic_auth.return_value,
            verify=True)

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache.AUTH_CLASSES', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_auth_session(self, mock_auth, mock_sushy):
        self.node.driver_info['redfish_auth_type'] = 'session'
        mock_session_auth = mock_auth['session']
        redfish_utils.get_system(self.node)
        mock_session_auth.assert_called_with(
            username=self.parsed_driver_info['username'],
            password=self.parsed_driver_info['password']
        )
        mock_sushy.assert_called_with(
            mock.ANY, verify=mock.ANY,
            auth=mock_session_auth.return_value
        )

    @mock.patch.object(sushy, 'Sushy', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache.AUTH_CLASSES', autospec=True)
    @mock.patch('ironic.drivers.modules.redfish.utils.'
                'SessionCache._sessions', {})
    def test_auth_basic(self, mock_auth, mock_sushy):
        self.node.driver_info['redfish_auth_type'] = 'basic'
        mock_basic_auth = mock_auth['basic']
        redfish_utils.get_system(self.node)
        mock_basic_auth.assert_called_with(
            username=self.parsed_driver_info['username'],
            password=self.parsed_driver_info['password']
        )
        sushy.Sushy.assert_called_with(
            mock.ANY, verify=mock.ANY,
            auth=mock_basic_auth.return_value
        )
