# coding=utf-8

# Copyright 2013 Hewlett-Packard Development Company, L.P.
# Copyright 2013 International Business Machines Corporation
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

"""Test class for Ironic ManagerService."""

import eventlet
import mock
from oslo.config import cfg
from oslo.db import exception as db_exception
from oslo import messaging

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import keystone
from ironic.common import states
from ironic.common import utils as ironic_utils
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.db import api as dbapi
from ironic.drivers import base as drivers_base
from ironic import objects
from ironic.openstack.common import context
from ironic.tests import base as tests_base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as tests_db_base
from ironic.tests.db import utils
from ironic.tests.objects import utils as obj_utils

CONF = cfg.CONF


class _CommonMixIn(object):
    @staticmethod
    def _create_node(**kwargs):
        attrs = {'id': 1,
                 'uuid': ironic_utils.generate_uuid(),
                 'provision_state': states.POWER_OFF,
                 'maintenance': False,
                 'reservation': None}
        attrs.update(kwargs)
        node = mock.Mock(spec_set=objects.Node)
        for attr in attrs:
            setattr(node, attr, attrs[attr])
        return node

    def _create_task(self, node=None, node_attrs=None):
        if node_attrs is None:
            node_attrs = {}
        if node is None:
            node = self._create_node(**node_attrs)
        task = mock.Mock(spec_set=['node', 'release_resources',
                                   'spawn_after'])
        task.node = node
        return task

    def _get_nodeinfo_list_response(self, nodes=None):
        if nodes is None:
            nodes = [self.node]
        elif not isinstance(nodes, (list, tuple)):
            nodes = [nodes]
        return [tuple(getattr(n, c) for c in self.columns) for n in nodes]

    def _get_acquire_side_effect(self, task_infos):
        """Helper method to generate a task_manager.acquire() side effect.

        This accepts a list of information about task mocks to return.
        task_infos can be a single entity or a list.

        Each task_info can be a single entity, the task to return, or it
        can be a tuple of (task, exception_to_raise_on_exit). 'task' can
        be an exception to raise on __enter__.

        Examples: _get_acquire_side_effect(self, task): Yield task
                  _get_acquire_side_effect(self, [task, enter_exception(),
                                                  (task2, exit_exception())])
                       Yield task on first call to acquire()
                       raise enter_exception() in __enter__ on 2nd call to
                           acquire()
                       Yield task2 on 3rd call to acquire(), but raise
                           exit_exception() on __exit__()
        """
        tasks = []
        exit_exceptions = []
        if not isinstance(task_infos, list):
            task_infos = [task_infos]
        for task_info in task_infos:
            if isinstance(task_info, tuple):
                task, exc = task_info
            else:
                task = task_info
                exc = None
            tasks.append(task)
            exit_exceptions.append(exc)

        class FakeAcquire(object):
            def __init__(fa_self, context, node_id, *args, **kwargs):
                # We actually verify these arguments via
                # acquire_mock.call_args_list(). However, this stores the
                # node_id so we can assert we're returning the correct node
                # in __enter__().
                fa_self.node_id = node_id

            def __enter__(fa_self):
                task = tasks.pop(0)
                if isinstance(task, Exception):
                    raise task
                # NOTE(comstud): Not ideal to throw this into
                # a helper, however it's the cleanest way
                # to verify we're dealing with the correct task/node.
                if ironic_utils.is_int_like(fa_self.node_id):
                    self.assertEqual(fa_self.node_id, task.node.id)
                else:
                    self.assertEqual(fa_self.node_id, task.node.uuid)
                return task

            def __exit__(fa_self, exc_typ, exc_val, exc_tb):
                exc = exit_exceptions.pop(0)
                if exc_typ is None and exc is not None:
                    raise exc

        return FakeAcquire


class _ServiceSetUpMixin(object):
    def setUp(self):
        super(_ServiceSetUpMixin, self).setUp()
        self.hostname = 'test-host'
        self.config(enabled_drivers=['fake'])
        self.config(node_locked_retry_attempts=1, group='conductor')
        self.config(node_locked_retry_interval=0, group='conductor')
        self.service = manager.ConductorManager(self.hostname, 'test-topic')
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")

    def _stop_service(self):
        try:
            objects.Conductor.get_by_hostname(self.context, self.hostname)
        except exception.ConductorNotFound:
            return
        self.service.del_host()

    def _start_service(self):
        self.service.init_host()
        self.addCleanup(self._stop_service)


def _mock_record_keepalive(func_or_class):
    return mock.patch.object(
        manager.ConductorManager,
        '_conductor_service_record_keepalive',
        lambda: None)(func_or_class)


@_mock_record_keepalive
class StartStopTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_start_registers_conductor(self):
        self.assertRaises(exception.ConductorNotFound,
                          objects.Conductor.get_by_hostname,
                          self.context, self.hostname)
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])

    def test_stop_unregisters_conductor(self):
        self._start_service()
        res = objects.Conductor.get_by_hostname(self.context, self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        self.service.del_host()
        self.assertRaises(exception.ConductorNotFound,
                          objects.Conductor.get_by_hostname,
                          self.context, self.hostname)

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

    @mock.patch.object(driver_factory.DriverFactory, '__init__')
    def test_start_fails_on_missing_driver(self, mock_df):
        mock_df.side_effect = exception.DriverNotFound('test')
        with mock.patch.object(self.dbapi, 'register_conductor') as mock_reg:
            self.assertRaises(exception.DriverNotFound,
                              self.service.init_host)
            self.assertTrue(mock_df.called)
            self.assertFalse(mock_reg.called)


class KeepAliveTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
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


@_mock_record_keepalive
class ChangeNodePowerStateTestCase(_ServiceSetUpMixin,
                                   tests_db_base.DbTestCase):

    def test_change_node_power_state_power_on(self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        node = obj_utils.create_test_node(self.context,
                                          driver='fake',
                                          power_state=states.POWER_OFF)
        self._start_service()

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            self.service.change_node_power_state(self.context,
                                                 node.uuid,
                                                 states.POWER_ON)
            self.service._worker_pool.waitall()

            get_power_mock.assert_called_once_with(mock.ANY)
            node.refresh()
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNone(node.last_error)
            # Verify the reservation has been cleared by
            # background task's link callback.
            self.assertIsNone(node.reservation)

    @mock.patch.object(conductor_utils, 'node_power_action')
    def test_change_node_power_state_node_already_locked(self,
                                                         pwr_act_mock):
        # Test change_node_power_state with mocked
        # conductor.utils.node_power_action.
        fake_reservation = 'fake-reserv'
        pwr_state = states.POWER_ON
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          power_state=pwr_state,
                                          reservation=fake_reservation)
        self._start_service()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.change_node_power_state,
                                self.context,
                                node.uuid,
                                states.POWER_ON)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])

        # In this test worker should not be spawned, but waiting to make sure
        # the below perform_mock assertion is valid.
        self.service._worker_pool.waitall()
        self.assertFalse(pwr_act_mock.called, 'node_power_action has been '
                                              'unexpectedly called.')
        # Verify existing reservation wasn't broken.
        node.refresh()
        self.assertEqual(fake_reservation, node.reservation)

    def test_change_node_power_state_worker_pool_full(self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        initial_state = states.POWER_OFF
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          power_state=initial_state)
        self._start_service()

        with mock.patch.object(self.service,
                               '_spawn_worker') as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.change_node_power_state,
                                    self.context,
                                    node.uuid,
                                    states.POWER_ON)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])

            spawn_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                               mock.ANY)
            node.refresh()
            self.assertEqual(initial_state, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNotNone(node.last_error)
            # Verify the picked reservation has been cleared due to full pool.
            self.assertIsNone(node.reservation)

    def test_change_node_power_state_exception_in_background_task(
            self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        initial_state = states.POWER_OFF
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          power_state=initial_state)
        self._start_service()

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            with mock.patch.object(self.driver.power,
                                   'set_power_state') as set_power_mock:
                new_state = states.POWER_ON
                set_power_mock.side_effect = exception.PowerStateFailure(
                    pstate=new_state
                )

                self.service.change_node_power_state(self.context,
                                                     node.uuid,
                                                     new_state)
                self.service._worker_pool.waitall()

                get_power_mock.assert_called_once_with(mock.ANY)
                set_power_mock.assert_called_once_with(mock.ANY, new_state)
                node.refresh()
                self.assertEqual(initial_state, node.power_state)
                self.assertIsNone(node.target_power_state)
                self.assertIsNotNone(node.last_error)
                # Verify the reservation has been cleared by background task's
                # link callback despite exception in background task.
                self.assertIsNone(node.reservation)

    def test_change_node_power_state_validate_fail(self):
        # Test change_node_power_state where task.driver.power.validate
        # fails and raises an exception
        initial_state = states.POWER_ON
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          power_state=initial_state)
        self._start_service()

        with mock.patch.object(self.driver.power,
                               'validate') as validate_mock:
            validate_mock.side_effect = exception.InvalidParameterValue(
                'wrong power driver info')

            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.change_node_power_state,
                                    self.context,
                                    node.uuid,
                                    states.POWER_ON)

            self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

            node.refresh()
            validate_mock.assert_called_once_with(mock.ANY)
            self.assertEqual(states.POWER_ON, node.power_state)
            self.assertIsNone(node.target_power_state)
            self.assertIsNone(node.last_error)


@_mock_record_keepalive
class UpdateNodeTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_update_node(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          extra={'test': 'one'})

        # check that ManagerService.update_node actually updates the node
        node.extra = {'test': 'two'}
        res = self.service.update_node(self.context, node)
        self.assertEqual({'test': 'two'}, res['extra'])

    def test_update_node_clears_maintenance_reason(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          maintenance=True,
                                          maintenance_reason='reason')

        # check that ManagerService.update_node actually updates the node
        node.maintenance = False
        res = self.service.update_node(self.context, node)
        self.assertFalse(res['maintenance'])
        self.assertIsNone(res['maintenance_reason'])

    def test_update_node_already_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          extra={'test': 'one'})

        # check that it fails if something else has locked it already
        with task_manager.acquire(self.context, node['id'], shared=False):
            node.extra = {'test': 'two'}
            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.update_node,
                                    self.context,
                                    node)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.NodeLocked, exc.exc_info[0])

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual({'test': 'one'}, res['extra'])

    def test_associate_node_invalid_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          extra={'test': 'one'},
                                 instance_uuid=None,
                                 power_state=states.POWER_ON)

        # check that it fails because state is POWER_ON
        node.instance_uuid = 'fake-uuid'
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_node,
                                self.context,
                                node)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeInWrongPowerState, exc.exc_info[0])

        # verify change did not happen
        node.refresh()
        self.assertIsNone(node.instance_uuid)

    def test_associate_node_valid_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          power_state=states.NOSTATE)

        with mock.patch('ironic.drivers.modules.fake.FakePower.'
                        'get_power_state') as mock_get_power_state:

            mock_get_power_state.return_value = states.POWER_OFF
            node.instance_uuid = 'fake-uuid'
            self.service.update_node(self.context, node)

            # Check if the change was applied
            node.instance_uuid = 'meow'
            node.refresh()
            self.assertEqual('fake-uuid', node.instance_uuid)

    def test_update_node_invalid_driver(self):
        existing_driver = 'fake'
        wrong_driver = 'wrong-driver'
        node = obj_utils.create_test_node(self.context,
                                          driver=existing_driver,
                                          extra={'test': 'one'},
                                          instance_uuid=None,
                                          task_state=states.POWER_ON)
        # check that it fails because driver not found
        node.driver = wrong_driver
        node.driver_info = {}
        self.assertRaises(exception.DriverNotFound,
                          self.service.update_node,
                          self.context,
                          node)

        # verify change did not happen
        node.refresh()
        self.assertEqual(existing_driver, node.driver)


@_mock_record_keepalive
class VendorPassthruTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):

    @mock.patch.object(task_manager.TaskManager, 'spawn_after')
    def test_vendor_passthru_async(self, mock_spawn):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'baz'}
        self._start_service()

        ret, is_async = self.service.vendor_passthru(self.context, node.uuid,
                                                     'first_method', 'POST',
                                                     info)
        # Waiting to make sure the below assertions are valid.
        self.service._worker_pool.waitall()

        # Assert spawn_after was called
        self.assertTrue(mock_spawn.called)
        self.assertIsNone(ret)
        self.assertTrue(is_async)

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch.object(task_manager.TaskManager, 'spawn_after')
    def test_vendor_passthru_sync(self, mock_spawn):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'meow'}
        self._start_service()

        ret, is_async = self.service.vendor_passthru(self.context, node.uuid,
                                                     'third_method_sync',
                                                     'POST', info)
        # Waiting to make sure the below assertions are valid.
        self.service._worker_pool.waitall()

        # Assert no workers were used
        self.assertFalse(mock_spawn.called)
        self.assertTrue(ret)
        self.assertFalse(is_async)

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_http_method_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()

        # GET not supported by first_method
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.vendor_passthru,
                                self.context, node.uuid,
                                'first_method', 'GET', {})
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_node_already_locked(self):
        fake_reservation = 'test_reserv'
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation=fake_reservation)
        info = {'bar': 'baz'}
        self._start_service()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.vendor_passthru,
                                self.context, node.uuid, 'first_method',
                                'POST', info)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify the existing reservation is not broken.
        self.assertEqual(fake_reservation, node.reservation)

    def test_vendor_passthru_unsupported_method(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'baz'}
        self._start_service()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.vendor_passthru,
                                self.context, node.uuid,
                                'unsupported_method', 'POST', info)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue,
                         exc.exc_info[0])

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_missing_method_parameters(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'invalid_param': 'whatever'}
        self._start_service()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.vendor_passthru,
                                self.context, node.uuid,
                                'first_method', 'POST', info)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.MissingParameterValue, exc.exc_info[0])

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_vendor_interface_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'baz'}
        self.driver.vendor = None
        self._start_service()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.vendor_passthru,
                                self.context, node.uuid,
                                'whatever_method', 'POST', info)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

        node.refresh()
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_worker_pool_full(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'baz'}
        self._start_service()

        with mock.patch.object(self.service,
                               '_spawn_worker') as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.vendor_passthru,
                                    self.context, node.uuid,
                                    'first_method', 'POST', info)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])

            # Waiting to make sure the below assertions are valid.
            self.service._worker_pool.waitall()

            node.refresh()
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)

    @mock.patch.object(task_manager, 'acquire')
    def test_vendor_passthru_backwards_compat(self, acquire_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        vendor_passthru_ref = mock.Mock()
        self._start_service()

        driver = mock.Mock()
        driver.vendor.vendor_routes = {}
        driver.vendor.vendor_passthru = vendor_passthru_ref

        task = mock.Mock()
        task.node = node
        task.driver = driver

        acquire_mock.return_value.__enter__.return_value = task

        response = self.service.vendor_passthru(
            self.context, node.uuid, 'test_method', 'POST', {'bar': 'baz'})

        self.assertEqual((None, True), response)
        task.spawn_after.assert_called_once_with(mock.ANY, vendor_passthru_ref,
            task, bar='baz', method='test_method')

    def test_get_node_vendor_passthru_methods(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        fake_routes = {'test_method': {'async': True,
                                       'description': 'foo',
                                       'http_methods': ['POST'],
                                       'func': None}}
        self.driver.vendor.vendor_routes = fake_routes
        self._start_service()

        data = self.service.get_node_vendor_passthru_methods(self.context,
                                                         node.uuid)
        # The function reference should not be returned
        del fake_routes['test_method']['func']
        self.assertEqual(fake_routes, data)

    def test_get_node_vendor_passthru_methods_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self.driver.vendor = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.get_node_vendor_passthru_methods,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    @mock.patch.object(manager.ConductorManager, '_spawn_worker')
    def test_driver_vendor_passthru_sync(self, mock_spawn):
        expected = {'foo': 'bar'}
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        test_method = mock.MagicMock(return_value=expected)
        self.driver.vendor.driver_routes = {'test_method':
                                           {'func': test_method,
                                            'async': False,
                                            'http_methods': ['POST']}}
        self.service.init_host()
        # init_host() called _spawn_worker because of the heartbeat
        mock_spawn.reset_mock()

        vendor_args = {'test': 'arg'}
        got, is_async = self.service.driver_vendor_passthru(self.context,
                            'fake', 'test_method', 'POST', vendor_args)

        # Assert that the vendor interface has no custom
        # driver_vendor_passthru()
        self.assertFalse(hasattr(self.driver.vendor, 'driver_vendor_passthru'))
        self.assertEqual(expected, got)
        self.assertFalse(is_async)
        test_method.assert_called_once_with(self.context, **vendor_args)
        # No worker was spawned
        self.assertFalse(mock_spawn.called)

    @mock.patch.object(manager.ConductorManager, '_spawn_worker')
    def test_driver_vendor_passthru_async(self, mock_spawn):
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        test_method = mock.MagicMock()
        self.driver.vendor.driver_routes = {'test_sync_method':
                                           {'func': test_method,
                                            'async': True,
                                            'http_methods': ['POST']}}
        self.service.init_host()
        # init_host() called _spawn_worker because of the heartbeat
        mock_spawn.reset_mock()

        vendor_args = {'test': 'arg'}
        got, is_async = self.service.driver_vendor_passthru(self.context,
                            'fake', 'test_sync_method', 'POST', vendor_args)

        # Assert that the vendor interface has no custom
        # driver_vendor_passthru()
        self.assertFalse(hasattr(self.driver.vendor, 'driver_vendor_passthru'))
        self.assertIsNone(got)
        self.assertTrue(is_async)
        mock_spawn.assert_called_once_with(test_method, self.context,
                                           **vendor_args)

    def test_driver_vendor_passthru_http_method_not_supported(self):
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        self.driver.vendor.driver_routes = {'test_method':
                                           {'func': mock.MagicMock(),
                                            'async': True,
                                            'http_methods': ['POST']}}
        self.service.init_host()
        # GET not supported by test_method
        exc = self.assertRaises(messaging.ExpectedException,
                                self.service.driver_vendor_passthru,
                                self.context, 'fake', 'test_method',
                                'GET', {})
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue,
                         exc.exc_info[0])

    def test_driver_vendor_passthru_vendor_interface_not_supported(self):
        # Test for when no vendor interface is set at all
        self.driver.vendor = None
        self.service.init_host()
        exc = self.assertRaises(messaging.ExpectedException,
                                self.service.driver_vendor_passthru,
                                self.context, 'fake', 'test_method',
                                'POST', {})
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    def test_driver_vendor_passthru_method_not_supported(self):
        # Test for when the vendor interface is set, but hasn't passed a
        # driver_passthru_mapping to MixinVendorInterface
        self.service.init_host()
        exc = self.assertRaises(messaging.ExpectedException,
                                self.service.driver_vendor_passthru,
                                self.context, 'fake', 'test_method',
                                'POST', {})
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue,
                         exc.exc_info[0])

    def test_driver_vendor_passthru_driver_not_found(self):
        self.service.init_host()
        self.assertRaises(messaging.ExpectedException,
                          self.service.driver_vendor_passthru,
                          self.context, 'does_not_exist', 'test_method',
                          'POST', {})

    def test_driver_vendor_passthru_backwards_compat(self):
        expected = {'foo': 'bar'}
        driver_vendor_passthru_ref = mock.Mock(return_value=expected)

        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        self.driver.vendor.driver_routes = {}
        self.driver.vendor.driver_vendor_passthru = driver_vendor_passthru_ref

        self.service.init_host()

        vendor_args = {'test': 'arg'}
        response = self.service.driver_vendor_passthru(self.context,
                       'fake', 'test_method', 'POST', vendor_args)

        self.assertEqual((expected, False), response)
        driver_vendor_passthru_ref.assert_called_once_with(
                self.context, test='arg', method='test_method')

    def test_get_driver_vendor_passthru_methods(self):
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        fake_routes = {'test_method': {'async': True,
                                       'description': 'foo',
                                       'http_methods': ['POST'],
                                       'func': None}}
        self.driver.vendor.driver_routes = fake_routes
        self.service.init_host()

        data = self.service.get_driver_vendor_passthru_methods(self.context,
                                                               'fake')
        # The function reference should not be returned
        del fake_routes['test_method']['func']
        self.assertEqual(fake_routes, data)

    def test_get_driver_vendor_passthru_methods_not_supported(self):
        self.service.init_host()
        self.driver.vendor = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                              self.service.get_driver_vendor_passthru_methods,
                              self.context, 'fake')
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    @mock.patch.object(drivers_base.VendorInterface, 'driver_validate')
    def test_driver_vendor_passthru_validation_failed(self, validate_mock):
        validate_mock.side_effect = exception.MissingParameterValue('error')
        test_method = mock.Mock()
        self.driver.vendor.driver_routes = {'test_method':
                                           {'func': test_method,
                                            'async': False,
                                            'http_methods': ['POST']}}
        self.service.init_host()
        exc = self.assertRaises(messaging.ExpectedException,
                                self.service.driver_vendor_passthru,
                                self.context, 'fake', 'test_method',
                                'POST', {})
        self.assertEqual(exception.MissingParameterValue,
                         exc.exc_info[0])
        self.assertFalse(test_method.called)


@_mock_record_keepalive
class DoNodeDeployTearDownTestCase(_ServiceSetUpMixin,
                                   tests_db_base.DbTestCase):
    def test_do_node_deploy_invalid_state(self):
        # test node['provision_state'] is not NOSTATE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_do_node_deploy_maintenance(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          maintenance=True)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeInMaintenance, exc.exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def _test_do_node_deploy_validate_fail(self, mock_validate):
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(self.context, driver='fake')
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.validate')
    def test_do_node_deploy_validate_fail(self, mock_validate):
        self._test_do_node_deploy_validate_fail(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_deploy_power_validate_fail(self, mock_validate):
        self._test_do_node_deploy_validate_fail(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_driver_raises_error(self, mock_deploy):
        # test when driver.deploy.deploy raises an exception
        mock_deploy.side_effect = exception.InstanceDeployFailure('test')
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          self.service._do_node_deploy, task)
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok(self, mock_deploy):
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_node_deploy(task)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    def test_do_node_deploy_partial_ok(self):
        self._start_service()
        thread = self.service._spawn_worker(lambda: None)
        with mock.patch.object(self.service, '_spawn_worker') as mock_spawn:
            mock_spawn.return_value = thread

            node = obj_utils.create_test_node(self.context, driver='fake',
                                              provision_state=states.NOSTATE)

            self.service.do_node_deploy(self.context, node.uuid)
            self.service._worker_pool.waitall()
            node.refresh()
            self.assertEqual(states.DEPLOYING, node.provision_state)
            self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
            # This is a sync operation last_error should be None.
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)
            mock_spawn.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_active_state(self, mock_deploy):
        self._start_service()
        mock_deploy.return_value = states.DEPLOYING
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self.service._worker_pool.waitall()
        node.refresh()
        self.assertEqual(states.DEPLOYING, node.provision_state)
        self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_deployfail_state(self, mock_deploy):
        self._start_service()
        mock_deploy.return_value = states.DEPLOYING
        node = obj_utils.create_test_node(self.context, driver='fake',
                                        provision_state=states.DEPLOYFAIL)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self.service._worker_pool.waitall()
        node.refresh()
        self.assertEqual(states.DEPLOYING, node.provision_state)
        self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_error_state(self, mock_deploy):
        self._start_service()
        mock_deploy.return_value = states.DEPLOYING
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ERROR)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self.service._worker_pool.waitall()
        node.refresh()
        self.assertEqual(states.DEPLOYING, node.provision_state)
        self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)

    def test_do_node_deploy_rebuild_nostate_state(self):
        # test node will not rebuild if state is NOSTATE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.NOSTATE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'], rebuild=True)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])
        # Last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_do_node_deploy_worker_pool_full(self):
        prv_state = states.NOSTATE
        tgt_prv_state = states.NOSTATE
        node = obj_utils.create_test_node(self.context,
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None, driver='fake')
        self._start_service()

        with mock.patch.object(self.service, '_spawn_worker') as mock_spawn:
            mock_spawn.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.do_node_deploy,
                                    self.context, node.uuid)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
            self.service._worker_pool.waitall()
            node.refresh()
            # Make sure things were rolled back
            self.assertEqual(prv_state, node.provision_state)
            self.assertEqual(tgt_prv_state, node.target_provision_state)
            self.assertIsNotNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)

    def test_do_node_tear_down_invalid_state(self):
        # test node.provision_state is incorrect for tear_down
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.NOSTATE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_tear_down,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_tear_down_validate_fail(self, mock_validate):
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                               self.service.do_node_tear_down,
                               self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_driver_raises_error(self, mock_tear_down):
        # test when driver.deploy.tear_down raises exception
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE,
                                          instance_info={'foo': 'bar'})

        task = task_manager.TaskManager(self.context, node.uuid)
        self._start_service()
        mock_tear_down.side_effect = exception.InstanceDeployFailure('test')
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service._do_node_tear_down, task)
        node.refresh()
        self.assertEqual(states.ERROR, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Assert instance_info was erased
        self.assertEqual({}, node.instance_info)
        mock_tear_down.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_ok(self, mock_tear_down):
        # test when driver.deploy.tear_down returns DELETED
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DELETING,
                                          instance_info={'foo': 'bar'})

        task = task_manager.TaskManager(self.context, node.uuid)
        self._start_service()
        mock_tear_down.return_value = states.DELETED
        self.service._do_node_tear_down(task)
        node.refresh()
        self.assertEqual(states.NOSTATE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        self.assertEqual({}, node.instance_info)
        mock_tear_down.assert_called_once_with(mock.ANY)

    # NOTE(deva): partial tear-down was broken. A node left in a state of
    #             DELETING could not have tear_down called on it a second time
    #             Thus, I have removed the unit test, which faultily asserted
    #             only that a node could be left in a state of incomplete
    #             deletion -- not that such a node's deletion could later be
    #             completed.

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_node_tear_down_worker_pool_full(self, mock_spawn):
        prv_state = states.ACTIVE
        tgt_prv_state = states.NOSTATE
        fake_instance_info = {'foo': 'bar'}
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          instance_info=fake_instance_info,
                                          last_error=None)
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_tear_down,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
        self.service._worker_pool.waitall()
        node.refresh()
        # Assert instance_info was not touched
        self.assertEqual(fake_instance_info, node.instance_info)
        # Make sure things were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)


@_mock_record_keepalive
class MiscTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_get_driver_known(self):
        self._start_service()
        driver = self.service._get_driver('fake')
        self.assertTrue(isinstance(driver, drivers_base.BaseDriver))

    def test_get_driver_unknown(self):
        self._start_service()
        self.assertRaises(exception.DriverNotFound,
                          self.service._get_driver, 'unknown_driver')

    def test__mapped_to_this_conductor(self):
        self._start_service()
        n = utils.get_test_node()
        self.assertTrue(self.service._mapped_to_this_conductor(n['uuid'],
                                                               'fake'))
        self.assertFalse(self.service._mapped_to_this_conductor(n['uuid'],
                                                                'otherdriver'))

    def test_validate_driver_interfaces(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        ret = self.service.validate_driver_interfaces(self.context,
                                                      node.uuid)
        expected = {'console': {'result': True},
                    'power': {'result': True},
                    'management': {'result': True},
                    'deploy': {'result': True}}
        self.assertEqual(expected, ret)

    def test_validate_driver_interfaces_validation_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        with mock.patch(
                 'ironic.drivers.modules.fake.FakeDeploy.validate'
             ) as deploy:
            reason = 'fake reason'
            deploy.side_effect = exception.InvalidParameterValue(reason)
            ret = self.service.validate_driver_interfaces(self.context,
                                                          node.uuid)
            self.assertFalse(ret['deploy']['result'])
            self.assertEqual(reason, ret['deploy']['reason'])


@_mock_record_keepalive
class ConsoleTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_set_console_mode_worker_pool_full(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()
        with mock.patch.object(self.service,
                               '_spawn_worker') as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.set_console_mode,
                                    self.context, node.uuid, True)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
            self.service._worker_pool.waitall()
            spawn_mock.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_set_console_mode_enabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, True)
        self.service._worker_pool.waitall()
        node.refresh()
        self.assertTrue(node.console_enabled)

    def test_set_console_mode_disabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, False)
        self.service._worker_pool.waitall()
        node.refresh()
        self.assertFalse(node.console_enabled)

    def test_set_console_mode_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          last_error=None)
        self._start_service()
        # null the console interface
        self.driver.console = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.set_console_mode, self.context,
                                node.uuid, True)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])
        self.service._worker_pool.waitall()
        node.refresh()

    def test_set_console_mode_validation_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          last_error=None)
        self._start_service()
        with mock.patch.object(self.driver.console, 'validate') as mock_val:
            mock_val.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.set_console_mode,
                                    self.context, node.uuid, True)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    def test_set_console_mode_start_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          last_error=None,
                                          console_enabled=False)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.service.set_console_mode(self.context, node.uuid, True)
            self.service._worker_pool.waitall()
            mock_sc.assert_called_once_with(mock.ANY)
            node.refresh()
            self.assertIsNotNone(node.last_error)

    def test_set_console_mode_stop_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          last_error=None,
                                          console_enabled=True)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'stop_console') as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.service.set_console_mode(self.context, node.uuid, False)
            self.service._worker_pool.waitall()
            mock_sc.assert_called_once_with(mock.ANY)
            node.refresh()
            self.assertIsNotNone(node.last_error)

    def test_enable_console_already_enabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'start_console') as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, True)
            self.service._worker_pool.waitall()
            self.assertFalse(mock_sc.called)

    def test_disable_console_already_disabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=False)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'stop_console') as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, False)
            self.service._worker_pool.waitall()
            self.assertFalse(mock_sc.called)

    def test_get_console(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        console_info = {'test': 'test info'}
        with mock.patch.object(self.driver.console, 'get_console') as mock_gc:
            mock_gc.return_value = console_info
            data = self.service.get_console_information(self.context,
                                                        node.uuid)
            self.assertEqual(console_info, data)

    def test_get_console_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        # null the console interface
        self.driver.console = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                          self.service.get_console_information,
                          self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    def test_get_console_disabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=False)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.get_console_information,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeConsoleNotEnabled, exc.exc_info[0])

    def test_get_console_validate_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        with mock.patch.object(self.driver.console, 'validate') as mock_gc:
            mock_gc.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.get_console_information,
                                    self.context, node.uuid)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])


@_mock_record_keepalive
class DestroyNodeTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_destroy_node(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake')
        self.service.destroy_node(self.context, node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid,
                          node.uuid)

    def test_destroy_node_reserved(self):
        self._start_service()
        fake_reservation = 'fake-reserv'
        node = obj_utils.create_test_node(self.context,
                                          reservation=fake_reservation)

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])
        # Verify existing reservation wasn't broken.
        node.refresh()
        self.assertEqual(fake_reservation, node.reservation)

    def test_destroy_node_associated(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          instance_uuid='fake-uuid')

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeAssociated, exc.exc_info[0])

        # Verify reservation was released.
        node.refresh()
        self.assertIsNone(node.reservation)

    def test_destroy_node_power_on(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          power_state=states.POWER_ON)

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeInWrongPowerState, exc.exc_info[0])
        # Verify reservation was released.
        node.refresh()
        self.assertIsNone(node.reservation)

    def test_destroy_node_power_off(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          power_state=states.POWER_OFF)
        self.service.destroy_node(self.context, node.uuid)


@_mock_record_keepalive
class UpdatePortTestCase(_ServiceSetUpMixin, tests_db_base.DbTestCase):
    def test_update_port(self):
        node = obj_utils.create_test_node(self.context, driver='fake')

        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'foo': 'bar'})
        new_extra = {'foo': 'baz'}
        port.extra = new_extra
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_extra, res.extra)

    def test_update_port_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                   reservation='fake-reserv')

        port = obj_utils.create_test_port(self.context, node_id=node.id)
        port.extra = {'foo': 'baz'}
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id'})
        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_address, res.address)
        mac_update_mock.assert_called_once_with('fake-id', new_address,
                                                token=self.context.auth_token)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_fail(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id'})
        old_address = port.address
        port.address = '11:22:33:44:55:bb'
        mac_update_mock.side_effect = exception.FailedToUpdateMacOnPort(
                                                            port_id=port.uuid)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.FailedToUpdateMacOnPort, exc.exc_info[0])
        port.refresh()
        self.assertEqual(old_address, port.address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_no_vif_id(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context, node_id=node.id)

        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_address, res.address)
        self.assertFalse(mac_update_mock.called)

    def test__filter_out_unsupported_types_all(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['All'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = self.service._filter_out_unsupported_types(
                                                       fake_sensors_data)
        expected_result = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        self.assertEqual(expected_result, actual_result)

    def test__filter_out_unsupported_types_part(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['t1'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = self.service._filter_out_unsupported_types(
                                                       fake_sensors_data)
        expected_result = {"t1": {'f1': 'v1'}}
        self.assertEqual(expected_result, actual_result)

    def test__filter_out_unsupported_types_non(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['t3'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = self.service._filter_out_unsupported_types(
                                                       fake_sensors_data)
        expected_result = {}
        self.assertEqual(expected_result, actual_result)

    @mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
    @mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
    @mock.patch.object(task_manager, 'acquire')
    def test___send_sensor_data(self, acquire_mock, get_nodeinfo_list_mock,
         _mapped_to_this_conductor_mock):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake')
        self._start_service()
        CONF.set_override('send_sensor_data', True, group='conductor')
        acquire_mock.return_value.__enter__.return_value.driver = self.driver
        with mock.patch.object(self.driver.management,
                               'get_sensors_data') as get_sensors_data_mock:
            with mock.patch.object(self.driver.management,
                                   'validate') as validate_mock:
                get_sensors_data_mock.return_value = 'fake-sensor-data'
                _mapped_to_this_conductor_mock.return_value = True
                get_nodeinfo_list_mock.return_value = [(node.uuid, node.driver,
                                                     node.instance_uuid)]
                self.service._send_sensor_data(self.context)
                self.assertTrue(get_nodeinfo_list_mock.called)
                self.assertTrue(_mapped_to_this_conductor_mock.called)
                self.assertTrue(acquire_mock.called)
                self.assertTrue(get_sensors_data_mock.called)
                self.assertTrue(validate_mock.called)

    @mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
    @mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
    @mock.patch.object(task_manager, 'acquire')
    def test___send_sensor_data_disabled(self, acquire_mock,
        get_nodeinfo_list_mock, _mapped_to_this_conductor_mock):
        node = obj_utils.create_test_node(self.context,
                                          driver='fake')
        self._start_service()
        acquire_mock.return_value.__enter__.return_value.driver = self.driver
        with mock.patch.object(self.driver.management,
                               'get_sensors_data') as get_sensors_data_mock:
            with mock.patch.object(self.driver.management,
                                   'validate') as validate_mock:
                get_sensors_data_mock.return_value = 'fake-sensor-data'
                _mapped_to_this_conductor_mock.return_value = True
                get_nodeinfo_list_mock.return_value = [(node.uuid, node.driver,
                                                     node.instance_uuid)]
                self.service._send_sensor_data(self.context)
                self.assertFalse(get_nodeinfo_list_mock.called)
                self.assertFalse(_mapped_to_this_conductor_mock.called)
                self.assertFalse(acquire_mock.called)
                self.assertFalse(get_sensors_data_mock.called)
                self.assertFalse(validate_mock.called)

    def test_set_boot_device(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        with mock.patch.object(self.driver.management, 'validate') as mock_val:
            with mock.patch.object(self.driver.management,
                                   'set_boot_device') as mock_sbd:
                self.service.set_boot_device(self.context, node.uuid,
                                             boot_devices.PXE)
                mock_val.assert_called_once_with(mock.ANY)
                mock_sbd.assert_called_once_with(mock.ANY, boot_devices.PXE,
                                                 persistent=False)

    def test_set_boot_device_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation='fake-reserv')
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.set_boot_device,
                                self.context, node.uuid, boot_devices.DISK)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])

    def test_set_boot_device_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        # null the console interface
        self.driver.management = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                          self.service.set_boot_device,
                          self.context, node.uuid, boot_devices.DISK)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    def test_set_boot_device_validate_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        with mock.patch.object(self.driver.management, 'validate') as mock_val:
            mock_val.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.set_boot_device,
                                    self.context, node.uuid, boot_devices.DISK)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    def test_get_boot_device(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        bootdev = self.service.get_boot_device(self.context, node.uuid)
        expected = {'boot_device': boot_devices.PXE, 'persistent': False}
        self.assertEqual(expected, bootdev)

    def test_get_boot_device_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation='fake-reserv')
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.get_boot_device,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])

    def test_get_boot_device_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        # null the management interface
        self.driver.management = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                          self.service.get_boot_device,
                          self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    def test_get_boot_device_validate_fail(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        with mock.patch.object(self.driver.management, 'validate') as mock_val:
            mock_val.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.rpc.ExpectedException,
                                    self.service.get_boot_device,
                                    self.context, node.uuid)
            # Compare true exception hidden by @messaging.expected_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])

    def test_get_supported_boot_devices(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        bootdevs = self.service.get_supported_boot_devices(self.context,
                                                           node.uuid)
        self.assertEqual([boot_devices.PXE], bootdevs)

    def test_get_supported_boot_devices_iface_not_supported(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        # null the management interface
        self.driver.management = None
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                          self.service.get_supported_boot_devices,
                          self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])


class ManagerSpawnWorkerTestCase(tests_base.TestCase):
    def setUp(self):
        super(ManagerSpawnWorkerTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')

    def test__spawn_worker(self):
        worker_pool = mock.Mock(spec_set=['free', 'spawn'])
        worker_pool.free.return_value = True
        self.service._worker_pool = worker_pool

        self.service._spawn_worker('fake', 1, 2, foo='bar', cat='meow')

        worker_pool.spawn.assert_called_once_with(
                'fake', 1, 2, foo='bar', cat='meow')

    def test__spawn_worker_none_free(self):
        worker_pool = mock.Mock(spec_set=['free', 'spawn'])
        worker_pool.free.return_value = False
        self.service._worker_pool = worker_pool

        self.assertRaises(exception.NoFreeConductorWorker,
                          self.service._spawn_worker, 'fake')

        self.assertFalse(worker_pool.spawn.called)


@mock.patch.object(conductor_utils, 'node_power_action')
class ManagerDoSyncPowerStateTestCase(tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerDoSyncPowerStateTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.driver = mock.Mock(spec_set=drivers_base.BaseDriver)
        self.power = self.driver.power
        self.node = mock.Mock(spec_set=objects.Node)
        self.task = mock.Mock(spec_set=['context', 'driver', 'node'])
        self.task.context = self.context
        self.task.driver = self.driver
        self.task.node = self.node
        self.config(force_power_state_during_sync=False, group='conductor')

    def _do_sync_power_state(self, old_power_state, new_power_states,
                             fail_validate=False, fail_change=False):
        if not isinstance(new_power_states, (list, tuple)):
            new_power_states = [new_power_states]
        if fail_validate:
            exc = exception.InvalidParameterValue('error')
            self.power.validate.side_effect = exc
        if fail_change:
            exc = exception.IronicException('test')
            self.power.node_power_action.side_effect = exc
        for new_power_state in new_power_states:
            self.node.power_state = old_power_state
            if isinstance(new_power_state, Exception):
                self.power.get_power_state.side_effect = new_power_state
            else:
                self.power.get_power_state.return_value = new_power_state
            self.service._do_sync_power_state(self.task)

    def test_state_unchanged(self, node_power_action):
        self._do_sync_power_state('fake-power', 'fake-power')

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertEqual('fake-power', self.node.power_state)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)

    def test_state_not_set(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON)

        self.power.validate.assert_called_once_with(self.task)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.node.save.assert_called_once_with()
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    def test_validate_fail(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON,
                                  fail_validate=True)

        self.power.validate.assert_called_once_with(self.task)
        self.assertFalse(self.power.get_power_state.called)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)
        self.assertEqual(None, self.node.power_state)

    def test_get_power_state_fail(self, node_power_action):
        self._do_sync_power_state('fake',
                                  exception.IronicException('foo'))

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)
        self.assertEqual('fake', self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_get_power_state_error(self, node_power_action):
        self._do_sync_power_state('fake', states.ERROR)
        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)
        self.assertEqual('fake', self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_state_changed_no_sync(self, node_power_action):
        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.node.save.assert_called_once_with()
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_OFF, self.node.power_state)

    def test_state_changed_sync(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=1, group='conductor')

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(self.node.save.called)
        node_power_action.assert_called_once_with(self.task, states.POWER_ON)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    def test_state_changed_sync_failed(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF,
                                  fail_change=True)

        # Just testing that this test doesn't raise.
        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(self.node.save.called)
        node_power_action.assert_called_once_with(self.task, states.POWER_ON)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_max_retries_exceeded(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=1, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task)] * 2
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.node.save.assert_called_once_with()
        node_power_action.assert_called_once_with(self.task, states.POWER_ON)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])
        self.assertTrue(self.node.maintenance)
        self.assertIsNotNone(self.node.maintenance_reason)

    def test_max_retries_exceeded2(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=2, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF,
                                                    states.POWER_OFF])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task)] * 3
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.node.save.assert_called_once_with()
        npa_exp_calls = [mock.call(self.task, states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(2,
                         self.service.power_state_sync_count[self.node.uuid])
        self.assertTrue(self.node.maintenance)

    def test_retry_then_success(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=2, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF,
                                                    states.POWER_ON])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task)] * 3
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.assertFalse(self.node.save.called)
        npa_exp_calls = [mock.call(self.task, states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertNotIn(self.node.uuid, self.service.power_state_sync_count)

    def test_power_state_sync_max_retries_gps_exception(self,
                                                        node_power_action):
        self.config(power_state_sync_max_retries=2, group='conductor')
        self.service.power_state_sync_count[self.node.uuid] = 2

        self._do_sync_power_state('fake',
                                  exception.IronicException('foo'),
                                  fail_change=True)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)

        self.assertEqual(None, self.node.power_state)
        self.assertTrue(self.node.maintenance)
        self.assertTrue(self.node.save.called)

        self.assertFalse(node_power_action.called)


@mock.patch.object(manager.ConductorManager, '_do_sync_power_state')
@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(objects.Node, 'get_by_id')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerSyncPowerStatesTestCase(_CommonMixIn, tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerSyncPowerStatesTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.service.dbapi = self.dbapi
        self.node = self._create_node()
        self.filters = {'reserved': False, 'maintenance': False}
        self.columns = ['id', 'uuid', 'driver']

    def test_node_not_mapped(self, get_nodeinfo_mock, get_node_mock,
                             mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = False

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        self.assertFalse(get_node_mock.called)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_disappeared(self, get_nodeinfo_mock, get_node_mock,
                              mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        get_node_mock.side_effect = exception.NodeNotFound(node=self.node.uuid)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_in_deploywait(self, get_nodeinfo_mock, get_node_mock,
                                mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        self.node.provision_state = states.DEPLOYWAIT

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_in_maintenance(self, get_nodeinfo_mock, get_node_mock,
                                 mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        self.node.maintenance = True

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_has_reservation(self, get_nodeinfo_mock, get_node_mock,
                                  mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        self.node.reservation = 'fake'

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_locked_on_acquire(self, get_nodeinfo_mock, get_node_mock,
                                    mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeLocked(node=self.node.uuid,
                                                        host='fake')

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(sync_mock.called)

    def test_node_in_deploywait_on_acquire(self, get_nodeinfo_mock,
                                           get_node_mock, mapped_mock,
                                           acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        task = self._create_task(
                node_attrs=dict(provision_state=states.DEPLOYWAIT,
                                id=self.node.id))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(sync_mock.called)

    def test_node_in_maintenance_on_acquire(self, get_nodeinfo_mock,
                                            get_node_mock, mapped_mock,
                                            acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        task = self._create_task(
                node_attrs=dict(maintenance=True, id=self.node.id))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(sync_mock.called)

    def test_node_disappears_on_acquire(self, get_nodeinfo_mock,
                                        get_node_mock, mapped_mock,
                                        acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeNotFound(node=self.node.uuid,
                                                          host='fake')

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(sync_mock.called)

    def test_single_node(self, get_nodeinfo_mock, get_node_mock,
                         mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        task = self._create_task(node_attrs=dict(id=self.node.id))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.context, self.node.id)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        sync_mock.assert_called_once_with(task)

    def test__sync_power_state_multiple_nodes(self, get_nodeinfo_mock,
                                              get_node_mock, mapped_mock,
                                              acquire_mock, sync_mock):
        # Create 11 nodes:
        # 1st node: Should acquire and try to sync
        # 2nd node: Not mapped to this conductor
        # 3rd node: In DEPLOYWAIT provision_state
        # 4th node: In maintenance mode
        # 5th node: Has a reservation
        # 6th node: Disappears after getting nodeinfo list.
        # 7th node: task_manger.acquire() fails due to lock
        # 8th node: task_manger.acquire() fails due to node disappearing
        # 9th node: In DEPLOYWAIT provision_state acquire()
        # 10th node: In maintenance mode on acquire()
        # 11th node: Should acquire and try to sync
        nodes = []
        get_node_map = {}
        mapped_map = {}
        for i in range(1, 12):
            attrs = {'id': i,
                     'uuid': ironic_utils.generate_uuid()}
            if i == 3:
                attrs['provision_state'] = states.DEPLOYWAIT
            elif i == 4:
                attrs['maintenance'] = True
            elif i == 5:
                attrs['reservation'] = 'fake'

            n = self._create_node(**attrs)
            nodes.append(n)
            mapped_map[n.uuid] = False if i == 2 else True
            get_node_map[n.uuid] = n

        tasks = [self._create_task(node_attrs=dict(id=1)),
                 exception.NodeLocked(node=7, host='fake'),
                 exception.NodeNotFound(node=8, host='fake'),
                 self._create_task(
                     node_attrs=dict(id=9,
                                     provision_state=states.DEPLOYWAIT)),
                 self._create_task(
                     node_attrs=dict(id=10, maintenance=True)),
                 self._create_task(node_attrs=dict(id=11))]

        def _get_node_side_effect(ctxt, node_id):
            if node_id == 6:
                # Make this node disappear
                raise exception.NodeNotFound(node=node_id)
            return nodes[node_id - 1]

        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                nodes)
        mapped_mock.side_effect = lambda x, y: mapped_map[x]
        get_node_mock.side_effect = _get_node_side_effect
        acquire_mock.side_effect = self._get_acquire_side_effect(tasks)

        with mock.patch.object(eventlet, 'sleep') as sleep_mock:
            self.service._sync_power_states(self.context)
            # Ensure we've yielded on every iteration
            self.assertEqual(len(nodes), sleep_mock.call_count)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_calls = [mock.call(x.uuid, x.driver) for x in nodes]
        self.assertEqual(mapped_calls, mapped_mock.call_args_list)
        get_node_calls = [mock.call(self.context, x.id)
                for x in nodes[:1] + nodes[2:]]
        self.assertEqual(get_node_calls,
                         get_node_mock.call_args_list)
        acquire_calls = [mock.call(self.context, x.id)
                for x in nodes[:1] + nodes[6:]]
        self.assertEqual(acquire_calls, acquire_mock.call_args_list)
        sync_calls = [mock.call(tasks[0]), mock.call(tasks[5])]
        self.assertEqual(sync_calls, sync_mock.call_args_list)


@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerCheckDeployTimeoutsTestCase(_CommonMixIn,
                                         tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerCheckDeployTimeoutsTestCase, self).setUp()
        self.config(deploy_callback_timeout=300, group='conductor')
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.service.dbapi = self.dbapi

        self.node = self._create_node(provision_state=states.DEPLOYWAIT)
        self.task = self._create_task(node=self.node)

        self.node2 = self._create_node(provision_state=states.DEPLOYWAIT)
        self.task2 = self._create_task(node=self.node2)

        self.filters = {'reserved': False, 'maintenance': False,
                        'provisioned_before': 300,
                        'provision_state': states.DEPLOYWAIT}
        self.columns = ['uuid', 'driver']

    def _assert_get_nodeinfo_args(self, get_nodeinfo_mock):
        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters,
                sort_key='provision_updated_at', sort_dir='asc')

    def test_disabled(self, get_nodeinfo_mock, mapped_mock,
                      acquire_mock):
        self.config(deploy_callback_timeout=0, group='conductor')

        self.service._check_deploy_timeouts(self.context)

        self.assertFalse(get_nodeinfo_mock.called)
        self.assertFalse(mapped_mock.called)
        self.assertFalse(acquire_mock.called)

    def test_not_mapped(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = False

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)

    def test_timeout(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(self.task)

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid)
        self.task.spawn_after.assert_called_with(
                self.service._spawn_worker,
                conductor_utils.cleanup_after_timeout, self.task)

    def test_acquire_node_disappears(self, get_nodeinfo_mock, mapped_mock,
                                     acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeNotFound(node='fake')

        # Exception eaten
        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(
                self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid)
        self.assertFalse(self.task.spawn_after.called)

    def test_acquire_node_locked(self, get_nodeinfo_mock, mapped_mock,
                                 acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeLocked(node='fake',
                                                        host='fake')

        # Exception eaten
        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(
                self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid)
        self.assertFalse(self.task.spawn_after.called)

    def test_no_deploywait_after_lock(self, get_nodeinfo_mock, mapped_mock,
                                      acquire_mock):
        task = self._create_task(
                node_attrs=dict(provision_state=states.NOSTATE,
                                uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(
                self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid)
        self.assertFalse(task.spawn_after.called)

    def test_maintenance_after_lock(self, get_nodeinfo_mock, mapped_mock,
                                    acquire_mock):
        task = self._create_task(
                node_attrs=dict(provision_state=states.DEPLOYWAIT,
                                maintenance=True,
                                uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                [task.node, self.node2])
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                [task, self.task2])

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        self.assertEqual([mock.call(self.node.uuid, task.node.driver),
                          mock.call(self.node2.uuid, self.node2.driver)],
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid),
                          mock.call(self.context, self.node2.uuid)],
                         acquire_mock.call_args_list)
        # First node skipped
        self.assertFalse(task.spawn_after.called)
        # Second node spawned
        self.task2.spawn_after.assert_called_with(
                self.service._spawn_worker,
                conductor_utils.cleanup_after_timeout, self.task2)

    def test_exiting_no_worker_avail(self, get_nodeinfo_mock, mapped_mock,
                                     acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                [self.node, self.node2])
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                [(self.task, exception.NoFreeConductorWorker()), self.task2])

        # Exception should be nuked
        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        # mapped should be only called for the first node as we should
        # have exited the loop early due to NoFreeConductorWorker
        mapped_mock.assert_called_once_with(
                self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid)
        self.task.spawn_after.assert_called_with(
                self.service._spawn_worker,
                conductor_utils.cleanup_after_timeout, self.task)

    def test_exiting_with_other_exception(self, get_nodeinfo_mock,
                                          mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                [self.node, self.node2])
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                [(self.task, exception.IronicException('foo')), self.task2])

        # Should re-raise
        self.assertRaises(exception.IronicException,
                          self.service._check_deploy_timeouts,
                          self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        # mapped should be only called for the first node as we should
        # have exited the loop early due to unknown exception
        mapped_mock.assert_called_once_with(
                self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid)
        self.task.spawn_after.assert_called_with(
                self.service._spawn_worker,
                conductor_utils.cleanup_after_timeout, self.task)

    def test_worker_limit(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        self.config(periodic_max_workers=2, group='conductor')

        # Use the same nodes/tasks to make life easier in the tests
        # here

        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                [self.node] * 3)
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                [self.task] * 3)

        self.service._check_deploy_timeouts(self.context)

        # Should only have ran 2.
        self.assertEqual([mock.call(self.node.uuid, self.node.driver)] * 2,
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid)] * 2,
                         acquire_mock.call_args_list)
        spawn_after_call = mock.call(self.service._spawn_worker,
                                     conductor_utils.cleanup_after_timeout,
                                     self.task)
        self.assertEqual([spawn_after_call] * 2,
                         self.task.spawn_after.call_args_list)

    @mock.patch.object(dbapi.IMPL, 'update_port')
    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_duplicate_mac(self, get_nodeinfo_mock, mapped_mock,
            acquire_mock, mac_update_mock, mock_up):
        node = utils.create_test_node(driver='fake')
        port = obj_utils.create_test_port(self.context, node_id=node.id)
        mock_up.side_effect = exception.MACAlreadyExists(mac=port.address)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.MACAlreadyExists, exc.exc_info[0])
        # ensure Neutron wasn't updated
        self.assertFalse(mac_update_mock.called)


class ManagerTestProperties(tests_db_base.DbTestCase):

    def setUp(self):
        super(ManagerTestProperties, self).setUp()
        self.service = manager.ConductorManager('test-host', 'test-topic')

    def _check_driver_properties(self, driver, expected):
        mgr_utils.mock_the_extension_manager(driver=driver)
        self.driver = driver_factory.get_driver(driver)
        self.service.init_host()
        properties = self.service.get_driver_properties(self.context, driver)
        self.assertEqual(sorted(expected), sorted(properties.keys()))

    def test_driver_properties_fake(self):
        expected = ['A1', 'A2', 'B1', 'B2']
        self._check_driver_properties("fake", expected)

    def test_driver_properties_fake_ipmitool(self):
        expected = ['ipmi_address', 'ipmi_terminal_port',
                    'ipmi_password', 'ipmi_priv_level',
                    'ipmi_username', 'ipmi_bridging',
                    'ipmi_transit_channel', 'ipmi_transit_address',
                    'ipmi_target_channel', 'ipmi_target_address',
                    'ipmi_local_address'
                    ]
        self._check_driver_properties("fake_ipmitool", expected)

    def test_driver_properties_fake_ipminative(self):
        expected = ['ipmi_address', 'ipmi_password', 'ipmi_username',
                    'ipmi_terminal_port']
        self._check_driver_properties("fake_ipminative", expected)

    def test_driver_properties_fake_ssh(self):
        expected = ['ssh_address', 'ssh_username', 'ssh_virt_type',
                    'ssh_key_contents', 'ssh_key_filename',
                    'ssh_password', 'ssh_port']
        self._check_driver_properties("fake_ssh", expected)

    def test_driver_properties_fake_pxe(self):
        expected = ['pxe_deploy_kernel', 'pxe_deploy_ramdisk']
        self._check_driver_properties("fake_pxe", expected)

    def test_driver_properties_fake_seamicro(self):
        expected = ['seamicro_api_endpoint', 'seamicro_password',
                    'seamicro_server_id', 'seamicro_username',
                    'seamicro_api_version', 'seamicro_terminal_port']
        self._check_driver_properties("fake_seamicro", expected)

    def test_driver_properties_fake_snmp(self):
        expected = ['snmp_driver', 'snmp_address', 'snmp_port', 'snmp_version',
                    'snmp_community', 'snmp_security', 'snmp_outlet']
        self._check_driver_properties("fake_snmp", expected)

    def test_driver_properties_pxe_ipmitool(self):
        expected = ['ipmi_address', 'ipmi_terminal_port',
                    'ipmi_password', 'ipmi_priv_level',
                    'ipmi_username', 'ipmi_bridging', 'ipmi_transit_channel',
                    'ipmi_transit_address', 'ipmi_target_channel',
                    'ipmi_target_address', 'ipmi_local_address',
                    'pxe_deploy_kernel', 'pxe_deploy_ramdisk'
                    ]
        self._check_driver_properties("pxe_ipmitool", expected)

    def test_driver_properties_pxe_ipminative(self):
        expected = ['ipmi_address', 'ipmi_password', 'ipmi_username',
                    'pxe_deploy_kernel', 'pxe_deploy_ramdisk',
                    'ipmi_terminal_port']
        self._check_driver_properties("pxe_ipminative", expected)

    def test_driver_properties_pxe_ssh(self):
        expected = ['pxe_deploy_kernel', 'pxe_deploy_ramdisk',
                    'ssh_address', 'ssh_username', 'ssh_virt_type',
                    'ssh_key_contents', 'ssh_key_filename',
                    'ssh_password', 'ssh_port']
        self._check_driver_properties("pxe_ssh", expected)

    def test_driver_properties_pxe_seamicro(self):
        expected = ['pxe_deploy_kernel', 'pxe_deploy_ramdisk',
                   'seamicro_api_endpoint', 'seamicro_password',
                   'seamicro_server_id', 'seamicro_username',
                   'seamicro_api_version', 'seamicro_terminal_port']
        self._check_driver_properties("pxe_seamicro", expected)

    def test_driver_properties_pxe_snmp(self):
        expected = ['pxe_deploy_kernel', 'pxe_deploy_ramdisk',
                    'snmp_driver', 'snmp_address', 'snmp_port', 'snmp_version',
                    'snmp_community', 'snmp_security', 'snmp_outlet']
        self._check_driver_properties("pxe_snmp", expected)

    def test_driver_properties_fake_ilo(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                   'client_port', 'client_timeout']
        self._check_driver_properties("fake_ilo", expected)

    def test_driver_properties_ilo_iscsi(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                   'client_port', 'client_timeout', 'ilo_deploy_iso',
                   'console_port']
        self._check_driver_properties("iscsi_ilo", expected)

    def test_driver_properties_agent_ilo(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                   'client_port', 'client_timeout', 'ilo_deploy_iso',
                   'console_port']
        self._check_driver_properties("agent_ilo", expected)

    def test_driver_properties_fail(self):
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")
        self.service.init_host()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                          self.service.get_driver_properties,
                          self.context, "bad-driver")
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.DriverNotFound, exc.exc_info[0])


@mock.patch.object(keystone, 'get_admin_auth_token')
@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerSyncLocalStateTestCase(_CommonMixIn, tests_db_base.DbTestCase):

    def setUp(self):
        super(ManagerSyncLocalStateTestCase, self).setUp()

        self.service = manager.ConductorManager('hostname', 'test-topic')

        self.service.conductor = mock.Mock()
        self.service.dbapi = self.dbapi
        self.service.ring_manager = mock.Mock()

        self.node = self._create_node(provision_state=states.ACTIVE)
        self.task = self._create_task(node=self.node)

        self.filters = {'reserved': False,
                        'maintenance': False,
                        'provision_state': states.ACTIVE}
        self.columns = ['id', 'uuid', 'driver', 'conductor_affinity']

    def _assert_get_nodeinfo_args(self, get_nodeinfo_mock):
        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)

    def test_not_mapped(self, get_nodeinfo_mock, mapped_mock, acquire_mock,
                        get_authtoken_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = False

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(get_authtoken_mock.called)
        self.service.ring_manager.reset.assert_called_once_with()

    def test_already_mapped(self, get_nodeinfo_mock, mapped_mock,
                             acquire_mock, get_authtoken_mock):
        # Node is already mapped to the conductor running the periodic task
        self.node.conductor_affinity = 123
        self.service.conductor.id = 123

        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(get_authtoken_mock.called)
        self.service.ring_manager.reset.assert_called_once_with()

    @mock.patch.object(context, 'get_admin_context')
    def test_good(self, get_ctx_mock, get_nodeinfo_mock, mapped_mock,
                  acquire_mock, get_authtoken_mock):
        get_ctx_mock.return_value = self.context
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(self.task)

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        get_authtoken_mock.assert_called_once_with()
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        # assert spawn_after has been called
        self.task.spawn_after.assert_called_once_with(
                self.service._spawn_worker,
                self.service._do_takeover, self.task)

    @mock.patch.object(context, 'get_admin_context')
    def test_no_free_worker(self, get_ctx_mock, get_nodeinfo_mock, mapped_mock,
                            acquire_mock, get_authtoken_mock):
        get_ctx_mock.return_value = self.context
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                                       [self.task] * 3)
        self.task.spawn_after.side_effect = [
            None,
            exception.NoFreeConductorWorker('error')
        ]

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                                             [self.node] * 3)

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert  _mapped_to_this_conductor() gets called 2 times only
        # instead of 3. When NoFreeConductorWorker is raised the loop
        # should be broken
        expected = [mock.call(self.node.uuid, self.node.driver)] * 2
        self.assertEqual(expected, mapped_mock.call_args_list)

        # assert  acquire() gets called 2 times only instead of 3. When
        # NoFreeConductorWorker is raised the loop should be broken
        expected = [mock.call(self.context, self.node.id)] * 2
        self.assertEqual(expected, acquire_mock.call_args_list)

        # Only one auth token needed for all runs
        get_authtoken_mock.assert_called_once_with()

        # assert spawn_after has been called twice
        expected = [mock.call(self.service._spawn_worker,
                    self.service._do_takeover, self.task)] * 2
        self.assertEqual(expected, self.task.spawn_after.call_args_list)

    @mock.patch.object(context, 'get_admin_context')
    def test_node_locked(self, get_ctx_mock, get_nodeinfo_mock, mapped_mock,
                            acquire_mock, get_authtoken_mock):
        get_ctx_mock.return_value = self.context
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                [self.task, exception.NodeLocked('error'), self.task])
        self.task.spawn_after.side_effect = [None, None]

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                                             [self.node] * 3)

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert _mapped_to_this_conductor() gets called 3 times
        expected = [mock.call(self.node.uuid, self.node.driver)] * 3
        self.assertEqual(expected, mapped_mock.call_args_list)

        # assert acquire() gets called 3 times
        expected = [mock.call(self.context, self.node.id)] * 3
        self.assertEqual(expected, acquire_mock.call_args_list)

        # Only one auth token needed for all runs
        get_authtoken_mock.assert_called_once_with()

        # assert spawn_after has been called only 2 times
        expected = [mock.call(self.service._spawn_worker,
                    self.service._do_takeover, self.task)] * 2
        self.assertEqual(expected, self.task.spawn_after.call_args_list)

    @mock.patch.object(context, 'get_admin_context')
    def test_worker_limit(self, get_ctx_mock, get_nodeinfo_mock, mapped_mock,
                          acquire_mock, get_authtoken_mock):
        # Limit to only 1 worker
        self.config(periodic_max_workers=1, group='conductor')
        get_ctx_mock.return_value = self.context
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
                                       [self.task] * 3)
        self.task.spawn_after.side_effect = [None] * 3

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                                             [self.node] * 3)

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert _mapped_to_this_conductor() gets called only once
        # because of the worker limit
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)

        # assert acquire() gets called only once because of the worker limit
        acquire_mock.assert_called_once_with(self.context, self.node.id)

        # Only one auth token needed for all runs
        get_authtoken_mock.assert_called_once_with()

        # assert spawn_after has been called
        self.task.spawn_after.assert_called_once_with(
                self.service._spawn_worker,
                self.service._do_takeover, self.task)
