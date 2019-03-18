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
"""Test class for iBMC Driver common utils."""

import copy
import os

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.ibmc import utils
from ironic.tests.unit.drivers.modules.ibmc import base

constants = importutils.try_import('ibmc_client.constants')
ibmc_client = importutils.try_import('ibmc_client')
ibmc_error = importutils.try_import('ibmc_client.exceptions')


class IBMCUtilsTestCase(base.IBMCTestCase):

    def setUp(self):
        super(IBMCUtilsTestCase, self).setUp()
        # Redfish specific configurations
        self.config(connection_attempts=2, group='ibmc')
        self.parsed_driver_info = {
            'address': 'https://example.com',
            'username': 'username',
            'password': 'password',
            'verify_ca': True,
        }

    def test_parse_driver_info(self):
        response = utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme(self):
        self.node.driver_info['ibmc_address'] = 'example.com'
        response = utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme_with_port(self):
        self.node.driver_info['ibmc_address'] = 'example.com:42'
        self.parsed_driver_info['address'] = 'https://example.com:42'
        response = utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_missing_info(self):
        for prop in utils.REQUIRED_PROPERTIES:
            self.node.driver_info = self.driver_info.copy()
            self.node.driver_info.pop(prop)
            self.assertRaises(exception.MissingParameterValue,
                              utils.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_address(self):
        for value in ['/banana!', '#location', '?search=hello']:
            self.node.driver_info['ibmc_address'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'Invalid iBMC address',
                                   utils.parse_driver_info, self.node)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_parse_driver_info_path_verify_ca(self,
                                              mock_isdir):
        mock_isdir.return_value = True
        fake_path = '/path/to/a/valid/CA'
        self.node.driver_info['ibmc_verify_ca'] = fake_path
        self.parsed_driver_info['verify_ca'] = fake_path

        response = utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)
        mock_isdir.assert_called_once_with(fake_path)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_parse_driver_info_valid_capath(self, mock_isfile):
        mock_isfile.return_value = True
        fake_path = '/path/to/a/valid/CA.pem'
        self.node.driver_info['ibmc_verify_ca'] = fake_path
        self.parsed_driver_info['verify_ca'] = fake_path

        response = utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)
        mock_isfile.assert_called_once_with(fake_path)

    def test_parse_driver_info_invalid_value_verify_ca(self):
        # Integers are not supported
        self.node.driver_info['ibmc_verify_ca'] = 123456
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Invalid value type',
                               utils.parse_driver_info, self.node)

    def test_parse_driver_info_valid_string_value_verify_ca(self):
        for value in ('0', 'f', 'false', 'off', 'n', 'no'):
            self.node.driver_info['ibmc_verify_ca'] = value
            response = utils.parse_driver_info(self.node)
            parsed_driver_info = copy.deepcopy(self.parsed_driver_info)
            parsed_driver_info['verify_ca'] = False
            self.assertEqual(parsed_driver_info, response)

        for value in ('1', 't', 'true', 'on', 'y', 'yes'):
            self.node.driver_info['ibmc_verify_ca'] = value
            response = utils.parse_driver_info(self.node)
            self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_invalid_string_value_verify_ca(self):
        for value in ('xyz', '*', '!123', '123'):
            self.node.driver_info['ibmc_verify_ca'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'The value should be a Boolean',
                                   utils.parse_driver_info, self.node)

    def test_revert_dictionary(self):
        data = {
            "key1": "value1",
            "key2": "value2"
        }

        revert = utils.revert_dictionary(data)
        self.assertEqual({
            "value1": "key1",
            "value2": "key2"
        }, revert)

    @mock.patch.object(ibmc_client, 'connect', autospec=True)
    def test_handle_ibmc_exception_retry(self, connect_ibmc):

        @utils.handle_ibmc_exception('get IBMC system')
        def get_ibmc_system(_task):
            driver_info = utils.parse_driver_info(_task.node)
            with ibmc_client.connect(**driver_info) as _conn:
                return _conn.system.get()

        conn = self.mock_ibmc_conn(connect_ibmc)
        # Mocks
        conn.system.get.side_effect = [
            ibmc_error.ConnectionError(url=self.ibmc['address'],
                                       error='Failed to connect to host'),
            mock.PropertyMock(
                boot_source_override=mock.PropertyMock(
                    target=constants.BOOT_SOURCE_TARGET_PXE,
                    enabled=constants.BOOT_SOURCE_ENABLED_CONTINUOUS
                )
            )
        ]

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            system = get_ibmc_system(task)

            # Asserts
            self.assertEqual(constants.BOOT_SOURCE_TARGET_PXE,
                             system.boot_source_override.target)
            self.assertEqual(constants.BOOT_SOURCE_ENABLED_CONTINUOUS,
                             system.boot_source_override.enabled)

            # 1 failed, 1 succeed
            connect_ibmc.assert_called_with(**self.ibmc)
            self.assertEqual(2, connect_ibmc.call_count)

            # 1 failed, 1 succeed
            self.assertEqual(2, conn.system.get.call_count)
