# Copyright 2015 Cloudbase Solutions Srl
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

"""
Test class for MSFT OCS common functions
"""

import mock

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.msftocs import common as msftocs_common
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_msftocs_info()


class MSFTOCSCommonTestCase(db_base.DbTestCase):
    def setUp(self):
        super(MSFTOCSCommonTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_msftocs')
        self.info = INFO_DICT
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_msftocs',
                                               driver_info=self.info)

    def test_get_client_info(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            driver_info = task.node.driver_info
            (client, blade_id) = msftocs_common.get_client_info(driver_info)

            self.assertEqual(driver_info['msftocs_base_url'], client._base_url)
            self.assertEqual(driver_info['msftocs_username'], client._username)
            self.assertEqual(driver_info['msftocs_password'], client._password)
            self.assertEqual(driver_info['msftocs_blade_id'], blade_id)

    @mock.patch.object(msftocs_common, '_is_valid_url', autospec=True)
    def test_parse_driver_info(self, mock_is_valid_url):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            msftocs_common.parse_driver_info(task.node)
            mock_is_valid_url.assert_called_once_with(
                task.node.driver_info['msftocs_base_url'])

    def test_parse_driver_info_fail_missing_param(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            del task.node.driver_info['msftocs_base_url']
            self.assertRaises(exception.MissingParameterValue,
                              msftocs_common.parse_driver_info,
                              task.node)

    def test_parse_driver_info_fail_bad_url(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info['msftocs_base_url'] = "bad-url"
            self.assertRaises(exception.InvalidParameterValue,
                              msftocs_common.parse_driver_info,
                              task.node)

    def test_parse_driver_info_fail_bad_blade_id_type(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info['msftocs_blade_id'] = "bad-blade-id"
            self.assertRaises(exception.InvalidParameterValue,
                              msftocs_common.parse_driver_info,
                              task.node)

    def test_parse_driver_info_fail_bad_blade_id_value(self):
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            task.node.driver_info['msftocs_blade_id'] = 0
            self.assertRaises(exception.InvalidParameterValue,
                              msftocs_common.parse_driver_info,
                              task.node)

    def test__is_valid_url(self):
        self.assertIs(True, msftocs_common._is_valid_url("http://fake.com"))
        self.assertIs(
            True, msftocs_common._is_valid_url("http://www.fake.com"))
        self.assertIs(True, msftocs_common._is_valid_url("http://FAKE.com"))
        self.assertIs(True, msftocs_common._is_valid_url("http://fake"))
        self.assertIs(
            True, msftocs_common._is_valid_url("http://fake.com/blah"))
        self.assertIs(True, msftocs_common._is_valid_url("http://localhost"))
        self.assertIs(True, msftocs_common._is_valid_url("https://fake.com"))
        self.assertIs(True, msftocs_common._is_valid_url("http://10.0.0.1"))
        self.assertIs(False, msftocs_common._is_valid_url("bad-url"))
        self.assertIs(False, msftocs_common._is_valid_url("http://.bad-url"))
        self.assertIs(False, msftocs_common._is_valid_url("http://bad-url$"))
        self.assertIs(False, msftocs_common._is_valid_url("http://$bad-url"))
        self.assertIs(False, msftocs_common._is_valid_url("http://bad$url"))
        self.assertIs(False, msftocs_common._is_valid_url(None))
        self.assertIs(False, msftocs_common._is_valid_url(0))
