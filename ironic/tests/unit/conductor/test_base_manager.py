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

import collections

import eventlet
import futurist
from futurist import periodics
import mock
from oslo_config import cfg
from oslo_db import exception as db_exception
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.conductor import base_manager
from ironic.conductor import manager
from ironic.conductor import notification_utils
from ironic.conductor import task_manager
from ironic.drivers import fake_hardware
from ironic.drivers import generic
from ironic import objects
from ironic.objects import fields
from ironic.tests import base as tests_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils


CONF = cfg.CONF


@mgr_utils.mock_record_keepalive
class StartStopTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
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
    @mock.patch.object(driver_factory, 'StorageInterfaceFactory')
    @mock.patch.object(driver_factory, 'NetworkInterfaceFactory')
    def test_start_registers_driver_names(self, net_factory,
                                          storage_factory):
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
            self._stop_service()

            # verify that restart registers new driver names
            self.config(enabled_drivers=restart_names)
            mock_names.return_value = restart_names
            self._start_service()
            res = objects.Conductor.get_by_hostname(self.context,
                                                    self.hostname)
            self.assertEqual(restart_names, res['drivers'])
        self.assertEqual(2, net_factory.call_count)
        self.assertEqual(2, storage_factory.call_count)

    @mock.patch.object(driver_factory.DriverFactory, '__getitem__')
    def test_start_registers_driver_specific_tasks(self, get_mock):
        init_names = ['fake1']
        self.config(enabled_drivers=init_names)

        class TestInterface(object):
            @periodics.periodic(spacing=100500)
            def iface(self):
                pass

        class Driver(object):
            core_interfaces = []
            standard_interfaces = ['iface']
            all_interfaces = core_interfaces + standard_interfaces

            iface = TestInterface()

            @periodics.periodic(spacing=42)
            def task(self, context):
                pass

        obj = Driver()
        get_mock.return_value = mock.Mock(obj=obj)

        with mock.patch.object(
                driver_factory.DriverFactory()._extension_manager,
                'names') as mock_names:
            mock_names.return_value = init_names
            self._start_service(start_periodic_tasks=True)

        tasks = {c[0] for c in self.service._periodic_task_callables}
        self.assertTrue(periodics.is_periodic(obj.iface.iface))
        self.assertIn(obj.iface.iface, tasks)

        # no periodic tasks from the Driver object
        self.assertTrue(periodics.is_periodic(obj.task))
        self.assertNotIn(obj.task, tasks)

    @mock.patch.object(driver_factory.DriverFactory, '__init__')
    def test_start_fails_on_missing_driver(self, mock_df):
        mock_df.side_effect = exception.DriverNotFound('test')
        with mock.patch.object(self.dbapi, 'register_conductor') as mock_reg:
            self.assertRaises(exception.DriverNotFound,
                              self.service.init_host)
            self.assertTrue(mock_df.called)
            self.assertFalse(mock_reg.called)

    def test_start_fails_on_no_enabled_interfaces(self):
        self.config(enabled_boot_interfaces=[])
        self.assertRaisesRegex(exception.ConfigInvalid,
                               'options enabled_boot_interfaces',
                               self.service.init_host)

    def test_starts_without_enabled_hardware_types(self):
        self.config(enabled_hardware_types=[])
        self.config(enabled_boot_interfaces=[])
        self._start_service()

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(driver_factory, 'HardwareTypesFactory')
    @mock.patch.object(driver_factory, 'DriverFactory')
    def test_start_fails_on_no_driver_or_hw_types(self, df_mock, ht_mock,
                                                  log_mock):
        driver_factory_mock = mock.MagicMock(names=[])
        df_mock.return_value = driver_factory_mock
        ht_mock.return_value = driver_factory_mock
        self.assertRaises(exception.NoDriversLoaded,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)
        df_mock.assert_called_once_with()
        ht_mock.assert_called_once_with()

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(base_manager.BaseConductorManager, 'del_host',
                       autospec=True)
    @mock.patch.object(driver_factory, 'DriverFactory')
    def test_starts_with_only_dynamic_drivers(self, df_mock, del_mock,
                                              log_mock):
        # don't load any classic drivers
        driver_factory_mock = mock.MagicMock(names=[])
        df_mock.return_value = driver_factory_mock
        self.service.init_host()
        self.assertFalse(log_mock.error.called)
        df_mock.assert_called_once_with()
        self.assertFalse(del_mock.called)

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(base_manager.BaseConductorManager, 'del_host',
                       autospec=True)
    @mock.patch.object(driver_factory, 'HardwareTypesFactory')
    def test_starts_with_only_classic_drivers(self, ht_mock, del_mock,
                                              log_mock):
        # don't load any dynamic drivers
        driver_factory_mock = mock.MagicMock(names=[])
        ht_mock.return_value = driver_factory_mock
        self.service.init_host()
        self.assertFalse(log_mock.error.called)
        ht_mock.assert_called_once_with()
        self.assertFalse(del_mock.called)

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(base_manager.BaseConductorManager,
                       '_register_and_validate_hardware_interfaces')
    @mock.patch.object(base_manager.BaseConductorManager, 'del_host')
    def test_start_fails_hw_type_register(self, del_mock, reg_mock, log_mock):
        reg_mock.side_effect = exception.DriverNotFound('hw-type')
        self.assertRaises(exception.DriverNotFound,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)
        del_mock.assert_called_once_with()

    @mock.patch.object(base_manager, 'LOG')
    @mock.patch.object(driver_factory, 'HardwareTypesFactory')
    @mock.patch.object(driver_factory, 'DriverFactory')
    def test_start_fails_on_name_conflict(self, df_mock, ht_mock, log_mock):
        driver_factory_mock = mock.MagicMock(names=['dupe-driver'])
        df_mock.return_value = driver_factory_mock
        ht_mock.return_value = driver_factory_mock
        self.assertRaises(exception.DriverNameConflict,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)
        df_mock.assert_called_once_with()
        ht_mock.assert_called_once_with()

    def test_prevent_double_start(self):
        self._start_service()
        self.assertRaisesRegex(RuntimeError, 'already running',
                               self.service.init_host)

    @mock.patch.object(base_manager, 'LOG')
    def test_warning_on_low_workers_pool(self, log_mock):
        CONF.set_override('workers_pool_size', 3, 'conductor')
        self._start_service()
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(eventlet.greenpool.GreenPool, 'waitall')
    def test_del_host_waits_on_workerpool(self, wait_mock):
        self._start_service()
        self.service.del_host()
        self.assertTrue(wait_mock.called)

    def test_start_fails_on_missing_config_for_configdrive(self):
        """Check to fail conductor on missing config options"""

        missing_parameters_error = ("Parameters missing to make a "
                                    "connection with radosgw")
        CONF.set_override('configdrive_use_object_store', True,
                          group='deploy')
        CONF.set_override('object_store_endpoint_type', 'radosgw',
                          group='deploy')
        params = {'auth_url': 'http://1.2.3.4',
                  'username': 'foo', 'password': 'foo_pass'}
        CONF.register_opts((cfg.StrOpt(x) for x in params),
                           group='swift')
        for key, value in params.items():
            test_params = params.copy()
            test_params[key] = None
            for test_key, test_value in test_params.items():
                CONF.set_override(key, test_value, group='swift')
            with self.assertRaisesRegex(exception.ConfigInvalid,
                                        missing_parameters_error):
                self._start_service()

    def test_conductor_shutdown_flag(self):
        self._start_service()
        self.assertFalse(self.service._shutdown)
        self.service.del_host()
        self.assertTrue(self.service._shutdown)


class CheckInterfacesTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    def test__check_enabled_interfaces_success(self):
        base_manager._check_enabled_interfaces()

    def test__check_enabled_interfaces_failure(self):
        self.config(enabled_boot_interfaces=[])
        self.assertRaisesRegex(exception.ConfigInvalid,
                               'options enabled_boot_interfaces',
                               base_manager._check_enabled_interfaces)

    def test__check_enabled_interfaces_skip_if_no_hw_types(self):
        self.config(enabled_hardware_types=[])
        self.config(enabled_boot_interfaces=[])
        base_manager._check_enabled_interfaces()


class KeepAliveTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
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

    def test__conductor_service_record_keepalive_failed_error(self):
        self._start_service()
        # avoid wasting time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        with mock.patch.object(self.dbapi, 'touch_conductor') as mock_touch:
            mock_touch.side_effect = [None, Exception(),
                                      None]
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set') as mock_is_set:
                mock_is_set.side_effect = [False, False, False, True]
                self.service._conductor_service_record_keepalive()
            self.assertEqual(3, mock_touch.call_count)


class ManagerSpawnWorkerTestCase(tests_base.TestCase):
    def setUp(self):
        super(ManagerSpawnWorkerTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.executor = mock.Mock(spec=futurist.GreenThreadPoolExecutor)
        self.service._executor = self.executor

    def test__spawn_worker(self):
        self.service._spawn_worker('fake', 1, 2, foo='bar', cat='meow')

        self.executor.submit.assert_called_once_with(
            'fake', 1, 2, foo='bar', cat='meow')

    def test__spawn_worker_none_free(self):
        self.executor.submit.side_effect = futurist.RejectedSubmission()

        self.assertRaises(exception.NoFreeConductorWorker,
                          self.service._spawn_worker, 'fake')


@mock.patch.object(objects.Conductor, 'unregister_all_hardware_interfaces',
                   autospec=True)
@mock.patch.object(objects.Conductor, 'register_hardware_interfaces',
                   autospec=True)
@mock.patch.object(driver_factory, 'default_interface', autospec=True)
@mock.patch.object(driver_factory, 'enabled_supported_interfaces',
                   autospec=True)
@mgr_utils.mock_record_keepalive
class RegisterInterfacesTestCase(mgr_utils.ServiceSetUpMixin,
                                 db_base.DbTestCase):
    def setUp(self):
        super(RegisterInterfacesTestCase, self).setUp()
        self._start_service()

    def test__register_and_validate_hardware_interfaces(self,
                                                        esi_mock,
                                                        default_mock,
                                                        reg_mock,
                                                        unreg_mock):
        # these must be same order as esi_mock side effect
        hardware_types = collections.OrderedDict((
            ('fake-hardware', fake_hardware.FakeHardware()),
            ('manual-management', generic.ManualManagementHardware),
        ))
        esi_mock.side_effect = [
            collections.OrderedDict((
                ('management', ['fake', 'noop']),
                ('deploy', ['agent', 'iscsi']),
            )),
            collections.OrderedDict((
                ('management', ['fake']),
                ('deploy', ['agent', 'fake']),
            )),
        ]
        default_mock.side_effect = ('fake', 'agent', 'fake', 'agent')
        expected_calls = [
            mock.call(mock.ANY, 'fake-hardware', 'management',
                      ['fake', 'noop'], 'fake'),
            mock.call(mock.ANY, 'fake-hardware', 'deploy', ['agent', 'iscsi'],
                      'agent'),
            mock.call(mock.ANY, 'manual-management', 'management', ['fake'],
                      'fake'),
            mock.call(mock.ANY, 'manual-management', 'deploy',
                      ['agent', 'fake'], 'agent'),
        ]

        self.service._register_and_validate_hardware_interfaces(hardware_types)

        unreg_mock.assert_called_once_with(mock.ANY)
        # we're iterating over dicts, don't worry about order
        reg_mock.assert_has_calls(expected_calls)

    def test__register_and_validate_no_valid_default(self,
                                                     esi_mock,
                                                     default_mock,
                                                     reg_mock,
                                                     unreg_mock):
        # these must be same order as esi_mock side effect
        hardware_types = collections.OrderedDict((
            ('fake-hardware', fake_hardware.FakeHardware()),
        ))
        esi_mock.side_effect = [
            collections.OrderedDict((
                ('management', ['fake', 'noop']),
                ('deploy', ['agent', 'iscsi']),
            )),
        ]
        default_mock.side_effect = exception.NoValidDefaultForInterface("boo")

        self.assertRaises(
            exception.NoValidDefaultForInterface,
            self.service._register_and_validate_hardware_interfaces,
            hardware_types)

        default_mock.assert_called_once_with(
            hardware_types['fake-hardware'],
            mock.ANY, driver_name='fake-hardware')
        unreg_mock.assert_called_once_with(mock.ANY)
        self.assertFalse(reg_mock.called)


class StartConsolesTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    @mock.patch.object(notification_utils, 'emit_console_notification')
    def test__start_consoles(self, mock_notify):
        obj_utils.create_test_node(self.context,
                                   driver='fake',
                                   console_enabled=True)
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake',
            console_enabled=True
        )
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake'
        )
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_start_console:
            self.service._start_consoles(self.context)
            self.assertEqual(2, mock_start_console.call_count)
            mock_notify.assert_has_calls(
                [mock.call(mock.ANY, 'console_restore',
                           fields.NotificationStatus.START),
                 mock.call(mock.ANY, 'console_restore',
                           fields.NotificationStatus.END)])

    @mock.patch.object(notification_utils, 'emit_console_notification')
    def test__start_consoles_no_console_enabled(self, mock_notify):
        obj_utils.create_test_node(self.context,
                                   driver='fake',
                                   console_enabled=False)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_start_console:
            self.service._start_consoles(self.context)
            self.assertFalse(mock_start_console.called)
            self.assertFalse(mock_notify.called)

    @mock.patch.object(notification_utils, 'emit_console_notification')
    def test__start_consoles_failed(self, mock_notify):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake',
                                               console_enabled=True)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_start_console:
            mock_start_console.side_effect = Exception()
            self.service._start_consoles(self.context)
            mock_start_console.assert_called_once_with(mock.ANY)
            test_node.refresh()
            self.assertFalse(test_node.console_enabled)
            self.assertIsNotNone(test_node.last_error)
            mock_notify.assert_has_calls(
                [mock.call(mock.ANY, 'console_restore',
                           fields.NotificationStatus.START),
                 mock.call(mock.ANY, 'console_restore',
                           fields.NotificationStatus.ERROR)])

    @mock.patch.object(notification_utils, 'emit_console_notification')
    @mock.patch.object(base_manager, 'LOG')
    def test__start_consoles_node_locked(self, log_mock, mock_notify):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake',
                                               console_enabled=True,
                                               reservation='fake-host')
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_start_console:
            self.service._start_consoles(self.context)
            self.assertFalse(mock_start_console.called)
            test_node.refresh()
            self.assertTrue(test_node.console_enabled)
            self.assertIsNone(test_node.last_error)
            self.assertTrue(log_mock.warning.called)
            self.assertFalse(mock_notify.called)

    @mock.patch.object(notification_utils, 'emit_console_notification')
    @mock.patch.object(base_manager, 'LOG')
    def test__start_consoles_node_not_found(self, log_mock, mock_notify):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake',
                                               console_enabled=True)
        self._start_service()
        with mock.patch.object(task_manager, 'acquire') as mock_acquire:
            mock_acquire.side_effect = exception.NodeNotFound(node='not found')
            with mock.patch.object(self.driver.console,
                                   'start_console') as mock_start_console:
                self.service._start_consoles(self.context)
                self.assertFalse(mock_start_console.called)
                test_node.refresh()
                self.assertTrue(test_node.console_enabled)
                self.assertIsNone(test_node.last_error)
                self.assertTrue(log_mock.warning.called)
                self.assertFalse(mock_notify.called)
