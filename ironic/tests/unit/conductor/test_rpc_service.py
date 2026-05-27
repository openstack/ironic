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
import multiprocessing.reduction
import os
import pickle
import sys
import time
from unittest import mock

import fixtures
from oslo_config import cfg
import oslo_messaging
from oslo_service import service as base_service
from oslo_utils import timeutils

from ironic.common import console_factory
from ironic.common import context
from ironic.common import rpc
from ironic.common import service as ironic_service
from ironic.conductor import manager
from ironic.conductor import rpc_service
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start(self, mock_ctx, mock_init_method,
                   mock_rpc, mock_ios, mock_target, mock_prepare_method,
                   mock_console_factory):
        mock_rpc.return_value.start = mock.MagicMock()
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start_no_rpc(self, mock_ctx, mock_init_method,
                          mock_rpc, mock_ios, mock_target,
                          mock_prepare_method, mock_console_factory):
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(manager.ConductorManager, 'prepare_host', autospec=True)
    @mock.patch.object(oslo_messaging, 'Target', autospec=True)
    @mock.patch.object(objects_base, 'IronicObjectSerializer', autospec=True)
    @mock.patch.object(rpc, 'get_server', autospec=True)
    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    @mock.patch.object(context, 'get_admin_context', autospec=True)
    def test_start_failure(self, mock_ctx, mock_init_method, mock_rpc,
                           mock_ios, mock_target, mock_prepare_method,
                           mock_console_factory):
        mock_rpc.return_value.start = mock.MagicMock()
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_instant(self, mock_sleep, mock_utcnow,
                          mock_console_factory):
        # del_host returns instantly
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_after_full_reset_interval(self, mock_sleep, mock_utcnow,
                                            mock_console_factory):
        # del_host returns instantly
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_after_remaining_interval(self, mock_sleep, mock_utcnow,
                                           mock_console_factory):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_slow(self, mock_sleep, mock_utcnow,
                       mock_console_factory):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(console_factory, 'ConsoleContainerFactory',
                       autospec=True)
    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    @mock.patch.object(time, 'sleep', autospec=True)
    def test_stop_has_reserved(self, mock_sleep, mock_utcnow,
                               mock_console_factory):
        mock_utcnow.return_value = datetime.datetime(2023, 2, 2, 21, 10, 0)
        mock_console_factory.return_value.provider.stop_all_containers = (
            mock.MagicMock())
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

    @mock.patch.object(timeutils, 'utcnow', autospec=True)
    def test_shutdown_timeout_reached(self, mock_utcnow):

        initial_time = datetime.datetime(2023, 2, 2, 21, 10, 0)
        before_graceful = initial_time + datetime.timedelta(seconds=30)
        after_graceful = initial_time + datetime.timedelta(seconds=90)
        before_drain = initial_time + datetime.timedelta(seconds=1700)
        after_drain = initial_time + datetime.timedelta(seconds=1900)

        mock_utcnow.return_value = before_graceful
        self.assertFalse(self.rpc_svc._shutdown_timeout_reached(initial_time))

        mock_utcnow.return_value = after_graceful
        self.assertTrue(self.rpc_svc._shutdown_timeout_reached(initial_time))

        with mock.patch.object(self.rpc_svc, 'is_draining',
                               return_value=True,
                               autospec=True) as mock_drain:
            self.assertFalse(
                self.rpc_svc._shutdown_timeout_reached(initial_time))
            self.assertEqual(1, mock_drain.call_count)

            mock_utcnow.return_value = before_drain
            self.assertFalse(
                self.rpc_svc._shutdown_timeout_reached(initial_time))
            self.assertEqual(2, mock_drain.call_count)

            mock_utcnow.return_value = after_drain
            self.assertTrue(
                self.rpc_svc._shutdown_timeout_reached(initial_time))
            self.assertEqual(3, mock_drain.call_count)

            CONF.set_override('drain_shutdown_timeout', 0)
            self.assertFalse(
                self.rpc_svc._shutdown_timeout_reached(initial_time))
            self.assertEqual(4, mock_drain.call_count)

    @mock.patch('ironic.common.service.prepare_command', autospec=True)
    def test_pickle_roundtrip(self, mock_prepare):
        """Test that RPCService can be pickled for oslo.service spawn check.

        oslo.service uses ForkingPickler.dumps() to determine whether
        to use the spawn or fork multiprocessing context. This test
        verifies that RPCService survives a pickle roundtrip.
        """
        # Verify ForkingPickler.dumps succeeds (this is the exact call
        # oslo.service makes)
        data = multiprocessing.reduction.ForkingPickler.dumps(self.rpc_svc)
        restored = pickle.loads(data)
        self.assertEqual(self.rpc_svc.host, restored.host)
        self.assertEqual(self.rpc_svc.topic, restored.topic)
        self.assertFalse(restored._started)
        # Manager should survive the roundtrip
        self.assertEqual(self.rpc_svc.manager.host, restored.manager.host)
        self.assertEqual(self.rpc_svc.manager.topic, restored.manager.topic)
        # threading.Event should be recreated as unset
        self.assertFalse(restored.manager._shutdown.is_set())
        # Thread pool executors and periodic tasks should be excluded
        # from pickle and set to None after unpickling (to be recreated
        # during startup)
        self.assertIsNone(restored.manager._executor)
        self.assertIsNone(restored.manager._reserved_executor)
        self.assertIsNone(restored.manager._periodic_tasks)
        self.assertIsNone(restored.manager._periodic_tasks_worker)

    def test_getstate_includes_argv(self):
        """__getstate__ saves sys.argv so __setstate__ can restore CONF."""
        import sys
        state = self.rpc_svc.__getstate__()
        self.assertIn('_argv', state)
        self.assertEqual(sys.argv[:], state['_argv'])
        # tg must be excluded (contains un-picklable threading objects)
        self.assertNotIn('tg', state)

    def test_manager_getstate_excludes_unpicklable(self):
        """Manager __getstate__ excludes thread pools and periodic tasks.

        Thread pool executors and periodic task objects contain threading
        primitives that cannot be pickled. Verify they are excluded from
        the pickled state and will be recreated during startup.
        """
        state = self.rpc_svc.manager.__getstate__()
        # Threading objects must be excluded
        self.assertNotIn('_executor', state)
        self.assertNotIn('_reserved_executor', state)
        self.assertNotIn('_periodic_tasks', state)
        self.assertNotIn('_periodic_tasks_worker', state)
        self.assertNotIn('sensors_notifier', state)
        self.assertNotIn('dbapi', state)
        # _shutdown should be converted to bool
        self.assertIn('_shutdown', state)
        self.assertIsInstance(state['_shutdown'], bool)

    @mock.patch('ironic.common.service.prepare_command', autospec=True)
    def test_setstate_calls_prepare_command(self, mock_prepare):
        """__setstate__ re-configures CONF when _argv is present.

        In a spawned child process CONF starts empty; BaseRPCService
        must call prepare_command() with the parent's argv to restore it.
        """
        state = self.rpc_svc.__getstate__()
        state['_argv'] = ['ironic', '--config-file', '/etc/ironic/ironic.conf']
        new_svc = object.__new__(rpc_service.RPCService)
        new_svc.__setstate__(state)
        mock_prepare.assert_called_once_with(
            ['ironic', '--config-file', '/etc/ironic/ironic.conf'])

    @mock.patch('ironic.common.service.prepare_command', autospec=True)
    def test_setstate_no_argv_skips_prepare_command(self, mock_prepare):
        """__setstate__ without _argv does not call prepare_command.

        This covers the non-spawn (fork or in-process) path where CONF
        is already populated and must not be re-initialised.
        """
        state = self.rpc_svc.__getstate__()
        state.pop('_argv', None)
        new_svc = object.__new__(rpc_service.RPCService)
        new_svc.__setstate__(state)
        mock_prepare.assert_not_called()

    def test_pickle_roundtrip_with_conf(self):
        """Full oslo.service spawn probe: both service and conf.

        ``_select_service_manager_context()`` probes the service instance
        **and** ``conf`` in the same try block.  This test verifies that
        both succeed after the ConfigOpts spawn-safety patch is applied.
        """
        ironic_service._make_conf_spawn_safe()

        def _cleanup_patch():
            for attr in ('__reduce__', '_ironic_spawn_safe'):
                try:
                    delattr(cfg.ConfigOpts, attr)
                except AttributeError:
                    pass
        self.addCleanup(_cleanup_patch)

        # Service probe
        data_svc = multiprocessing.reduction.ForkingPickler.dumps(
            self.rpc_svc)
        self.assertIsNotNone(data_svc)
        # Conf probe
        data_conf = multiprocessing.reduction.ForkingPickler.dumps(CONF)
        self.assertIsNotNone(data_conf)

    def _restore_conductor_manager_module(self, saved_module):
        """Put back ironic.conductor.manager after an import-order test."""
        sys.modules.pop('ironic.conductor.manager', None)
        if saved_module is not None:
            sys.modules['ironic.conductor.manager'] = saved_module

    def test_send_sensor_data_periodic_flag_refreshed_after_config(self):
        """Lazy enabled applies when periodics refresh after config."""
        manager_name = 'ironic.conductor.manager'
        saved_module = sys.modules.pop(manager_name, None)
        self.addCleanup(self._restore_conductor_manager_module, saved_module)

        CONF.set_override('send_sensor_data', False, group='sensor_data')
        from ironic.conductor import manager as mgr
        from ironic.conductor import periodics as conductor_periodics

        fn = mgr.ConductorManager._send_sensor_data
        self.assertFalse(getattr(fn, '_is_periodic', True))

        conductor_periodics.refresh_periodic_attributes(fn)
        self.assertFalse(getattr(fn, '_is_periodic', True))

        CONF.set_override('send_sensor_data', True, group='sensor_data')
        conductor_periodics.refresh_periodic_attributes(fn)
        self.assertTrue(CONF.sensor_data.send_sensor_data)
        self.assertTrue(getattr(fn, '_is_periodic', False))

    @mock.patch('ironic.common.service.prepare_command', autospec=True)
    def test_spawn_unpickle_send_sensor_data_periodic_enabled(
            self, mock_prepare):
        """Spawn unpickle refreshes _send_sensor_data after prepare_command.

        oslo.service spawn unpickles the manager before __setstate__ runs
        prepare_command(), bypassing the import-order guard added for
        LP #1562258 in ironic.command.conductor. The mock applies the
        config-file value without re-parsing argv in tests.
        """
        conf_dir = self.useFixture(fixtures.TempDir()).path
        conf_path = os.path.join(conf_dir, 'ironic.conf')
        with open(conf_path, 'w', encoding='utf-8') as conf_file:
            conf_file.write(
                '[DEFAULT]\n'
                'host=localhost\n'
                '\n'
                '[sensor_data]\n'
                'send_sensor_data=true\n'
                'interval=60\n')

        argv = ['ironic-conductor', '--config-file', conf_path]

        def _restore_conf_from_argv(restored_argv):
            if restored_argv == argv:
                CONF.set_override('send_sensor_data', True,
                                  group='sensor_data')

        mock_prepare.side_effect = _restore_conf_from_argv

        saved_argv = sys.argv[:]
        self.addCleanup(setattr, sys, 'argv', saved_argv)
        sys.argv = argv[:]
        data = multiprocessing.reduction.ForkingPickler.dumps(self.rpc_svc)

        manager_name = 'ironic.conductor.manager'
        saved_module = sys.modules.pop(manager_name, None)
        self.addCleanup(self._restore_conductor_manager_module, saved_module)

        CONF.set_override('send_sensor_data', False, group='sensor_data')

        pickle.loads(data)

        mock_prepare.assert_called_once_with(argv)
        from ironic.conductor import manager as mgr
        fn = mgr.ConductorManager._send_sensor_data
        self.assertTrue(getattr(fn, '_is_periodic', False),
                        '__setstate__ should refresh _send_sensor_data after '
                        'prepare_command restores CONF')
        self.assertTrue(CONF.sensor_data.send_sensor_data)
