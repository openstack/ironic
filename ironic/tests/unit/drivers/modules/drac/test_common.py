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
Test class for common methods used by DRAC modules.
"""

import dracclient.client
import mock

from ironic.common import exception
from ironic.drivers.modules.drac import common as drac_common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracCommonMethodsTestCase(db_base.DbTestCase):

    def test_parse_driver_info(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        info = drac_common.parse_driver_info(node)
        self.assertEqual(INFO_DICT['drac_address'], info['drac_address'])
        self.assertEqual(INFO_DICT['drac_port'], info['drac_port'])
        self.assertEqual(INFO_DICT['drac_path'], info['drac_path'])
        self.assertEqual(INFO_DICT['drac_protocol'], info['drac_protocol'])
        self.assertEqual(INFO_DICT['drac_username'], info['drac_username'])
        self.assertEqual(INFO_DICT['drac_password'], info['drac_password'])

    @mock.patch.object(drac_common.LOG, 'warning')
    def test_parse_driver_info_drac_host(self, mock_log):
        driver_info = db_utils.get_test_drac_info()
        driver_info['drac_host'] = '4.5.6.7'
        driver_info.pop('drac_address')
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=driver_info)
        info = drac_common.parse_driver_info(node)
        self.assertEqual('4.5.6.7', info['drac_address'])
        self.assertNotIn('drac_host', info)
        self.assertTrue(mock_log.called)

    @mock.patch.object(drac_common.LOG, 'warning')
    def test_parse_driver_info_drac_host_and_drac_address(self, mock_log):
        driver_info = db_utils.get_test_drac_info()
        driver_info['drac_host'] = '4.5.6.7'
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=driver_info)
        info = drac_common.parse_driver_info(node)
        self.assertEqual('4.5.6.7', driver_info['drac_host'])
        self.assertEqual(driver_info['drac_address'], info['drac_address'])
        self.assertTrue(mock_log.called)

    def test_parse_driver_info_missing_host(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_address']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_port']

        info = drac_common.parse_driver_info(node)
        self.assertEqual(443, info['drac_port'])

    def test_parse_driver_info_invalid_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        node.driver_info['drac_port'] = 'foo'
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_path(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_path']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('/wsman', info['drac_path'])

    def test_parse_driver_info_missing_protocol(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_protocol']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('https', info['drac_protocol'])

    def test_parse_driver_info_invalid_protocol(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        node.driver_info['drac_protocol'] = 'foo'

        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_username(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_username']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_password(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_password']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    @mock.patch.object(dracclient.client, 'DRACClient', autospec=True)
    def test_get_drac_client(self, mock_dracclient):
        expected_call = mock.call('1.2.3.4', 'admin', 'fake', 443, '/wsman',
                                  'https')
        node = obj_utils.create_test_node(self.context,
                                          driver='fake_drac',
                                          driver_info=INFO_DICT)

        drac_common.get_drac_client(node)

        self.assertEqual(mock_dracclient.mock_calls, [expected_call])
