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

"""Test class for Ironic BaseConductorManager."""

import eventlet
import mock
from oslo_config import cfg
from oslo_db import exception as db_exception

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import base_manager
from ironic.conductor import manager
from ironic.drivers import base as drivers_base
from ironic import objects
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as tests_db_base
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF


@mgr_utils.mock_record_keepalive
class StartStopTestCase(mgr_utils.ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_start_registers_conductor(self):
        self.assertRaises(exception.ConductorNotFound,
                          objects.Conductor.get_by_hostname,
                          self.context, self.hostname)
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])

    def test_start_clears_conductor_locks(self):
        node = obj_utils.create_test_node(self.context,
                                          reservation=self.hostname)
        node.save()
        self._start_service()
        node.refresh()
        self.assertIsNone(node.reservation)

    def test_stop_unregisters_conductor(self):
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        self.service.del_host()
        self.assertRaises(exception.ConductorNotFound,
                          objects.Conductor.get_by_hostname,
                          self.context, self.hostname)

    def test_stop_doesnt_unregister_conductor(self):
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        self.service.del_host(deregister=False)
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])

    @mock.patch.object(manager.ConductorManager, 'init_host')
    def test_stop_uninitialized_conductor(self, mock_init):
        self._start_service()
        self.service.del_host()

    @mock.patch.object(driver_factory.DriverFactory, '__getitem__',
                       lambda *args: mock.MagicMock())
    def test_start_registers_driver_names(self):
        init_names = ['fake1', 'fake2']
        restart_names = ['fake3', 'fake4']

        df = driver_factory.DriverFactory()
        with mock.patch.object(df._extension_manager, 'names') as mock_names:
            # verify driver names are registered
            self.config(enabled_drivers=init_names)
            mock_names.return_value = init_names
            self._start_service()
            res = objects.Conductor.get_by_hostname(self.context,
                                                    self.hostname)
            self.assertEqual(init_names, res['drivers'])

            # verify that restart registers new driver names
            self.config(enabled_drivers=restart_names)
            mock_names.return_value = restart_names
            self._start_service()
            res = objects.Conductor.get_by_hostname(self.context,
                                                    self.hostname)
            self.assertEqual(restart_names, res['drivers'])

    @mock.patch.object(driver_factory.DriverFactory, '__getitem__')
    def test_start_registers_driver_specific_tasks(self, get_mock):
        init_names = ['fake1']
        expected_name = 'ironic.tests.unit.conductor.test_base_manager.task'
        expected_name2 = 'ironic.tests.unit.conductor.test_base_manager.iface'
        self.config(enabled_drivers=init_names)

        class TestInterface(object):
            @drivers_base.driver_periodic_task(spacing=100500)
            def iface(self):
                pass

        class Driver(object):
            core_interfaces = []
            standard_interfaces = ['iface']

            iface = TestInterface()

            @drivers_base.driver_periodic_task(spacing=42)
            def task(self, context):
                pass

        obj = Driver()
        self.assertTrue(obj.task._periodic_enabled)
        get_mock.return_value = mock.Mock(obj=obj)

        with mock.patch.object(
                driver_factory.DriverFactory()._extension_manager,
                'names') as mock_names:
            mock_names.return_value = init_names
            self._start_service()
        tasks = dict(self.service._periodic_tasks)
        self.assertEqual(obj.task, tasks[expected_name])
        self.assertEqual(obj.iface.iface, tasks[expected_name2])
        self.assertEqual(42,
                         self.service._periodic_spacing[expected_name])
        self.assertEqual(100500,
                         self.service._periodic_spacing[expected_name2])
        self.assertIn(expected_name, self.service._periodic_last_run)
        self.assertIn(expected_name2, self.service._periodic_last_run)

    @mock.patch.object(driver_factory.DriverFactory, '__init__')
    def test_start_fails_on_missing_driver(self, mock_df):
        mock_df.side_effect = exception.DriverNotFound('test')
        with mock.patch.object(self.dbapi, 'register_conductor') as mock_reg:
            self.assertRaises(exception.DriverNotFound,
                              self.service.init_host)
            self.assertTrue(mock_df.called)
            self.assertFalse(mock_reg.called)

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(driver_factory, 'DriverFactory')
    def test_start_fails_on_no_driver(self, df_mock, log_mock):
        driver_factory_mock = mock.MagicMock(names=[])
        df_mock.return_value = driver_factory_mock
        self.assertRaises(exception.NoDriversLoaded,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)

    @mock.patch.object(eventlet.greenpool.GreenPool, 'waitall')
    def test_del_host_waits_on_workerpool(self, wait_mock):
        self._start_service()
        self.service.del_host()
        self.assertTrue(wait_mock.called)


class KeepAliveTestCase(mgr_utils.ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test__conductor_service_record_keepalive(self):
        self._start_service()
        # avoid wasting time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        with mock.patch.object(self.dbapi, 'touch_conductor') as mock_touch:
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set') as mock_is_set:
                mock_is_set.side_effect = [False, True]
                self.service._conductor_service_record_keepalive()
            mock_touch.assert_called_once_with(self.hostname)

    def test__conductor_service_record_keepalive_failed_db_conn(self):
        self._start_service()
        # avoid wasting time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        with mock.patch.object(self.dbapi, 'touch_conductor') as mock_touch:
            mock_touch.side_effect = [None, db_exception.DBConnectionError(),
                                      None]
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set') as mock_is_set:
                mock_is_set.side_effect = [False, False, False, True]
                self.service._conductor_service_record_keepalive()
            self.assertEqual(3, mock_touch.call_count)
