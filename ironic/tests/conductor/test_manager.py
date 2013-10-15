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

from ironic.common import exception
from ironic.common import states
from ironic.conductor import manager
from ironic.conductor import task_manager
from ironic.db import api as dbapi
from ironic import objects
from ironic.openstack.common import context
from ironic.tests.conductor import utils as mgr_utils
from ironic.tests.db import base
from ironic.tests.db import utils


class ManagerTestCase(base.DbTestCase):

    def setUp(self):
        super(ManagerTestCase, self).setUp()
        self.service = manager.ConductorManager('test-host', 'test-topic')
        self.context = context.get_admin_context()
        self.dbapi = dbapi.get_instance()
        self.driver = mgr_utils.get_mocked_node_manager()

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
        with task_manager.acquire(node['id'], shared=False):
            node['extra'] = {'test': 'two'}
            self.assertRaises(exception.NodeLocked,
                              self.service.update_node,
                              self.context,
                              node)

        # verify change did not happen
        res = objects.Node.get_by_uuid(self.context, node['uuid'])
        self.assertEqual(res['extra'], {'test': 'one'})

    def test_update_node_invalid_state(self):
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

    def test_update_node_valid_state(self):
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

    def test_update_node_invalid_driver_info(self):
        # TODO(deva)
        pass

    def test_update_node_get_power_state_failure(self):
        # TODO(deva)
        pass

    def test_udpate_node_set_driver_info_and_power_state(self):
        # TODO(deva)
        pass

    def test_update_node_associate_instance(self):
        # TODO(deva)
        pass

    def test_update_node_unassociate_instance(self):
        # TODO(deva)
        pass

    def test_change_node_power_state_power_on(self):
        """Test if start_power_state to turn node power on
        is successful or not.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_OFF

            self.service.change_node_power_state(self.context,
                                                 node, states.POWER_ON)

            get_power_mock.assert_called_once_with(mock.ANY, node)
            self.assertEqual(node['power_state'], states.POWER_ON)
            self.assertEqual(node['target_power_state'], None)

    def test_change_node_power_state_power_off(self):
        """Test if start_power_state to turn node power off
        is successful or not.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.service.change_node_power_state(self.context, node,
                                                 states.POWER_OFF)

            get_power_mock.assert_called_once_with(mock.ANY, node)
            self.assertEqual(node['power_state'], states.POWER_OFF)
            self.assertEqual(node['target_power_state'], None)

    def test_change_node_power_state_already_locked(self):
        """Test if an exception is thrown when applying an exclusive
        lock to the node failed.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        # check if the node is locked
        with task_manager.acquire(node['id'], shared=False):
            self.assertRaises(exception.NodeLocked,
                              self.service.change_node_power_state,
                              self.context,
                              node,
                              states.POWER_ON)

    def test_change_node_power_state_invalid_state(self):
        """Test if an NodeInWrongPowerState exception is thrown
        when the node is in an invalid state to perform current operation.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            get_power_mock.return_value = states.POWER_ON

            self.assertRaises(exception.NodeInWrongPowerState,
                              self.service.change_node_power_state,
                              self.context,
                              node,
                              states.POWER_ON)
            get_power_mock.assert_called_once_with(mock.ANY, node)

    def test_change_node_power_state_invalid_driver_info(self):
        """Test if an exception is thrown when the driver validation is
        failed.
        """
        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_ON)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'validate') \
                as validate_mock:
            validate_mock.side_effect = exception.InvalidParameterValue(
                    'wrong power driver info')

            self.assertRaises(exception.InvalidParameterValue,
                              self.service.change_node_power_state,
                              self.context,
                              node,
                              states.POWER_ON)
            validate_mock.assert_called_once_with(node)

    def test_change_node_power_state_set_power_failure(self):
        """Test if an exception is thrown when the set_power call is
        failed.
        """
        class TestException(Exception):
            pass

        ndict = utils.get_test_node(driver='fake',
                                    power_state=states.POWER_OFF)
        node = self.dbapi.create_node(ndict)

        with mock.patch.object(self.driver.power, 'get_power_state') \
                as get_power_mock:
            with mock.patch.object(self.driver.power, 'set_power_state') \
                    as set_power_mock:
                get_power_mock.return_value = states.POWER_OFF
                set_power_mock.side_effect = TestException()

                self.assertRaises(TestException,
                                  self.service.change_node_power_state,
                                  self.context,
                                  node,
                                  states.POWER_ON)
                get_power_mock.assert_called_once_with(mock.ANY, node)
                set_power_mock.assert_called_once_with(mock.ANY, node,
                                                       states.POWER_ON)

    def test_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.service.do_vendor_action(self.context, n['uuid'], 'foo', info)

    def test_validate_vendor_action(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.assertTrue(self.service.validate_vendor_action(self.context,
                                                     n['uuid'], 'foo', info))

    def test_validate_vendor_action_unsupported_method(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'abc', info)

    def test_validate_vendor_action_no_parameter(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'fake': 'baz'}
        self.assertRaises(exception.InvalidParameterValue,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'foo', info)

    def test_validate_vendor_action_unsupported(self):
        n = utils.get_test_node(driver='fake')
        self.dbapi.create_node(n)
        info = {'bar': 'baz'}
        self.driver.vendor = None
        self.assertRaises(exception.UnsupportedDriverExtension,
                          self.service.validate_vendor_action,
                          self.context, n['uuid'], 'foo', info)

    def test_do_node_deploy_invalid_state(self):
        # test node['provision_state'] is not NOSTATE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service.do_node_deploy,
                          self.context, node)

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
                              self.context, node)
            self.assertEqual(node['provision_state'],
                             states.ERROR)
            deploy.assert_called_once()

    def test_do_node_deploy_ok(self):
        # test when driver.deploy.deploy returns DEPLOYDONE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy') \
                as deploy:
            deploy.return_value = states.DEPLOYDONE
            self.service.do_node_deploy(self.context, node)
            self.assertEqual(node['provision_state'],
                             states.ACTIVE)
            self.assertEqual(node['target_provision_state'],
                             states.NOSTATE)
            deploy.assert_called_once()

    def test_do_node_deploy_partial_ok(self):
        # test when driver.deploy.deploy doesn't return DEPLOYDONE
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.deploy') \
                as deploy:
            deploy.return_value = states.DEPLOYING
            self.service.do_node_deploy(self.context, node)
            self.assertEqual(node['provision_state'],
                             states.DEPLOYING)
            self.assertEqual(node['target_provision_state'],
                             states.DEPLOYDONE)
            deploy.assert_called_once()

    def test_do_node_tear_down_invalid_state(self):
        # test node['provision_state'] is incorrect for tear_down
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.NOSTATE)
        node = self.dbapi.create_node(ndict)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.service.do_node_tear_down,
                          self.context, node)

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
                              self.context, node)
            self.assertEqual(node['provision_state'],
                             states.ERROR)
            deploy.assert_called_once()

    def test_do_node_tear_down_ok(self):
        # test when driver.deploy.tear_down returns DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down') \
                as deploy:
            deploy.return_value = states.DELETED
            self.service.do_node_tear_down(self.context, node)
            self.assertEqual(node['provision_state'],
                             states.NOSTATE)
            self.assertEqual(node['target_provision_state'],
                             states.NOSTATE)
            deploy.assert_called_once()

    def test_do_node_tear_down_partial_ok(self):
        # test when driver.deploy.tear_down doesn't return DELETED
        ndict = utils.get_test_node(driver='fake',
                                    provision_state=states.ACTIVE)
        node = self.dbapi.create_node(ndict)

        with mock.patch('ironic.drivers.modules.fake.FakeDeploy.tear_down') \
                as deploy:
            deploy.return_value = states.DELETING
            self.service.do_node_tear_down(self.context, node)
            self.assertEqual(node['provision_state'],
                             states.DELETING)
            self.assertEqual(node['target_provision_state'],
                             states.DELETED)
            deploy.assert_called_once()
