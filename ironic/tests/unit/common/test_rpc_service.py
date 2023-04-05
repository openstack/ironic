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

import datetime
import time
from unittest import mock

from oslo_config import cfg
import oslo_messaging
from oslo_service import service as base_service
from oslo_utils import timeutils

from ironic.common import context
from ironic.common import rpc
from ironic.common import rpc_service
from ironic.common import service as ironic_service
from ironic.conductor import manager
from ironic.objects import base as objects_base
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.db import utils as db_utils

CONF = cfg.CONF


@mock.patch.object(base_service.Service, '__init__', lambda *_, **__: None)
class TestRPCService(db_base.DbTestCase):

    def setUp(self):
        super(TestRPCService, self).setUp()
        host = "fake_host"
        mgr_module = "ironic.conductor.manager"
        mgr_class = "ConductorManager"
        self.rpc_svc = rpc_service.RPCService(host, mgr_module, mgr_class)
        # register oslo_service DEFAULT config options
        ironic_service.process_launcher()
        self.rpc_svc.manager.dbapi = self.dbapi

    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start(self, mock_ctx, mock_init_method,
                   mock_rpc, mock_ios, mock_target, mock_prepare_method):
        mock_rpc.return_value.start = mock.MagicMock()
        self.rpc_svc.handle_signal = mock.MagicMock()
        self.assertFalse(self.rpc_svc._started)
        self.assertFalse(self.rpc_svc._failure)
        self.rpc_svc.start()
        mock_ctx.assert_called_once_with()
        mock_target.assert_called_once_with(topic=self.rpc_svc.topic,
                                            server="fake_host")
        mock_ios.assert_called_once_with(is_server=True)
        mock_prepare_method.assert_called_once_with(self.rpc_svc.manager)
        mock_init_method.assert_called_once_with(self.rpc_svc.manager,
                                                 mock_ctx.return_value)
        self.assertIs(rpc.GLOBAL_MANAGER, self.rpc_svc.manager)
        self.assertTrue(self.rpc_svc._started)
        self.assertFalse(self.rpc_svc._failure)
        self.rpc_svc.wait_for_start()  # should be no-op

    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start_no_rpc(self, mock_ctx, mock_init_method,
                          mock_rpc, mock_ios, mock_target,
                          mock_prepare_method):
        CONF.set_override('rpc_transport', 'none')
        self.rpc_svc.start()

        self.assertIsNone(self.rpc_svc.rpcserver)
        mock_ctx.assert_called_once_with()
        mock_target.assert_not_called()
        mock_rpc.assert_not_called()
        mock_ios.assert_called_once_with(is_server=True)
        mock_prepare_method.assert_called_once_with(self.rpc_svc.manager)
        mock_init_method.assert_called_once_with(self.rpc_svc.manager,
                                                 mock_ctx.return_value)
        self.assertIs(rpc.GLOBAL_MANAGER, self.rpc_svc.manager)

    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start_failure(self, mock_ctx, mock_init_method, mock_rpc,
                           mock_ios, mock_target, mock_prepare_method):
        mock_rpc.return_value.start = mock.MagicMock()
        self.rpc_svc.handle_signal = mock.MagicMock()
        mock_init_method.side_effect = RuntimeError("boom")
        self.assertFalse(self.rpc_svc._started)
        self.assertFalse(self.rpc_svc._failure)
        self.assertRaises(RuntimeError, self.rpc_svc.start)
        mock_ctx.assert_called_once_with()
        mock_target.assert_called_once_with(topic=self.rpc_svc.topic,
                                            server="fake_host")
        mock_ios.assert_called_once_with(is_server=True)
        mock_prepare_method.assert_called_once_with(self.rpc_svc.manager)
        mock_init_method.assert_called_once_with(self.rpc_svc.manager,
                                                 mock_ctx.return_value)
        self.assertIsNone(rpc.GLOBAL_MANAGER)
        self.assertFalse(self.rpc_svc._started)
        self.assertIn("boom", self.rpc_svc._failure)
        self.assertRaises(SystemExit, self.rpc_svc.wait_for_start)

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_instant(self, mock_sleep, mock_utcnow):
        # del_host returns instantly
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        conductor1 = db_utils.get_test_conductor(hostname='fake_host')
        with mock.patch.object(self.dbapi, 'get_online_conductors',
                               autospec=True) as mock_cond_list:
            mock_cond_list.return_value = [conductor1]
            with mock.patch.object(self.dbapi, 'get_nodeinfo_list',
                                   autospec=True) as mock_nodeinfo_list:
                mock_nodeinfo_list.return_value = []
                self.rpc_svc.stop()

        # single conductor so exit immediately without waiting
        mock_sleep.assert_not_called()

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_after_full_reset_interval(self, mock_sleep, mock_utcnow):
        # del_host returns instantly
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        conductor1 = db_utils.get_test_conductor(hostname='fake_host')
        conductor2 = db_utils.get_test_conductor(hostname='other_fake_host')
        with mock.patch.object(self.dbapi, 'get_online_conductors',
                               autospec=True) as mock_cond_list:
            # multiple conductors, so wait for hash_ring_reset_interval
            mock_cond_list.return_value = [conductor1, conductor2]
            with mock.patch.object(self.dbapi, 'get_nodeinfo_list',
                                   autospec=True) as mock_nodeinfo_list:
                mock_nodeinfo_list.return_value = []
                self.rpc_svc.stop()
                mock_nodeinfo_list.assert_called_once()

        # wait the total CONF.hash_ring_reset_interval 15 seconds
        mock_sleep.assert_has_calls([mock.call(15)])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_after_remaining_interval(self, mock_sleep, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        conductor1 = db_utils.get_test_conductor(hostname='fake_host')
        conductor2 = db_utils.get_test_conductor(hostname='other_fake_host')

        # del_host returns after 5 seconds
        mock_utcnow.side_effect = [
            datetime.datetime(2023, 2, 2, 21, 10, 0),
            datetime.datetime(2023, 2, 2, 21, 10, 5),
        ]
        with mock.patch.object(self.dbapi, 'get_online_conductors',
                               autospec=True) as mock_cond_list:
            # multiple conductors, so wait for hash_ring_reset_interval
            mock_cond_list.return_value = [conductor1, conductor2]
            with mock.patch.object(self.dbapi, 'get_nodeinfo_list',
                                   autospec=True) as mock_nodeinfo_list:
                mock_nodeinfo_list.return_value = []
                self.rpc_svc.stop()
                mock_nodeinfo_list.assert_called_once()

        # wait the remaining 10 seconds
        mock_sleep.assert_has_calls([mock.call(10)])

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_slow(self, mock_sleep, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        conductor1 = db_utils.get_test_conductor(hostname='fake_host')
        conductor2 = db_utils.get_test_conductor(hostname='other_fake_host')

        # del_host returns after 16 seconds
        mock_utcnow.side_effect = [
            datetime.datetime(2023, 2, 2, 21, 10, 0),
            datetime.datetime(2023, 2, 2, 21, 10, 16),
        ]
        with mock.patch.object(self.dbapi, 'get_online_conductors',
                               autospec=True) as mock_cond_list:
            # multiple conductors, so wait for hash_ring_reset_interval
            mock_cond_list.return_value = [conductor1, conductor2]
            with mock.patch.object(self.dbapi, 'get_nodeinfo_list',
                                   autospec=True) as mock_nodeinfo_list:
                mock_nodeinfo_list.return_value = []
                self.rpc_svc.stop()
                mock_nodeinfo_list.assert_called_once()

        # no wait required, CONF.hash_ring_reset_interval already exceeded
        mock_sleep.assert_not_called()

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_has_reserved(self, mock_sleep, mock_utcnow):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        conductor1 = db_utils.get_test_conductor(hostname='fake_host')
        conductor2 = db_utils.get_test_conductor(hostname='other_fake_host')

        with mock.patch.object(self.dbapi, 'get_online_conductors',
                               autospec=True) as mock_cond_list:
            # multiple conductors, so wait for hash_ring_reset_interval
            mock_cond_list.return_value = [conductor1, conductor2]
            with mock.patch.object(self.dbapi, 'get_nodeinfo_list',
                                   autospec=True) as mock_nodeinfo_list:
                # 3 calls to manager has_reserved until all reservation locks
                # are released
                mock_nodeinfo_list.side_effect = [['a', 'b'], ['a'], []]
                self.rpc_svc.stop()
                self.assertEqual(3, mock_nodeinfo_list.call_count)

        # wait the remaining 15 seconds, then wait until has_reserved
        # returns False
        mock_sleep.assert_has_calls(
            [mock.call(15), mock.call(1), mock.call(1)])
