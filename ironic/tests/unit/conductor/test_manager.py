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

import datetime

import eventlet
import mock
from oslo_config import cfg
import oslo_messaging as messaging
from oslo_utils import uuidutils
from oslo_versionedobjects import base as ovo_base
from oslo_versionedobjects import fields

from ironic.common import boot_devices
from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import images
from ironic.common import states
from ironic.common import swift
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.db import api as dbapi
from ironic.drivers import base as drivers_base
from ironic.drivers.modules import fake
from ironic import objects
from ironic.objects import base as obj_base
from ironic.tests import base as tests_base
from ironic.tests.unit.conductor import mgr_utils
from ironic.tests.unit.db import base as tests_db_base
from ironic.tests.unit.db import utils
from ironic.tests.unit.objects import utils as obj_utils

CONF = cfg.CONF


@mgr_utils.mock_record_keepalive
class ChangeNodePowerStateTestCase(mgr_utils.ServiceSetUpMixin,
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
            self._stop_service()

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
        self._stop_service()
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
                self._stop_service()

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


@mgr_utils.mock_record_keepalive
class UpdateNodeTestCase(mgr_utils.ServiceSetUpMixin,
                         tests_db_base.DbTestCase):
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

    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state')
    def _test_associate_node(self, power_state, mock_get_power_state):
        mock_get_power_state.return_value = power_state
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          power_state=states.NOSTATE)
        uuid1 = uuidutils.generate_uuid()
        uuid2 = uuidutils.generate_uuid()
        node.instance_uuid = uuid1
        self.service.update_node(self.context, node)

        # Check if the change was applied
        node.instance_uuid = uuid2
        node.refresh()
        self.assertEqual(uuid1, node.instance_uuid)

    def test_associate_node_powered_off(self):
        self._test_associate_node(states.POWER_OFF)

    def test_associate_node_powered_on(self):
        self._test_associate_node(states.POWER_ON)

    def test_update_node_invalid_driver(self):
        existing_driver = 'fake'
        wrong_driver = 'wrong-driver'
        node = obj_utils.create_test_node(self.context,
                                          driver=existing_driver,
                                          extra={'test': 'one'},
                                          instance_uuid=None)
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

    def test_update_network_node_deleting_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DELETING,
                                          network_interface='flat')
        old_iface = node.network_interface
        node.network_interface = 'noop'
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_node,
                                self.context, node)
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        node.refresh()
        self.assertEqual(old_iface, node.network_interface)

    def test_update_network_node_manageable_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.MANAGEABLE,
                                          network_interface='flat')
        node.network_interface = 'noop'
        self.service.update_node(self.context, node)
        node.refresh()
        self.assertEqual('noop', node.network_interface)

    def test_update_network_node_active_state_and_maintenance(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE,
                                          network_interface='flat',
                                          maintenance=True)
        node.network_interface = 'noop'
        self.service.update_node(self.context, node)
        node.refresh()
        self.assertEqual('noop', node.network_interface)

    def test_update_node_invalid_network_interface(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.MANAGEABLE,
                                          network_interface='flat')
        old_iface = node.network_interface
        node.network_interface = 'cosci'
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_node,
                                self.context, node)
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])
        node.refresh()
        self.assertEqual(old_iface, node.network_interface)


@mgr_utils.mock_record_keepalive
class VendorPassthruTestCase(mgr_utils.ServiceSetUpMixin,
                             tests_db_base.DbTestCase):

    @mock.patch.object(task_manager.TaskManager, 'upgrade_lock')
    @mock.patch.object(task_manager.TaskManager, 'spawn_after')
    def test_vendor_passthru_async(self, mock_spawn, mock_upgrade):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'baz'}
        self._start_service()

        response = self.service.vendor_passthru(self.context, node.uuid,
                                                'first_method', 'POST',
                                                info)
        # Waiting to make sure the below assertions are valid.
        self._stop_service()

        # Assert spawn_after was called
        self.assertTrue(mock_spawn.called)
        self.assertIsNone(response['return'])
        self.assertTrue(response['async'])

        # Assert lock was upgraded to an exclusive one
        self.assertEqual(1, mock_upgrade.call_count)

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch.object(task_manager.TaskManager, 'upgrade_lock')
    @mock.patch.object(task_manager.TaskManager, 'spawn_after')
    def test_vendor_passthru_sync(self, mock_spawn, mock_upgrade):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'meow'}
        self._start_service()

        response = self.service.vendor_passthru(self.context, node.uuid,
                                                'third_method_sync',
                                                'POST', info)
        # Waiting to make sure the below assertions are valid.
        self._stop_service()

        # Assert no workers were used
        self.assertFalse(mock_spawn.called)
        self.assertTrue(response['return'])
        self.assertFalse(response['async'])

        # Assert lock was upgraded to an exclusive one
        self.assertEqual(1, mock_upgrade.call_count)

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch.object(task_manager.TaskManager, 'upgrade_lock')
    @mock.patch.object(task_manager.TaskManager, 'spawn_after')
    def test_vendor_passthru_shared_lock(self, mock_spawn, mock_upgrade):
        node = obj_utils.create_test_node(self.context, driver='fake')
        info = {'bar': 'woof'}
        self._start_service()

        response = self.service.vendor_passthru(self.context, node.uuid,
                                                'fourth_method_shared_lock',
                                                'POST', info)
        # Waiting to make sure the below assertions are valid.
        self._stop_service()

        # Assert spawn_after was called
        self.assertTrue(mock_spawn.called)
        self.assertIsNone(response['return'])
        self.assertTrue(response['async'])

        # Assert lock was never upgraded to an exclusive one
        self.assertFalse(mock_upgrade.called)

        node.refresh()
        self.assertIsNone(node.last_error)
        # Verify there's no reservation on the node
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
            self._stop_service()

            node.refresh()
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)

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
        self.driver.vendor.driver_routes = {
            'test_method': {'func': test_method,
                            'async': False,
                            'attach': False,
                            'http_methods': ['POST']}}
        self.service.init_host()
        # init_host() called _spawn_worker because of the heartbeat
        mock_spawn.reset_mock()

        vendor_args = {'test': 'arg'}
        response = self.service.driver_vendor_passthru(
            self.context, 'fake', 'test_method', 'POST', vendor_args)

        # Assert that the vendor interface has no custom
        # driver_vendor_passthru()
        self.assertFalse(hasattr(self.driver.vendor, 'driver_vendor_passthru'))
        self.assertEqual(expected, response['return'])
        self.assertFalse(response['async'])
        test_method.assert_called_once_with(self.context, **vendor_args)
        # No worker was spawned
        self.assertFalse(mock_spawn.called)

    @mock.patch.object(manager.ConductorManager, '_spawn_worker')
    def test_driver_vendor_passthru_async(self, mock_spawn):
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        test_method = mock.MagicMock()
        self.driver.vendor.driver_routes = {
            'test_sync_method': {'func': test_method,
                                 'async': True,
                                 'attach': False,
                                 'http_methods': ['POST']}}
        self.service.init_host()
        # init_host() called _spawn_worker because of the heartbeat
        mock_spawn.reset_mock()

        vendor_args = {'test': 'arg'}
        response = self.service.driver_vendor_passthru(
            self.context, 'fake', 'test_sync_method', 'POST', vendor_args)

        # Assert that the vendor interface has no custom
        # driver_vendor_passthru()
        self.assertFalse(hasattr(self.driver.vendor, 'driver_vendor_passthru'))
        self.assertIsNone(response['return'])
        self.assertTrue(response['async'])
        mock_spawn.assert_called_once_with(test_method, self.context,
                                           **vendor_args)

    def test_driver_vendor_passthru_http_method_not_supported(self):
        self.driver.vendor = mock.Mock(spec=drivers_base.VendorInterface)
        self.driver.vendor.driver_routes = {
            'test_method': {'func': mock.MagicMock(),
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
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.service.get_driver_vendor_passthru_methods,
            self.context, 'fake')
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc.exc_info[0])

    @mock.patch.object(drivers_base.VendorInterface, 'driver_validate')
    def test_driver_vendor_passthru_validation_failed(self, validate_mock):
        validate_mock.side_effect = exception.MissingParameterValue('error')
        test_method = mock.Mock()
        self.driver.vendor.driver_routes = {
            'test_method': {'func': test_method,
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


@mgr_utils.mock_record_keepalive
@mock.patch.object(images, 'is_whole_disk_image')
class ServiceDoNodeDeployTestCase(mgr_utils.ServiceSetUpMixin,
                                  tests_db_base.DbTestCase):
    def test_do_node_deploy_invalid_state(self, mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        # test that node deploy fails if the node is already provisioned
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.ACTIVE,
            target_provision_state=states.NOSTATE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidStateRequested, exc.exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertNotIn('is_whole_disk_image', node.driver_internal_info)

    def test_do_node_deploy_maintenance(self, mock_iwdi):
        mock_iwdi.return_value = False
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
        self.assertFalse(mock_iwdi.called)

    def _test_do_node_deploy_validate_fail(self, mock_validate, mock_iwdi):
        mock_iwdi.return_value = False
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(self.context, driver='fake')
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])
        # Check the message of InstanceDeployFailure. In a
        # messaging.rpc.ExpectedException sys.exc_info() is stored in exc_info
        # in the exception object. So InstanceDeployFailure will be in
        # exc_info[1]
        self.assertIn(r'node 1be26c0b-03f2-4d2e-ae87-c02d7f33c123',
                      str(exc.exc_info[1]))
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertNotIn('is_whole_disk_image', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.validate')
    def test_do_node_deploy_validate_fail(self, mock_validate, mock_iwdi):
        self._test_do_node_deploy_validate_fail(mock_validate, mock_iwdi)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_deploy_power_validate_fail(self, mock_validate,
                                                mock_iwdi):
        self._test_do_node_deploy_validate_fail(mock_validate, mock_iwdi)

    def test_do_node_deploy_partial_ok(self, mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        thread = self.service._spawn_worker(lambda: None)
        with mock.patch.object(self.service, '_spawn_worker') as mock_spawn:
            mock_spawn.return_value = thread

            node = obj_utils.create_test_node(self.context, driver='fake',
                                              provision_state=states.AVAILABLE)

            self.service.do_node_deploy(self.context, node.uuid)
            self._stop_service()
            node.refresh()
            self.assertEqual(states.DEPLOYING, node.provision_state)
            self.assertEqual(states.ACTIVE, node.target_provision_state)
            # This is a sync operation last_error should be None.
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)
            mock_spawn.assert_called_once_with(mock.ANY, mock.ANY,
                                               mock.ANY, None)
            mock_iwdi.assert_called_once_with(self.context, node.instance_info)
            self.assertFalse(node.driver_internal_info['is_whole_disk_image'])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_active_state(self, mock_deploy, mock_iwdi):
        # This tests manager.do_node_deploy(), the 'else' path of
        # 'if new_state == states.DEPLOYDONE'. The node's states
        # aren't changed in this case.
        mock_iwdi.return_value = True
        self._start_service()
        mock_deploy.return_value = states.DEPLOYING
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ACTIVE,
            target_provision_state=states.NOSTATE,
            instance_info={'image_source': uuidutils.generate_uuid(),
                           'kernel': 'aaaa', 'ramdisk': 'bbbb'},
            driver_internal_info={'is_whole_disk_image': False})

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.DEPLOYING, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)
        # Verify instance_info values has been cleared.
        self.assertNotIn('kernel', node.instance_info)
        self.assertNotIn('ramdisk', node.instance_info)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        # Verify is_whole_disk_image reflects correct value on rebuild.
        self.assertTrue(node.driver_internal_info['is_whole_disk_image'])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_active_state_waiting(self, mock_deploy,
                                                         mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        mock_deploy.return_value = states.DEPLOYWAIT
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ACTIVE,
            target_provision_state=states.NOSTATE,
            instance_info={'image_source': uuidutils.generate_uuid()})

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.DEPLOYWAIT, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertFalse(node.driver_internal_info['is_whole_disk_image'])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_active_state_done(self, mock_deploy,
                                                      mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ACTIVE,
            target_provision_state=states.NOSTATE)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertFalse(node.driver_internal_info['is_whole_disk_image'])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_deployfail_state(self, mock_deploy,
                                                     mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.DEPLOYFAIL,
            target_provision_state=states.NOSTATE)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertFalse(node.driver_internal_info['is_whole_disk_image'])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test_do_node_deploy_rebuild_error_state(self, mock_deploy, mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ERROR,
            target_provision_state=states.NOSTATE)

        self.service.do_node_deploy(self.context, node.uuid, rebuild=True)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        # last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertFalse(node.driver_internal_info['is_whole_disk_image'])

    def test_do_node_deploy_rebuild_from_available_state(self, mock_iwdi):
        mock_iwdi.return_value = False
        self._start_service()
        # test node will not rebuild if state is AVAILABLE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.AVAILABLE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'], rebuild=True)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidStateRequested, exc.exc_info[0])
        # Last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)
        self.assertNotIn('is_whole_disk_image', node.driver_internal_info)

    def test_do_node_deploy_worker_pool_full(self, mock_iwdi):
        mock_iwdi.return_value = False
        prv_state = states.AVAILABLE
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
            self._stop_service()
            node.refresh()
            # Make sure things were rolled back
            self.assertEqual(prv_state, node.provision_state)
            self.assertEqual(tgt_prv_state, node.target_provision_state)
            self.assertIsNotNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)
            mock_iwdi.assert_called_once_with(self.context, node.instance_info)
            self.assertFalse(node.driver_internal_info['is_whole_disk_image'])


@mgr_utils.mock_record_keepalive
class DoNodeDeployTearDownTestCase(mgr_utils.ServiceSetUpMixin,
                                   tests_db_base.DbTestCase):
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_node_deploy_driver_raises_prepare_error(self, mock_prepare,
                                                         mock_deploy):
        self._start_service()
        # test when driver.deploy.prepare raises an exception
        mock_prepare.side_effect = exception.InstanceDeployFailure('test')
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          manager.do_node_deploy, task,
                          self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        # NOTE(deva): failing a deploy does not clear the target state
        #             any longer. Instead, it is cleared when the instance
        #             is deleted.
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(mock_prepare.called)
        self.assertFalse(mock_deploy.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_driver_raises_error(self, mock_deploy):
        self._start_service()
        # test when driver.deploy.deploy raises an exception
        mock_deploy.side_effect = exception.InstanceDeployFailure('test')
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          manager.do_node_deploy, task,
                          self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        # NOTE(deva): failing a deploy does not clear the target state
        #             any longer. Instead, it is cleared when the instance
        #             is deleted.
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch.object(manager, '_store_configdrive')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok(self, mock_deploy, mock_store):
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        manager.do_node_deploy(task, self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)
        # assert _store_configdrive wasn't invoked
        self.assertFalse(mock_store.called)

    @mock.patch.object(manager, '_store_configdrive')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok_configdrive(self, mock_deploy, mock_store):
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)
        configdrive = 'foo'

        manager.do_node_deploy(task, self.service.conductor.id,
                               configdrive=configdrive)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)
        mock_store.assert_called_once_with(task.node, configdrive)

    @mock.patch.object(swift, 'SwiftAPI')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_configdrive_swift_error(self, mock_deploy,
                                                     mock_swift):
        CONF.set_override('configdrive_use_swift', True, group='conductor')
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DEPLOYING,
                                          target_provision_state=states.ACTIVE)
        task = task_manager.TaskManager(self.context, node.uuid)

        mock_swift.side_effect = exception.SwiftOperationError('error')
        self.assertRaises(exception.SwiftOperationError,
                          manager.do_node_deploy, task,
                          self.service.conductor.id,
                          configdrive=b'fake config drive')
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(mock_deploy.called)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok_2(self, mock_deploy):
        # NOTE(rloo): a different way of testing for the same thing as in
        # test__do_node_deploy_ok()
        self._start_service()
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        node = obj_utils.create_test_node(self.context, driver='fake')
        task = task_manager.TaskManager(self.context, node.uuid)
        task.process_event('deploy')

        manager.do_node_deploy(task, self.service.conductor.id)
        node.refresh()
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.clean_up')
    def test__check_deploy_timeouts(self, mock_cleanup):
        self._start_service()
        CONF.set_override('deploy_callback_timeout', 1, group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.DEPLOYWAIT,
            target_provision_state=states.ACTIVE,
            provision_updated_at=datetime.datetime(2000, 1, 1, 0, 0))

        self.service._check_deploy_timeouts(self.context)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_cleanup.assert_called_once_with(mock.ANY)

    def _check_cleanwait_timeouts(self, manual=False):
        self._start_service()
        CONF.set_override('clean_callback_timeout', 1, group='conductor')
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANWAIT,
            target_provision_state=tgt_prov_state,
            provision_updated_at=datetime.datetime(2000, 1, 1, 0, 0),
            clean_step={
                'interface': 'deploy',
                'step': 'erase_devices'},
            driver_internal_info={
                'cleaning_reboot': manual,
                'clean_step_index': 0})

        self.service._check_cleanwait_timeouts(self.context)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Test that cleaning parameters have been purged in order
        # to prevent looping of the cleaning sequence
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertNotIn('cleaning_reboot', node.driver_internal_info)

    def test__check_cleanwait_timeouts_automated_clean(self):
        self._check_cleanwait_timeouts()

    def test__check_cleanwait_timeouts_manual_clean(self):
        self._check_cleanwait_timeouts(manual=True)

    def test_do_node_tear_down_invalid_state(self):
        self._start_service()
        # test node.provision_state is incorrect for tear_down
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.AVAILABLE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_tear_down,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidStateRequested, exc.exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_tear_down_validate_fail(self, mock_validate):
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ACTIVE,
            target_provision_state=states.NOSTATE)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_tear_down,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc.exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_driver_raises_error(self, mock_tear_down):
        # test when driver.deploy.tear_down raises exception
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.DELETING,
            target_provision_state=states.AVAILABLE,
            instance_info={'foo': 'bar'},
            driver_internal_info={'is_whole_disk_image': False})

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

    @mock.patch('ironic.conductor.manager.ConductorManager._do_node_clean')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test__do_node_tear_down_ok(self, mock_tear_down, mock_clean):
        # test when driver.deploy.tear_down succeeds
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.DELETING,
            target_provision_state=states.AVAILABLE,
            instance_uuid=uuidutils.generate_uuid(),
            instance_info={'foo': 'bar'},
            driver_internal_info={'is_whole_disk_image': False,
                                  'instance': {'ephemeral_gb': 10}})

        task = task_manager.TaskManager(self.context, node.uuid)
        self._start_service()
        self.service._do_node_tear_down(task)
        node.refresh()
        # Node will be moved to AVAILABLE after cleaning, not tested here
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(states.AVAILABLE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        self.assertIsNone(node.instance_uuid)
        self.assertEqual({}, node.instance_info)
        self.assertNotIn('instance', node.driver_internal_info)
        mock_tear_down.assert_called_once_with(mock.ANY)
        mock_clean.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.conductor.manager.ConductorManager._do_node_clean')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def _test_do_node_tear_down_from_state(self, init_state, mock_tear_down,
                                           mock_clean):
        node = obj_utils.create_test_node(
            self.context, driver='fake', uuid=uuidutils.generate_uuid(),
            provision_state=init_state,
            target_provision_state=states.AVAILABLE,
            driver_internal_info={'is_whole_disk_image': False})

        self._start_service()
        self.service.do_node_tear_down(self.context, node.uuid)
        self._stop_service()
        node.refresh()
        # Node will be moved to AVAILABLE after cleaning, not tested here
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(states.AVAILABLE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        self.assertEqual({}, node.instance_info)
        mock_tear_down.assert_called_once_with(mock.ANY)
        mock_clean.assert_called_once_with(mock.ANY)

    def test__do_node_tear_down_from_valid_states(self):
        valid_states = [states.ACTIVE, states.DEPLOYWAIT, states.DEPLOYFAIL,
                        states.ERROR]
        for state in valid_states:
            self._test_do_node_tear_down_from_state(state)

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
        driver_internal_info = {'is_whole_disk_image': False}
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=prv_state,
            target_provision_state=tgt_prv_state,
            instance_info=fake_instance_info,
            driver_internal_info=driver_internal_info, last_error=None)
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_tear_down,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
        self._stop_service()
        node.refresh()
        # Assert instance_info/driver_internal_info was not touched
        self.assertEqual(fake_instance_info, node.instance_info)
        self.assertEqual(driver_internal_info, node.driver_internal_info)
        # Make sure things were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_provisioning_action_worker_pool_full(self, mock_spawn):
        prv_state = states.MANAGEABLE
        tgt_prv_state = states.NOSTATE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None)
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_provisioning_action,
                                self.context, node.uuid, 'provide')
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
        self._stop_service()
        node.refresh()
        # Make sure things were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_provision_action_provide(self, mock_spawn):
        # test when a node is cleaned going from manageable to available
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.MANAGEABLE,
            target_provision_state=states.AVAILABLE)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'provide')
        node.refresh()
        # Node will be moved to AVAILABLE after cleaning, not tested here
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(states.AVAILABLE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_spawn.assert_called_with(self.service._do_node_clean, mock.ANY)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_provision_action_manage(self, mock_spawn):
        # test when a node is verified going from enroll to manageable
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ENROLL,
            target_provision_state=states.MANAGEABLE)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'manage')
        node.refresh()
        # Node will be moved to MANAGEABLE after verification, not tested here
        self.assertEqual(states.VERIFYING, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_spawn.assert_called_with(self.service._do_node_verify, mock.ANY)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def _do_provision_action_abort(self, mock_spawn, manual=False):
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANWAIT,
            target_provision_state=tgt_prov_state)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'abort')
        node.refresh()
        # Node will be moved to tgt_prov_state after cleaning, not tested here
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_spawn.assert_called_with(self.service._do_node_clean_abort,
                                      mock.ANY)

    def test_do_provision_action_abort_automated_clean(self):
        self._do_provision_action_abort()

    def test_do_provision_action_abort_manual_clean(self):
        self._do_provision_action_abort(manual=True)

    def test_do_provision_action_abort_clean_step_not_abortable(self):
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            clean_step={'step': 'foo', 'abortable': False})

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'abort')
        node.refresh()
        # Assert the current clean step was marked to be aborted later
        self.assertIn('abort_after', node.clean_step)
        self.assertTrue(node.clean_step['abort_after'])
        # Make sure things stays as it was before
        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(states.AVAILABLE, node.target_provision_state)

    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _test__do_node_clean_abort(self, step_name, tear_mock):
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANFAIL,
            target_provision_state=states.AVAILABLE,
            clean_step={'step': 'foo', 'abortable': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            self.service._do_node_clean_abort(task, step_name=step_name)
            self.assertIsNotNone(task.node.last_error)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            if step_name:
                self.assertIn(step_name, task.node.last_error)
            # assert node's clean_step was cleaned up
            self.assertEqual({}, task.node.clean_step)

    def test__do_node_clean_abort(self):
        self._test__do_node_clean_abort(None)

    def test__do_node_clean_abort_with_step_name(self):
        self._test__do_node_clean_abort('foo')

    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def test__do_node_clean_abort_tear_down_fail(self, tear_mock):
        tear_mock.side_effect = Exception('Surprise')

        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANFAIL,
            target_provision_state=states.AVAILABLE,
            clean_step={'step': 'foo', 'abortable': True})

        with task_manager.acquire(self.context, node.uuid) as task:
            self.service._do_node_clean_abort(task)
            tear_mock.assert_called_once_with(task.driver.deploy, task)
            self.assertIsNotNone(task.node.last_error)
            self.assertIsNotNone(task.node.maintenance_reason)
            self.assertTrue(task.node.maintenance)


@mgr_utils.mock_record_keepalive
class DoNodeCleanTestCase(mgr_utils.ServiceSetUpMixin,
                          tests_db_base.DbTestCase):
    def setUp(self):
        super(DoNodeCleanTestCase, self).setUp()
        self.config(automated_clean=True, group='conductor')
        self.power_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'power'}
        self.deploy_update = {
            'step': 'update_firmware', 'priority': 10, 'interface': 'deploy'}
        self.deploy_erase = {
            'step': 'erase_disks', 'priority': 20, 'interface': 'deploy'}
        # Automated cleaning should be executed in this order
        self.clean_steps = [self.deploy_erase, self.power_update,
                            self.deploy_update]
        self.next_clean_step_index = 1
        # Manual clean step
        self.deploy_raid = {
            'step': 'build_raid', 'priority': 0, 'interface': 'deploy'}

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_clean_maintenance(self, mock_validate):
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.MANAGEABLE,
            target_provision_state=states.NOSTATE,
            maintenance=True, maintenance_reason='reason')
        self._start_service()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_clean,
                                self.context, node.uuid, [])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeInMaintenance, exc.exc_info[0])
        self.assertFalse(mock_validate.called)

    @mock.patch('ironic.conductor.task_manager.TaskManager.process_event')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_clean_validate_fail(self, mock_validate, mock_process):
        # power validate fails
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.MANAGEABLE,
            target_provision_state=states.NOSTATE)
        self._start_service()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_clean,
                                self.context, node.uuid, [])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])
        mock_validate.assert_called_once_with(mock.ANY)
        self.assertFalse(mock_process.called)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_clean_invalid_state(self, mock_validate):
        # test node.provision_state is incorrect for clean
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.ENROLL,
            target_provision_state=states.NOSTATE)
        self._start_service()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_clean,
                                self.context, node.uuid, [])
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidStateRequested, exc.exc_info[0])
        mock_validate.assert_called_once_with(mock.ANY)
        node.refresh()
        self.assertNotIn('clean_steps', node.driver_internal_info)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_clean_ok(self, mock_validate, mock_spawn):
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.MANAGEABLE,
            target_provision_state=states.NOSTATE, last_error='old error')
        self._start_service()
        clean_steps = [self.deploy_raid]
        self.service.do_node_clean(self.context, node.uuid, clean_steps)
        mock_validate.assert_called_once_with(mock.ANY)
        mock_spawn.assert_called_with(self.service._do_node_clean, mock.ANY,
                                      clean_steps)
        node.refresh()
        # Node will be moved to CLEANING
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertNotIn('clean_steps', node.driver_internal_info)
        self.assertIsNone(node.last_error)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_do_node_clean_worker_pool_full(self, mock_validate, mock_spawn):
        prv_state = states.MANAGEABLE
        tgt_prv_state = states.NOSTATE
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=prv_state,
            target_provision_state=tgt_prv_state)
        self._start_service()
        clean_steps = [self.deploy_raid]
        mock_spawn.side_effect = exception.NoFreeConductorWorker()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.do_node_clean,
                                self.context, node.uuid, clean_steps)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
        self._stop_service()
        mock_validate.assert_called_once_with(mock.ANY)
        mock_spawn.assert_called_with(self.service._do_node_clean, mock.ANY,
                                      clean_steps)
        node.refresh()
        # Make sure states were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)

        self.assertIsNotNone(node.last_error)
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_continue_node_clean_worker_pool_full(self, mock_spawn):
        # Test the appropriate exception is raised if the worker pool is full
        prv_state = states.CLEANWAIT
        tgt_prv_state = states.AVAILABLE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None)
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        self.assertRaises(exception.NoFreeConductorWorker,
                          self.service.continue_node_clean,
                          self.context, node.uuid)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_continue_node_clean_wrong_state(self, mock_spawn):
        # Test the appropriate exception is raised if node isn't already
        # in CLEANWAIT state
        prv_state = states.DELETING
        tgt_prv_state = states.AVAILABLE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None)
        self._start_service()

        self.assertRaises(exception.InvalidStateRequested,
                          self.service.continue_node_clean,
                          self.context, node.uuid)

        self._stop_service()
        node.refresh()
        # Make sure things were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def _continue_node_clean(self, return_state, mock_spawn, manual=False):
        # test a node can continue cleaning via RPC
        prv_state = return_state
        tgt_prv_state = states.MANAGEABLE if manual else states.AVAILABLE
        driver_info = {'clean_steps': self.clean_steps,
                       'clean_step_index': 0}
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None,
                                          driver_internal_info=driver_info,
                                          clean_step=self.clean_steps[0])
        self._start_service()
        self.service.continue_node_clean(self.context, node.uuid)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        mock_spawn.assert_called_with(self.service._do_next_clean_step,
                                      mock.ANY, self.next_clean_step_index)

    def test_continue_node_clean_automated(self):
        self._continue_node_clean(states.CLEANWAIT)

    def test_continue_node_clean_manual(self):
        self._continue_node_clean(states.CLEANWAIT, manual=True)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def _continue_node_clean_skip_step(self, mock_spawn, skip=True):
        # test that skipping current step mechanism works
        driver_info = {'clean_steps': self.clean_steps,
                       'clean_step_index': 0}
        if not skip:
            driver_info['skip_current_clean_step'] = skip
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.CLEANWAIT,
            target_provision_state=states.MANAGEABLE,
            driver_internal_info=driver_info, clean_step=self.clean_steps[0])
        self._start_service()
        self.service.continue_node_clean(self.context, node.uuid)
        self._stop_service()
        node.refresh()
        if skip:
            expected_step_index = 1
        else:
            self.assertNotIn(
                'skip_current_clean_step', node.driver_internal_info)
            expected_step_index = 0
        mock_spawn.assert_called_with(self.service._do_next_clean_step,
                                      mock.ANY, expected_step_index)

    def test_continue_node_clean_skip_step(self):
        self._continue_node_clean_skip_step()

    def test_continue_node_clean_no_skip_step(self):
        self._continue_node_clean_skip_step(skip=False)

    def _continue_node_clean_abort(self, manual=False):
        last_clean_step = self.clean_steps[0]
        last_clean_step['abortable'] = False
        last_clean_step['abort_after'] = True
        driver_info = {'clean_steps': self.clean_steps,
                       'clean_step_index': 0}
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.CLEANWAIT,
            target_provision_state=tgt_prov_state, last_error=None,
            driver_internal_info=driver_info, clean_step=self.clean_steps[0])

        self._start_service()
        self.service.continue_node_clean(self.context, node.uuid)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # assert the clean step name is in the last error message
        self.assertIn(self.clean_steps[0]['step'], node.last_error)

    def test_continue_node_clean_automated_abort(self):
        self._continue_node_clean_abort()

    def test_continue_node_clean_manual_abort(self):
        self._continue_node_clean_abort(manual=True)

    def _continue_node_clean_abort_last_clean_step(self, manual=False):
        last_clean_step = self.clean_steps[0]
        last_clean_step['abortable'] = False
        last_clean_step['abort_after'] = True
        driver_info = {'clean_steps': [self.clean_steps[0]],
                       'clean_step_index': 0}
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.CLEANWAIT,
            target_provision_state=tgt_prov_state, last_error=None,
            driver_internal_info=driver_info, clean_step=self.clean_steps[0])

        self._start_service()
        self.service.continue_node_clean(self.context, node.uuid)
        self._stop_service()
        node.refresh()
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertIsNone(node.last_error)

    def test_continue_node_clean_automated_abort_last_clean_step(self):
        self._continue_node_clean_abort_last_clean_step()

    def test_continue_node_clean_manual_abort_last_clean_step(self):
        self._continue_node_clean_abort_last_clean_step(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def __do_node_clean_validate_fail(self, mock_validate, clean_steps=None):
        # InvalidParameterValue should be cause node to go to CLEANFAIL
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_validate.assert_called_once_with(mock.ANY)

    def test__do_node_clean_automated_validate_fail(self):
        self.__do_node_clean_validate_fail()

    def test__do_node_clean_manual_validate_fail(self):
        self.__do_node_clean_validate_fail(clean_steps=[])

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test__do_node_clean_automated_disabled(self, mock_validate):
        self.config(automated_clean=False, group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=states.AVAILABLE,
            last_error=None)

        self._start_service()
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task)
        self._stop_service()
        node.refresh()

        # Assert that the node was moved to available without cleaning
        self.assertFalse(mock_validate.called)
        self.assertEqual(states.AVAILABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_steps', node.driver_internal_info)
        self.assertNotIn('clean_step_index', node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning')
    def __do_node_clean_prepare_clean_fail(self, mock_prep, clean_steps=None):
        # Exception from task.driver.deploy.prepare_cleaning should cause node
        # to go to CLEANFAIL
        mock_prep.side_effect = exception.InvalidParameterValue('error')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_prep.assert_called_once_with(mock.ANY)

    def test__do_node_clean_automated_prepare_clean_fail(self):
        self.__do_node_clean_prepare_clean_fail()

    def test__do_node_clean_manual_prepare_clean_fail(self):
        self.__do_node_clean_prepare_clean_fail(clean_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare_cleaning')
    def __do_node_clean_prepare_clean_wait(self, mock_prep, clean_steps=None):
        mock_prep.return_value = states.CLEANWAIT
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_prep.assert_called_once_with(mock.ANY)

    def test__do_node_clean_automated_prepare_clean_wait(self):
        self.__do_node_clean_prepare_clean_wait()

    def test__do_node_clean_manual_prepare_clean_wait(self):
        self.__do_node_clean_prepare_clean_wait(clean_steps=[self.deploy_raid])

    @mock.patch.object(conductor_utils, 'set_node_cleaning_steps')
    def __do_node_clean_steps_fail(self, mock_steps, clean_steps=None,
                                   invalid_exc=True):
        if invalid_exc:
            mock_steps.side_effect = exception.InvalidParameterValue('invalid')
        else:
            mock_steps.side_effect = exception.NodeCleaningFailure('failure')
        tgt_prov_state = states.MANAGEABLE if clean_steps else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            uuid=uuidutils.generate_uuid(),
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state)
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task, clean_steps=clean_steps)
        node.refresh()
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        mock_steps.assert_called_once_with(mock.ANY)

    def test__do_node_clean_automated_steps_fail(self):
        for invalid in (True, False):
            self.__do_node_clean_steps_fail(invalid_exc=invalid)

    def test__do_node_clean_manual_steps_fail(self):
        for invalid in (True, False):
            self.__do_node_clean_steps_fail(clean_steps=[self.deploy_raid],
                                            invalid_exc=invalid)

    @mock.patch.object(conductor_utils, 'set_node_cleaning_steps')
    @mock.patch('ironic.conductor.manager.ConductorManager.'
                '_do_next_clean_step')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def __do_node_clean(self, mock_validate, mock_next_step, mock_steps,
                        clean_steps=None):
        if clean_steps:
            tgt_prov_state = states.MANAGEABLE
            driver_info = {}
        else:
            tgt_prov_state = states.AVAILABLE
            driver_info = {'clean_steps': self.clean_steps}
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            power_state=states.POWER_OFF,
            driver_internal_info=driver_info)

        self._start_service()
        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_node_clean(task, clean_steps=clean_steps)

        self._stop_service()
        node.refresh()

        mock_validate.assert_called_once_with(task)
        mock_next_step.assert_called_once_with(mock.ANY, 0)
        mock_steps.assert_called_once_with(task)
        if clean_steps:
            self.assertEqual(clean_steps,
                             node.driver_internal_info['clean_steps'])

        # Check that state didn't change
        self.assertEqual(states.CLEANING, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)

    def test__do_node_clean_automated(self):
        self.__do_node_clean()

    def test__do_node_clean_manual(self):
        self.__do_node_clean(clean_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    def _do_next_clean_step_first_step_async(self, return_state, mock_execute,
                                             clean_steps=None):
        # Execute the first async clean step on a node
        driver_internal_info = {'clean_step_index': None}
        if clean_steps:
            tgt_prov_state = states.MANAGEABLE
            driver_internal_info['clean_steps'] = clean_steps
        else:
            tgt_prov_state = states.AVAILABLE
            driver_internal_info['clean_steps'] = self.clean_steps

        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=driver_internal_info,
            clean_step={})
        mock_execute.return_value = return_state
        expected_first_step = node.driver_internal_info['clean_steps'][0]

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, 0)

        self._stop_service()
        node.refresh()

        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(expected_first_step, node.clean_step)
        self.assertEqual(0, node.driver_internal_info['clean_step_index'])
        mock_execute.assert_called_once_with(mock.ANY, expected_first_step)

    def test_do_next_clean_step_automated_first_step_async(self):
        self._do_next_clean_step_first_step_async(states.CLEANWAIT)

    def test_do_next_clean_step_manual_first_step_async(self):
        self._do_next_clean_step_first_step_async(
            states.CLEANWAIT, clean_steps=[self.deploy_raid])

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step')
    def _do_next_clean_step_continue_from_last_cleaning(self, return_state,
                                                        mock_execute,
                                                        manual=False):
        # Resume an in-progress cleaning after the first async step
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': 0},
            clean_step=self.clean_steps[0])
        mock_execute.return_value = return_state

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, self.next_clean_step_index)

        self._stop_service()
        node.refresh()

        self.assertEqual(states.CLEANWAIT, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual(self.clean_steps[1], node.clean_step)
        self.assertEqual(1, node.driver_internal_info['clean_step_index'])
        mock_execute.assert_called_once_with(mock.ANY, self.clean_steps[1])

    def test_do_next_clean_step_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(states.CLEANWAIT)

    def test_do_next_clean_step_manual_continue_from_last_cleaning(self):
        self._do_next_clean_step_continue_from_last_cleaning(states.CLEANWAIT,
                                                             manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    def _do_next_clean_step_last_step_noop(self, mock_execute, manual=False):
        # Resume where last_step is the last cleaning step, should be noop
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        info = {'clean_steps': self.clean_steps,
                'clean_step_index': len(self.clean_steps) - 1}
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info=info,
            clean_step=self.clean_steps[-1])

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, None)

        self._stop_service()
        node.refresh()

        # Cleaning should be complete without calling additional steps
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        self.assertFalse(mock_execute.called)

    def test__do_next_clean_step_automated_last_step_noop(self):
        self._do_next_clean_step_last_step_noop()

    def test__do_next_clean_step_manual_last_step_noop(self):
        self._do_next_clean_step_last_step_noop(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    def _do_next_clean_step_all(self, mock_deploy_execute,
                                mock_power_execute, manual=False):
        # Run all steps from start to finish (all synchronous)
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        mock_deploy_execute.return_value = None
        mock_power_execute.return_value = None

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, 0)

        self._stop_service()
        node.refresh()

        # Cleaning should be complete
        self.assertEqual(tgt_prov_state, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNone(node.driver_internal_info['clean_steps'])
        mock_power_execute.assert_called_once_with(mock.ANY,
                                                   self.clean_steps[1])
        mock_deploy_execute.assert_has_calls = [
            mock.call(self.clean_steps[0]),
            mock.call(self.clean_steps[2])
        ]

    def test_do_next_clean_step_automated_all(self):
        self._do_next_clean_step_all()

    def test_do_next_clean_step_manual_all(self):
        self._do_next_clean_step_all(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _do_next_clean_step_execute_fail(self, tear_mock, mock_execute,
                                         manual=False):
        # When a clean step fails, go to CLEANFAIL
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        mock_execute.side_effect = Exception()

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, 0)
            tear_mock.assert_called_once_with(task.driver.deploy, task)

        self._stop_service()
        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        mock_execute.assert_called_once_with(mock.ANY, self.clean_steps[0])

    def test__do_next_clean_step_automated_execute_fail(self):
        self._do_next_clean_step_execute_fail()

    def test__do_next_clean_step_manual_execute_fail(self):
        self._do_next_clean_step_execute_fail(manual=True)

    @mock.patch.object(manager, 'LOG', autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step',
                autospec=True)
    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step',
                autospec=True)
    @mock.patch.object(fake.FakeDeploy, 'tear_down_cleaning', autospec=True)
    def _do_next_clean_step_fail_in_tear_down_cleaning(
            self, tear_mock, power_exec_mock, deploy_exec_mock, log_mock,
            manual=True):
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})

        deploy_exec_mock.return_value = None
        power_exec_mock.return_value = None
        tear_mock.side_effect = Exception('boom')

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, 0)

        self._stop_service()
        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertEqual(1, tear_mock.call_count)
        self.assertTrue(node.maintenance)
        deploy_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.clean_steps[0]),
            mock.call(mock.ANY, mock.ANY, self.clean_steps[2]),
        ]
        self.assertEqual(deploy_exec_calls, deploy_exec_mock.call_args_list)

        power_exec_calls = [
            mock.call(mock.ANY, mock.ANY, self.clean_steps[1]),
        ]
        self.assertEqual(power_exec_calls, power_exec_mock.call_args_list)
        log_mock.exception.assert_called_once_with(
            'Failed to tear down from cleaning for node {}, reason: boom'
            .format(node.uuid))

    def test__do_next_clean_step_automated_fail_in_tear_down_cleaning(self):
        self._do_next_clean_step_fail_in_tear_down_cleaning()

    def test__do_next_clean_step_manual_fail_in_tear_down_cleaning(self):
        self._do_next_clean_step_fail_in_tear_down_cleaning(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    def _do_next_clean_step_no_steps(self, mock_execute, manual=False):

        for info in ({'clean_steps': None, 'clean_step_index': None},
                     {'clean_steps': None}):
            # Resume where there are no steps, should be a noop
            tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
            node = obj_utils.create_test_node(
                self.context, driver='fake',
                uuid=uuidutils.generate_uuid(),
                provision_state=states.CLEANING,
                target_provision_state=tgt_prov_state,
                last_error=None,
                driver_internal_info=info,
                clean_step={})

            self._start_service()

            with task_manager.acquire(
                    self.context, node.uuid, shared=False) as task:
                self.service._do_next_clean_step(task, None)

            self._stop_service()
            node.refresh()

            # Cleaning should be complete without calling additional steps
            self.assertEqual(tgt_prov_state, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertEqual({}, node.clean_step)
            self.assertNotIn('clean_step_index', node.driver_internal_info)
            self.assertFalse(mock_execute.called)
            mock_execute.reset_mock()

    def test__do_next_clean_step_automated_no_steps(self):
        self._do_next_clean_step_no_steps()

    def test__do_next_clean_step_manual_no_steps(self):
        self._do_next_clean_step_no_steps(manual=True)

    @mock.patch('ironic.drivers.modules.fake.FakePower.execute_clean_step')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.execute_clean_step')
    def _do_next_clean_step_bad_step_return_value(
            self, deploy_exec_mock, power_exec_mock, manual=False):
        # When a clean step fails, go to CLEANFAIL
        tgt_prov_state = states.MANAGEABLE if manual else states.AVAILABLE
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANING,
            target_provision_state=tgt_prov_state,
            last_error=None,
            driver_internal_info={'clean_steps': self.clean_steps,
                                  'clean_step_index': None},
            clean_step={})
        deploy_exec_mock.return_value = "foo"

        self._start_service()

        with task_manager.acquire(
                self.context, node.uuid, shared=False) as task:
            self.service._do_next_clean_step(task, 0)

        self._stop_service()
        node.refresh()

        # Make sure we go to CLEANFAIL, clear clean_steps
        self.assertEqual(states.CLEANFAIL, node.provision_state)
        self.assertEqual(tgt_prov_state, node.target_provision_state)
        self.assertEqual({}, node.clean_step)
        self.assertNotIn('clean_step_index', node.driver_internal_info)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(node.maintenance)
        deploy_exec_mock.assert_called_once_with(mock.ANY,
                                                 self.clean_steps[0])
        # Make sure we don't execute any other step and return
        self.assertFalse(power_exec_mock.called)

    def test__do_next_clean_step_automated_bad_step_return_value(self):
        self._do_next_clean_step_bad_step_return_value()

    def test__do_next_clean_step_manual_bad_step_return_value(self):
        self._do_next_clean_step_bad_step_return_value(manual=True)

    def __get_node_next_clean_steps(self, skip=True):
        driver_internal_info = {'clean_steps': self.clean_steps,
                                'clean_step_index': 0}
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            clean_step=self.clean_steps[0])

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = self.service._get_node_next_clean_steps(
                task, skip_current_step=skip)
            expected_index = 1 if skip else 0
            self.assertEqual(expected_index, step_index)

    def test__get_node_next_clean_steps(self):
        self.__get_node_next_clean_steps()

    def test__get_node_next_clean_steps_no_skip(self):
        self.__get_node_next_clean_steps(skip=False)

    def test__get_node_next_clean_steps_unset_clean_step(self):
        driver_internal_info = {'clean_steps': self.clean_steps,
                                'clean_step_index': None}
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.CLEANWAIT,
            target_provision_state=states.AVAILABLE,
            driver_internal_info=driver_internal_info,
            last_error=None,
            clean_step=None)

        with task_manager.acquire(self.context, node.uuid) as task:
            step_index = self.service._get_node_next_clean_steps(task)
            self.assertEqual(0, step_index)


@mgr_utils.mock_record_keepalive
class DoNodeVerifyTestCase(mgr_utils.ServiceSetUpMixin,
                           tests_db_base.DbTestCase):
    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test__do_node_verify(self, mock_validate, mock_get_power_state):
        mock_get_power_state.return_value = states.POWER_OFF
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        self._start_service()
        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            self.service._do_node_verify(task)

        self._stop_service()
        node.refresh()

        mock_validate.assert_called_once_with(task)
        mock_get_power_state.assert_called_once_with(task)

        self.assertEqual(states.MANAGEABLE, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertIsNone(node.last_error)
        self.assertEqual(states.POWER_OFF, node.power_state)

    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test__do_node_verify_validation_fails(self, mock_validate,
                                              mock_get_power_state):
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        mock_validate.side_effect = RuntimeError("boom")

        self._start_service()
        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            self.service._do_node_verify(task)

        self._stop_service()
        node.refresh()

        mock_validate.assert_called_once_with(task)

        self.assertEqual(states.ENROLL, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertTrue(node.last_error)
        self.assertFalse(mock_get_power_state.called)

    @mock.patch('ironic.drivers.modules.fake.FakePower.get_power_state')
    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test__do_node_verify_get_state_fails(self, mock_validate,
                                             mock_get_power_state):
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.VERIFYING,
            target_provision_state=states.MANAGEABLE,
            last_error=None,
            power_state=states.NOSTATE)

        mock_get_power_state.side_effect = RuntimeError("boom")

        self._start_service()
        with task_manager.acquire(
                self.context, node['id'], shared=False) as task:
            self.service._do_node_verify(task)

        self._stop_service()
        node.refresh()

        mock_get_power_state.assert_called_once_with(task)

        self.assertEqual(states.ENROLL, node.provision_state)
        self.assertIsNone(node.target_provision_state)
        self.assertTrue(node.last_error)


@mgr_utils.mock_record_keepalive
class MiscTestCase(mgr_utils.ServiceSetUpMixin, mgr_utils.CommonMixIn,
                   tests_db_base.DbTestCase):
    def test__mapped_to_this_conductor(self):
        self._start_service()
        n = utils.get_test_node()
        self.assertTrue(self.service._mapped_to_this_conductor(n['uuid'],
                                                               'fake'))
        self.assertFalse(self.service._mapped_to_this_conductor(n['uuid'],
                                                                'otherdriver'))

    @mock.patch.object(images, 'is_whole_disk_image')
    def test_validate_driver_interfaces(self, mock_iwdi):
        mock_iwdi.return_value = False
        target_raid_config = {'logical_disks': [{'size_gb': 1,
                                                 'raid_level': '1'}]}
        node = obj_utils.create_test_node(
            self.context, driver='fake', target_raid_config=target_raid_config)
        ret = self.service.validate_driver_interfaces(self.context,
                                                      node.uuid)
        expected = {'console': {'result': True},
                    'power': {'result': True},
                    'inspect': {'result': True},
                    'management': {'result': True},
                    'boot': {'result': True},
                    'raid': {'result': True},
                    'deploy': {'result': True},
                    'network': {'result': True}}
        self.assertEqual(expected, ret)
        mock_iwdi.assert_called_once_with(self.context, node.instance_info)

    @mock.patch.object(images, 'is_whole_disk_image')
    def test_validate_driver_interfaces_validation_fail(self, mock_iwdi):
        mock_iwdi.return_value = False
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
            mock_iwdi.assert_called_once_with(self.context, node.instance_info)

    @mock.patch.object(manager.ConductorManager, '_fail_if_in_state',
                       autospec=True)
    @mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
    @mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
    def test_iter_nodes(self, mock_nodeinfo_list, mock_mapped,
                        mock_fail_if_state):
        self._start_service()
        self.columns = ['uuid', 'driver', 'id']
        nodes = [self._create_node(id=i, driver='fake') for i in range(2)]
        mock_nodeinfo_list.return_value = self._get_nodeinfo_list_response(
            nodes)
        mock_mapped.side_effect = [True, False]

        result = list(self.service.iter_nodes(fields=['id'],
                                              filters=mock.sentinel.filters))
        self.assertEqual([(nodes[0].uuid, 'fake', 0)], result)
        mock_nodeinfo_list.assert_called_once_with(
            columns=self.columns, filters=mock.sentinel.filters)
        mock_fail_if_state.assert_called_once_with(
            mock.ANY, mock.ANY,
            {'provision_state': 'deploying', 'reserved': False},
            'deploying', 'provision_updated_at',
            last_error=mock.ANY)


@mgr_utils.mock_record_keepalive
class ConsoleTestCase(mgr_utils.ServiceSetUpMixin, tests_db_base.DbTestCase):
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
            self._stop_service()
            spawn_mock.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_set_console_mode_enabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, True)
        self._stop_service()
        node.refresh()
        self.assertTrue(node.console_enabled)

    def test_set_console_mode_disabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, False)
        self._stop_service()
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
        self._stop_service()
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
            self._stop_service()
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
            self._stop_service()
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
            self._stop_service()
            self.assertFalse(mock_sc.called)

    def test_disable_console_already_disabled(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=False)
        self._start_service()
        with mock.patch.object(self.driver.console,
                               'stop_console') as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, False)
            self._stop_service()
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


@mgr_utils.mock_record_keepalive
class DestroyNodeTestCase(mgr_utils.ServiceSetUpMixin,
                          tests_db_base.DbTestCase):

    def test_destroy_node(self):
        self._start_service()
        for state in states.DELETE_ALLOWED_STATES:
            node = obj_utils.create_test_node(self.context,
                                              provision_state=state)
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
        node = obj_utils.create_test_node(
            self.context, instance_uuid=uuidutils.generate_uuid())

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeAssociated, exc.exc_info[0])

        # Verify reservation was released.
        node.refresh()
        self.assertIsNone(node.reservation)

    def test_destroy_node_invalid_provision_state(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          provision_state=states.ACTIVE)

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        # Verify reservation was released.
        node.refresh()
        self.assertIsNone(node.reservation)

    def test_destroy_node_allowed_in_maintenance(self):
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, instance_uuid=uuidutils.generate_uuid(),
            provision_state=states.ACTIVE, maintenance=True)
        self.service.destroy_node(self.context, node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node_by_uuid,
                          node.uuid)

    def test_destroy_node_power_off(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          power_state=states.POWER_OFF)
        self.service.destroy_node(self.context, node.uuid)

    def test_destroy_node_console_enabled(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        with mock.patch.object(self.driver.console,
                               'stop_console') as mock_sc:
            self.service.destroy_node(self.context, node.uuid)
            mock_sc.assert_called_once_with(mock.ANY)
            self.assertRaises(exception.NodeNotFound,
                              self.dbapi.get_node_by_uuid,
                              node.uuid)

    def test_destroy_node_adopt_failed_no_power_change(self):
        self._start_service()
        node = obj_utils.create_test_node(self.context,
                                          driver='fake',
                                          provision_state=states.ADOPTFAIL)
        with mock.patch.object(self.driver.power,
                               'set_power_state') as mock_power:
            self.service.destroy_node(self.context, node.uuid)
            self.assertFalse(mock_power.called)


@mgr_utils.mock_record_keepalive
class UpdatePortTestCase(mgr_utils.ServiceSetUpMixin,
                         tests_db_base.DbTestCase):
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
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='available')
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
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='available')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id'})
        old_address = port.address
        port.address = '11:22:33:44:55:bb'
        mac_update_mock.side_effect = (
            exception.FailedToUpdateMacOnPort(port_id=port.uuid))
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.FailedToUpdateMacOnPort, exc.exc_info[0])
        port.refresh()
        self.assertEqual(old_address, port.address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_no_vif_id(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='available')
        port = obj_utils.create_test_port(self.context, node_id=node.id)

        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_address, res.address)
        self.assertFalse(mac_update_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_active_node(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='active')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id'})
        old_address = port.address
        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        port.refresh()
        self.assertEqual(old_address, port.address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_instance_uuid(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid='uuid',
                                          provision_state='error')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id'})
        old_address = port.address
        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        port.refresh()
        self.assertEqual(old_address, port.address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_address_maintenance(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid='uuid',
                                          provision_state='active',
                                          maintenance=True)
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
    def test_update_port_portgroup_active_node(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='active')
        pg1 = obj_utils.create_test_portgroup(self.context, node_id=node.id)
        pg2 = obj_utils.create_test_portgroup(
            self.context, node_id=node.id, name='bar',
            address='aa:bb:cc:dd:ee:ff', uuid=uuidutils.generate_uuid())
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          portgroup_id=pg1.id)
        port.portgroup_id = pg2.id
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        port.refresh()
        self.assertEqual(pg1.id, port.portgroup_id)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_port_portgroup_enroll_node(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          instance_uuid=None,
                                          provision_state='enroll')
        pg1 = obj_utils.create_test_portgroup(self.context, node_id=node.id)
        pg2 = obj_utils.create_test_portgroup(
            self.context, node_id=node.id, name='bar',
            address='aa:bb:cc:dd:ee:ff', uuid=uuidutils.generate_uuid())
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          portgroup_id=pg1.id)
        port.portgroup_id = pg2.id
        self.service.update_port(self.context, port)
        port.refresh()
        self.assertEqual(pg2.id, port.portgroup_id)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    def test_update_port_client_id(self, dhcp_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id',
                                                 'client-id': 'fake1'})
        expected_extra = {'vif_port_id': 'fake-id', 'client-id': 'fake2'}
        expected_dhcp_opts = [{'opt_name': 'client-id', 'opt_value': 'fake2'}]
        port.extra = expected_extra
        res = self.service.update_port(self.context, port)
        self.assertEqual(expected_extra, res.extra)
        dhcp_update_mock.assert_called_once_with('fake-id', expected_dhcp_opts,
                                                 token=self.context.auth_token)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    def test_update_port_vif(self, dhcp_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'vif_port_id': 'fake-id',
                                                 'client-id': 'fake1'})
        expected_extra = {'vif_port_id': 'new_ake-id', 'client-id': 'fake1'}
        port.extra = expected_extra
        res = self.service.update_port(self.context, port)
        self.assertEqual(expected_extra, res.extra)
        self.assertFalse(dhcp_update_mock.called)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    def test_update_port_client_id_fail(self, dhcp_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        expected_extra = {'vif_port_id': 'fake-id', 'client-id': 'fake1'}
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra=expected_extra)
        extra = {'vif_port_id': 'fake-id', 'client-id': 'fake2'}
        port.extra = extra
        dhcp_update_mock.side_effect = (
            exception.FailedToUpdateDHCPOptOnPort(port_id=port.uuid))
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(
            exception.FailedToUpdateDHCPOptOnPort, exc.exc_info[0])
        port.refresh()
        self.assertEqual(expected_extra, port.extra)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_dhcp_opts')
    def test_update_port_client_id_no_vif_id(self, dhcp_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        port = obj_utils.create_test_port(self.context, node_id=node.id)

        expected_extra = {'client-id': 'fake2'}
        port.extra = expected_extra
        res = self.service.update_port(self.context, port)
        self.assertEqual(expected_extra, res.extra)
        self.assertFalse(dhcp_update_mock.called)

    def test_update_port_node_deleting_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.DELETING)
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'foo': 'bar'})
        old_pxe = port.pxe_enabled
        port.pxe_enabled = True
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_port,
                                self.context, port)
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        port.refresh()
        self.assertEqual(old_pxe, port.pxe_enabled)

    def test_update_port_node_manageable_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.MANAGEABLE)
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'foo': 'bar'})
        port.pxe_enabled = True
        self.service.update_port(self.context, port)
        port.refresh()
        self.assertEqual(True, port.pxe_enabled)

    def test_update_port_node_active_state_and_maintenance(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.ACTIVE,
                                          maintenance=True)
        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id,
                                          extra={'foo': 'bar'})
        port.pxe_enabled = True
        self.service.update_port(self.context, port)
        port.refresh()
        self.assertEqual(True, port.pxe_enabled)

    def test__filter_out_unsupported_types_all(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['All'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = (
            self.service._filter_out_unsupported_types(fake_sensors_data))
        expected_result = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        self.assertEqual(expected_result, actual_result)

    def test__filter_out_unsupported_types_part(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['t1'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = (
            self.service._filter_out_unsupported_types(fake_sensors_data))
        expected_result = {"t1": {'f1': 'v1'}}
        self.assertEqual(expected_result, actual_result)

    def test__filter_out_unsupported_types_non(self):
        self._start_service()
        CONF.set_override('send_sensor_data_types', ['t3'], group='conductor')
        fake_sensors_data = {"t1": {'f1': 'v1'}, "t2": {'f1': 'v1'}}
        actual_result = (
            self.service._filter_out_unsupported_types(fake_sensors_data))
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

    @mock.patch.object(manager.ConductorManager, '_fail_if_in_state',
                       autospec=True)
    @mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
    @mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
    @mock.patch.object(task_manager, 'acquire')
    def test___send_sensor_data_disabled(self, acquire_mock,
                                         get_nodeinfo_list_mock,
                                         _mapped_to_this_conductor_mock,
                                         mock_fail_if_state):
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
                mock_fail_if_state.assert_called_once_with(
                    mock.ANY, mock.ANY,
                    {'provision_state': 'deploying', 'reserved': False},
                    'deploying', 'provision_updated_at',
                    last_error=mock.ANY)

    @mock.patch.object(manager.ConductorManager, 'iter_nodes', autospec=True)
    @mock.patch.object(task_manager, 'acquire', autospec=True)
    def test___send_sensor_data_no_management(self, acquire_mock,
                                              iter_nodes_mock):
        CONF.set_override('send_sensor_data', True, group='conductor')
        iter_nodes_mock.return_value = [('fake_uuid1', 'fake', 'fake_uuid2')]
        self.driver.management = None
        acquire_mock.return_value.__enter__.return_value.driver = self.driver

        with mock.patch.object(fake.FakeManagement, 'get_sensors_data',
                               autospec=True) as get_sensors_data_mock:
            with mock.patch.object(fake.FakeManagement, 'validate',
                                   autospec=True) as validate_mock:
                self.service._send_sensor_data(self.context)

        self.assertTrue(iter_nodes_mock.called)
        self.assertTrue(acquire_mock.called)
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


@mgr_utils.mock_record_keepalive
class UpdatePortgroupTestCase(mgr_utils.ServiceSetUpMixin,
                              tests_db_base.DbTestCase):
    def test_update_portgroup(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id,
                                                    extra={'foo': 'bar'})
        new_extra = {'foo': 'baz'}
        portgroup.extra = new_extra
        self.service.update_portgroup(self.context, portgroup)
        portgroup.refresh()
        self.assertEqual(new_extra, portgroup.extra)

    def test_update_portgroup_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation='fake-reserv')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id)
        old_extra = portgroup.extra
        portgroup.extra = {'foo': 'baz'}
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_portgroup,
                                self.context, portgroup)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])
        portgroup.refresh()
        self.assertEqual(old_extra, portgroup.extra)

    def test_update_portgroup_to_node_in_deleting_state(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id,
                                                    extra={'foo': 'bar'})
        update_node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.DELETING,
            uuid=uuidutils.generate_uuid())

        old_node_id = portgroup.node_id
        portgroup.node_id = update_node.id
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_portgroup,
                                self.context, portgroup)
        self.assertEqual(exception.InvalidState, exc.exc_info[0])
        portgroup.refresh()
        self.assertEqual(old_node_id, portgroup.node_id)

    @mock.patch.object(dbapi.IMPL, 'get_ports_by_portgroup_id')
    def test_update_portgroup_to_node_in_manageable_state(self,
                                                          mock_get_ports):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id,
                                                    extra={'foo': 'bar'})
        update_node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.MANAGEABLE,
            uuid=uuidutils.generate_uuid())
        mock_get_ports.return_value = []

        self._start_service()

        portgroup.node_id = update_node.id
        self.service.update_portgroup(self.context, portgroup)
        portgroup.refresh()
        self.assertEqual(update_node.id, portgroup.node_id)
        mock_get_ports.assert_called_once_with(portgroup.uuid)

    @mock.patch.object(dbapi.IMPL, 'get_ports_by_portgroup_id')
    def test_update_portgroup_to_node_in_active_state_and_maintenance(
            self, mock_get_ports):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id,
                                                    extra={'foo': 'bar'})
        update_node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ACTIVE,
            maintenance=True,
            uuid=uuidutils.generate_uuid())
        mock_get_ports.return_value = []

        self._start_service()

        portgroup.node_id = update_node.id
        self.service.update_portgroup(self.context, portgroup)
        portgroup.refresh()
        self.assertEqual(update_node.id, portgroup.node_id)
        mock_get_ports.assert_called_once_with(portgroup.uuid)

    @mock.patch.object(dbapi.IMPL, 'get_ports_by_portgroup_id')
    def test_update_portgroup_association_with_ports(self, mock_get_ports):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id,
                                                    extra={'foo': 'bar'})
        update_node = obj_utils.create_test_node(
            self.context, driver='fake',
            maintenance=True,
            uuid=uuidutils.generate_uuid())
        mock_get_ports.return_value = ['test_port']

        self._start_service()

        old_node_id = portgroup.node_id
        portgroup.node_id = update_node.id
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_portgroup,
                                self.context, portgroup)
        self.assertEqual(exception.PortgroupNotEmpty, exc.exc_info[0])
        portgroup.refresh()
        self.assertEqual(old_node_id, portgroup.node_id)
        mock_get_ports.assert_called_once_with(portgroup.uuid)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_portgroup_address(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=node.id,
            extra={'vif_port_id': 'fake-id'})
        new_address = '11:22:33:44:55:bb'
        pg.address = new_address
        self.service.update_portgroup(self.context, pg)
        pg.refresh()
        self.assertEqual(new_address, pg.address)
        mac_update_mock.assert_called_once_with('fake-id', new_address,
                                                token=self.context.auth_token)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_portgroup_address_fail(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        pg = obj_utils.create_test_portgroup(
            self.context, node_id=node.id,
            extra={'vif_port_id': 'fake-id'})
        old_address = pg.address
        pg.address = '11:22:33:44:55:bb'
        mac_update_mock.side_effect = (
            exception.FailedToUpdateMacOnPort(port_id=pg.uuid))
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.update_portgroup,
                                self.context, pg)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.FailedToUpdateMacOnPort, exc.exc_info[0])
        pg.refresh()
        self.assertEqual(old_address, pg.address)

    @mock.patch('ironic.dhcp.neutron.NeutronDHCPApi.update_port_address')
    def test_update_portgroup_address_no_vif_id(self, mac_update_mock):
        node = obj_utils.create_test_node(self.context, driver='fake')
        pg = obj_utils.create_test_portgroup(self.context, node_id=node.id)

        new_address = '11:22:33:44:55:bb'
        pg.address = new_address
        self.service.update_portgroup(self.context, pg)
        pg.refresh()
        self.assertEqual(new_address, pg.address)
        self.assertFalse(mac_update_mock.called)


@mgr_utils.mock_record_keepalive
class RaidTestCases(mgr_utils.ServiceSetUpMixin, tests_db_base.DbTestCase):

    def setUp(self):
        super(RaidTestCases, self).setUp()
        self.node = obj_utils.create_test_node(
            self.context, driver='fake', provision_state=states.MANAGEABLE)

    def test_get_raid_logical_disk_properties(self):
        self._start_service()
        properties = self.service.get_raid_logical_disk_properties(
            self.context, 'fake')
        self.assertIn('raid_level', properties)
        self.assertIn('size_gb', properties)

    def test_get_raid_logical_disk_properties_iface_not_supported(self):
        self.driver.raid = None
        self._start_service()
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.get_raid_logical_disk_properties,
                                self.context, 'fake')
        self.assertEqual(exception.UnsupportedDriverExtension, exc.exc_info[0])

    def test_set_target_raid_config(self):
        raid_config = {'logical_disks': [{'size_gb': 100, 'raid_level': '1'}]}
        self.service.set_target_raid_config(
            self.context, self.node.uuid, raid_config)
        self.node.refresh()
        self.assertEqual(raid_config, self.node.target_raid_config)

    def test_set_target_raid_config_empty(self):
        self.node.target_raid_config = {'foo': 'bar'}
        self.node.save()
        raid_config = {}
        self.service.set_target_raid_config(
            self.context, self.node.uuid, raid_config)
        self.node.refresh()
        self.assertEqual({}, self.node.target_raid_config)

    def test_set_target_raid_config_iface_not_supported(self):
        raid_config = {'logical_disks': [{'size_gb': 100, 'raid_level': '1'}]}
        self.driver.raid = None
        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.service.set_target_raid_config,
            self.context, self.node.uuid, raid_config)
        self.node.refresh()
        self.assertEqual({}, self.node.target_raid_config)
        self.assertEqual(exception.UnsupportedDriverExtension, exc.exc_info[0])

    def test_set_target_raid_config_invalid_parameter_value(self):
        # Missing raid_level in the below raid config.
        raid_config = {'logical_disks': [{'size_gb': 100}]}
        self.node.target_raid_config = {'foo': 'bar'}
        self.node.save()

        exc = self.assertRaises(
            messaging.rpc.ExpectedException,
            self.service.set_target_raid_config,
            self.context, self.node.uuid, raid_config)

        self.node.refresh()
        self.assertEqual({'foo': 'bar'}, self.node.target_raid_config)
        self.assertEqual(exception.InvalidParameterValue, exc.exc_info[0])


@mock.patch.object(conductor_utils, 'node_power_action')
class ManagerDoSyncPowerStateTestCase(tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerDoSyncPowerStateTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.driver = mock.Mock(spec_set=drivers_base.BaseDriver)
        self.power = self.driver.power
        self.node = obj_utils.create_test_node(
            self.context, driver='fake', maintenance=False,
            provision_state=states.AVAILABLE)
        self.task = mock.Mock(spec_set=['context', 'driver', 'node',
                                        'upgrade_lock', 'shared'])
        self.task.context = self.context
        self.task.driver = self.driver
        self.task.node = self.node
        self.task.shared = False
        self.config(force_power_state_during_sync=False, group='conductor')

    def _do_sync_power_state(self, old_power_state, new_power_states,
                             fail_validate=False):
        self.node.power_state = old_power_state
        if not isinstance(new_power_states, (list, tuple)):
            new_power_states = [new_power_states]
        if fail_validate:
            exc = exception.InvalidParameterValue('error')
            self.power.validate.side_effect = exc
        for new_power_state in new_power_states:
            self.node.power_state = old_power_state
            if isinstance(new_power_state, Exception):
                self.power.get_power_state.side_effect = new_power_state
            else:
                self.power.get_power_state.return_value = new_power_state
            count = manager.do_sync_power_state(
                self.task, self.service.power_state_sync_count[self.node.uuid])
            self.service.power_state_sync_count[self.node.uuid] = count

    def test_state_unchanged(self, node_power_action):
        self._do_sync_power_state('fake-power', 'fake-power')

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertEqual('fake-power', self.node.power_state)
        self.assertFalse(node_power_action.called)
        self.assertFalse(self.task.upgrade_lock.called)

    def test_state_not_set(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON)

        self.power.validate.assert_called_once_with(self.task)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.task.upgrade_lock.assert_called_once_with()

    def test_validate_fail(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON,
                                  fail_validate=True)

        self.power.validate.assert_called_once_with(self.task)
        self.assertFalse(self.power.get_power_state.called)
        self.assertFalse(node_power_action.called)
        self.assertIsNone(self.node.power_state)

    def test_get_power_state_fail(self, node_power_action):
        self._do_sync_power_state('fake',
                                  exception.IronicException('foo'))

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(node_power_action.called)
        self.assertEqual('fake', self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_get_power_state_error(self, node_power_action):
        self._do_sync_power_state('fake', states.ERROR)
        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(node_power_action.called)
        self.assertEqual('fake', self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_state_changed_no_sync(self, node_power_action):
        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.task.upgrade_lock.assert_called_once_with()

    def test_state_changed_sync(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=1, group='conductor')

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        node_power_action.assert_called_once_with(self.task, states.POWER_ON)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.task.upgrade_lock.assert_called_once_with()

    def test_state_changed_sync_failed(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')

        node_power_action.side_effect = exception.IronicException('test')
        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        # Just testing that this test doesn't raise.
        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
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
        node_power_action.assert_called_once_with(self.task, states.POWER_ON)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(2,
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
        npa_exp_calls = [mock.call(self.task, states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(3,
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
        npa_exp_calls = [mock.call(self.task, states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertEqual(0,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_power_state_sync_max_retries_gps_exception(self,
                                                        node_power_action):
        self.config(power_state_sync_max_retries=2, group='conductor')
        self.service.power_state_sync_count[self.node.uuid] = 2

        node_power_action.side_effect = exception.IronicException('test')
        self._do_sync_power_state('fake',
                                  exception.IronicException('SpongeBob'))

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)

        self.assertIsNone(self.node.power_state)
        self.assertTrue(self.node.maintenance)

        self.assertFalse(node_power_action.called)
        # make sure the actual error is in the last_error attribute
        self.assertIn('SpongeBob', self.node.last_error)

    def test_maintenance_on_upgrade_lock(self, node_power_action):
        self.node.maintenance = True

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertFalse(node_power_action.called)
        self.task.upgrade_lock.assert_called_once_with()

    def test_wrong_provision_state_on_upgrade_lock(self, node_power_action):
        self.node.provision_state = states.DEPLOYWAIT

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertFalse(node_power_action.called)
        self.task.upgrade_lock.assert_called_once_with()

    def test_correct_power_state_on_upgrade_lock(self, node_power_action):
        def _fake_upgrade():
            self.node.power_state = states.POWER_OFF

        self.task.upgrade_lock.side_effect = _fake_upgrade

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task)
        self.assertFalse(node_power_action.called)
        self.task.upgrade_lock.assert_called_once_with()


@mock.patch.object(manager, 'do_sync_power_state')
@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerSyncPowerStatesTestCase(mgr_utils.CommonMixIn,
                                     tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerSyncPowerStatesTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.service.dbapi = self.dbapi
        self.node = self._create_node()
        self.filters = {'reserved': False, 'maintenance': False}
        self.columns = ['uuid', 'driver', 'id']

    def test_node_not_mapped(self, get_nodeinfo_mock,
                             mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = False

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        self.assertFalse(acquire_mock.called)
        self.assertFalse(sync_mock.called)

    def test_node_locked_on_acquire(self, get_nodeinfo_mock,
                                    mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeLocked(node=self.node.uuid,
                                                        host='fake')

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_node_in_deploywait_on_acquire(self, get_nodeinfo_mock,
                                           mapped_mock, acquire_mock,
                                           sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        task = self._create_task(
            node_attrs=dict(provision_state=states.DEPLOYWAIT,
                            target_provision_state=states.ACTIVE,
                            uuid=self.node.uuid))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_node_in_enroll_on_acquire(self, get_nodeinfo_mock, mapped_mock,
                                       acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        task = self._create_task(
            node_attrs=dict(provision_state=states.ENROLL,
                            target_provision_state=states.NOSTATE,
                            uuid=self.node.uuid))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_node_in_power_transition_on_acquire(self, get_nodeinfo_mock,
                                                 mapped_mock, acquire_mock,
                                                 sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        task = self._create_task(
            node_attrs=dict(target_power_state=states.POWER_ON,
                            uuid=self.node.uuid))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_node_in_maintenance_on_acquire(self, get_nodeinfo_mock,
                                            mapped_mock, acquire_mock,
                                            sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        task = self._create_task(
            node_attrs=dict(maintenance=True, uuid=self.node.uuid))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_node_disappears_on_acquire(self, get_nodeinfo_mock,
                                        mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeNotFound(node=self.node.uuid,
                                                          host='fake')

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        self.assertFalse(sync_mock.called)

    def test_single_node(self, get_nodeinfo_mock,
                         mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        task = self._create_task(node_attrs=dict(uuid=self.node.uuid))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY,
                                             shared=True)
        sync_mock.assert_called_once_with(task, mock.ANY)

    def test__sync_power_state_multiple_nodes(self, get_nodeinfo_mock,
                                              mapped_mock, acquire_mock,
                                              sync_mock):
        # Create 8 nodes:
        # 1st node: Should acquire and try to sync
        # 2nd node: Not mapped to this conductor
        # 3rd node: In DEPLOYWAIT provision_state
        # 4th node: In maintenance mode
        # 5th node: Is in power transition
        # 6th node: Disappears after getting nodeinfo list
        # 7th node: Should acquire and try to sync
        # 8th node: do_sync_power_state raises NodeLocked
        nodes = []
        node_attrs = {}
        mapped_map = {}
        for i in range(1, 8):
            attrs = {'id': i,
                     'uuid': uuidutils.generate_uuid()}
            if i == 3:
                attrs['provision_state'] = states.DEPLOYWAIT
                attrs['target_provision_state'] = states.ACTIVE
            elif i == 4:
                attrs['maintenance'] = True
            elif i == 5:
                attrs['target_power_state'] = states.POWER_ON

            n = self._create_node(**attrs)
            nodes.append(n)
            node_attrs[n.uuid] = attrs
            mapped_map[n.uuid] = False if i == 2 else True

        tasks = [self._create_task(node_attrs=node_attrs[x.uuid])
                 for x in nodes if x.id != 2]
        # not found during acquire (4 = index of Node6 after removing Node2)
        tasks[4] = exception.NodeNotFound(node=6)
        sync_results = [0] * 7 + [exception.NodeLocked(node=8, host='')]

        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response(nodes))
        mapped_mock.side_effect = lambda x, y: mapped_map[x]
        acquire_mock.side_effect = self._get_acquire_side_effect(tasks)
        sync_mock.side_effect = sync_results

        with mock.patch.object(eventlet, 'sleep') as sleep_mock:
            self.service._sync_power_states(self.context)
            # Ensure we've yielded on every iteration, except for node
            # not mapped to this conductor
            self.assertEqual(len(nodes) - 1, sleep_mock.call_count)

        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)
        mapped_calls = [mock.call(x.uuid, x.driver) for x in nodes]
        self.assertEqual(mapped_calls, mapped_mock.call_args_list)
        acquire_calls = [mock.call(self.context, x.uuid,
                                   purpose=mock.ANY,
                                   shared=True)
                         for x in nodes if x.id != 2]
        self.assertEqual(acquire_calls, acquire_mock.call_args_list)
        # Nodes 1 and 7 (5 = index of Node7 after removing Node2)
        sync_calls = [mock.call(tasks[0], mock.ANY),
                      mock.call(tasks[5], mock.ANY)]
        self.assertEqual(sync_calls, sync_mock.call_args_list)


@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerCheckDeployTimeoutsTestCase(mgr_utils.CommonMixIn,
                                         tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerCheckDeployTimeoutsTestCase, self).setUp()
        self.config(deploy_callback_timeout=300, group='conductor')
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.service.dbapi = self.dbapi

        self.node = self._create_node(provision_state=states.DEPLOYWAIT,
                                      target_provision_state=states.ACTIVE)
        self.task = self._create_task(node=self.node)

        self.node2 = self._create_node(provision_state=states.DEPLOYWAIT,
                                       target_provision_state=states.ACTIVE)
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
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with(
            'fail',
            callback=self.service._spawn_worker,
            call_args=(conductor_utils.cleanup_after_timeout, self.task),
            err_handler=conductor_utils.provisioning_error_handler,
            target_state=None)

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
                                             self.node.uuid,
                                             purpose=mock.ANY)
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
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.assertFalse(self.task.spawn_after.called)

    def test_no_deploywait_after_lock(self, get_nodeinfo_mock, mapped_mock,
                                      acquire_mock):
        task = self._create_task(
            node_attrs=dict(provision_state=states.AVAILABLE,
                            uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(
            self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.assertFalse(task.spawn_after.called)

    def test_maintenance_after_lock(self, get_nodeinfo_mock, mapped_mock,
                                    acquire_mock):
        task = self._create_task(
            node_attrs=dict(provision_state=states.DEPLOYWAIT,
                            target_provision_state=states.ACTIVE,
                            maintenance=True,
                            uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([task.node, self.node2]))
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([task, self.task2]))

        self.service._check_deploy_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        self.assertEqual([mock.call(self.node.uuid, task.node.driver),
                          mock.call(self.node2.uuid, self.node2.driver)],
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid,
                                    purpose=mock.ANY),
                          mock.call(self.context, self.node2.uuid,
                                    purpose=mock.ANY)],
                         acquire_mock.call_args_list)
        # First node skipped
        self.assertFalse(task.spawn_after.called)
        # Second node spawned
        self.task2.process_event.assert_called_with(
            'fail',
            callback=self.service._spawn_worker,
            call_args=(conductor_utils.cleanup_after_timeout, self.task2),
            err_handler=conductor_utils.provisioning_error_handler,
            target_state=None)

    def test_exiting_no_worker_avail(self, get_nodeinfo_mock, mapped_mock,
                                     acquire_mock):
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node, self.node2]))
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
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with(
            'fail',
            callback=self.service._spawn_worker,
            call_args=(conductor_utils.cleanup_after_timeout, self.task),
            err_handler=conductor_utils.provisioning_error_handler,
            target_state=None)

    def test_exiting_with_other_exception(self, get_nodeinfo_mock,
                                          mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node, self.node2]))
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
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with(
            'fail',
            callback=self.service._spawn_worker,
            call_args=(conductor_utils.cleanup_after_timeout, self.task),
            err_handler=conductor_utils.provisioning_error_handler,
            target_state=None)

    def test_worker_limit(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        self.config(periodic_max_workers=2, group='conductor')

        # Use the same nodes/tasks to make life easier in the tests
        # here

        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node] * 3))
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([self.task] * 3))

        self.service._check_deploy_timeouts(self.context)

        # Should only have ran 2.
        self.assertEqual([mock.call(self.node.uuid, self.node.driver)] * 2,
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid,
                                    purpose=mock.ANY)] * 2,
                         acquire_mock.call_args_list)
        process_event_call = mock.call(
            'fail',
            callback=self.service._spawn_worker,
            call_args=(conductor_utils.cleanup_after_timeout, self.task),
            err_handler=conductor_utils.provisioning_error_handler,
            target_state=None)
        self.assertEqual([process_event_call] * 2,
                         self.task.process_event.call_args_list)

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


@mgr_utils.mock_record_keepalive
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
                    'ipmi_password', 'ipmi_port', 'ipmi_priv_level',
                    'ipmi_username', 'ipmi_bridging',
                    'ipmi_transit_channel', 'ipmi_transit_address',
                    'ipmi_target_channel', 'ipmi_target_address',
                    'ipmi_local_address', 'ipmi_protocol_version',
                    'ipmi_force_boot_device'
                    ]
        self._check_driver_properties("fake_ipmitool", expected)

    def test_driver_properties_fake_ipminative(self):
        expected = ['ipmi_address', 'ipmi_password', 'ipmi_username',
                    'ipmi_terminal_port', 'ipmi_force_boot_device']
        self._check_driver_properties("fake_ipminative", expected)

    def test_driver_properties_fake_ssh(self):
        expected = ['ssh_address', 'ssh_username',
                    'vbox_use_headless', 'ssh_virt_type',
                    'ssh_key_contents', 'ssh_key_filename',
                    'ssh_password', 'ssh_port', 'ssh_terminal_port']
        self._check_driver_properties("fake_ssh", expected)

    def test_driver_properties_fake_pxe(self):
        expected = ['deploy_kernel', 'deploy_ramdisk',
                    'deploy_forces_oob_reboot']
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
                    'ipmi_password', 'ipmi_port', 'ipmi_priv_level',
                    'ipmi_username', 'ipmi_bridging', 'ipmi_transit_channel',
                    'ipmi_transit_address', 'ipmi_target_channel',
                    'ipmi_target_address', 'ipmi_local_address',
                    'deploy_kernel', 'deploy_ramdisk', 'ipmi_protocol_version',
                    'ipmi_force_boot_device', 'deploy_forces_oob_reboot']
        self._check_driver_properties("pxe_ipmitool", expected)

    def test_driver_properties_pxe_ipminative(self):
        expected = ['ipmi_address', 'ipmi_password', 'ipmi_username',
                    'deploy_kernel', 'deploy_ramdisk',
                    'ipmi_terminal_port', 'ipmi_force_boot_device',
                    'deploy_forces_oob_reboot']
        self._check_driver_properties("pxe_ipminative", expected)

    def test_driver_properties_pxe_ssh(self):
        expected = ['deploy_kernel', 'deploy_ramdisk',
                    'ssh_address', 'ssh_username',
                    'vbox_use_headless', 'ssh_virt_type',
                    'ssh_key_contents', 'ssh_key_filename',
                    'ssh_password', 'ssh_port', 'ssh_terminal_port',
                    'deploy_forces_oob_reboot']
        self._check_driver_properties("pxe_ssh", expected)

    def test_driver_properties_pxe_seamicro(self):
        expected = ['deploy_kernel', 'deploy_ramdisk',
                    'seamicro_api_endpoint', 'seamicro_password',
                    'seamicro_server_id', 'seamicro_username',
                    'seamicro_api_version', 'seamicro_terminal_port',
                    'deploy_forces_oob_reboot']
        self._check_driver_properties("pxe_seamicro", expected)

    def test_driver_properties_pxe_snmp(self):
        expected = ['deploy_kernel', 'deploy_ramdisk',
                    'snmp_driver', 'snmp_address', 'snmp_port', 'snmp_version',
                    'snmp_community', 'snmp_security', 'snmp_outlet',
                    'deploy_forces_oob_reboot']
        self._check_driver_properties("pxe_snmp", expected)

    def test_driver_properties_fake_ilo(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                    'client_port', 'client_timeout', 'ilo_change_password',
                    'ca_file']
        self._check_driver_properties("fake_ilo", expected)

    def test_driver_properties_ilo_iscsi(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                    'client_port', 'client_timeout', 'ilo_deploy_iso',
                    'console_port', 'ilo_change_password',
                    'deploy_forces_oob_reboot', 'ca_file']
        self._check_driver_properties("iscsi_ilo", expected)

    def test_driver_properties_agent_ilo(self):
        expected = ['ilo_address', 'ilo_username', 'ilo_password',
                    'client_port', 'client_timeout', 'ilo_deploy_iso',
                    'console_port', 'ilo_change_password',
                    'deploy_forces_oob_reboot', 'ca_file']
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


@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerSyncLocalStateTestCase(mgr_utils.CommonMixIn,
                                    tests_db_base.DbTestCase):

    def setUp(self):
        super(ManagerSyncLocalStateTestCase, self).setUp()

        self.service = manager.ConductorManager('hostname', 'test-topic')

        self.service.conductor = mock.Mock()
        self.service.dbapi = self.dbapi
        self.service.ring_manager = mock.Mock()

        self.node = self._create_node(provision_state=states.ACTIVE,
                                      target_provision_state=states.NOSTATE)
        self.task = self._create_task(node=self.node)

        self.filters = {'reserved': False,
                        'maintenance': False,
                        'provision_state': states.ACTIVE}
        self.columns = ['uuid', 'driver', 'id', 'conductor_affinity']

    def _assert_get_nodeinfo_args(self, get_nodeinfo_mock):
        get_nodeinfo_mock.assert_called_once_with(
            columns=self.columns, filters=self.filters)

    def test_not_mapped(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = False

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)

    def test_already_mapped(self, get_nodeinfo_mock, mapped_mock,
                            acquire_mock):
        # Node is already mapped to the conductor running the periodic task
        self.node.conductor_affinity = 123
        self.service.conductor.id = 123

        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)

    def test_good(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(self.task)

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY)
        # assert spawn_after has been called
        self.task.spawn_after.assert_called_once_with(
            self.service._spawn_worker,
            self.service._do_takeover, self.task)

    def test_no_free_worker(self, get_nodeinfo_mock, mapped_mock,
                            acquire_mock):
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([self.task] * 3))
        self.task.spawn_after.side_effect = [
            None,
            exception.NoFreeConductorWorker('error')
        ]

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node] * 3))

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert  _mapped_to_this_conductor() gets called 2 times only
        # instead of 3. When NoFreeConductorWorker is raised the loop
        # should be broken
        expected = [mock.call(self.node.uuid, self.node.driver)] * 2
        self.assertEqual(expected, mapped_mock.call_args_list)

        # assert  acquire() gets called 2 times only instead of 3. When
        # NoFreeConductorWorker is raised the loop should be broken
        expected = [mock.call(self.context, self.node.uuid,
                              purpose=mock.ANY)] * 2
        self.assertEqual(expected, acquire_mock.call_args_list)

        # assert spawn_after has been called twice
        expected = [mock.call(self.service._spawn_worker,
                    self.service._do_takeover, self.task)] * 2
        self.assertEqual(expected, self.task.spawn_after.call_args_list)

    def test_node_locked(self, get_nodeinfo_mock, mapped_mock, acquire_mock,):
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
            [self.task, exception.NodeLocked('error'), self.task])
        self.task.spawn_after.side_effect = [None, None]

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node] * 3))

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert _mapped_to_this_conductor() gets called 3 times
        expected = [mock.call(self.node.uuid, self.node.driver)] * 3
        self.assertEqual(expected, mapped_mock.call_args_list)

        # assert acquire() gets called 3 times
        expected = [mock.call(self.context, self.node.uuid,
                              purpose=mock.ANY)] * 3
        self.assertEqual(expected, acquire_mock.call_args_list)

        # assert spawn_after has been called only 2 times
        expected = [mock.call(self.service._spawn_worker,
                    self.service._do_takeover, self.task)] * 2
        self.assertEqual(expected, self.task.spawn_after.call_args_list)

    def test_worker_limit(self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        # Limit to only 1 worker
        self.config(periodic_max_workers=1, group='conductor')
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([self.task] * 3))
        self.task.spawn_after.side_effect = [None] * 3

        # 3 nodes to be checked
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node] * 3))

        self.service._sync_local_state(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)

        # assert _mapped_to_this_conductor() gets called only once
        # because of the worker limit
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)

        # assert acquire() gets called only once because of the worker limit
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY)

        # assert spawn_after has been called
        self.task.spawn_after.assert_called_once_with(
            self.service._spawn_worker,
            self.service._do_takeover, self.task)


@mock.patch.object(swift, 'SwiftAPI')
class StoreConfigDriveTestCase(tests_base.TestCase):

    def setUp(self):
        super(StoreConfigDriveTestCase, self).setUp()
        self.node = obj_utils.get_test_node(self.context, driver='fake',
                                            instance_info=None)

    def test_store_configdrive(self, mock_swift):
        manager._store_configdrive(self.node, 'foo')
        expected_instance_info = {'configdrive': 'foo'}
        self.assertEqual(expected_instance_info, self.node.instance_info)
        self.assertFalse(mock_swift.called)

    def test_store_configdrive_swift(self, mock_swift):
        container_name = 'foo_container'
        timeout = 123
        expected_obj_name = 'configdrive-%s' % self.node.uuid
        expected_obj_header = {'X-Delete-After': str(timeout)}
        expected_instance_info = {'configdrive': 'http://1.2.3.4'}

        # set configs and mocks
        CONF.set_override('configdrive_use_swift', True, group='conductor')
        CONF.set_override('configdrive_swift_container', container_name,
                          group='conductor')
        CONF.set_override('deploy_callback_timeout', timeout,
                          group='conductor')
        mock_swift.return_value.get_temp_url.return_value = 'http://1.2.3.4'

        manager._store_configdrive(self.node, b'foo')

        mock_swift.assert_called_once_with()
        mock_swift.return_value.create_object.assert_called_once_with(
            container_name, expected_obj_name, mock.ANY,
            object_headers=expected_obj_header)
        mock_swift.return_value.get_temp_url.assert_called_once_with(
            container_name, expected_obj_name, timeout)
        self.assertEqual(expected_instance_info, self.node.instance_info)


@mgr_utils.mock_record_keepalive
class NodeInspectHardware(mgr_utils.ServiceSetUpMixin,
                          tests_db_base.DbTestCase):

    @mock.patch('ironic.drivers.modules.fake.FakeInspect.inspect_hardware')
    def test_inspect_hardware_ok(self, mock_inspect):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = states.MANAGEABLE
        manager._do_inspect_hardware(task)
        node.refresh()
        self.assertEqual(states.MANAGEABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_inspect.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeInspect.inspect_hardware')
    def test_inspect_hardware_return_inspecting(self, mock_inspect):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = states.INSPECTING
        manager._do_inspect_hardware(task)
        node.refresh()
        self.assertEqual(states.INSPECTING, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_inspect.assert_called_once_with(mock.ANY)

    @mock.patch.object(manager, 'LOG')
    @mock.patch('ironic.drivers.modules.fake.FakeInspect.inspect_hardware')
    def test_inspect_hardware_return_other_state(self, mock_inspect, log_mock):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.INSPECTING)
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_inspect.return_value = None
        self.assertRaises(exception.HardwareInspectionFailure,
                          manager._do_inspect_hardware, task)
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_inspect.assert_called_once_with(mock.ANY)
        self.assertTrue(log_mock.error.called)

    def test__check_inspect_timeouts(self):
        self._start_service()
        CONF.set_override('inspect_timeout', 1, group='conductor')
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.INSPECTING,
            target_provision_state=states.MANAGEABLE,
            provision_updated_at=datetime.datetime(2000, 1, 1, 0, 0),
            inspection_started_at=datetime.datetime(2000, 1, 1, 0, 0))

        self.service._check_inspect_timeouts(self.context)
        self._stop_service()
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_inspect_hardware_worker_pool_full(self, mock_spawn):
        prv_state = states.MANAGEABLE
        tgt_prv_state = states.NOSTATE
        node = obj_utils.create_test_node(self.context,
                                          provision_state=prv_state,
                                          target_provision_state=tgt_prv_state,
                                          last_error=None, driver='fake')
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.inspect_hardware,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc.exc_info[0])
        self._stop_service()
        node.refresh()
        # Make sure things were rolled back
        self.assertEqual(prv_state, node.provision_state)
        self.assertEqual(tgt_prv_state, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def _test_inspect_hardware_validate_fail(self, mock_validate):
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        node = obj_utils.create_test_node(self.context, driver='fake')
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.inspect_hardware,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.HardwareInspectionFailure, exc.exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.drivers.modules.fake.FakeInspect.validate')
    def test_inspect_hardware_validate_fail(self, mock_validate):
        self._test_inspect_hardware_validate_fail(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    def test_inspect_hardware_power_validate_fail(self, mock_validate):
        self._test_inspect_hardware_validate_fail(mock_validate)

    @mock.patch('ironic.drivers.modules.fake.FakeInspect.inspect_hardware')
    def test_inspect_hardware_raises_error(self, mock_inspect):
        self._start_service()
        mock_inspect.side_effect = exception.HardwareInspectionFailure('test')
        state = states.MANAGEABLE
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          provision_state=states.INSPECTING,
                                          target_provision_state=state)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.HardwareInspectionFailure,
                          manager._do_inspect_hardware, task)
        node.refresh()
        self.assertEqual(states.INSPECTFAIL, node.provision_state)
        self.assertEqual(states.MANAGEABLE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertTrue(mock_inspect.called)


@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerCheckInspectTimeoutsTestCase(mgr_utils.CommonMixIn,
                                          tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerCheckInspectTimeoutsTestCase, self).setUp()
        self.config(inspect_timeout=300, group='conductor')
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.service.dbapi = self.dbapi

        self.node = self._create_node(provision_state=states.INSPECTING,
                                      target_provision_state=states.MANAGEABLE)
        self.task = self._create_task(node=self.node)

        self.node2 = self._create_node(
            provision_state=states.INSPECTING,
            target_provision_state=states.MANAGEABLE)
        self.task2 = self._create_task(node=self.node2)

        self.filters = {'reserved': False,
                        'inspection_started_before': 300,
                        'provision_state': states.INSPECTING}
        self.columns = ['uuid', 'driver']

    def _assert_get_nodeinfo_args(self, get_nodeinfo_mock):
        get_nodeinfo_mock.assert_called_once_with(
            sort_dir='asc', columns=self.columns, filters=self.filters,
            sort_key='inspection_started_at')

    def test__check_inspect_timeouts_disabled(self, get_nodeinfo_mock,
                                              mapped_mock, acquire_mock):
        self.config(inspect_timeout=0, group='conductor')

        self.service._check_inspect_timeouts(self.context)

        self.assertFalse(get_nodeinfo_mock.called)
        self.assertFalse(mapped_mock.called)
        self.assertFalse(acquire_mock.called)

    def test__check_inspect_timeouts_not_mapped(self, get_nodeinfo_mock,
                                                mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = False

        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        self.assertFalse(acquire_mock.called)

    def test__check_inspect_timeout(self, get_nodeinfo_mock,
                                    mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(self.task)

        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context, self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with('fail', target_state=None)

    def test__check_inspect_timeouts_acquire_node_disappears(self,
                                                             get_nodeinfo_mock,
                                                             mapped_mock,
                                                             acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeNotFound(node='fake')

        # Exception eaten
        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.assertFalse(self.task.process_event.called)

    def test__check_inspect_timeouts_acquire_node_locked(self,
                                                         get_nodeinfo_mock,
                                                         mapped_mock,
                                                         acquire_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = exception.NodeLocked(node='fake',
                                                        host='fake')

        # Exception eaten
        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.assertFalse(self.task.process_event.called)

    def test__check_inspect_timeouts_no_acquire_after_lock(self,
                                                           get_nodeinfo_mock,
                                                           mapped_mock,
                                                           acquire_mock):
        task = self._create_task(
            node_attrs=dict(provision_state=states.AVAILABLE,
                            uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        mapped_mock.assert_called_once_with(
            self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.assertFalse(task.process_event.called)

    def test__check_inspect_timeouts_to_maintenance_after_lock(
            self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        task = self._create_task(
            node_attrs=dict(provision_state=states.INSPECTING,
                            target_provision_state=states.MANAGEABLE,
                            maintenance=True,
                            uuid=self.node.uuid))
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([task.node, self.node2]))
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([task, self.task2]))

        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        self.assertEqual([mock.call(self.node.uuid, task.node.driver),
                          mock.call(self.node2.uuid, self.node2.driver)],
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid,
                                    purpose=mock.ANY),
                          mock.call(self.context, self.node2.uuid,
                                    purpose=mock.ANY)],
                         acquire_mock.call_args_list)
        # First node skipped
        self.assertFalse(task.process_event.called)
        # Second node spawned
        self.task2.process_event.assert_called_with('fail', target_state=None)

    def test__check_inspect_timeouts_exiting_no_worker_avail(
            self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node, self.node2]))
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
            [(self.task, exception.NoFreeConductorWorker()), self.task2])

        # Exception should be nuked
        self.service._check_inspect_timeouts(self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        # mapped should be only called for the first node as we should
        # have exited the loop early due to NoFreeConductorWorker
        mapped_mock.assert_called_once_with(
            self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with('fail', target_state=None)

    def test__check_inspect_timeouts_exit_with_other_exception(
            self, get_nodeinfo_mock, mapped_mock, acquire_mock):
        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node, self.node2]))
        mapped_mock.return_value = True
        acquire_mock.side_effect = self._get_acquire_side_effect(
            [(self.task, exception.IronicException('foo')), self.task2])

        # Should re-raise
        self.assertRaises(exception.IronicException,
                          self.service._check_inspect_timeouts,
                          self.context)

        self._assert_get_nodeinfo_args(get_nodeinfo_mock)
        # mapped should be only called for the first node as we should
        # have exited the loop early due to unknown exception
        mapped_mock.assert_called_once_with(
            self.node.uuid, self.node.driver)
        acquire_mock.assert_called_once_with(self.context,
                                             self.node.uuid,
                                             purpose=mock.ANY)
        self.task.process_event.assert_called_with('fail', target_state=None)

    def test__check_inspect_timeouts_worker_limit(self, get_nodeinfo_mock,
                                                  mapped_mock, acquire_mock):
        self.config(periodic_max_workers=2, group='conductor')

        # Use the same nodes/tasks to make life easier in the tests
        # here

        get_nodeinfo_mock.return_value = (
            self._get_nodeinfo_list_response([self.node] * 3))
        mapped_mock.return_value = True
        acquire_mock.side_effect = (
            self._get_acquire_side_effect([self.task] * 3))

        self.service._check_inspect_timeouts(self.context)

        # Should only have ran 2.
        self.assertEqual([mock.call(self.node.uuid, self.node.driver)] * 2,
                         mapped_mock.call_args_list)
        self.assertEqual([mock.call(self.context, self.node.uuid,
                                    purpose=mock.ANY)] * 2,
                         acquire_mock.call_args_list)
        process_event_call = mock.call('fail', target_state=None)
        self.assertEqual([process_event_call] * 2,
                         self.task.process_event.call_args_list)


@mgr_utils.mock_record_keepalive
class DestroyPortTestCase(mgr_utils.ServiceSetUpMixin,
                          tests_db_base.DbTestCase):
    def test_destroy_port(self):
        node = obj_utils.create_test_node(self.context, driver='fake')

        port = obj_utils.create_test_port(self.context,
                                          node_id=node.id)
        self.service.destroy_port(self.context, port)
        self.assertRaises(exception.PortNotFound, port.refresh)

    def test_destroy_port_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation='fake-reserv')

        port = obj_utils.create_test_port(self.context, node_id=node.id)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])


@mgr_utils.mock_record_keepalive
class DestroyPortgroupTestCase(mgr_utils.ServiceSetUpMixin,
                               tests_db_base.DbTestCase):
    def test_destroy_portgroup(self):
        node = obj_utils.create_test_node(self.context, driver='fake')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id)
        self.service.destroy_portgroup(self.context, portgroup)
        self.assertRaises(exception.PortgroupNotFound, portgroup.refresh)

    def test_destroy_portgroup_node_locked(self):
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          reservation='fake-reserv')
        portgroup = obj_utils.create_test_portgroup(self.context,
                                                    node_id=node.id)
        exc = self.assertRaises(messaging.rpc.ExpectedException,
                                self.service.destroy_portgroup,
                                self.context, portgroup)
        # Compare true exception hidden by @messaging.expected_exceptions
        self.assertEqual(exception.NodeLocked, exc.exc_info[0])


@mgr_utils.mock_record_keepalive
@mock.patch.object(manager.ConductorManager, '_fail_if_in_state')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_offline_conductors')
class ManagerCheckDeployingStatusTestCase(mgr_utils.ServiceSetUpMixin,
                                          tests_db_base.DbTestCase):
    def setUp(self):
        super(ManagerCheckDeployingStatusTestCase, self).setUp()
        self._start_service()

        self.node = obj_utils.create_test_node(
            self.context, id=1, uuid=uuidutils.generate_uuid(),
            driver='fake', provision_state=states.DEPLOYING,
            target_provision_state=states.DEPLOYDONE,
            reservation='fake-conductor')

        # create a second node in a different state to test the
        # filtering nodes in DEPLOYING state
        obj_utils.create_test_node(
            self.context, id=10, uuid=uuidutils.generate_uuid(),
            driver='fake', provision_state=states.AVAILABLE,
            target_provision_state=states.NOSTATE)

    def test__check_deploying_status(self, mock_off_cond, mock_mapped,
                                     mock_fail_if):
        mock_off_cond.return_value = ['fake-conductor']

        self.service._check_deploying_status(self.context)

        self.node.refresh()
        mock_off_cond.assert_called_once_with()
        mock_mapped.assert_called_once_with(self.node.uuid, 'fake')
        mock_fail_if.assert_called_once_with(
            mock.ANY, {'id': self.node.id}, states.DEPLOYING,
            'provision_updated_at',
            callback_method=conductor_utils.cleanup_after_timeout,
            err_handler=conductor_utils.provisioning_error_handler)
        # assert node was released
        self.assertIsNone(self.node.reservation)

    def test__check_deploying_status_alive(self, mock_off_cond,
                                           mock_mapped, mock_fail_if):
        mock_off_cond.return_value = []

        self.service._check_deploying_status(self.context)

        self.node.refresh()
        mock_off_cond.assert_called_once_with()
        self.assertFalse(mock_mapped.called)
        self.assertFalse(mock_fail_if.called)
        # assert node still locked
        self.assertIsNotNone(self.node.reservation)

    @mock.patch.object(objects.Node, 'release')
    def test__check_deploying_status_release_exceptions_skipping(
            self, mock_release, mock_off_cond, mock_mapped, mock_fail_if):
        mock_off_cond.return_value = ['fake-conductor']
        # Add another node so we can check both exceptions
        node2 = obj_utils.create_test_node(
            self.context, id=2, uuid=uuidutils.generate_uuid(),
            driver='fake', provision_state=states.DEPLOYING,
            target_provision_state=states.DEPLOYDONE,
            reservation='fake-conductor')

        mock_mapped.return_value = True
        mock_release.side_effect = [exception.NodeNotFound('not found'),
                                    exception.NodeLocked('locked')]
        self.service._check_deploying_status(self.context)

        self.node.refresh()
        mock_off_cond.assert_called_once_with()
        expected_calls = [mock.call(self.node.uuid, 'fake'),
                          mock.call(node2.uuid, 'fake')]
        mock_mapped.assert_has_calls(expected_calls)
        # Assert we skipped and didn't try to call _fail_if_in_state
        self.assertFalse(mock_fail_if.called)

    @mock.patch.object(objects.Node, 'release')
    def test__check_deploying_status_release_node_not_locked(
            self, mock_release, mock_off_cond, mock_mapped, mock_fail_if):
        mock_off_cond.return_value = ['fake-conductor']
        mock_mapped.return_value = True
        mock_release.side_effect = exception.NodeNotLocked('not locked')
        self.service._check_deploying_status(self.context)

        self.node.refresh()
        mock_off_cond.assert_called_once_with()
        mock_mapped.assert_called_once_with(self.node.uuid, 'fake')
        mock_fail_if.assert_called_once_with(
            mock.ANY, {'id': self.node.id}, states.DEPLOYING,
            'provision_updated_at',
            callback_method=conductor_utils.cleanup_after_timeout,
            err_handler=conductor_utils.provisioning_error_handler)


class TestIndirectionApiConductor(tests_db_base.DbTestCase):

    def setUp(self):
        super(TestIndirectionApiConductor, self).setUp()
        self.conductor = manager.ConductorManager('test-host', 'test-topic')

    def _test_object_action(self, is_classmethod, raise_exception,
                            return_object=False):
        @obj_base.IronicObjectRegistry.register
        class TestObject(obj_base.IronicObject):
            context = self.context

            def foo(self, context, raise_exception=False, return_object=False):
                if raise_exception:
                    raise Exception('test')
                elif return_object:
                    return obj
                else:
                    return 'test'

            @classmethod
            def bar(cls, context, raise_exception=False, return_object=False):
                if raise_exception:
                    raise Exception('test')
                elif return_object:
                    return obj
                else:
                    return 'test'

        obj = TestObject(self.context)
        if is_classmethod:
            versions = ovo_base.obj_tree_get_versions(TestObject.obj_name())
            result = self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'bar', versions,
                tuple(), {'raise_exception': raise_exception,
                          'return_object': return_object})
        else:
            updates, result = self.conductor.object_action(
                self.context, obj, 'foo', tuple(),
                {'raise_exception': raise_exception,
                 'return_object': return_object})
        if return_object:
            self.assertEqual(obj, result)
        else:
            self.assertEqual('test', result)

    def test_object_action(self):
        self._test_object_action(False, False)

    def test_object_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, False, True)

    def test_object_action_on_object(self):
        self._test_object_action(False, False, True)

    def test_object_class_action(self):
        self._test_object_action(True, False)

    def test_object_class_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, True, True)

    def test_object_class_action_on_object(self):
        self._test_object_action(True, False, False)

    def test_object_action_copies_object(self):
        @obj_base.IronicObjectRegistry.register
        class TestObject(obj_base.IronicObject):
            fields = {'dict': fields.DictOfStringsField()}

            def touch_dict(self, context):
                self.dict['foo'] = 'bar'
                self.obj_reset_changes()

        obj = TestObject(self.context)
        obj.dict = {}
        obj.obj_reset_changes()
        updates, result = self.conductor.object_action(
            self.context, obj, 'touch_dict', tuple(), {})
        # NOTE(danms): If conductor did not properly copy the object, then
        # the new and reference copies of the nested dict object will be
        # the same, and thus 'dict' will not be reported as changed
        self.assertIn('dict', updates)
        self.assertEqual({'foo': 'bar'}, updates['dict'])

    def test_object_backport_versions(self):
        fake_backported_obj = 'fake-backported-obj'
        obj_name = 'fake-obj'
        test_obj = mock.Mock()
        test_obj.obj_name.return_value = obj_name
        test_obj.obj_to_primitive.return_value = fake_backported_obj
        fake_version_manifest = {obj_name: '1.0'}

        result = self.conductor.object_backport_versions(
            self.context, test_obj, fake_version_manifest)

        self.assertEqual(result, fake_backported_obj)
        test_obj.obj_to_primitive.assert_called_once_with(
            target_version='1.0', version_manifest=fake_version_manifest)


@mgr_utils.mock_record_keepalive
class DoNodeTakeOverTestCase(mgr_utils.ServiceSetUpMixin,
                             tests_db_base.DbTestCase):

    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_takeover(self, mock_prepare, mock_take_over,
                          mock_start_console):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake')
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_takeover(task)
        node.refresh()
        self.assertIsNone(node.last_error)
        self.assertFalse(node.console_enabled)
        mock_prepare.assert_called_once_with(mock.ANY)
        mock_take_over.assert_called_once_with(mock.ANY)
        self.assertFalse(mock_start_console.called)

    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_takeover_with_console_enabled(self, mock_prepare,
                                               mock_take_over,
                                               mock_start_console):
        self._start_service()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_takeover(task)
        node.refresh()
        self.assertIsNone(node.last_error)
        self.assertTrue(node.console_enabled)
        mock_prepare.assert_called_once_with(mock.ANY)
        mock_take_over.assert_called_once_with(mock.ANY)
        mock_start_console.assert_called_once_with(mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_takeover_with_console_exception(self, mock_prepare,
                                                 mock_take_over,
                                                 mock_start_console):
        self._start_service()
        mock_start_console.side_effect = Exception()
        node = obj_utils.create_test_node(self.context, driver='fake',
                                          console_enabled=True)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_takeover(task)
        node.refresh()
        self.assertIsNotNone(node.last_error)
        self.assertFalse(node.console_enabled)
        mock_prepare.assert_called_once_with(mock.ANY)
        mock_take_over.assert_called_once_with(mock.ANY)
        mock_start_console.assert_called_once_with(mock.ANY)


@mgr_utils.mock_record_keepalive
class DoNodeAdoptionTestCase(
        mgr_utils.ServiceSetUpMixin,
        tests_db_base.DbTestCase):

    @mock.patch('ironic.drivers.modules.fake.FakePower.validate')
    @mock.patch('ironic.drivers.modules.fake.FakeBoot.validate')
    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_adoption_with_takeover(self,
                                        mock_prepare,
                                        mock_take_over,
                                        mock_start_console,
                                        mock_boot_validate,
                                        mock_power_validate):
        """Test a successful node adoption"""
        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ADOPTING)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_adoption(task)
        node.refresh()

        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertIsNone(node.last_error)
        self.assertFalse(node.console_enabled)
        mock_prepare.assert_called_once_with(mock.ANY)
        mock_take_over.assert_called_once_with(mock.ANY)
        self.assertFalse(mock_start_console.called)
        self.assertTrue(mock_boot_validate.called)
        self.assertIn('is_whole_disk_image', task.node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakeBoot.validate')
    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_adoption_take_over_failure(self,
                                            mock_prepare,
                                            mock_take_over,
                                            mock_start_console,
                                            mock_boot_validate):
        """Test that adoption failed if an exception is raised"""
        # Note(TheJulia): Use of an actual possible exception that
        # can be raised due to a misconfiguration.
        mock_take_over.side_effect = exception.IPMIFailure(
            "something went wrong")

        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ADOPTING)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_adoption(task)
        node.refresh()

        self.assertEqual(states.ADOPTFAIL, node.provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(node.console_enabled)
        mock_prepare.assert_called_once_with(mock.ANY)
        mock_take_over.assert_called_once_with(mock.ANY)
        self.assertFalse(mock_start_console.called)
        self.assertTrue(mock_boot_validate.called)
        self.assertIn('is_whole_disk_image', task.node.driver_internal_info)

    @mock.patch('ironic.drivers.modules.fake.FakeBoot.validate')
    @mock.patch('ironic.drivers.modules.fake.FakeConsole.start_console')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.take_over')
    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.prepare')
    def test__do_adoption_boot_validate_failure(self,
                                                mock_prepare,
                                                mock_take_over,
                                                mock_start_console,
                                                mock_boot_validate):
        """Test that adoption fails if the boot validation fails"""
        # Note(TheJulia): Use of an actual possible exception that
        # can be raised due to a misconfiguration.
        mock_boot_validate.side_effect = exception.MissingParameterValue(
            "something is missing")

        self._start_service()
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ADOPTING)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_adoption(task)
        node.refresh()

        self.assertEqual(states.ADOPTFAIL, node.provision_state)
        self.assertIsNotNone(node.last_error)
        self.assertFalse(node.console_enabled)
        self.assertFalse(mock_prepare.called)
        self.assertFalse(mock_take_over.called)
        self.assertFalse(mock_start_console.called)
        self.assertTrue(mock_boot_validate.called)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_provisioning_action_adopt_node(self, mock_spawn):
        """Test an adoption request results in the node in ADOPTING"""
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.MANAGEABLE,
            target_provision_state=states.NOSTATE)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'adopt')
        node.refresh()
        self.assertEqual(states.ADOPTING, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_spawn.assert_called_with(self.service._do_adoption, mock.ANY)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_provisioning_action_adopt_node_retry(self, mock_spawn):
        """Test a retried adoption from ADOPTFAIL results in ADOPTING state"""
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ADOPTFAIL,
            target_provision_state=states.ACTIVE)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'adopt')
        node.refresh()
        self.assertEqual(states.ADOPTING, node.provision_state)
        self.assertEqual(states.ACTIVE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_spawn.assert_called_with(self.service._do_adoption, mock.ANY)

    def test_do_provisioning_action_manage_of_failed_adoption(self):
        """Test a node in ADOPTFAIL can be taken to MANAGEABLE"""
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.ADOPTFAIL,
            target_provision_state=states.ACTIVE)

        self._start_service()
        self.service.do_provisioning_action(self.context, node.uuid, 'manage')
        node.refresh()

        self.assertEqual(states.MANAGEABLE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_heartbeat(self, mock_spawn):
        """Test heartbeating."""
        node = obj_utils.create_test_node(
            self.context, driver='fake',
            provision_state=states.DEPLOYING,
            target_provision_state=states.ACTIVE)

        self._start_service()
        self.service.heartbeat(self.context, node.uuid, 'http://callback')
        mock_spawn.assert_called_with(self.driver.deploy.heartbeat,
                                      mock.ANY, 'http://callback')
