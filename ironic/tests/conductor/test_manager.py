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

import contextlib
import datetime
import time

import mock
from oslo.config import cfg

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils as ironic_utils
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.db import api as dbapi
from ironic.drivers import base as drivers_base
from ironic import objects
from ironic.openstack.common import context
from ironic.openstack.common.rpc import common as messaging
from ironic.openstack.common import timeutils
from ironic.tests import base as tests_base
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base as tests_db_base
from ironic.tests.db import utils

CONF = cfg.CONF


class ManagerTestCase(tests_db_base.DbTestCase):

    def setUp(self):
        super(ManagerTestCase, self).setUp()
        self.hostname = 'test-host'
        self.config(enabled_drivers=['fake'])
        self.service = manager.ConductorManager(self.hostname, 'test-topic')
        self.dbapi = dbapi.get_instance()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")

    def _stop_service(self):
        try:
            self.dbapi.get_conductor(self.hostname)
        except exception.ConductorNotFound:
            return
        self.service.stop()

    def _start_service(self):
        self.service.start()
        self.addCleanup(self._stop_service)

    def test_start_registers_conductor(self):
        self.assertRaises(exception.ConductorNotFound,
                          self.dbapi.get_conductor,
                          self.hostname)
        self._start_service()
        res = self.dbapi.get_conductor(self.hostname)
        self.assertEqual(self.hostname, res['hostname'])

    def test_stop_unregisters_conductor(self):
        self._start_service()
        res = self.dbapi.get_conductor(self.hostname)
        self.assertEqual(self.hostname, res['hostname'])
        self.service.stop()
        self.assertRaises(exception.ConductorNotFound,
                          self.dbapi.get_conductor,
                          self.hostname)

    def test_start_registers_driver_names(self):
        init_names = ['fake1', 'fake2']
        restart_names = ['fake3', 'fake4']

        df = driver_factory.DriverFactory()
        with mock.patch.object(df._extension_manager, 'names') as mock_names:
            # verify driver names are registered
            self.config(enabled_drivers=init_names)
            mock_names.return_value = init_names
            self._start_service()
            res = self.dbapi.get_conductor(self.hostname)
            self.assertEqual(init_names, res['drivers'])

            # verify that restart registers new driver names
            self.config(enabled_drivers=restart_names)
            mock_names.return_value = restart_names
            self._start_service()
            res = self.dbapi.get_conductor(self.hostname)
            self.assertEqual(restart_names, res['drivers'])

    @mock.patch.object(driver_factory.DriverFactory, '__init__')
    def test_start_fails_on_missing_driver(self, mock_df):
        mock_df.side_effect = exception.DriverNotFound('test')
        with mock.patch.object(self.dbapi, 'register_conductor') as mock_reg:
            self.assertRaises(exception.DriverNotFound,
                              self.service.start)
            self.assertTrue(mock_df.called)
            self.assertFalse(mock_reg.called)

    def test__mapped_to_this_conductor(self):
        self._start_service()
        n = utils.get_test_node()
        self.assertTrue(self.service._mapped_to_this_conductor(n['uuid'],
                                                               'fake'))
        self.assertFalse(self.service._mapped_to_this_conductor(n['uuid'],
                                                                'otherdriver'))

    def test__conductor_service_record_keepalive(self):
        self._start_service()
        with mock.patch.object(self.dbapi, 'touch_conductor') as mock_touch:
            self.service._conductor_service_record_keepalive(self.context)
            mock_touch.assert_called_once_with(self.hostname)

    def test_change_node_power_state_power_on(self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        n = utils.get_test_node(driver='fake',
                                power_state=states.POWER_OFF)
        db_node = self.dbapi.create_node(n)
        self._start_service()

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            self.service.change_node_power_state(self.context,
                                                 db_node.uuid,
                                                 states.POWER_ON)
            self.service._worker_pool.waitall()

            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            db_node.refresh(self.context)
            self.assertEqual(states.POWER_ON, db_node.power_state)
            self.assertIsNone(db_node.target_power_state)
            self.assertIsNone(db_node.last_error)
            # Verify the reservation has been cleared by
            # background task's link callback.
            self.assertIsNone(db_node.reservation)

    @mock.patch.object(conductor_utils, 'node_power_action')
    def test_change_node_power_state_node_already_locked(self,
                                                         pwr_act_mock):
        # Test change_node_power_state with mocked
        # conductor.utils.node_power_action.
        fake_reservation = 'fake-reserv'
        pwr_state = states.POWER_ON
        n = utils.get_test_node(driver='fake',
                                power_state=pwr_state,
                                reservation=fake_reservation)
        db_node = self.dbapi.create_node(n)
        self._start_service()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.change_node_power_state,
                                self.context,
                                db_node.uuid,
                                states.POWER_ON)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeLocked, exc._exc_info[0])

        # In this test worker should not be spawned, but waiting to make sure
        # the below perform_mock assertion is valid.
        self.service._worker_pool.waitall()
        self.assertFalse(pwr_act_mock.called, 'node_power_action has been '
                                              'unexpectedly called.')
        # Verify existing reservation wasn't broken.
        db_node.refresh(self.context)
        self.assertEqual(fake_reservation, db_node.reservation)

    def test_change_node_power_state_worker_pool_full(self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        initial_state = states.POWER_OFF
        n = utils.get_test_node(driver='fake',
                                power_state=initial_state)
        db_node = self.dbapi.create_node(n)
        self._start_service()

        with mock.patch.object(self.service, '_spawn_worker') \
                as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.ClientException,
                                    self.service.change_node_power_state,
                                    self.context,
                                    db_node.uuid,
                                    states.POWER_ON)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc._exc_info[0])

            spawn_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                               mock.ANY, mock.ANY)
            db_node.refresh(self.context)
            self.assertEqual(initial_state, db_node.power_state)
            self.assertIsNone(db_node.target_power_state)
            self.assertIsNone(db_node.last_error)
            # Verify the picked reservation has been cleared due to full pool.
            self.assertIsNone(db_node.reservation)

    def test_change_node_power_state_exception_in_background_task(
            self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        initial_state = states.POWER_OFF
        n = utils.get_test_node(driver='fake',
                                power_state=initial_state)
        db_node = self.dbapi.create_node(n)
        self._start_service()

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                new_state = states.POWER_ON
                set_power_mock.side_effect = exception.PowerStateFailure(
                    pstate=new_state
                )

                self.service.change_node_power_state(self.context,
                                                     db_node.uuid,
                                                     new_state)
                self.service._worker_pool.waitall()

                get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
                set_power_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                                       new_state)
                db_node.refresh(self.context)
                self.assertEqual(initial_state, db_node.power_state)
                self.assertIsNone(db_node.target_power_state)
                self.assertIsNotNone(db_node.last_error)
                # Verify the reservation has been cleared by background task's
                # link callback despite exception in background task.
                self.assertIsNone(db_node.reservation)

    def test_change_node_power_state_validate_fail(self):
        # Test change_node_power_state where task.driver.power.validate
        # fails and raises an exception
        initial_state = states.POWER_ON
        n = utils.get_test_node(driver='fake',
                                power_state=initial_state)
        db_node = self.dbapi.create_node(n)
        self._start_service()

        with mock.patch.object(self.driver.power, 'validate') \
                as validate_mock:
            validate_mock.side_effect = exception.InvalidParameterValue(
                'wrong power driver info')

            exc = self.assertRaises(messaging.ClientException,
                                    self.service.change_node_power_state,
                                    self.context,
                                    db_node.uuid,
                                    states.POWER_ON)

            self.assertEqual(exception.InvalidParameterValue, exc._exc_info[0])

            db_node.refresh(self.context)
            validate_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertEqual(states.POWER_ON, db_node.power_state)
            self.assertIsNone(db_node.target_power_state)
            self.assertIsNone(db_node.last_error)

    def test_update_node(self):
        ndict = utils.get_test_node(driver='fake', extra={'test': 'one'})
        node = self.dbapi.create_node(ndict)

        # check that ManagerService.update_node actually updates the node
        node['extra'] = {'test': 'two'}
        res = self.service.update_node(self.context, node)
        self.assertEqual({'test': 'two'}, res['extra'])

    def test_update_node_already_locked(self):
        ndict = utils.get_test_node(driver='fake', extra={'test': 'one'})
        node = self.dbapi.create_node(ndict)

        # check that it fails if something else has locked it already
        with task_manager.acquire(self.context, node['id'], shared=False):
            node['extra'] = {'test': 'two'}
            exc = self.assertRaises(messaging.ClientException,
                                    self.service.update_node,
                                    self.context,
                                    node)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.NodeLocked, exc._exc_info[0])

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual({'test': 'one'}, res['extra'])

    def test_associate_node_invalid_state(self):
        ndict = utils.get_test_node(driver='fake',
                                    extra={'test': 'one'},
                                    instance_uuid=None,
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        # check that it fails because state is POWER_ON
        node['instance_uuid'] = 'fake-uuid'
        exc = self.assertRaises(messaging.ClientException,
                                self.service.update_node,
                                self.context,
                                node)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeInWrongPowerState, exc._exc_info[0])

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertIsNone(res['instance_uuid'])

    def test_associate_node_valid_state(self):
        ndict = utils.get_test_node(driver='fake',
                                    instance_uuid=None,
                                    power_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakePower.'
                        'get_power_state') as mock_get_power_state:

            mock_get_power_state.return_value = states.POWER_OFF
            node['instance_uuid'] = 'fake-uuid'
            self.service.update_node(self.context, node)

            # Check if the change was applied
            res = objects.Node.get_by_uuid(self.context, node['uuid'])
            self.assertEqual('fake-uuid', res['instance_uuid'])

    def test_update_node_invalid_driver(self):
        existing_driver = 'fake'
        wrong_driver = 'wrong-driver'
        ndict = utils.get_test_node(driver=existing_driver,
                                    extra={'test': 'one'},
                                    instance_uuid=None,
                                    task_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)
        # check that it fails because driver not found
        node.driver = wrong_driver
        node.driver_info = {}
        self.assertRaises(exception.DriverNotFound,
                          self.service.update_node,
                          self.context,
                          node)

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(existing_driver, res['driver'])

    def test_vendor_passthru_success(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self._start_service()

        self.service.vendor_passthru(
            self.context, n['uuid'], 'first_method', info)
        # Waiting to make sure the below assertions are valid.
        self.service._worker_pool.waitall()

        node.refresh(self.context)
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_node_already_locked(self):
        fake_reservation = 'test_reserv'
        n = utils.get_test_node(driver='fake', reservation=fake_reservation)
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self._start_service()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.vendor_passthru,
                                self.context, n['uuid'], 'first_method', info)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeLocked, exc._exc_info[0])

        node.refresh(self.context)
        self.assertIsNone(node.last_error)
        # Verify the existing reservation is not broken.
        self.assertEqual(fake_reservation, node.reservation)

    def test_vendor_passthru_unsupported_method(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self._start_service()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.vendor_passthru,
                                self.context,
                                n['uuid'], 'unsupported_method', info)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc._exc_info[0])

        node.refresh(self.context)
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_invalid_method_parameters(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'invalid_param': 'whatever'}
        self._start_service()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.vendor_passthru,
                                self.context, n['uuid'], 'first_method', info)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.InvalidParameterValue, exc._exc_info[0])

        node.refresh(self.context)
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_vendor_interface_not_supported(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.driver.vendor = None
        self._start_service()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.vendor_passthru,
                                self.context,
                                n['uuid'], 'whatever_method', info)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc._exc_info[0])

        node.refresh(self.context)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_vendor_passthru_worker_pool_full(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self._start_service()

        with mock.patch.object(self.service, '_spawn_worker') \
                as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.ClientException,
                                    self.service.vendor_passthru,
                                    self.context,
                                    n['uuid'], 'first_method', info)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc._exc_info[0])

            # Waiting to make sure the below assertions are valid.
            self.service._worker_pool.waitall()

            node.refresh(self.context)
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)

    def test_do_node_deploy_invalid_state(self):
        # test node['provision_state'] is not NOSTATE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc._exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_do_node_deploy_maintenance(self):
        ndict = utils.get_test_node(driver='fake', maintenance=True)
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.do_node_deploy,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeInMaintenance, exc._exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.validate')
    def test_do_node_deploy_validate_fail(self, mock_validate):
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.do_node_deploy,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc._exc_info[0])
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_driver_raises_error(self, mock_deploy):
        # test when driver.deploy.deploy raises an exception
        mock_deploy.side_effect = exception.InstanceDeployFailure('test')
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.assertRaises(exception.InstanceDeployFailure,
                          self.service._do_node_deploy,
                          self.context, task)
        node.refresh(self.context)
        self.assertEqual(states.DEPLOYFAIL, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy')
    def test__do_node_deploy_ok(self, mock_deploy):
        # test when driver.deploy.deploy returns DEPLOYDONE
        mock_deploy.return_value = states.DEPLOYDONE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)
        task = task_manager.TaskManager(self.context, node.uuid)

        self.service._do_node_deploy(self.context, task)
        node.refresh(self.context)
        self.assertEqual(states.ACTIVE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_deploy_partial_ok(self):
        self._start_service()
        thread = self.service._spawn_worker(lambda: None)
        with mock.patch.object(self.service, '_spawn_worker') as mock_spawn:
            mock_spawn.return_value = thread

            ndict = utils.get_test_node(driver='fake',
                                        provision_state=states.NOSTATE)
            node = self.dbapi.create_node(ndict)

            self.service.do_node_deploy(self.context, node.uuid)
            self.service._worker_pool.waitall()
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYING, node.provision_state)
            self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
            # This is a sync operation last_error should be None.
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)
            mock_spawn.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_do_node_deploy_worker_pool_full(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self._start_service()

        with mock.patch.object(self.service, '_spawn_worker') as mock_spawn:
            mock_spawn.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.ClientException,
                                    self.service.do_node_deploy,
                                    self.context, node.uuid)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc._exc_info[0])
            self.service._worker_pool.waitall()
            node.refresh(self.context)
            # This is a sync operation last_error should be None.
            self.assertIsNone(node.last_error)
            # Verify reservation has been cleared.
            self.assertIsNone(node.reservation)

    def test_do_node_tear_down_invalid_state(self):
        # test node.provision_state is incorrect for tear_down
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.do_node_tear_down,
                                self.context, node['uuid'])
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc._exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.validate')
    def test_do_node_tear_down_validate_fail(self, mock_validate):
        # InvalidParameterValue should be re-raised as InstanceDeployFailure
        mock_validate.side_effect = exception.InvalidParameterValue('error')
        ndict = utils.get_test_node(driver='fake')
        ndict['provision_state'] = states.ACTIVE
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                               self.service.do_node_tear_down,
                               self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.InstanceDeployFailure, exc._exc_info[0])

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_driver_raises_error(self, mock_tear_down):
        # test when driver.deploy.tear_down raises exception
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        task = task_manager.TaskManager(self.context, node.uuid)
        self._start_service()
        mock_tear_down.side_effect = exception.InstanceDeployFailure('test')
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service._do_node_tear_down,
                          self.context, task)
        node.refresh(self.context)
        self.assertEqual(states.ERROR, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNotNone(node.last_error)
        mock_tear_down.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_ok(self, mock_tear_down):
        # test when driver.deploy.tear_down returns DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        task = task_manager.TaskManager(self.context, node.uuid)
        self._start_service()
        mock_tear_down.return_value = states.DELETED
        self.service._do_node_tear_down(self.context, task)
        node.refresh(self.context)
        self.assertEqual(states.NOSTATE, node.provision_state)
        self.assertEqual(states.NOSTATE, node.target_provision_state)
        self.assertIsNone(node.last_error)
        mock_tear_down.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down')
    def test_do_node_tear_down_partial_ok(self, mock_tear_down):
        # test when driver.deploy.tear_down doesn't return DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        self._start_service()
        task = task_manager.TaskManager(self.context, node.uuid)
        mock_tear_down.return_value = states.DELETING
        self.service._do_node_tear_down(self.context, task)
        node.refresh(self.context)
        self.assertEqual(states.DELETING, node.provision_state)
        self.assertIsNone(node.last_error)
        mock_tear_down.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('ironic.conductor.manager.ConductorManager._spawn_worker')
    def test_do_node_tear_down_worker_pool_full(self, mock_spawn):
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)
        self._start_service()

        mock_spawn.side_effect = exception.NoFreeConductorWorker()

        exc = self.assertRaises(messaging.ClientException,
                                self.service.do_node_tear_down,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NoFreeConductorWorker, exc._exc_info[0])
        self.service._worker_pool.waitall()
        node.refresh(self.context)
        # This is a sync operation last_error should be None.
        self.assertIsNone(node.last_error)
        # Verify reservation has been cleared.
        self.assertIsNone(node.reservation)

    def test_validate_driver_interfaces(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        ret = self.service.validate_driver_interfaces(self.context,
                                                      node['uuid'])
        expected = {'console': {'result': True},
                    'power': {'result': True},
                    'deploy': {'result': True}}
        self.assertEqual(expected, ret)

    def test_validate_driver_interfaces_validation_fail(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.validate') \
                as deploy:
            reason = 'fake reason'
            deploy.side_effect = exception.InvalidParameterValue(reason)
            ret = self.service.validate_driver_interfaces(self.context,
                                                          node['uuid'])
            self.assertFalse(ret['deploy']['result'])
            self.assertEqual(reason, ret['deploy']['reason'])

    def test_maintenance_mode_on(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.service.change_node_maintenance_mode(self.context, node.uuid,
                                                  True)
        node.refresh(self.context)
        self.assertTrue(node.maintenance)

    def test_maintenance_mode_off(self):
        ndict = utils.get_test_node(driver='fake',
                                    maintenance=True)
        node = self.dbapi.create_node(ndict)
        self.service.change_node_maintenance_mode(self.context, node.uuid,
                                                  False)
        node.refresh(self.context)
        self.assertFalse(node.maintenance)

    def test_maintenance_mode_on_failed(self):
        ndict = utils.get_test_node(driver='fake',
                                    maintenance=True)
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.change_node_maintenance_mode,
                                self.context, node.uuid, True)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeMaintenanceFailure, exc._exc_info[0])
        node.refresh(self.context)
        self.assertTrue(node.maintenance)

    def test_maintenance_mode_off_failed(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.change_node_maintenance_mode,
                                self.context, node.uuid, False)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeMaintenanceFailure, exc._exc_info[0])
        node.refresh(self.context)
        self.assertFalse(node.maintenance)

    def test__spawn_worker(self):
        func_mock = mock.Mock()
        args = (1, 2, "test")
        kwargs = dict(kw1='test1', kw2='test2')
        self._start_service()

        thread = self.service._spawn_worker(func_mock, *args, **kwargs)
        self.service._worker_pool.waitall()

        self.assertIsNotNone(thread)
        func_mock.assert_called_once_with(*args, **kwargs)

    # The tests below related to greenthread. We have they to assert our
    # assumptions about greenthread behavior.

    def test__spawn_link_callback_added_during_execution(self):
        def func():
            time.sleep(1)
        link_callback = mock.Mock()
        self._start_service()

        thread = self.service._spawn_worker(func)
        # func_mock executing at this moment
        thread.link(link_callback)
        self.service._worker_pool.waitall()

        link_callback.assert_called_once_with(thread)

    def test__spawn_link_callback_added_after_execution(self):
        def func():
            pass
        link_callback = mock.Mock()
        self._start_service()

        thread = self.service._spawn_worker(func)
        self.service._worker_pool.waitall()
        # func_mock finished at this moment
        thread.link(link_callback)

        link_callback.assert_called_once_with(thread)

    def test__spawn_link_callback_exception_inside_thread(self):
        def func():
            time.sleep(1)
            raise Exception()
        link_callback = mock.Mock()
        self._start_service()

        thread = self.service._spawn_worker(func)
        # func_mock executing at this moment
        thread.link(link_callback)
        self.service._worker_pool.waitall()

        link_callback.assert_called_once_with(thread)

    def test__spawn_link_callback_added_after_exception_inside_thread(self):
        def func():
            raise Exception()
        link_callback = mock.Mock()
        self._start_service()

        thread = self.service._spawn_worker(func)
        self.service._worker_pool.waitall()
        # func_mock finished at this moment
        thread.link(link_callback)

        link_callback.assert_called_once_with(thread)

    def test_destroy_node(self):
        self._start_service()
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.service.destroy_node(self.context, node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node,
                          node.uuid)

    def test_destroy_node_reserved(self):
        self._start_service()
        fake_reservation = 'fake-reserv'
        ndict = utils.get_test_node(reservation=fake_reservation)
        node = self.dbapi.create_node(ndict)

        exc = self.assertRaises(messaging.ClientException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeLocked, exc._exc_info[0])
        # Verify existing reservation wasn't broken.
        node.refresh(self.context)
        self.assertEqual(fake_reservation, node.reservation)

    def test_destroy_node_associated(self):
        self._start_service()
        ndict = utils.get_test_node(instance_uuid='fake-uuid')
        node = self.dbapi.create_node(ndict)

        exc = self.assertRaises(messaging.ClientException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeAssociated, exc._exc_info[0])

        # Verify reservation was released.
        node.refresh(self.context)
        self.assertIsNone(node.reservation)

    @mock.patch.object(timeutils, 'utcnow')
    def test__check_deploy_timeouts_timeout(self, mock_utcnow):
        self.config(deploy_callback_timeout=60, group='conductor')
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=5)
        mock_utcnow.return_value = past
        self._start_service()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
        self.service._conductor_service_record_keepalive(self.context)
        with mock.patch.object(self.driver.deploy, 'clean_up') as clean_mock:
            self.service._check_deploy_timeouts(self.context)
            self.service._worker_pool.waitall()
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYFAIL, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertIsNotNone(node.last_error)
            clean_mock.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(timeutils, 'utcnow')
    def test__check_deploy_timeouts_no_timeout(self, mock_utcnow):
        self.config(deploy_callback_timeout=600, group='conductor')
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=5)
        mock_utcnow.return_value = past
        self._start_service()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
        self.service._conductor_service_record_keepalive(self.context)
        with mock.patch.object(self.driver.deploy, 'clean_up') as clean_mock:
            self.service._check_deploy_timeouts(self.context)
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYWAIT, node.provision_state)
            self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
            self.assertIsNone(node.last_error)
            self.assertFalse(clean_mock.called)

    def test__check_deploy_timeouts_disabled(self):
        self.config(deploy_callback_timeout=0, group='conductor')
        self._start_service()
        with mock.patch.object(self.dbapi, 'get_nodeinfo_list') as get_mock:
            self.service._check_deploy_timeouts(self.context)
            self.assertFalse(get_mock.called)

    @mock.patch.object(timeutils, 'utcnow')
    def test__check_deploy_timeouts_cleanup_failed(self, mock_utcnow):
        self.config(deploy_callback_timeout=60, group='conductor')
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=5)
        mock_utcnow.return_value = past
        self._start_service()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
        self.service._conductor_service_record_keepalive(self.context)
        with mock.patch.object(self.driver.deploy, 'clean_up') as clean_mock:
            error = 'test-123'
            clean_mock.side_effect = exception.IronicException(message=error)
            self.service._check_deploy_timeouts(self.context)
            self.service._worker_pool.waitall()
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYFAIL, node.provision_state)
            self.assertEqual(states.NOSTATE, node.target_provision_state)
            self.assertIn(error, node.last_error)
            self.assertIsNone(node.reservation)

    def test_set_console_mode_worker_pool_full(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.service, '_spawn_worker') \
                as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            exc = self.assertRaises(messaging.ClientException,
                                    self.service.set_console_mode,
                                    self.context, node.uuid, True)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.NoFreeConductorWorker, exc._exc_info[0])
            self.service._worker_pool.waitall()
            spawn_mock.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY)

    def test_set_console_mode_enabled(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, True)
        self.service._worker_pool.waitall()
        node.refresh(self.context)
        self.assertTrue(node.console_enabled)

    def test_set_console_mode_disabled(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self._start_service()
        self.service.set_console_mode(self.context, node.uuid, False)
        self.service._worker_pool.waitall()
        node.refresh(self.context)
        self.assertFalse(node.console_enabled)

    def test_set_console_mode_not_supported(self):
        ndict = utils.get_test_node(driver='fake', last_error=None)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        # null the console interface
        self.driver.console = None
        exc = self.assertRaises(messaging.ClientException,
                                self.service.set_console_mode, self.context,
                                node.uuid, True)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc._exc_info[0])
        self.service._worker_pool.waitall()
        node.refresh(self.context)
        self.assertIsNotNone(node.last_error)

    def test_set_console_mode_validation_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.driver.console, 'validate') as mock_val:
            mock_val.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.ClientException,
                                    self.service.set_console_mode,
                                    self.context, node.uuid, True)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc._exc_info[0])

    def test_set_console_mode_start_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None,
                                    console_enabled=False)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.driver.console, 'start_console') \
                as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.service.set_console_mode(self.context, node.uuid, True)
            self.service._worker_pool.waitall()
            mock_sc.assert_called_once_with(mock.ANY, mock.ANY)
            node.refresh(self.context)
            self.assertIsNotNone(node.last_error)

    def test_set_console_mode_stop_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None,
                                    console_enabled=True)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.driver.console, 'stop_console') \
                as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.service.set_console_mode(self.context, node.uuid, False)
            self.service._worker_pool.waitall()
            mock_sc.assert_called_once_with(mock.ANY, mock.ANY)
            node.refresh(self.context)
            self.assertIsNotNone(node.last_error)

    def test_enable_console_already_enabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.driver.console, 'start_console') \
                as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, True)
            self.service._worker_pool.waitall()
            self.assertFalse(mock_sc.called)

    def test_disable_console_already_disabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=False)
        node = self.dbapi.create_node(ndict)
        self._start_service()
        with mock.patch.object(self.driver.console, 'stop_console') \
                as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, False)
            self.service._worker_pool.waitall()
            self.assertFalse(mock_sc.called)

    def test_get_console(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        console_info = {'test': 'test info'}
        with mock.patch.object(self.driver.console, 'get_console') as mock_gc:
            mock_gc.return_value = console_info
            data = self.service.get_console_information(self.context,
                                                        node.uuid)
            self.assertEqual(console_info, data)

    def test_get_console_not_supported(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        # null the console interface
        self.driver.console = None
        exc = self.assertRaises(messaging.ClientException,
                          self.service.get_console_information,
                          self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.UnsupportedDriverExtension,
                         exc._exc_info[0])

    def test_get_console_disabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=False)
        node = self.dbapi.create_node(ndict)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.get_console_information,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeConsoleNotEnabled, exc._exc_info[0])

    def test_get_console_validate_fail(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'validate') as mock_gc:
            mock_gc.side_effect = exception.InvalidParameterValue('error')
            exc = self.assertRaises(messaging.ClientException,
                                    self.service.get_console_information,
                                    self.context, node.uuid)
            # Compare true exception hidden by @messaging.client_exceptions
            self.assertEqual(exception.InvalidParameterValue, exc._exc_info[0])

    def test_destroy_node_power_on(self):
        self._start_service()
        ndict = utils.get_test_node(power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        exc = self.assertRaises(messaging.ClientException,
                                self.service.destroy_node,
                                self.context, node.uuid)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeInWrongPowerState, exc._exc_info[0])
        # Verify reservation was released.
        node.refresh(self.context)
        self.assertIsNone(node.reservation)

    def test_destroy_node_power_off(self):
        self._start_service()
        ndict = utils.get_test_node(power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        self.service.destroy_node(self.context, node.uuid)

    def test_update_port(self):
        ndict = utils.get_test_node(driver='fake')
        self.dbapi.create_node(ndict)

        pdict = utils.get_test_port(extra={'foo': 'bar'})
        port = self.dbapi.create_port(pdict)
        new_extra = {'foo': 'baz'}
        port.extra = new_extra
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_extra, res.extra)

    def test_update_port_node_locked(self):
        ndict = utils.get_test_node(driver='fake', reservation='fake-reserv')
        self.dbapi.create_node(ndict)

        pdict = utils.get_test_port()
        port = self.dbapi.create_port(pdict)
        port.extra = {'foo': 'baz'}
        exc = self.assertRaises(messaging.ClientException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.NodeLocked, exc._exc_info[0])

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_address')
    def test_update_port_address(self, mac_update_mock):
        ndict = utils.get_test_node(driver='fake')
        self.dbapi.create_node(ndict)

        pdict = utils.get_test_port(extra={'vif_port_id': 'fake-id'})
        port = self.dbapi.create_port(pdict)
        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_address, res.address)
        mac_update_mock.assert_called_once_with('fake-id', new_address)

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_address')
    def test_update_port_address_fail(self, mac_update_mock):
        ndict = utils.get_test_node(driver='fake')
        self.dbapi.create_node(ndict)

        pdict = utils.get_test_port(extra={'vif_port_id': 'fake-id'})
        port = self.dbapi.create_port(pdict)
        old_address = port.address
        port.address = '11:22:33:44:55:bb'
        mac_update_mock.side_effect = exception.FailedToUpdateMacOnPort(
                                                            port_id=port.uuid)
        exc = self.assertRaises(messaging.ClientException,
                                self.service.update_port,
                                self.context, port)
        # Compare true exception hidden by @messaging.client_exceptions
        self.assertEqual(exception.FailedToUpdateMacOnPort, exc._exc_info[0])
        port.refresh(self.context)
        self.assertEqual(old_address, port.address)

    @mock.patch('ironic.common.neutron.NeutronAPI.update_port_address')
    def test_update_port_address_no_vif_id(self, mac_update_mock):
        ndict = utils.get_test_node(driver='fake')
        self.dbapi.create_node(ndict)

        pdict = utils.get_test_port()
        port = self.dbapi.create_port(pdict)
        new_address = '11:22:33:44:55:bb'
        port.address = new_address
        res = self.service.update_port(self.context, port)
        self.assertEqual(new_address, res.address)
        self.assertFalse(mac_update_mock.called)


@mock.patch.object(conductor_utils, 'node_power_action')
class ManagerDoSyncPowerStateTestCase(tests_base.TestCase):
    def setUp(self):
        super(ManagerDoSyncPowerStateTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.context = context.get_admin_context()
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
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.assertEqual('fake-power', self.node.power_state)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)

    def test_state_not_set(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON)

        self.power.validate.assert_called_once_with(self.task, self.node)
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.node.save.assert_called_once_with(self.context)
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    def test_validate_fail(self, node_power_action):
        self._do_sync_power_state(None, states.POWER_ON,
                                  fail_validate=True)

        self.power.validate.assert_called_once_with(self.task, self.node)
        self.assertFalse(self.power.get_power_state.called)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)
        self.assertEqual(None, self.node.power_state)

    def test_get_power_state_fail(self, node_power_action):
        self._do_sync_power_state('fake',
                                  exception.IronicException('foo'))

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.assertFalse(self.node.save.called)
        self.assertFalse(node_power_action.called)
        self.assertEqual('fake', self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_state_changed_no_sync(self, node_power_action):
        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.node.save.assert_called_once_with(self.context)
        self.assertFalse(node_power_action.called)
        self.assertEqual(states.POWER_OFF, self.node.power_state)

    def test_state_changed_sync(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=1, group='conductor')

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF)

        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.assertFalse(self.node.save.called)
        node_power_action.assert_called_once_with(self.task, self.node,
                                                  states.POWER_ON)
        self.assertEqual(states.POWER_ON, self.node.power_state)

    def test_state_changed_sync_failed(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')

        self._do_sync_power_state(states.POWER_ON, states.POWER_OFF,
                                  fail_change=True)

        # Just testing that this test doesn't raise.
        self.assertFalse(self.power.validate.called)
        self.power.get_power_state.assert_called_once_with(self.task,
                                                           self.node)
        self.assertFalse(self.node.save.called)
        node_power_action.assert_called_once_with(self.task, self.node,
                                                  states.POWER_ON)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_max_retries_exceeded(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=1, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task, self.node)] * 2
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.node.save.assert_called_once_with(self.context)
        node_power_action.assert_called_once_with(self.task, self.node,
                                                  states.POWER_ON)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(1,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_max_retries_exceeded2(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=2, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF,
                                                    states.POWER_OFF])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task, self.node)] * 3
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.node.save.assert_called_once_with(self.context)
        npa_exp_calls = [mock.call(self.task, self.node,
                                   states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_OFF, self.node.power_state)
        self.assertEqual(2,
                         self.service.power_state_sync_count[self.node.uuid])

    def test_retry_then_success(self, node_power_action):
        self.config(force_power_state_during_sync=True, group='conductor')
        self.config(power_state_sync_max_retries=2, group='conductor')

        self._do_sync_power_state(states.POWER_ON, [states.POWER_OFF,
                                                    states.POWER_OFF,
                                                    states.POWER_ON])

        self.assertFalse(self.power.validate.called)
        power_exp_calls = [mock.call(self.task, self.node)] * 3
        self.assertEqual(power_exp_calls,
                         self.power.get_power_state.call_args_list)
        self.assertFalse(self.node.save.called)
        npa_exp_calls = [mock.call(self.task, self.node,
                                   states.POWER_ON)] * 2
        self.assertEqual(npa_exp_calls, node_power_action.call_args_list)
        self.assertEqual(states.POWER_ON, self.node.power_state)
        self.assertNotIn(self.node.uuid, self.service.power_state_sync_count)


@mock.patch.object(manager.ConductorManager, '_do_sync_power_state')
@mock.patch.object(task_manager, 'acquire')
@mock.patch.object(manager.ConductorManager, '_mapped_to_this_conductor')
@mock.patch.object(dbapi.IMPL, 'get_node')
@mock.patch.object(dbapi.IMPL, 'get_nodeinfo_list')
class ManagerSyncPowerStatesTestCase(tests_base.TestCase):
    def setUp(self):
        super(ManagerSyncPowerStatesTestCase, self).setUp()
        self.service = manager.ConductorManager('hostname', 'test-topic')
        self.dbapi = dbapi.get_instance()
        self.service.dbapi = self.dbapi
        self.context = context.get_admin_context()
        self.node = self._create_node()
        self.filters = {'reserved': False, 'maintenance': False}
        self.columns = ['id', 'uuid', 'driver']

    @staticmethod
    def _create_node(**kwargs):
        attrs = {'provision_state': states.POWER_OFF,
                 'maintenance': False,
                 'reservation': None}
        attrs.update(kwargs)
        node = mock.Mock(spec_set=objects.Node)
        for attr in attrs:
            setattr(node, attr, attrs[attr])
        return node

    def _create_task(self, node_attrs):
        task = mock.Mock(spec_set=['node'])
        task.node = self._create_node(**node_attrs)
        return task

    def _get_acquire_side_effect(self, tasks):
        if not isinstance(tasks, list):
            tasks = [tasks]
        else:
            tasks = tasks[:]

        @contextlib.contextmanager
        def _acquire_side_effect(ctxt, node_id):
            task = tasks.pop(0)
            if isinstance(task, Exception):
                raise task
            else:
                # NOTE(comstud): Not ideal to throw this into
                # a helper method, however it's the cleanest way
                # to verify we're dealing with the correct task/node.
                self.assertEqual(node_id, task.node.id)
                yield task
        return _acquire_side_effect

    def _get_nodeinfo_list_response(self, nodes=None):
        if nodes is None:
            nodes = [self.node]
        elif not isinstance(nodes, (list, tuple)):
            nodes = [nodes]
        return [tuple(getattr(n, c) for c in self.columns) for n in nodes]

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
        get_node_mock.assert_called_once_with(self.node.uuid)
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
        get_node_mock.assert_called_once_with(self.node.uuid)
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
        get_node_mock.assert_called_once_with(self.node.uuid)
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
        get_node_mock.assert_called_once_with(self.node.uuid)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        self.assertFalse(sync_mock.called)

    def test_single_node(self, get_nodeinfo_mock, get_node_mock,
                         mapped_mock, acquire_mock, sync_mock):
        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response()
        get_node_mock.return_value = self.node
        mapped_mock.return_value = True
        task = self._create_task(dict(id=self.node.id))
        acquire_mock.side_effect = self._get_acquire_side_effect(task)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_mock.assert_called_once_with(self.node.uuid,
                                            self.node.driver)
        get_node_mock.assert_called_once_with(self.node.uuid)
        acquire_mock.assert_called_once_with(self.context, self.node.id)
        sync_mock.assert_called_once_with(task)

    def test__sync_power_state_multiple_nodes(self, get_nodeinfo_mock,
                                              get_node_mock, mapped_mock,
                                              acquire_mock, sync_mock):
        # Create 6 nodes:
        # 1st node: Should acquire and try to sync
        # 2nd node: Not mapped to this conductor
        # 3rd node: In DEPLOYWAIT provision_state
        # 4th node: Disappears after getting nodeinfo list.
        # 5th node: task_manger.acquire() fails due to lock
        # 6th node: Should acquire and try to sync
        nodes = []
        get_node_map = {}
        mapped_map = {}
        for i in range(1, 7):
            attrs = {'id': i,
                     'uuid': ironic_utils.generate_uuid()}
            if i == 3:
                attrs['provision_state'] = states.DEPLOYWAIT

            n = self._create_node(**attrs)
            nodes.append(n)
            mapped_map[n.uuid] = False if i == 2 else True
            get_node_map[n.uuid] = n

        tasks = [self._create_task(dict(id=1)),
                 exception.NodeLocked(node=5, host='fake'),
                 self._create_task(dict(id=6))]

        def _get_node_side_effect(node_uuid):
            node = get_node_map[node_uuid]
            if node.id == 4:
                # Make this node disappear
                raise exception.NodeNotFound(node=node_uuid)
            return node

        get_nodeinfo_mock.return_value = self._get_nodeinfo_list_response(
                nodes)
        mapped_mock.side_effect = lambda x, y: mapped_map[x]
        get_node_mock.side_effect = _get_node_side_effect
        acquire_mock.side_effect = self._get_acquire_side_effect(tasks)

        self.service._sync_power_states(self.context)

        get_nodeinfo_mock.assert_called_once_with(
                columns=self.columns, filters=self.filters)
        mapped_calls = [mock.call(n.uuid, n.driver) for n in nodes]
        self.assertEqual(mapped_calls, mapped_mock.call_args_list)
        get_node_calls = [mock.call(n.uuid) for n in nodes[:1] + nodes[2:]]
        self.assertEqual(get_node_calls,
                         get_node_mock.call_args_list)
        acquire_calls = [mock.call(self.context, n.id)
                for n in nodes[:1] + nodes[4:]]
        self.assertEqual(acquire_calls, acquire_mock.call_args_list)
        sync_calls = [mock.call(tasks[0]), mock.call(tasks[2])]
        self.assertEqual(sync_calls, sync_mock.call_args_list)
