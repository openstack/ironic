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

"""Test class for Ironic SeaMicro driver."""

import mock

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers.modules import seamicro
from ironic.tests import base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as db_base
from ironic.tests.db import utils as db_utils

INFO_DICT = db_utils.get_test_seamicro_info()


class Fake_Server():
    def __init__(self, active=False, *args, **kwargs):
        self.active = active

    def power_on(self):
        self.active = True

    def power_off(self, force=False):
        self.active = False

    def reset(self):
        self.active = True


class SeaMicroValidateParametersTestCase(base.TestCase):

    def test__parse_driver_info_good(self):
        # make sure we get back the expected things
        node = db_utils.get_test_node(driver='fake_seamicro',
                                      driver_info=INFO_DICT)
        info = seamicro._parse_driver_info(node)
        self.assertIsNotNone(info.get('api_endpoint'))
        self.assertIsNotNone(info.get('username'))
        self.assertIsNotNone(info.get('password'))
        self.assertIsNotNone(info.get('server_id'))
        self.assertIsNotNone(info.get('uuid'))

    def test__parse_driver_info_missing_api_endpoint(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_api_endpoint']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_username(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_username']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_password(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_password']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._parse_driver_info,
                          node)

    def test__parse_driver_info_missing_server_id(self):
        # make sure error is raised when info is missing
        info = dict(INFO_DICT)
        del info['seamicro_server_id']
        node = db_utils.get_test_node(driver_info=info)
        self.assertRaises(exception.InvalidParameterValue,
                          seamicro._parse_driver_info,
                          node)


class SeaMicroPrivateMethodsTestCase(base.TestCase):

    def setUp(self):
        super(SeaMicroPrivateMethodsTestCase, self).setUp()
        self.node = db_utils.get_test_node(driver='fake_seamicro',
                                           driver_info=INFO_DICT)

        self.Server = Fake_Server

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_on(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_off(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__get_power_status_error(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=None)
        pstate = seamicro._get_power_status(self.node)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_on_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=False)
        pstate = seamicro._power_on(self.node, timeout=2)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_on_fail(self, mock_get_server):
        def fake_power_on():
            return

        server = self.Server(active=False)
        server.power_on = fake_power_on
        mock_get_server.return_value = server
        pstate = seamicro._power_on(self.node, timeout=2)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_off_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._power_off(self.node, timeout=2)
        self.assertEqual(states.POWER_OFF, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__power_off_fail(self, mock_get_server):
        def fake_power_off():
            return
        server = self.Server(active=True)
        server.power_off = fake_power_off
        mock_get_server.return_value = server
        pstate = seamicro._power_off(self.node, timeout=2)
        self.assertEqual(states.ERROR, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__reboot_good(self, mock_get_server):
        mock_get_server.return_value = self.Server(active=True)
        pstate = seamicro._reboot(self.node, timeout=2)
        self.assertEqual(states.POWER_ON, pstate)

    @mock.patch.object(seamicro, "_get_server")
    def test__reboot_fail(self, mock_get_server):
        def fake_reboot():
            return
        server = self.Server(active=False)
        server.reset = fake_reboot
        mock_get_server.return_value = server
        pstate = seamicro._reboot(self.node, timeout=2)
        self.assertEqual(states.ERROR, pstate)


class SeaMicroPowerDriverTestCase(db_base.DbTestCase):

    def setUp(self):
        super(SeaMicroPowerDriverTestCase, self).setUp()
        mgr_utils.mock_the_extension_manager(driver='fake_seamicro')
        self.driver = driver_factory.get_driver('fake_seamicro')
        self.node = db_utils.get_test_node(driver='fake_seamicro',
                                           driver_info=INFO_DICT)
        self.dbapi = dbapi.get_instance()
        self.dbapi.create_node(self.node)
        self.parse_drv_info_patcher = mock.patch.object(seamicro,
                                                        '_parse_driver_info')
        self.parse_drv_info_mock = None
        self.get_server_patcher = mock.patch.object(seamicro, '_get_server')

        self.get_server_mock = None
        self.Server = Fake_Server

    @mock.patch.object(seamicro, '_reboot')
    def test_reboot(self, mock_reboot):
        info = seamicro._parse_driver_info(self.node)

        mock_reboot.return_value = states.POWER_ON

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            task.resources[0].driver.power.reboot(task, self.node)

        mock_reboot.assert_called_once_with(self.node)

    def test_set_power_state_bad_state(self):
        info = seamicro ._parse_driver_info(self.node)
        self.get_server_mock = self.get_server_patcher.start()
        self.get_server_mock.return_value = self.Server()

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            self.assertRaises(exception.IronicException,
                              task.resources[0].driver.power.set_power_state,
                              task, self.node, "BAD_PSTATE")
        self.get_server_patcher.stop()

    @mock.patch.object(seamicro, '_power_on')
    def test_set_power_state_on_good(self, mock_power_on):
        info = seamicro._parse_driver_info(self.node)

        mock_power_on.return_value = states.POWER_ON

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            task.resources[0].driver.power.set_power_state(task,
                                                           self.node,
                                                           states.POWER_ON)

        mock_power_on.assert_called_once_with(self.node)

    @mock.patch.object(seamicro, '_power_on')
    def test_set_power_state_on_fail(self, mock_power_on):
        info = seamicro._parse_driver_info(self.node)

        mock_power_on.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.resources[0]
                              .driver.power.set_power_state,
                              task, self.node, states.POWER_ON)

        mock_power_on.assert_called_once_with(self.node)

    @mock.patch.object(seamicro, '_power_off')
    def test_set_power_state_off_good(self, mock_power_off):
        info = seamicro._parse_driver_info(self.node)

        mock_power_off.return_value = states.POWER_OFF

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            task.resources[0].driver.power.\
                set_power_state(task, self.node, states.POWER_OFF)

        mock_power_off.assert_called_once_with(self.node)

    @mock.patch.object(seamicro, '_power_off')
    def test_set_power_state_off_fail(self, mock_power_off):
        info = seamicro._parse_driver_info(self.node)

        mock_power_off.return_value = states.POWER_ON

        with task_manager.acquire(self.context, [info['uuid']],
                                  shared=False) as task:
            self.assertRaises(exception.PowerStateFailure,
                              task.resources[0]
                              .driver.power.set_power_state,
                              task, self.node, states.POWER_OFF)

        mock_power_off.assert_called_once_with(self.node)
