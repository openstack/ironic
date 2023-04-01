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
from unittest import mock
import uuid

import eventlet
import futurist
from futurist import periodics
from ironic_lib import mdns
from oslo_config import cfg
from oslo_db import exception as db_exception
from oslo_utils import uuidutils

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils as common_utils
from ironic.conductor import base_manager
from ironic.conductor import manager
from ironic.conductor import notification_utils
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic.drivers import fake_hardware
from ironic.drivers import generic
from ironic.drivers.modules import deploy_utils
from ironic.drivers.modules import fake
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

    def test_stop_clears_conductor_locks(self):
        node = obj_utils.create_test_node(self.context,
                                          reservation=self.hostname)
        node.save()
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        self.service.del_host()
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

    @mock.patch.object(manager.ConductorManager, 'init_host', autospec=True)
    def test_stop_uninitialized_conductor(self, mock_init):
        self._start_service()
        self.service.del_host()

    @mock.patch.object(driver_factory.HardwareTypesFactory, '__getitem__',
                       lambda *args: mock.MagicMock())
    @mock.patch.object(driver_factory, 'default_interface', autospec=True)
    def test_start_registers_driver_names(self, mock_def_iface):
        init_names = ['fake1', 'fake2']
        restart_names = ['fake3', 'fake4']

        mock_def_iface.return_value = 'fake'

        df = driver_factory.HardwareTypesFactory()
        with mock.patch.object(df._extension_manager, 'names',
                               autospec=True) as mock_names:
            # verify driver names are registered
            self.config(enabled_hardware_types=init_names)
            mock_names.return_value = init_names
            self._start_service()
            res = objects.Conductor.get_by_hostname(self.context,
                                                    self.hostname)
            self.assertEqual(init_names, res['drivers'])
            self._stop_service()

            # verify that restart registers new driver names
            self.config(enabled_hardware_types=restart_names)
            mock_names.return_value = restart_names
            self._start_service()
            res = objects.Conductor.get_by_hostname(self.context,
                                                    self.hostname)
            self.assertEqual(restart_names, res['drivers'])

    @mock.patch.object(base_manager.BaseConductorManager,
                       '_register_and_validate_hardware_interfaces',
                       autospec=True)
    @mock.patch.object(driver_factory, 'all_interfaces', autospec=True)
    @mock.patch.object(driver_factory, 'hardware_types', autospec=True)
    def test_start_registers_driver_specific_tasks(self,
                                                   mock_hw_types, mock_ifaces,
                                                   mock_reg_hw_ifaces):
        class TestHwType(generic.GenericHardware):
            @property
            def supported_management_interfaces(self):
                return []

            @property
            def supported_power_interfaces(self):
                return []

            # This should not be collected, since we don't collect periodic
            # tasks from hardware types
            @periodics.periodic(spacing=100500)
            def task(self):
                pass

        class TestInterface(object):
            @periodics.periodic(spacing=100500)
            def iface(self):
                pass

        class TestInterface2(object):
            @periodics.periodic(spacing=100500)
            def iface(self):
                pass

        hw_type = TestHwType()
        iface1 = TestInterface()
        iface2 = TestInterface2()
        expected = [iface1.iface, iface2.iface]

        mock_hw_types.return_value = {'fake1': hw_type}
        mock_ifaces.return_value = {
            'management': {'fake1': iface1},
            'power': {'fake2': iface2}
        }

        self._start_service(start_periodic_tasks=True)

        tasks = {c[0] for c in self.service._periodic_task_callables}
        for item in expected:
            self.assertTrue(periodics.is_periodic(item))
            self.assertIn(item, tasks)

        # no periodic tasks from the hardware type
        self.assertTrue(periodics.is_periodic(hw_type.task))
        self.assertNotIn(hw_type.task, tasks)

    @mock.patch.object(driver_factory.HardwareTypesFactory, '__init__',
                       autospec=True)
    def test_start_fails_on_missing_driver(self, mock_df):
        mock_df.side_effect = exception.DriverNotFound('test')
        with mock.patch.object(self.dbapi, 'register_conductor',
                               autospec=True) as mock_reg:
            self.assertRaises(exception.DriverNotFound,
                              self.service.init_host)
            self.assertTrue(mock_df.called)
            self.assertFalse(mock_reg.called)

    def test_start_with_no_enabled_interfaces(self):
        self.config(enabled_boot_interfaces=[],
                    enabled_deploy_interfaces=[],
                    enabled_hardware_types=['fake-hardware'])
        self._start_service()

    @mock.patch.object(base_manager, 'LOG', autospec=True)
    @mock.patch.object(driver_factory, 'HardwareTypesFactory', autospec=True)
    def test_start_fails_on_hw_types(self, ht_mock, log_mock):
        driver_factory_mock = mock.MagicMock(names=[])
        ht_mock.return_value = driver_factory_mock
        self.assertRaises(exception.NoDriversLoaded,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)
        ht_mock.assert_called_once_with()

    @mock.patch.object(base_manager, 'LOG', autospec=True)
    @mock.patch.object(base_manager.BaseConductorManager,
                       '_register_and_validate_hardware_interfaces',
                       autospec=True)
    @mock.patch.object(base_manager.BaseConductorManager, 'del_host',
                       autospec=True)
    def test_start_fails_hw_type_register(self, del_mock, reg_mock, log_mock):
        reg_mock.side_effect = exception.DriverNotFound('hw-type')
        self.assertRaises(exception.DriverNotFound,
                          self.service.init_host)
        self.assertTrue(log_mock.error.called)
        del_mock.assert_called_once()

    def test_prevent_double_start(self):
        self._start_service()
        self.assertRaisesRegex(RuntimeError, 'already running',
                               self.service.init_host)

    def test_start_recover_nodes_stuck(self):
        state_trans = [
            (states.DEPLOYING, states.DEPLOYFAIL),
            (states.CLEANING, states.CLEANFAIL),
            (states.VERIFYING, states.ENROLL),
            (states.INSPECTING, states.INSPECTFAIL),
            (states.ADOPTING, states.ADOPTFAIL),
            (states.RESCUING, states.RESCUEFAIL),
            (states.UNRESCUING, states.UNRESCUEFAIL),
            (states.DELETING, states.ERROR),
        ]
        nodes = [obj_utils.create_test_node(self.context, uuid=uuid.uuid4(),
                                            driver='fake-hardware',
                                            provision_state=state[0])
                 for state in state_trans]

        self._start_service()
        for node, state in zip(nodes, state_trans):
            node.refresh()
            self.assertEqual(state[1], node.provision_state,
                             'Test failed when recovering from %s' % state[0])

    @mock.patch.object(base_manager, 'LOG', autospec=True)
    def test_warning_on_low_workers_pool(self, log_mock):
        CONF.set_override('workers_pool_size', 3, 'conductor')
        self._start_service()
        self.assertTrue(log_mock.warning.called)

    @mock.patch.object(eventlet.greenpool.GreenPool, 'waitall', autospec=True)
    def test_del_host_waits_on_workerpool(self, wait_mock):
        self._start_service()
        self.service.del_host()
        self.assertTrue(wait_mock.called)

    def test_conductor_shutdown_flag(self):
        self._start_service()
        self.assertFalse(self.service._shutdown)
        self.service.del_host()
        self.assertTrue(self.service._shutdown)

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    @mock.patch.object(mdns, 'Zeroconf', autospec=True)
    def test_start_with_mdns(self, mock_zc, mock_api_url):
        CONF.set_override('debug', False)
        CONF.set_override('enable_mdns', True, 'conductor')
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        mock_zc.return_value.register_service.assert_called_once_with(
            'baremetal',
            mock_api_url.return_value,
            params={})

    @mock.patch.object(deploy_utils, 'get_ironic_api_url', autospec=True)
    @mock.patch.object(mdns, 'Zeroconf', autospec=True)
    def test_start_with_mdns_and_debug(self, mock_zc, mock_api_url):
        CONF.set_override('debug', True)
        CONF.set_override('enable_mdns', True, 'conductor')
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        mock_zc.return_value.register_service.assert_called_once_with(
            'baremetal',
            mock_api_url.return_value,
            params={'ipa_debug': True})

    def test_del_host_with_mdns(self):
        mock_zc = mock.Mock(spec=mdns.Zeroconf)
        self.service._zeroconf = mock_zc
        self._start_service()
        self.service.del_host()
        mock_zc.close.assert_called_once_with()
        self.assertIsNone(self.service._zeroconf)

    @mock.patch.object(dbapi, 'get_instance', autospec=True)
    def test_start_dbapi_single_call(self, mock_dbapi):
        self._start_service()
        # NOTE(TheJulia): This seems like it should only be 1, but
        # the hash ring initailization pulls it's own database connection
        # instance, which is likely a good thing, thus this is 2 instead of
        # 3 without reuse of the database connection.
        self.assertEqual(2, mock_dbapi.call_count)

    def test_start_with_json_rpc(self):
        CONF.set_override('rpc_transport', 'json-rpc')
        CONF.set_override('host', 'foo.bar.baz')
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])

    def test_start_with_json_rpc_port(self):
        CONF.set_override('rpc_transport', 'json-rpc')
        CONF.set_override('host', 'foo.bar.baz')
        CONF.set_override('port', 8192, group='json_rpc')

        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context,
                                                self.service.host)
        self.assertEqual(f'{self.hostname}:8192', res['hostname'])

    def test_start_without_jsonrpc_port_pined_version(self):
        CONF.set_override('rpc_transport', 'json-rpc')
        CONF.set_override('host', 'foo.bar.baz')
        CONF.set_override('port', 8192, group='json_rpc')
        CONF.set_override('pin_release_version', '21.4')
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context,
                                                self.service.host)
        self.assertEqual(self.hostname, res['hostname'])


class KeepAliveTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    def test__conductor_service_record_keepalive(self):
        self._start_service()
        # avoid wasting time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        with mock.patch.object(self.dbapi, 'touch_conductor',
                               autospec=True) as mock_touch:
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set', autospec=True) as mock_is_set:
                mock_is_set.side_effect = [False, True]
                self.service._conductor_service_record_keepalive()
            mock_touch.assert_not_called()
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set', autospec=True) as mock_is_set:
                mock_is_set.side_effect = [False, True]
                with mock.patch.object(common_utils, 'is_ironic_using_sqlite',
                                       autospec=True) as mock_is_sqlite:
                    mock_is_sqlite.return_value = False
                    self.service._conductor_service_record_keepalive()
                    self.assertEqual(1, mock_is_sqlite.call_count)
            mock_touch.assert_called_once_with(self.hostname)

    @mock.patch.object(common_utils, 'is_ironic_using_sqlite', autospec=True)
    def test__conductor_service_record_keepalive_failed_db_conn(
            self, is_sqlite_mock):
        self._start_service()
        # avoid wasting time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        is_sqlite_mock.return_value = False
        with mock.patch.object(self.dbapi, 'touch_conductor',
                               autospec=True) as mock_touch:
            mock_touch.side_effect = [None, db_exception.DBConnectionError(),
                                      None]
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set', autospec=True) as mock_is_set:
                mock_is_set.side_effect = [False, False, False, True]
                self.service._conductor_service_record_keepalive()
            self.assertEqual(3, mock_touch.call_count)
        self.assertEqual(1, is_sqlite_mock.call_count)

    @mock.patch.object(common_utils, 'is_ironic_using_sqlite', autospec=True)
    def test__conductor_service_record_keepalive_failed_error(self,
                                                              is_sqlite_mock):
        self._start_service()
        # minimal time at the event.wait()
        CONF.set_override('heartbeat_interval', 0, 'conductor')
        is_sqlite_mock.return_value = False
        with mock.patch.object(self.dbapi, 'touch_conductor',
                               autospec=True) as mock_touch:
            mock_touch.side_effect = [None, Exception(),
                                      None]
            with mock.patch.object(self.service._keepalive_evt,
                                   'is_set', autospec=True) as mock_is_set:
                mock_is_set.side_effect = [False, False, False, True]
                self.service._conductor_service_record_keepalive()
            self.assertEqual(3, mock_touch.call_count)
        self.assertEqual(1, is_sqlite_mock.call_count)


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
                ('deploy', ['direct', 'ansible']),
            )),
            collections.OrderedDict((
                ('management', ['fake']),
                ('deploy', ['direct', 'fake']),
            )),
        ]
        default_mock.side_effect = ('fake', 'direct', 'fake', 'direct')
        expected_calls = [
            mock.call(
                mock.ANY,
                [{'hardware_type': 'fake-hardware',
                  'interface_type': 'management',
                  'interface_name': 'fake',
                  'default': True},
                 {'hardware_type': 'fake-hardware',
                  'interface_type': 'management',
                  'interface_name': 'noop',
                  'default': False},
                 {'hardware_type': 'fake-hardware',
                  'interface_type': 'deploy',
                  'interface_name': 'direct',
                  'default': True},
                 {'hardware_type': 'fake-hardware',
                  'interface_type': 'deploy',
                  'interface_name': 'ansible',
                  'default': False},
                 {'hardware_type': 'manual-management',
                  'interface_type': 'management',
                  'interface_name': 'fake',
                  'default': True},
                 {'hardware_type': 'manual-management',
                  'interface_type': 'deploy',
                  'interface_name': 'direct',
                  'default': True},
                 {'hardware_type': 'manual-management',
                  'interface_type': 'deploy',
                  'interface_name': 'fake',
                  'default': False}]
            )
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
                ('deploy', ['direct', 'ansible']),
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


@mock.patch.object(fake.FakeConsole, 'start_console', autospec=True)
@mock.patch.object(notification_utils, 'emit_console_notification',
                   autospec=True)
class StartConsolesTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    def test__start_consoles(self, mock_notify, mock_start_console):
        obj_utils.create_test_node(self.context,
                                   driver='fake-hardware',
                                   console_enabled=True)
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
            console_enabled=True
        )
        obj_utils.create_test_node(
            self.context,
            uuid=uuidutils.generate_uuid(),
            driver='fake-hardware',
        )
        # Enable consoles *after* service has started, otherwise it races
        # as the service startup also launches consoles.
        self._start_service(start_consoles=False)
        self.service._start_consoles(self.context)
        self.assertEqual(2, mock_start_console.call_count)
        mock_notify.assert_has_calls(
            [mock.call(mock.ANY, 'console_restore',
                       fields.NotificationStatus.START),
             mock.call(mock.ANY, 'console_restore',
                       fields.NotificationStatus.END)])

    def test__start_consoles_no_console_enabled(self, mock_notify,
                                                mock_start_console):
        obj_utils.create_test_node(self.context,
                                   driver='fake-hardware',
                                   console_enabled=False)
        self._start_service()
        self.service._start_consoles(self.context)
        self.assertFalse(mock_start_console.called)
        self.assertFalse(mock_notify.called)

    def test__start_consoles_failed(self, mock_notify, mock_start_console):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               console_enabled=True)
        self._start_service()
        mock_start_console.side_effect = Exception()
        self.service._start_consoles(self.context)
        mock_start_console.assert_called_once_with(mock.ANY, mock.ANY)
        test_node.refresh()
        self.assertFalse(test_node.console_enabled)
        self.assertIsNotNone(test_node.last_error)
        mock_notify.assert_has_calls(
            [mock.call(mock.ANY, 'console_restore',
                       fields.NotificationStatus.START),
             mock.call(mock.ANY, 'console_restore',
                       fields.NotificationStatus.ERROR)])
        history = objects.NodeHistory.list_by_node_id(self.context,
                                                      test_node.id)
        entry = history[0]
        self.assertEqual('startup failure', entry['event_type'])
        self.assertEqual('ERROR', entry['severity'])
        self.assertIsNotNone(entry['event'])

    @mock.patch.object(base_manager, 'LOG', autospec=True)
    def test__start_consoles_node_locked(self, log_mock, mock_notify,
                                         mock_start_console):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               console_enabled=True,
                                               reservation='fake-host')
        self._start_service()
        self.service._start_consoles(self.context)
        self.assertFalse(mock_start_console.called)
        test_node.refresh()
        self.assertTrue(test_node.console_enabled)
        self.assertIsNone(test_node.last_error)
        self.assertTrue(log_mock.warning.called)
        self.assertFalse(mock_notify.called)

    @mock.patch.object(base_manager, 'LOG', autospec=True)
    def test__start_consoles_node_not_found(self, log_mock, mock_notify,
                                            mock_start_console):
        test_node = obj_utils.create_test_node(self.context,
                                               driver='fake-hardware',
                                               console_enabled=True)
        self._start_service()
        with mock.patch.object(task_manager, 'acquire',
                               autospec=True) as mock_acquire:
            mock_acquire.side_effect = exception.NodeNotFound(node='not found')
            self.service._start_consoles(self.context)
            self.assertFalse(mock_start_console.called)
            test_node.refresh()
            self.assertTrue(test_node.console_enabled)
            self.assertIsNone(test_node.last_error)
            self.assertTrue(log_mock.warning.called)
            self.assertFalse(mock_notify.called)


class MiscTestCase(mgr_utils.ServiceSetUpMixin, db_base.DbTestCase):
    def setUp(self):
        super(MiscTestCase, self).setUp()
        self._start_service()

    def test__fail_transient_state(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake-hardware',
                                          provision_state=states.DEPLOYING)
        self.service._fail_transient_state(states.DEPLOYING, 'unknown err')
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)

    def test__fail_transient_state_maintenance(self):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake-hardware',
                                          maintenance=True,
                                          provision_state=states.DEPLOYING)
        self.service._fail_transient_state(states.DEPLOYING, 'unknown err')
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        history = objects.NodeHistory.list_by_node_id(self.context,
                                                      node.id)
        entry = history[0]
        self.assertEqual('transition', entry['event_type'])
        self.assertEqual('ERROR', entry['severity'])
        self.assertEqual('unknown err', entry['event'])
