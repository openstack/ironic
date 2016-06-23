#    Copyright 2015, Cisco Systems.

#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at

#        http://www.apache.org/licenses/LICENSE-2.0

#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Test class for common methods used by UCS modules."""

import mock
from oslo_utils import importutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers.modules.ucs import helper as ucs_helper
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

ucs_error = importutils.try_import('UcsSdk.utils.exception')

INFO_DICT = db_utils.get_test_ucs_info()


class UcsValidateParametersTestCase(db_base.DbTestCase):

    def setUp(self):
        super(UcsValidateParametersTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_ucs")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ucs',
                                               driver_info=INFO_DICT)
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.helper = ucs_helper.CiscoUcsHelper(task)

    def test_parse_driver_info(self):
        info = ucs_helper.parse_driver_info(self.node)

        self.assertEqual(INFO_DICT['ucs_address'], info['ucs_address'])
        self.assertEqual(INFO_DICT['ucs_username'], info['ucs_username'])
        self.assertEqual(INFO_DICT['ucs_password'], info['ucs_password'])
        self.assertEqual(INFO_DICT['ucs_service_profile'],
                         info['ucs_service_profile'])

    def test_parse_driver_info_missing_address(self):

        del self.node.driver_info['ucs_address']
        self.assertRaises(exception.MissingParameterValue,
                          ucs_helper.parse_driver_info, self.node)

    def test_parse_driver_info_missing_username(self):
        del self.node.driver_info['ucs_username']
        self.assertRaises(exception.MissingParameterValue,
                          ucs_helper.parse_driver_info, self.node)

    def test_parse_driver_info_missing_password(self):
        del self.node.driver_info['ucs_password']
        self.assertRaises(exception.MissingParameterValue,
                          ucs_helper.parse_driver_info, self.node)

    def test_parse_driver_info_missing_service_profile(self):
        del self.node.driver_info['ucs_service_profile']
        self.assertRaises(exception.MissingParameterValue,
                          ucs_helper.parse_driver_info, self.node)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    def test_connect_ucsm(self, mock_helper):
        mock_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.helper.connect_ucsm()

            mock_helper.generate_ucsm_handle.assert_called_once_with(
                task.node.driver_info['ucs_address'],
                task.node.driver_info['ucs_username'],
                task.node.driver_info['ucs_password']
            )

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper',
                spec_set=True, autospec=True)
    def test_connect_ucsm_fail(self, mock_helper):
        side_effect = ucs_error.UcsConnectionError(
            message='connecting to ucsm',
            error='failed')
        mock_helper.generate_ucsm_handle.side_effect = side_effect
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.assertRaises(exception.UcsConnectionError,
                              self.helper.connect_ucsm
                              )
            mock_helper.generate_ucsm_handle.assert_called_once_with(
                task.node.driver_info['ucs_address'],
                task.node.driver_info['ucs_username'],
                task.node.driver_info['ucs_password']
            )

    @mock.patch('ironic.drivers.modules.ucs.helper',
                autospec=True)
    def test_logout(self, mock_helper):
        self.helper.logout()


class UcsCommonMethodsTestcase(db_base.DbTestCase):

    def setUp(self):
        super(UcsCommonMethodsTestcase, self).setUp()
        self.dbapi = dbapi.get_instance()
        mgr_utils.mock_the_extension_manager(driver="fake_ucs")
        self.node = obj_utils.create_test_node(self.context,
                                               driver='fake_ucs',
                                               driver_info=INFO_DICT.copy())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            self.helper = ucs_helper.CiscoUcsHelper(task)

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper', autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.helper.CiscoUcsHelper',
                autospec=True)
    def test_requires_ucs_client_ok_logout(self, mc_helper, mock_ucs_helper):
        mock_helper = mc_helper.return_value
        mock_helper.logout.return_value = None
        mock_working_function = mock.Mock()
        mock_working_function.__name__ = "Working"
        mock_working_function.return_valure = "Success"
        mock_ucs_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:
            wont_error = ucs_helper.requires_ucs_client(
                mock_working_function)
            wont_error(wont_error, task)
            mock_helper.logout.assert_called_once_with()

    @mock.patch('ironic.drivers.modules.ucs.helper.ucs_helper', autospec=True)
    @mock.patch('ironic.drivers.modules.ucs.helper.CiscoUcsHelper',
                autospec=True)
    def test_requires_ucs_client_fail_logout(self, mc_helper, mock_ucs_helper):
        mock_helper = mc_helper.return_value
        mock_helper.logout.return_value = None
        mock_broken_function = mock.Mock()
        mock_broken_function.__name__ = "Broken"
        mock_broken_function.side_effect = exception.IronicException()
        mock_ucs_helper.generate_ucsm_handle.return_value = (True, mock.Mock())
        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=True) as task:

            will_error = ucs_helper.requires_ucs_client(mock_broken_function)
            self.assertRaises(exception.IronicException,
                              will_error, will_error, task)
            mock_helper.logout.assert_called_once_with()
