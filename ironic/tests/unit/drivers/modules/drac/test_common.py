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

from unittest import mock

import dracclient.client

from ironic.common import exception
from ironic.drivers.modules.drac import common as drac_common
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.drivers.modules.drac import utils as test_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_drac_info()


class DracCommonMethodsTestCase(test_utils.BaseDracTest):
    def test_parse_driver_info(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        info = drac_common.parse_driver_info(node)
        self.assertEqual(INFO_DICT['drac_address'], info['drac_address'])
        self.assertEqual(INFO_DICT['drac_port'], info['drac_port'])
        self.assertEqual(INFO_DICT['drac_path'], info['drac_path'])
        self.assertEqual(INFO_DICT['drac_protocol'], info['drac_protocol'])
        self.assertEqual(INFO_DICT['drac_username'], info['drac_username'])
        self.assertEqual(INFO_DICT['drac_password'], info['drac_password'])

    def test_parse_driver_info_missing_host(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_address']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_port']

        info = drac_common.parse_driver_info(node)
        self.assertEqual(443, info['drac_port'])

    def test_parse_driver_info_invalid_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        node.driver_info['drac_port'] = 'foo'
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_path(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_path']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('/wsman', info['drac_path'])

    def test_parse_driver_info_missing_protocol(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_protocol']

        info = drac_common.parse_driver_info(node)
        self.assertEqual('https', info['drac_protocol'])

    def test_parse_driver_info_invalid_protocol(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        node.driver_info['drac_protocol'] = 'foo'

        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_username(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_username']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_parse_driver_info_missing_password(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)
        del node.driver_info['drac_password']
        self.assertRaises(exception.InvalidParameterValue,
                          drac_common.parse_driver_info, node)

    def test_get_drac_client(self):
        if not mock._is_instance_mock(dracclient.client):
            mock.patch.object(dracclient.client, 'DRACClient',
                              autospec=True).start()
        mock_dracclient = dracclient.client.DRACClient
        expected_call = mock.call('1.2.3.4', 'admin', 'fake', 443, '/wsman',
                                  'https')
        node = obj_utils.create_test_node(self.context,
                                          driver='idrac',
                                          driver_info=INFO_DICT)

        drac_common.get_drac_client(node)

        self.assertEqual(mock_dracclient.mock_calls, [expected_call])
