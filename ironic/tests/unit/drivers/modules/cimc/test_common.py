# Copyright 2015, Cisco Systems.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from oslo_config import cfg
from oslo_utils import importutils
from oslo_utils import uuidutils

from ironic.common import exception
from ironic.conductor import task_manager
from ironic.drivers.modules.cimc import common as cimc_common
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils
from ironic.tests.unit.objects import utils as obj_utils

INFO_DICT = db_utils.get_test_cimc_info()

imcsdk = importutils.try_import('ImcSdk')

CONF = cfg.CONF


class CIMCBaseTestCase(db_base.DbTestCase):

    def setUp(self):
        super(CIMCBaseTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver="fake_cimc")
        self.node = obj_utils.create_test_node(
            self.context,
            driver='fake_cimc',
            driver_info=INFO_DICT,
            instance_uuid=uuidutils.generate_uuid())
        CONF.set_override('max_retry', 2, 'cimc')
        CONF.set_override('action_interval', 0, 'cimc')


class ParseDriverInfoTestCase(CIMCBaseTestCase):

    def test_parse_driver_info(self):
        info = cimc_common.parse_driver_info(self.node)

        self.assertEqual(INFO_DICT['cimc_address'], info['cimc_address'])
        self.assertEqual(INFO_DICT['cimc_username'], info['cimc_username'])
        self.assertEqual(INFO_DICT['cimc_password'], info['cimc_password'])

    def test_parse_driver_info_missing_address(self):
        del self.node.driver_info['cimc_address']
        self.assertRaises(exception.MissingParameterValue,
                          cimc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_username(self):
        del self.node.driver_info['cimc_username']
        self.assertRaises(exception.MissingParameterValue,
                          cimc_common.parse_driver_info, self.node)

    def test_parse_driver_info_missing_password(self):
        del self.node.driver_info['cimc_password']
        self.assertRaises(exception.MissingParameterValue,
                          cimc_common.parse_driver_info, self.node)


@mock.patch.object(cimc_common, 'cimc_handle', autospec=True)
class CIMCHandleLogin(CIMCBaseTestCase):

    def test_cimc_handle_login(self, mock_handle):
        info = cimc_common.parse_driver_info(self.node)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                cimc_common.handle_login(task, handle, info)

                handle.login.assert_called_once_with(
                    self.node.driver_info['cimc_address'],
                    self.node.driver_info['cimc_username'],
                    self.node.driver_info['cimc_password'])

    def test_cimc_handle_login_exception(self, mock_handle):
        info = cimc_common.parse_driver_info(self.node)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with mock_handle(task) as handle:
                handle.login.side_effect = imcsdk.ImcException('Boom')

                self.assertRaises(exception.CIMCException,
                                  cimc_common.handle_login,
                                  task, handle, info)

                handle.login.assert_called_once_with(
                    self.node.driver_info['cimc_address'],
                    self.node.driver_info['cimc_username'],
                    self.node.driver_info['cimc_password'])


class CIMCHandleTestCase(CIMCBaseTestCase):

    @mock.patch.object(imcsdk, 'ImcHandle', autospec=True)
    @mock.patch.object(cimc_common, 'handle_login', autospec=True)
    def test_cimc_handle(self, mock_login, mock_handle):
        mo_hand = mock.MagicMock()
        mo_hand.username = self.node.driver_info['cimc_username']
        mo_hand.password = self.node.driver_info['cimc_password']
        mo_hand.name = self.node.driver_info['cimc_address']
        mock_handle.return_value = mo_hand
        info = cimc_common.parse_driver_info(self.node)

        with task_manager.acquire(self.context, self.node.uuid,
                                  shared=False) as task:
            with cimc_common.cimc_handle(task) as handle:
                self.assertEqual(handle, mock_handle.return_value)

        mock_login.assert_called_once_with(task, mock_handle.return_value,
                                           info)
        mock_handle.return_value.logout.assert_called_once_with()
