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

import mock

from oslo_utils import importutils

from ironic.drivers.modules.xclarity import common
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

xclarity_exceptions = importutils.try_import('xclarity_client.exceptions')
xclarity_constants = importutils.try_import('xclarity_client.constants')


class XClarityCommonTestCase(db_base.DbTestCase):

    def setUp(self):
        super(XClarityCommonTestCase, self).setUp()

        self.config(manager_ip='1.2.3.4', group='xclarity')
        self.config(username='user', group='xclarity')
        self.config(password='password', group='xclarity')

        self.node = obj_utils.create_test_node(
            self.context, driver='fake-xclarity',
            properties=db_utils.get_test_xclarity_properties(),
            driver_info=db_utils.get_test_xclarity_driver_info(),
        )

    def test_get_server_hardware_id(self):
        driver_info = self.node.driver_info
        driver_info['xclarity_hardware_id'] = 'test'
        self.node.driver_info = driver_info
        result = common.get_server_hardware_id(self.node)
        self.assertEqual(result, 'test')

    @mock.patch.object(common, 'get_server_hardware_id',
                       spec_set=True, autospec=True)
    @mock.patch.object(common, 'get_xclarity_client',
                       spec_set=True, autospec=True)
    def test_check_node_managed_by_xclarity(self, mock_xc_client,
                                            mock_validate_driver_info):
        driver_info = self.node.driver_info
        driver_info['xclarity_hardware_id'] = 'abcd'
        self.node.driver_info = driver_info

        xclarity_client = mock_xc_client()
        mock_validate_driver_info.return_value = '12345'
        common.is_node_managed_by_xclarity(xclarity_client,
                                           self.node)
        xclarity_client.is_node_managed.assert_called_once_with('12345')
