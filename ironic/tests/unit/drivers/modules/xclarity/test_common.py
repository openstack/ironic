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

from unittest import mock

from oslo_utils import importutils

from ironic.common import exception
from ironic.drivers.modules.xclarity import common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

xclarity_client = importutils.try_import('xclarity_client.client')
xclarity_exceptions = importutils.try_import('xclarity_client.exceptions')
xclarity_constants = importutils.try_import('xclarity_client.constants')

INFO_DICT = db_utils.get_test_xclarity_driver_info()


class XClarityCommonTestCase(db_base.DbTestCase):

    def setUp(self):
        super(XClarityCommonTestCase, self).setUp()
        self.config(enabled_hardware_types=['xclarity'],
                    enabled_power_interfaces=['xclarity'],
                    enabled_management_interfaces=['xclarity'])
        self.node = obj_utils.create_test_node(
            self.context, driver='xclarity',
            properties=db_utils.get_test_xclarity_properties(),
            driver_info=INFO_DICT)

    def test_parse_driver_info(self):
        info = common.parse_driver_info(self.node)
        self.assertEqual(INFO_DICT['xclarity_manager_ip'],
                         info['xclarity_manager_ip'])
        self.assertEqual(INFO_DICT['xclarity_username'],
                         info['xclarity_username'])
        self.assertEqual(INFO_DICT['xclarity_password'],
                         info['xclarity_password'])
        self.assertEqual(INFO_DICT['xclarity_port'], info['xclarity_port'])
        self.assertEqual(INFO_DICT['xclarity_hardware_id'],
                         info['xclarity_hardware_id'])

    def test_parse_driver_info_missing_hardware_id(self):
        del self.node.driver_info['xclarity_hardware_id']
        self.assertRaises(exception.InvalidParameterValue,
                          common.parse_driver_info, self.node)

    def test_parse_driver_info_get_param_from_config(self):
        del self.node.driver_info['xclarity_manager_ip']
        del self.node.driver_info['xclarity_username']
        del self.node.driver_info['xclarity_password']
        self.config(manager_ip='5.6.7.8', group='xclarity')
        self.config(username='user', group='xclarity')
        self.config(password='password', group='xclarity')
        info = common.parse_driver_info(self.node)
        self.assertEqual('5.6.7.8', info['xclarity_manager_ip'])
        self.assertEqual('user', info['xclarity_username'])
        self.assertEqual('password', info['xclarity_password'])

    def test_parse_driver_info_missing_driver_info_and_config(self):
        del self.node.driver_info['xclarity_manager_ip']
        del self.node.driver_info['xclarity_username']
        del self.node.driver_info['xclarity_password']
        e = self.assertRaises(exception.InvalidParameterValue,
                              common.parse_driver_info, self.node)
        self.assertIn('xclarity_manager_ip', str(e))
        self.assertIn('xclarity_username', str(e))
        self.assertIn('xclarity_password', str(e))

    def test_parse_driver_info_invalid_port(self):
        self.node.driver_info['xclarity_port'] = 'asd'
        self.assertRaises(exception.InvalidParameterValue,
                          common.parse_driver_info, self.node)
        self.node.driver_info['xclarity_port'] = '65536'
        self.assertRaises(exception.InvalidParameterValue,
                          common.parse_driver_info, self.node)
        self.node.driver_info['xclarity_port'] = 'invalid'
        self.assertRaises(exception.InvalidParameterValue,
                          common.parse_driver_info, self.node)
        self.node.driver_info['xclarity_port'] = '-1'
        self.assertRaises(exception.InvalidParameterValue,
                          common.parse_driver_info, self.node)

    @mock.patch.object(xclarity_client, 'Client', autospec=True)
    def test_get_xclarity_client(self, mock_xclarityclient):
        expected_call = mock.call(ip='1.2.3.4', password='fake', port=443,
                                  username='USERID')
        common.get_xclarity_client(self.node)

        self.assertEqual(mock_xclarityclient.mock_calls, [expected_call])

    def test_get_server_hardware_id(self):
        driver_info = self.node.driver_info
        driver_info['xclarity_hardware_id'] = 'test'
        self.node.driver_info = driver_info
        result = common.get_server_hardware_id(self.node)
        self.assertEqual(result, 'test')
