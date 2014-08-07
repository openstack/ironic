# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""Test class for common methods used by iLO modules."""

import mock

from oslo.config import cfg
from oslo.utils import importutils

from ironic.common import exception
from ironic.db import api as dbapi
from ironic.drivers.modules.ilo import common as ilo_common
from ironic.openstack.common import context
from ironic.tests import base
from ironic.tests.db import utils as db_utils
from ironic.tests.objects import utils as obj_utils

ilo_client = importutils.try_import('proliantutils.ilo.ribcl')


INFO_DICT = db_utils.get_test_ilo_info()
CONF = cfg.CONF


class IloCommonMethodsTestCase(base.TestCase):

    def setUp(self):
        super(IloCommonMethodsTestCase, self).setUp()
        self.dbapi = dbapi.get_instance()
        self.context = context.get_admin_context()

    def test_parse_driver_info(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        info = ilo_common.parse_driver_info(node)

        self.assertIsNotNone(info.get('ilo_address'))
        self.assertIsNotNone(info.get('ilo_username'))
        self.assertIsNotNone(info.get('ilo_password'))
        self.assertIsNotNone(info.get('client_timeout'))
        self.assertIsNotNone(info.get('client_port'))

    def test_parse_driver_info_missing_address(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        del node.driver_info['ilo_address']
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, node)

    def test_parse_driver_info_missing_username(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        del node.driver_info['ilo_username']
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, node)

    def test_parse_driver_info_missing_password(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        del node.driver_info['ilo_password']
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, node)

    def test_parse_driver_info_invalid_timeout(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        node.driver_info['client_timeout'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, node)

    def test_parse_driver_info_invalid_port(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        node.driver_info['client_port'] = 'qwe'
        self.assertRaises(exception.InvalidParameterValue,
                          ilo_common.parse_driver_info, node)

    def test_parse_driver_info_missing_multiple_params(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        del node.driver_info['ilo_password']
        node.driver_info['client_port'] = 'qwe'
        try:
            ilo_common.parse_driver_info(node)
            self.fail("parse_driver_info did not throw exception.")
        except exception.InvalidParameterValue as e:
            self.assertIn('ilo_password', str(e))
            self.assertIn('client_port', str(e))

    @mock.patch.object(ilo_common, 'ilo_client')
    def test_get_ilo_object(self, ilo_client_mock):
        info = INFO_DICT
        info['client_timeout'] = 60
        info['client_port'] = 443
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        ilo_client_mock.IloClient.return_value = 'ilo_object'
        returned_ilo_object = ilo_common.get_ilo_object(node)
        ilo_client_mock.IloClient.assert_called_with(
            INFO_DICT['ilo_address'],
            INFO_DICT['ilo_username'],
            INFO_DICT['ilo_password'],
            info['client_timeout'],
            info['client_port'])
        self.assertEqual('ilo_object', returned_ilo_object)

    @mock.patch.object(ilo_common, 'ilo_client')
    def test_get_ilo_license(self, ilo_client_mock):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        ilo_advanced_license = {'LICENSE_TYPE': 'iLO 3 Advanced'}
        ilo_standard_license = {'LICENSE_TYPE': 'iLO 3'}

        ilo_mock_object = ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_all_licenses.return_value = ilo_advanced_license

        license = ilo_common.get_ilo_license(node)
        self.assertEqual(license, ilo_common.ADVANCED_LICENSE)

        ilo_mock_object.get_all_licenses.return_value = ilo_standard_license
        license = ilo_common.get_ilo_license(node)
        self.assertEqual(license, ilo_common.STANDARD_LICENSE)

    @mock.patch.object(ilo_common, 'ilo_client')
    def test_get_ilo_license_fail(self, ilo_client_mock):
        node = obj_utils.create_test_node(self.context,
                                          driver='ilo',
                                          driver_info=INFO_DICT)
        ilo_client_mock.IloError = Exception
        ilo_mock_object = ilo_client_mock.IloClient.return_value
        ilo_mock_object.get_all_licenses.side_effect = [Exception()]
        self.assertRaises(exception.IloOperationError,
                          ilo_common.get_ilo_license,
                          node)
