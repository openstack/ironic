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
import time

import mock
from oslo.config import cfg
from testtools.matchers import HasLength

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils as ironic_utils
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.conductor import utils as conductor_utils
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import context
from ironic.openstack.common import timeutils
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils

CONF = cfg.CONF


class ManagerTestCase(base.DbTestCase):

    def setUp(self):
        super(ManagerTestCase, self).setUp()
        self.service = manager.ConductorManager('test-host', 'test-topic')
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        mgr_utils.mock_the_extension_manager()
        self.driver = driver_factory.get_driver("fake")

    def test_start_registers_conductor(self):
        self.assertRaises(exception.ConductorNotFound,
                          self.dbapi.get_conductor,
                          'test-host')
        self.service.start()
        res = self.dbapi.get_conductor('test-host')
        self.assertEqual('test-host', res['hostname'])

    def test_start_registers_driver_names(self):
        init_names = ['fake1', 'fake2']
        restart_names = ['fake3', 'fake4']

        df = driver_factory.DriverFactory()
        with mock.patch.object(df._extension_manager, 'names') as mock_names:
            # verify driver names are registered
            mock_names.return_value = init_names
            self.service.start()
            res = self.dbapi.get_conductor('test-host')
            self.assertEqual(init_names, res['drivers'])

            # verify that restart registers new driver names
            mock_names.return_value = restart_names
            self.service.start()
            res = self.dbapi.get_conductor('test-host')
            self.assertEqual(restart_names, res['drivers'])

    def test__conductor_service_record_keepalive(self):
        self.service.start()
        with mock.patch.object(self.dbapi, 'touch_conductor') as mock_touch:
            self.service._conductor_service_record_keepalive(self.context)
            mock_touch.assert_called_once_with('test-host')

    def test__sync_power_state_no_sync(self):
        self.service.start()
        n = utils.get_test_node(driver='fake', power_state='fake-power')
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = 'fake-power'
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        node = self.dbapi.get_node(n['id'])
        self.assertEqual('fake-power', node['power_state'])

    def test__sync_power_state_not_set(self):
        self.service.start()
        n = utils.get_test_node(driver='fake', power_state=None)
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        node = self.dbapi.get_node(n['id'])
        self.assertEqual(states.POWER_ON, node['power_state'])

    @mock.patch.object(objects.node.Node, 'save')
    def test__sync_power_state_unchanged(self, save_mock):
        self.service.start()
        n = utils.get_test_node(driver='fake', power_state=states.POWER_ON)
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertFalse(save_mock.called)

    @mock.patch.object(conductor_utils, 'node_power_action')
    @mock.patch.object(objects.node.Node, 'save')
    def test__sync_power_state_changed_sync(self, save_mock, npa_mock):
        self.service.start()
        self.config(force_power_state_during_sync=True, group='conductor')
        n = utils.get_test_node(driver='fake', power_state=states.POWER_ON)
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            npa_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                             states.POWER_ON)
            self.assertFalse(save_mock.called)

    @mock.patch.object(conductor_utils, 'node_power_action')
    @mock.patch.object(objects.node.Node, 'save')
    def test__sync_power_state_changed_failed(self, save_mock, npa_mock):
        self.service.start()
        self.config(force_power_state_during_sync=True, group='conductor')
        n = utils.get_test_node(driver='fake', power_state=states.POWER_ON)
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF
            npa_mock.side_effect = exception.IronicException('test')
            # we are testing that this does NOT raise an exception
            # so don't assertRaises here
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            npa_mock.assert_called_once_with(mock.ANY, mock.ANY,
                                             states.POWER_ON)
            self.assertFalse(save_mock.called)

    @mock.patch.object(conductor_utils, 'node_power_action')
    @mock.patch.object(objects.node.Node, 'save')
    def test__sync_power_state_changed_save(self, save_mock, npa_mock):
        self.service.start()
        self.config(force_power_state_during_sync=False, group='conductor')
        n = utils.get_test_node(driver='fake', power_state=states.POWER_OFF)
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertFalse(npa_mock.called)
            self.assertTrue(save_mock.called)

    def test__sync_power_state_node_locked(self):
        self.service.start()
        n = utils.get_test_node(driver='fake', power_state='fake-power')
        self.dbapi.create_node(n)
        self.dbapi.reserve_nodes('fake-reserve', [n['id']])
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            self.service._sync_power_states(self.context)
            self.assertFalse(get_power_mock.called)
        node = self.dbapi.get_node(n['id'])
        self.assertEqual('fake-power', node['power_state'])

    def test__sync_power_state_multiple_nodes(self):
        self.service.start()
        self.config(force_power_state_during_sync=False, group='conductor')

        # create three nodes
        nodes = []
        nodeinfo = []
        for i in range(0, 3):
            n = utils.get_test_node(id=i, uuid=ironic_utils.generate_uuid(),
                    driver='fake', power_state=states.POWER_OFF)
            self.dbapi.create_node(n)
            nodes.append(n['uuid'])
            nodeinfo.append([i, n['uuid'], 'fake'])

        # lock the first node
        self.dbapi.reserve_nodes('fake-reserve', [nodes[0]])

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            with mock.patch.object(self.dbapi,
                                   'get_nodeinfo_list') as get_fnl_mock:
                # delete the second node
                self.dbapi.destroy_node(nodes[1])
                get_fnl_mock.return_value = nodeinfo
                self.service._sync_power_states(self.context)
            # check that get_power only called once, which updated third node
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        n1 = self.dbapi.get_node(nodes[0])
        n3 = self.dbapi.get_node(nodes[2])
        self.assertEqual(states.POWER_OFF, n1['power_state'])
        self.assertEqual(states.POWER_ON, n3['power_state'])

    def test__sync_power_state_node_no_power_state(self):
        self.service.start()
        self.config(force_power_state_during_sync=False, group='conductor')

        # create three nodes
        nodes = []
        for i in range(0, 3):
            n = utils.get_test_node(id=i, uuid=ironic_utils.generate_uuid(),
                    driver='fake', power_state=states.POWER_OFF)
            self.dbapi.create_node(n)
            nodes.append(n['uuid'])

        # cannot get power state of node 2; only nodes 1 & 3 have
        # their power states changed.
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            returns = [states.POWER_ON,
                       exception.InvalidParameterValue("invalid"),
                       states.POWER_ON]

            def side_effect(*args):
                result = returns.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result

            get_power_mock.side_effect = side_effect
            self.service._sync_power_states(self.context)
            self.assertThat(returns, HasLength(0))

        final = [states.POWER_ON, states.POWER_OFF, states.POWER_ON]
        for i in range(0, 3):
            n = self.dbapi.get_node(nodes[i])
            self.assertEqual(final[i], n.power_state)

    def test__sync_power_state_node_deploywait(self):
        self.service.start()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT)
        self.dbapi.create_node(n)

        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            self.service._sync_power_states(self.context)
            self.assertFalse(get_power_mock.called)

    def test_change_node_power_state_power_on(self):
        # Test change_node_power_state including integration with
        # conductor.utils.node_power_action and lower.
        n = utils.get_test_node(driver='fake',
                                power_state=states.POWER_OFF)
        db_node = self.dbapi.create_node(n)
        self.service.start()

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
        self.service.start()

        self.assertRaises(exception.NodeLocked,
                          self.service.change_node_power_state,
                          self.context,
                          db_node.uuid,
                          states.POWER_ON)
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
        self.service.start()

        with mock.patch.object(self.service, '_spawn_worker') \
                as spawn_mock:
            spawn_mock.side_effect = exception.NoFreeConductorWorker()

            self.assertRaises(exception.NoFreeConductorWorker,
                              self.service.change_node_power_state,
                              self.context,
                              db_node.uuid,
                              states.POWER_ON)

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
        self.service.start()

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
            self.assertRaises(exception.NodeLocked,
                              self.service.update_node,
                              self.context,
                              node)

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
        self.assertRaises(exception.NodeInWrongPowerState,
                          self.service.update_node,
                          self.context,
                          node)

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
        node['driver'] = wrong_driver
        node['driver_info'] = {}
        self.assertRaises(exception.DriverNotFound,
                          self.service.update_node,
                          self.context,
                          node)

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(existing_driver, res['driver'])

    def test_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.service.do_vendor_action(
                self.context, n['uuid'], 'first_method', info)

    def test_validate_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.service.validate_vendor_action(
                self.context, n['uuid'], 'first_method', info)
        node.refresh(self.context)
        self.assertIsNone(node.last_error)

    def test_validate_vendor_action_unsupported_method(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'abc', info)
        node.refresh(self.context)
        self.assertIsNotNone(node.last_error)

    def test_validate_vendor_action_no_parameter(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'fake': 'baz'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'first_method', info)
        node.refresh(self.context)
        self.assertIsNotNone(node.last_error)

    def test_validate_vendor_action_unsupported(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.driver.vendor = None
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'foo', info)
        node.refresh(self.context)
        self.assertIsNotNone(node.last_error)

    def test_do_node_deploy_invalid_state(self):
        # test node['provision_state'] is not NOSTATE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service.do_node_deploy,
                          self.context, node['uuid'])

    def test_do_node_deploy_maintenance(self):
        ndict = utils.get_test_node(driver='fake', maintenance=True)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.NodeInMaintenance,
                          self.service.do_node_deploy,
                          self.context, node['uuid'])

    def test_do_node_deploy_driver_raises_error(self):
        # test when driver.deploy.deploy raises an exception
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy') \
                as deploy:
            deploy.side_effect = exception.InstanceDeployFailure('test')
            self.assertRaises(exception.InstanceDeployFailure,
                              self.service.do_node_deploy,
                              self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYFAIL, node['provision_state'])
            self.assertEqual(states.NOSTATE, node['target_provision_state'])
            self.assertIsNotNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_deploy_ok(self):
        # test when driver.deploy.deploy returns DEPLOYDONE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy') \
                as deploy:
            deploy.return_value = states.DEPLOYDONE
            self.service.do_node_deploy(self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(states.ACTIVE, node['provision_state'])
            self.assertEqual(states.NOSTATE, node['target_provision_state'])
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_deploy_partial_ok(self):
        # test when driver.deploy.deploy doesn't return DEPLOYDONE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy') \
                as deploy:
            deploy.return_value = states.DEPLOYING
            self.service.do_node_deploy(self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYING, node['provision_state'])
            self.assertEqual(states.DEPLOYDONE, node['target_provision_state'])
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_tear_down_invalid_state(self):
        # test node['provision_state'] is incorrect for tear_down
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service.do_node_tear_down,
                          self.context, node['uuid'])

    def test_do_node_tear_down_driver_raises_error(self):
        # test when driver.deploy.tear_down raises exception
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down') \
                as deploy:
            deploy.side_effect = exception.InstanceDeployFailure('test')
            self.assertRaises(exception.InstanceDeployFailure,
                              self.service.do_node_tear_down,
                              self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(states.ERROR, node['provision_state'])
            self.assertEqual(states.NOSTATE, node['target_provision_state'])
            self.assertIsNotNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_tear_down_ok(self):
        # test when driver.deploy.tear_down returns DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down') \
                as deploy:
            deploy.return_value = states.DELETED
            self.service.do_node_tear_down(self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(states.NOSTATE, node['provision_state'])
            self.assertEqual(states.NOSTATE, node['target_provision_state'])
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_do_node_tear_down_partial_ok(self):
        # test when driver.deploy.tear_down doesn't return DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down') \
                as deploy:
            deploy.return_value = states.DELETING
            self.service.do_node_tear_down(self.context, node['uuid'])
            node.refresh(self.context)
            self.assertEqual(node['provision_state'], states.DELETING)
            self.assertEqual(states.DELETED, node['target_provision_state'])
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once_with(mock.ANY, mock.ANY)

    def test_validate_driver_interfaces(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        ret = self.service.validate_driver_interfaces(self.context,
                                                      node['uuid'])
        expected = {'console': {'result': True},
                    'rescue': {'result': None, 'reason': 'not supported'},
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
        self.assertRaises(exception.NodeMaintenanceFailure,
                          self.service.change_node_maintenance_mode,
                          self.context, node.uuid, True)
        node.refresh(self.context)
        self.assertTrue(node.maintenance)

    def test_maintenance_mode_off_failed(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.NodeMaintenanceFailure,
                          self.service.change_node_maintenance_mode,
                          self.context, node.uuid, False)
        node.refresh(self.context)
        self.assertFalse(node.maintenance)

    def test__spawn_worker(self):
        func_mock = mock.Mock()
        args = (1, 2, "test")
        kwargs = dict(kw1='test1', kw2='test2')
        self.service.start()

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
        self.service.start()

        thread = self.service._spawn_worker(func)
        # func_mock executing at this moment
        thread.link(link_callback)
        self.service._worker_pool.waitall()

        link_callback.assert_called_once_with(thread)

    def test__spawn_link_callback_added_after_execution(self):
        def func():
            pass
        link_callback = mock.Mock()
        self.service.start()

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
        self.service.start()

        thread = self.service._spawn_worker(func)
        # func_mock executing at this moment
        thread.link(link_callback)
        self.service._worker_pool.waitall()

        link_callback.assert_called_once_with(thread)

    def test__spawn_link_callback_added_after_exception_inside_thread(self):
        def func():
            raise Exception()
        link_callback = mock.Mock()
        self.service.start()

        thread = self.service._spawn_worker(func)
        self.service._worker_pool.waitall()
        # func_mock finished at this moment
        thread.link(link_callback)

        link_callback.assert_called_once_with(thread)

    def test_destroy_node(self):
        self.service.start()
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.service.destroy_node(self.context, node.uuid)
        self.assertRaises(exception.NodeNotFound,
                          self.dbapi.get_node,
                          node.uuid)

    def test_destroy_node_reserved(self):
        self.service.start()
        fake_reservation = 'fake-reserv'
        ndict = utils.get_test_node(reservation=fake_reservation)
        node = self.dbapi.create_node(ndict)

        self.assertRaises(exception.NodeLocked, self.service.destroy_node,
                          self.context, node.uuid)
        # Verify existing reservation wasn't broken.
        node.refresh(self.context)
        self.assertEqual(fake_reservation, node.reservation)

    def test_destroy_node_associated(self):
        self.service.start()
        ndict = utils.get_test_node(instance_uuid='fake-uuid')
        node = self.dbapi.create_node(ndict)

        self.assertRaises(exception.NodeAssociated, self.service.destroy_node,
                          self.context, node.uuid)
        # Verify reservation was released.
        node.refresh(self.context)
        self.assertIsNone(node.reservation)

    @mock.patch.object(timeutils, 'utcnow')
    def test__check_deploy_timeouts_timeout(self, mock_utcnow):
        self.config(deploy_callback_timeout=60, group='conductor')
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=5)
        mock_utcnow.return_value = past
        self.service.start()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
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
        self.service.start()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
        with mock.patch.object(self.driver.deploy, 'clean_up') as clean_mock:
            self.service._check_deploy_timeouts(self.context)
            node.refresh(self.context)
            self.assertEqual(states.DEPLOYWAIT, node.provision_state)
            self.assertEqual(states.DEPLOYDONE, node.target_provision_state)
            self.assertIsNone(node.last_error)
            self.assertFalse(clean_mock.called)

    def test__check_deploy_timeouts_disabled(self):
        self.config(deploy_callback_timeout=0, group='conductor')
        self.service.start()
        with mock.patch.object(self.dbapi, 'get_nodeinfo_list') as get_mock:
            self.service._check_deploy_timeouts(self.context)
            self.assertFalse(get_mock.called)

    @mock.patch.object(timeutils, 'utcnow')
    def test__check_deploy_timeouts_cleanup_failed(self, mock_utcnow):
        self.config(deploy_callback_timeout=60, group='conductor')
        past = datetime.datetime(2000, 1, 1, 0, 0)
        present = past + datetime.timedelta(minutes=5)
        mock_utcnow.return_value = past
        self.service.start()
        n = utils.get_test_node(provision_state=states.DEPLOYWAIT,
                                target_provision_state=states.DEPLOYDONE,
                                provision_updated_at=past)
        node = self.dbapi.create_node(n)
        mock_utcnow.return_value = present
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

    def test_set_console_mode_enabled(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.service.set_console_mode(self.context, node.uuid, True)
        node.refresh(self.context)
        self.assertTrue(node.console_enabled)

    def test_set_console_mode_disabled(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        self.service.set_console_mode(self.context, node.uuid, False)
        node.refresh(self.context)
        self.assertFalse(node.console_enabled)

    def test_set_console_mode_not_supported(self):
        ndict = utils.get_test_node(driver='fake', last_error=None)
        node = self.dbapi.create_node(ndict)
        # null the console interface
        self.driver.console = None
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.service.set_console_mode, self.context,
                          node.uuid, True)
        node.refresh(self.context)
        self.assertIsNotNone(node.last_error)

    def test_set_console_mode_validation_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'validate') as mock_val:
            mock_val.side_effect = exception.InvalidParameterValue('error')
            self.assertRaises(exception.InvalidParameterValue,
                              self.service.set_console_mode, self.context,
                              node.uuid, True)
            node.refresh(self.context)
            self.assertIsNotNone(node.last_error)

    def test_set_console_mode_start_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None,
                                    console_enabled=False)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'start_console') \
                as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.assertRaises(exception.IronicException,
                              self.service.set_console_mode, self.context,
                              node.uuid, True)
            mock_sc.assert_called_once_with(mock.ANY, mock.ANY)
            node.refresh(self.context)
            self.assertIsNotNone(node.last_error)

    def test_set_console_mode_stop_fail(self):
        ndict = utils.get_test_node(driver='fake', last_error=None,
                                    console_enabled=True)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'stop_console') \
                as mock_sc:
            mock_sc.side_effect = exception.IronicException('test-error')
            self.assertRaises(exception.IronicException,
                              self.service.set_console_mode, self.context,
                              node.uuid, False)
            mock_sc.assert_called_once_with(mock.ANY, mock.ANY)
            node.refresh(self.context)
            self.assertIsNotNone(node.last_error)

    def test_enable_console_already_enabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'start_console') \
                as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, True)
            self.assertFalse(mock_sc.called)

    def test_disable_console_already_disabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=False)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'stop_console') \
                as mock_sc:
            self.service.set_console_mode(self.context, node.uuid, False)
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
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.service.get_console_information,
                          self.context, node.uuid)

    def test_get_console_disabled(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=False)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.NodeConsoleNotEnabled,
                          self.service.get_console_information,
                          self.context, node.uuid)

    def test_get_console_validate_fail(self):
        ndict = utils.get_test_node(driver='fake', console_enabled=True)
        node = self.dbapi.create_node(ndict)
        with mock.patch.object(self.driver.console, 'validate') as mock_gc:
            mock_gc.side_effect = exception.InvalidParameterValue('error')
            self.assertRaises(exception.InvalidParameterValue,
                              self.service.get_console_information,
                              self.context, node.uuid)

    def test_destroy_node_power_on(self):
        self.service.start()
        ndict = utils.get_test_node(power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        self.assertRaises(exception.NodeInWrongPowerState,
                          self.service.destroy_node, self.context, node.uuid)
        # Verify reservation was released.
        node.refresh(self.context)
        self.assertIsNone(node.reservation)

    def test_destroy_node_power_off(self):
        self.service.start()
        ndict = utils.get_test_node(power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)
        self.service.destroy_node(self.context, node.uuid)
