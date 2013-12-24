# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import mock
from oslo.config import cfg

from ironic.common import driver_factory
from ironic.common import exception
from ironic.common import states
from ironic.common import utils as ironic_utils
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import context
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
        self.driver = mgr_utils.get_mocked_node_manager()

    def test_start_registers_conductor(self):
        self.assertRaises(exception.ConductorNotFound,
                          self.dbapi.get_conductor,
                          'test-host')
        self.service.start()
        res = self.dbapi.get_conductor('test-host')
        self.assertEqual(res['hostname'], 'test-host')

    def test_start_registers_driver_names(self):
        init_names = ['fake1', 'fake2']
        restart_names = ['fake3', 'fake4']

        df = driver_factory.DriverFactory()
        with mock.patch.object(df._extension_manager, 'names') as mock_names:
            # verify driver names are registered
            mock_names.return_value = init_names
            self.service.start()
            res = self.dbapi.get_conductor('test-host')
            self.assertEqual(res['drivers'], init_names)

            # verify that restart registers new driver names
            mock_names.return_value = restart_names
            self.service.start()
            res = self.dbapi.get_conductor('test-host')
            self.assertEqual(res['drivers'], restart_names)

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
        self.assertEqual(node['power_state'], 'fake-power')

    def test__sync_power_state_do_sync(self):
        self.service.start()
        n = utils.get_test_node(driver='fake', power_state='fake-power')
        self.dbapi.create_node(n)
        with mock.patch.object(self.driver.power,
                               'get_power_state') as get_power_mock:
            get_power_mock.return_value = states.POWER_ON
            self.service._sync_power_states(self.context)
            get_power_mock.assert_called_once_with(mock.ANY, mock.ANY)
        node = self.dbapi.get_node(n['id'])
        self.assertEqual(node['power_state'], states.POWER_ON)

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
        self.assertEqual(n1['power_state'], states.POWER_OFF)
        self.assertEqual(n3['power_state'], states.POWER_ON)

    def test_get_power_state(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)

        # FakeControlDriver.get_power_state will "pass"
        # and states.NOSTATE is None, so this test should pass.
        state = self.service.get_node_power_state(self.context, n['uuid'])
        self.assertEqual(state, states.NOSTATE)

    def test_get_power_state_with_mock(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.side_effect = [states.POWER_OFF, states.POWER_ON]
            expected = [mock.call(mock.ANY, mock.ANY),
                        mock.call(mock.ANY, mock.ANY)]

            state = self.service.get_node_power_state(self.context, n['uuid'])
            self.assertEqual(state, states.POWER_OFF)
            state = self.service.get_node_power_state(self.context, n['uuid'])
            self.assertEqual(state, states.POWER_ON)
            self.assertEqual(get_power_mock.call_args_list, expected)

    def test_update_node(self):
        ndict = utils.get_test_node(driver='fake', extra={'test': 'one'})
        node = self.dbapi.create_node(ndict)

        # check that ManagerService.update_node actually updates the node
        node['extra'] = {'test': 'two'}
        res = self.service.update_node(self.context, node)
        self.assertEqual(res['extra'], {'test': 'two'})

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
        self.assertEqual(res['extra'], {'test': 'one'})

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
        self.assertEqual(res['instance_uuid'], None)

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
            self.assertEqual(res['instance_uuid'], 'fake-uuid')

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
        self.assertEqual(res['driver'], existing_driver)

    def test_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.service.do_vendor_action(self.context, n['uuid'], 'foo', info)

    def test_validate_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.assertTrue(self.service.validate_vendor_action(self.context,
                                                     n['uuid'], 'foo', info))
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
                          self.context, n['uuid'], 'foo', info)
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
        self.assertRaises(exception.InstanceDeployFailure,
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
            self.assertEqual(node['provision_state'], states.DEPLOYFAIL)
            self.assertEqual(node['target_provision_state'], states.NOSTATE)
            self.assertIsNotNone(node['last_error'])
            deploy.assert_called_once()

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
            self.assertEqual(node['provision_state'], states.ACTIVE)
            self.assertEqual(node['target_provision_state'], states.NOSTATE)
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once()

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
            self.assertEqual(node['provision_state'], states.DEPLOYING)
            self.assertEqual(node['target_provision_state'], states.DEPLOYDONE)
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once()

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
            self.assertEqual(node['provision_state'], states.ERROR)
            self.assertEqual(node['target_provision_state'], states.NOSTATE)
            self.assertIsNotNone(node['last_error'])
            deploy.assert_called_once()

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
            self.assertEqual(node['provision_state'], states.NOSTATE)
            self.assertEqual(node['target_provision_state'], states.NOSTATE)
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once()

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
            self.assertEqual(node['target_provision_state'], states.DELETED)
            self.assertIsNone(node['last_error'])
            deploy.assert_called_once()

    def test_validate_driver_interfaces(self):
        ndict = utils.get_test_node(driver='fake')
        node = self.dbapi.create_node(ndict)
        ret = self.service.validate_driver_interfaces(self.context,
                                                      node['uuid'])
        expected = {'console': {'result': None, 'reason': 'not supported'},
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
